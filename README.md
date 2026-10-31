# Traceable Airworthiness Directive engine

An airline airworthiness engineer or B1 technician asks in plain English:
*"Which ADs apply to this aircraft, what must I do, by when, and which revision is
current?"* Claude turns that into a structured query; a knowledge graph and plain
code find and decide the answer; the UI shows the proof.

The point is not that it answers. It is that **it knows what it cannot determine,
and proves what it can.**

## The idea in one paragraph

FAA Airworthiness Directives follow a fixed paragraph structure — (a) Effective
Date, (b) Affected ADs, (c) Applicability, (f) Compliance, (g) Required Actions,
and so on. That structure is explicit XML markup in the Federal Register, not
prose to be guessed at. We parse it once, offline, into a knowledge graph, and
turn each applicability paragraph into machine-checkable `Rule` records, each
carrying a source quote verified to be verbatim in its paragraph. At query time
**no model sits inside retrieval**: a rules engine, not an LLM, produces every
applies / does-not-apply / cannot-determine decision.

## Architecture

```
Federal Register API ─┐
NPRM spreadsheet    ──┼─► ingest ─► knowledge graph ─┐
OpenSky aircraft DB ─┘   (lxml,     (NetworkX +      │
                          no LLM)    SQLite FTS5)    │
                                                     ▼
  query ─► entity pass ─► hybrid retrieval ─► rules engine ─► answer ─► verifier ─► UI
           (regex, 0.04ms) (BM25+dense, 12ms)  (pure code)   (Sonnet)   (pure code)
                      └────────── no LLM in this path ──────────┘
```

Only two model calls exist in a query: a Haiku query plan before retrieval, and a
Sonnet answer writer after the decision is already made.

## Measured, not claimed

| Stage | p50 | p95 | Target |
|---|---|---|---|
| Entity pass | 0.07 ms | 0.13 ms | 5 ms |
| Retrieval (graph filter + BM25 + dense, RRF) | 28.42 ms | 39.25 ms | 100 ms |

Measured warm over 585 samples against the built index of **25,687 paragraphs
across 2,117 ADs**. Reproduce with:

```bash
python3 -m engine.retrieval.latency_bench
```

The queries are generated from the corpus, not hand-picked — a third name a
real AD, a third are real paragraph headings, a third name a fleet aircraft
model — so the mix cannot be chosen to flatter the result. Only the model-free
stages are claimed here; query planning and answer writing are network calls.

These replace figures measured when the corpus was 353 paragraphs. Growing it
73x moved p50 from 11.96 ms to 28.42 ms and left p95 better than before
(47.64 ms to 39.25 ms), because the graph filter narrows on the AD before
either arm runs, so a query that names an AD does not scan 25,687 paragraphs.

API spend to date: **$1.98** across 7,058 recorded calls, against a $50 budget.
Bulk extraction runs on Haiku 5.5 through the Batch API at half price and
accounts for $0.93 of that — 6,431 calls over the 25,687-paragraph corpus, an
average of **$0.0000363 per paragraph**. That is an average over the corpus,
not a per-call price: only applicability, compliance and required-action
paragraphs get a pass. The rest is query-time answers and the two eval arms,
each of which pays for a Sonnet answer per question.

Reproduce every figure above with:

```bash
python3 -m engine.llm.report
```

It reads `data/build/cost_ledger.jsonl`, which the client appends to on every
call including cache hits. A content-addressed disk cache makes a re-run free:
481 of those 7,058 calls were already cache hits.

## Why it refuses

Refusals are a feature here, not a failure. Each is code-triggered, names the
exact missing thing, and says who can resolve it. Full catalogue in
[`docs/refusals.md`](docs/refusals.md).

The headline case is real and in the corpus. FAA ADs that adopt foreign
directives delegate applicability outright:

> *(c) Applicability — This AD applies to Airbus SAS Model A330-941 airplanes,
> certificated in any category, **as identified in European Union Aviation Safety
> Agency (EASA) AD 2025-0208**, dated September 24, 2025.*

Plain vector RAG reads "Model A330-941" and confidently answers *applies*. That is
wrong — EASA AD 2025-0208 may scope by serial number or modification state. This
engine emits a `ForeignAD` node with `held=false` and refuses
`EXTERNAL_SOURCE_REQUIRED`, naming the document you need.

The same shape appears for compliance times buried in manufacturer service
bulletins: the AD *does* apply and we say so, but the deadline lives in a document
we do not hold, so we refuse that part and name the bulletin.

| Code | Fires when | Who resolves it |
|---|---|---|
| `NEED_CONFIG` | A value the engineer knows but the fleet record lacks | The user |
| `EXTERNAL_SOURCE_REQUIRED` | Applicability/deadline delegated to a document we lack | Loading it |
| `CANNOT_DETERMINE` | Applicability text the extractor could not parse | A human reading it |
| `NO_EVIDENCE` | Nothing retrieved above threshold | Outside the corpus |
| `OUT_OF_SCOPE` | Not an AD question | — |
| `SUPERSEDED` | Older revision asked about — **still answers**, with a banner | Read the current one |

