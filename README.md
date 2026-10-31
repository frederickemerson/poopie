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

## What it gets right

Every claim below is a measurement with its method attached. None is a projection,
and the one place the engine fails badly is in this list too.

**Zero wrong answers on the adversarial set.** 31 trap questions built to elicit a
confident false verdict — a superseded revision quoted as current, applicability
delegated to a document we do not hold, a model designation that silently names a
whole fleet. All 31 are blocked. Two root-cause fixes moved that from 23/31 to
**31/31**, and correct refusal codes from 21/31 to 28/31, with false refusals
unchanged at 2/20. All 10 delegation traps held `EXTERNAL_SOURCE_REQUIRED`.

**Zero fabrications on an external 39-prompt suite.** Run against a supplied answer
key over the NPRM workbook: **0 fabricated sentences across all 39 prompts**,
including W25, which explicitly baits a retired synthetic fixture ("do not reuse the
old 100-hour answer"). It did not. It also answered none of the 17 prompts that
wanted a substantive answer — see *Honest status*, which treats that as the failure
it is rather than rounding it into the win.

**The deciding is effectively instantaneous.** Measured over 20 consecutive live
queries, both model calls in the loop, nothing served from cache:

| | Measured |
|---|---|
| Applicability verdict | **0.5 ms** |
| Everything this engine decides (entity pass, retrieval, applicability, verification) | **117 ms** |
| Average refusal, end to end | **1.2 s** |
| Average answered question, end to end | **2.5 s** (p50 1.6 s, p95 4.3 s) |

2.9% of an answered question is this engine; the other 97.1% is the two model calls
at either end. A refusal is fastest because it never reaches the answer writer.

**The corpus is 8.4× the challenge's bar** — 8,363 distinct Federal Register pages
against a 1,000-page requirement, counted from the documents' own page fields.

**Every sentence is held to a verbatim span, or deleted.** The verifier re-checks each
drafted sentence against the paragraph it cites and drops the ones that do not hold;
if too few survive, the answer is withheld entirely rather than padded. This is
observable in the traces — it routinely deletes the engine's own prose.

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

A latency number means nothing without the corpus it was measured on, so the
size comes first.

**The indexed corpus: 2,592 Federal Register documents — 2,161 adopted ADs and
431 proposals — 28,735 paragraphs, 2,117 ADs, and 8,363 distinct Federal
Register pages**, against the challenge's 1,000-page bar: 8.4×. The page count
is the documents' own `start_page`/`end_page` from the Federal Register index,
counted as distinct `(volume, page)` pairs so a page two documents share is
counted once. 7,081 of those pages are adopted ADs and 1,282 are proposals.

```bash
python3 -m engine.api.citations              # pages, from the built nodes
python3 -m engine.api.citations --from-index # same, from the cached FR index
```

| Stage | p50 | p95 | Target |
|---|---|---|---|
| Entity pass | 0.07 ms | 0.09–0.11 ms | 5 ms |
| Retrieval (graph filter + BM25 + dense, RRF) | 23.2–25.1 ms | 62.2–66.5 ms | 100 ms |
| Whole query, model calls included | 1,627 ms | 4,309 ms | 3,000 ms |

The whole-query row is a separate measurement: 20 consecutive live queries with
both model calls in the loop and nothing served from cache. Its p50 beats the
3,000 ms target and **its p95 does not** — the overrun is entirely the answer
writer, which averages 2,783 ms on its own. The deterministic rows below are
measured warm over 585 samples (39 generated queries × 15 repeats) against the
built index named above. Reproduce with:

```bash
python3 -m engine.retrieval.latency_bench
```

A range is quoted rather than one run's decimals, because the spread between
runs is larger than the decimals: nine runs of the bench — eight here plus one
run by a second process on the same build — gave retrieval p50 between 23.19
and 25.09 ms and p95 between 62.20 and 66.46 ms. One further run, taken while a
dev server was rebuilding, gave p50 31.68 ms; it is named rather than dropped.
Index load was 0.63–0.69 s throughout. The bench prints the paragraph and AD
count beside every result, because a p95 without a corpus size is not a
measurement.

The 3,000 ms row is the contract's `total_p95` target and it is **not claimed
here**: two of the stages in a whole query are network calls to Anthropic, and
their latency is not this engine's to promise. What this engine is responsible
for — the entity pass, retrieval, the rules engine, the verifier — is model-free
and lands in tens of milliseconds, leaving the 3-second budget almost entirely
to the two model calls.

The queries are generated from the corpus, not hand-picked — a third name a
real AD, a third are real paragraph headings, a third name a fleet aircraft
model — so the mix cannot be chosen to flatter the result.

These replace figures measured when the corpus was 353 paragraphs. Growing it
81x moved retrieval p50 from 11.96 ms to about 24 ms and p95 from 47.64 ms to
about 65 ms — an 81x corpus for roughly 2x the median, because the graph filter
narrows on the AD before either arm runs, so a query that names an AD never
scans 28,735 paragraphs. The p95 is the tail of the queries that name no AD,
and adding the 3,048 proposal paragraphs — which carry no AD number to narrow
on — is what grew it. Both still sit inside the 100 ms target.

API spend to date: **$1.98** across 7,058 recorded calls, against a $50 budget.
Bulk extraction runs on Haiku 5.5 through the Batch API at half price and
accounts for $0.93 of that — 6,431 calls over the 25,687 adopted-AD paragraphs,
an average of **$0.0000363 per paragraph**. That is an average over the corpus,
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

## What a citation carries

Every citation has two halves, and it needs both.

**The anchor is provable.** A citation id is
`{document_id}#{label}@{char_start}-{char_end}`. The offsets are computed by
`str.find` in `engine/api/answer.py` — the answer writer is never asked for a
number, it is asked to quote — and `engine/verify/verifier.py` re-checks that
the text at that span is the quote, character for character. A quote that is
not there yields no citation and the sentence is dropped.

**The reference is findable.** An anchor like `2026-21864#(g)@4120-4193` cannot
be taken to a paper copy of the Federal Register, so `engine/api/citations.py`
puts the reference beside it:

> **2026-21-12 · 91 FR 67442 · pp. 67442–67445 · ¶(g) REQUIRED_ACTIONS · in force**

For a proposal the handle is the challenge index's `record_id` instead of an AD
number, and the stage word is **proposal**:

> **NPRM-001 · 91 FR 66019 · pp. 66019–66022 · ¶(c) APPLICABILITY · proposal**
> *a proposal open for comment — not a requirement, and nothing to comply with*

Three rules hold:

- **Every rendered citation shows its `document_stage`** — on the pill itself,
  not in a tooltip. `HumanReference` cannot be constructed without a contract
  stage, so a stage-less citation cannot reach a renderer. An NPRM citation
  reads as a proposal everywhere it appears.
- **No page number is ever invented.** `fr_citation`, `start_page` and
  `end_page` are copied from the Federal Register index, and
  `engine/ingest/emit.py` refuses a `Revision` whose `start_page` is not the
  page its own citation names, or that has a page with no citation beside it.
  There is no node shape in which a made-up page can be written. A proposal's
  pages come from the same index, joined on its `fr_document_number`, so the
  rubric's `91 FR 66019` is the register's own string and not a parse of the
  spreadsheet's prose.
- **An absent field says so.** A document whose pages we do not hold renders
  `page range not recorded` and is named in the envelope's `limitations` as a
  citation that can be checked against the indexed text but not a printed page.
  The NPRM spreadsheet's own citation column is free prose in 233 distinct
  shapes; it is shown verbatim and never parsed into a citation.

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

Built, tested and running end to end (`make verify` → 488 passed; `make demo`
walks it): the contract and its gate, ingest and the knowledge graph, the real
fleet layer, hybrid retrieval with measured latency, the rules engine wired
into the live gate, the answer writer and verifier, the refusal layer, the
answer envelope, reference traversal and dependency expansion, the SSE
backend, and the UI against that live backend (tsc clean, `pnpm build` passes,
zero console errors on a live run).

The corpus is the full window: **2,161 revisions / 2,117 ADs / 431 proposals /
28,735 paragraphs / 8,363 distinct Federal Register pages** (7,081 adopted +
1,282 proposed). Retrieval still measures p95 63–66 ms against a 100 ms target
at that size.

Not finished, stated plainly:

- **The proposals half of the corpus is effectively unreachable by question, and
  one refusal states a falsehood.** A 39-prompt external suite over the NPRM
  workbook refused all 39 and answered none of the 17 that wanted a substantive
  answer. Three causes, each confirmed from the run: `NPRM-001`-style identifiers
  are not recognised by the entity pass, so every such prompt returns an entirely
  empty entity set and the engine never resolves the document named; record lookup
  is scoped to adopted ADs; and where NPRM text *was* retrieved the verifier
  dropped every drafted sentence. The scoping produces the serious one — W01 asked
  for docket `FAA-2026-11814` and got `NO_EVIDENCE: "FAA-2026-11814 is not in the
  2117 airworthiness directives loaded here"`, which is false: that docket is in
  the graph both as an NPRM node and as a `Docket` node, as are all 322 NPRM
  dockets. The engine is reporting the emptiness of a filter as the emptiness of
  the corpus. For a project whose whole claim is that it knows what it cannot
  determine, asserting the absence of a record it holds is the worst failure
  available, and it is open. Separately, `EXTERNAL_SOURCE_REQUIRED` fires on these
  prompts naming documents unrelated to the question asked.
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
- **A proposal's reference depends on resolving it to a Federal Register
  document.** All 431 do today, so every proposal carries `91 FR 66019` and
  `66019-66022` from the register's own fields. A row that stopped resolving
  would fall back to the spreadsheet's prose citation, shown verbatim, and
  report its page range as `not recorded` — visibly degraded rather than
  guessed, but degraded. The challenge index's own page column is never parsed:
  it writes four different shapes (`66019-66022`, `Pages 45118-45119`,
  `Page 6708`, `14293)`) and 200 of its 431 cells are not two integers.

See [`docs/positioning.md`](docs/positioning.md) for how this compares to
regulatory portals, OEM documentation platforms and existing AI reference tools.
