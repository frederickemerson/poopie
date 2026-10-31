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
| Entity pass | 0.04 ms | 0.13 ms | 5 ms |
| Retrieval (graph filter + BM25 + dense, RRF) | 11.96 ms | 47.64 ms | 100 ms |

Measured warm over 40 queries against the built index.

API spend to date: **under $0.01**. Bulk extraction runs on Haiku 5.5 through the
Batch API at half price, measured at **$0.000076 per paragraph**, with a
content-addressed disk cache that makes re-runs free.

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
| Federal Register API | Final ADs, full XML, `docket_ids`, `effective_on` | No auth. ~10,360 ADs available |
| AD NPRM spreadsheet | 431 proposed rules, 323 dockets | Joins to final rules on docket number |
| OpenSky aircraft DB | 478 real aircraft, 30 operators | Real serials. **No synthesized values** |

The fleet is real. Fields the source does not carry stay null, and null is what
produces an honest `CANNOT_DETERMINE` — `category`, `equipment`, `modification`
and `part_number` have no source column at all, which is why amber cells appear
in BlastRadius. See [`docs/fleet.md`](docs/fleet.md) for the full null-rate table.

## Running it

```bash
# Python side
python3 -m pytest tests/ -q              # 191 passed
python3 -m engine.retrieval.index --build
uvicorn engine.api.server:app --port 8000

# UI
cd web && pnpm install && pnpm dev       # http://localhost:3000
```

An `ANTHROPIC_API_KEY` in `.env` (gitignored) enables the query planner and answer
writer. Without one the engine runs offline and marks what it cannot extract as
`unparsed` → `CANNOT_DETERMINE`, rather than guessing.

## Honest status

Built and tested: the contract and its gate, ingest and the knowledge graph,
the real fleet layer, hybrid retrieval with measured latency, the verifier and
refusal layer, the SSE backend, and the UI (builds clean, four scenarios on a
mock stream).

Not finished: the rules engine is written and unit-tested but **not yet wired
into the live gate**, so `decision` currently streams null; the evaluation
harness and vector-RAG baseline are not built; and the corpus is currently 28
final ADs plus 431 NPRMs rather than the full ~1,900-AD window — the harvester
takes a date-range flag and the architecture does not change with corpus size.

See [`docs/positioning.md`](docs/positioning.md) for how this compares to
regulatory portals, OEM documentation platforms and existing AI reference tools.