## The contract

`contracts/contract.json` pins every node type, edge type, enum value, SSE event
and payload key. `tests/test_contract.py` is the gate: it fails the build on any
invented vocabulary, on any `Rule` whose `source_quote` is not verbatim in its
paragraph, and on a stale TypeScript mirror. It was written *before* any
producer or consumer code, deliberately — parallel workers inventing the same
vocabulary differently is a failure this project has seen before.

## Data — all public, no credentials

| Source | What it gives | Note |
|---|---|---|
| Federal Register API | Final ADs, full XML, `docket_ids`, `effective_on` | No auth. 2,117 ADs harvested over 2021-01-01..2026-10-31; ~10,360 available in total |
| AD NPRM spreadsheet | 431 rows over 322 dockets | 306 are live proposals; 125 are withdrawals and comment-period notices. Joins to final rules on docket number |
| OpenSky aircraft DB | 478 real aircraft, 30 operators | Real serials. **No synthesized values** |

The fleet is real. Fields the source does not carry stay null, and null is what
produces an honest `CANNOT_DETERMINE` — `category`, `equipment`, `modification`
and `part_number` have no source column at all, which is why amber cells appear
in BlastRadius. See [`docs/fleet.md`](docs/fleet.md) for the full null-rate table.

## Running it

`make help` lists every canonical command. The ones that matter:

```bash
make verify     # the gate: whole test suite, then latency vs contract targets
make demo       # walk the engine end to end on four questions -- free, no model calls
make cost       # what has actually been spent, from the append-only ledger

uvicorn engine.api.server:app --port 8000   # SSE backend
make web                                    # UI on http://localhost:3000
```

`make demo` is the quickest honest look at the engine: it calls the same
functions in the same order as the SSE server, so it cannot flatter the
product by reimplementing it. It prints, per question, the entities code found,
how the graph filter narrowed, what was retrieved, what the rules engine
decided and on which rule, and every refusal with its code. Add
`make demo-live` to also run the answer writer and see each sentence either
kept with its computed citation or dropped with the reason.

Rebuilding from scratch has a dependency order, because the derived artifacts
key on paragraph ids: `make ingest && make extract && make index`. Running
them out of order leaves rules pointing at ids that no longer exist, which the
contract gate catches.

An `ANTHROPIC_API_KEY` in `.env` (gitignored) enables the query planner and answer
writer. Without one the engine runs offline and marks what it cannot extract as
`unparsed` → `CANNOT_DETERMINE`, rather than guessing.

## Honest status

Built, tested and running end to end (`make verify` → 339 passed; `make demo`
walks it): the contract and its gate, ingest and the knowledge graph, the real
fleet layer, hybrid retrieval with measured latency, the rules engine wired
into the live gate, the answer writer and verifier, the refusal layer, the
answer envelope, reference traversal and dependency expansion, the SSE
backend, and the UI against that live backend (tsc clean, `pnpm build` passes,
zero console errors on a live run).

The corpus is the full window: **2,161 revisions / 2,117 ADs / 25,687
paragraphs**, plus 431 NPRM rows. Retrieval still measures p95 39 ms against a
100 ms target at that size.

Not finished, stated plainly:

- **The thresholds in `engine/verify/thresholds.py` are untuned defaults.** No
  sweep against a labelled set has been run, so `TERM_COVERAGE_MIN = 0.50` and
  `NO_EVIDENCE_COSINE_MIN = 0.30` are reasoned guesses. The file says so. Any
  false-refusal / false-answer rate quoted for them would be invented.
- **Every extracted rule is machine-extracted and unreviewed.** `review_status`
  is `UNREVIEWED` on all 6,403 of them, and the envelope's `limitations` says
  so on every answer that uses one. A human has checked none of them.
- **Cross-encoder reranking is off.** It was built and measured: no quality
  gain and 3–5.6× the latency target. `docs/reranking.md` has the numbers.
- **Paragraph-role ranking is weak.** An applicability question can rank an
  `ADDITIONAL_INFO` paragraph above the `APPLICABILITY` one from the same AD.
  Both reach the answer writer, so answers are not wrong, but the ordering
  should use the role and intent enums and does not yet.
- **The engine has no channel to accept a missing value.** `NEED_CONFIG` names
  the field an engineer could supply in seconds, but `/stream` takes only `q`
  and `tail_number`, so supplying it cannot re-run the decision yet.

See [`docs/positioning.md`](docs/positioning.md) for how this compares to
regulatory portals, OEM documentation platforms and existing AI reference tools.
