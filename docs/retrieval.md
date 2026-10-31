# Retrieval, verification and the refusal gate

Finds the paragraphs of the AD corpus that bear on a question, then checks that
anything written from them is actually supported by them. Nothing here generates
text. Every step before the answer writer is deterministic code, and the verifier
that follows the writer is too.

Code: `engine/retrieval/*.py` and `engine/verify/*.py`. Related: `docs/refusals.md`
(what each refusal means to a user), `docs/rules.md` (the applicability decision
the gate passes through), `docs/ingest.md` (where paragraphs and offsets come from).

---

## Pipeline

```
query
  |
  v
1. entity pass            regex + table lookup, no model, no I/O          ~0.04 ms
  |
  v   (plan_query, Haiku, advisory: see "Where a model does run")
  |
  v
2. graph filter           AD / docket / amendment / revision / model / make
  |                        narrows the candidate paragraph set BEFORE any scoring
  v
3. hybrid search          FTS5 keyword  +  dense cosine  -->  reciprocal rank fusion
  |
  v
4. refusal gate           identifier miss, out of scope, below floor, rules engine, superseded
  |
  v
5. (answer writer)  -->   6. verifier: citations resolve, spans verbatim, terms overlap
```

---

## 1. The entity pass

`entities.extract_entities(query, known_ad_numbers=...)` is pure regex and table
lookup: no model, no network, no disk. It runs first and often is the whole answer:
"what does AD 2026-21-13 require?" needs the paragraphs of one revision, not
semantic search. Because it never calls out, it is also the fallback when planning
is slow or fails.

It extracts AD numbers, dockets, part-39 amendments, tail numbers, serial numbers,
models, typecodes, manufacturers, ATA chapters and foreign AD numbers. Two rules
govern it:

- **A structured authority decides where one exists.** Tail numbers follow the
  14 CFR 47.15 N-number grammar, not `N\w+`. Models, typecodes and manufacturers
  come from `data/reference/aircraft_normalization.json`; a string not in the table
  is not a model as far as this engine is concerned. A serial number needs a cue
  token (`MSN`, `S/N`, "serial number", "line number"); a bare number is never a
  serial.
- **An ambiguous token is classified by evidence, never preference.** `2026-21-13`
  is shaped like both an AD number and an ISO date. It is an AD number only if an
  `AD` token precedes it or the corpus holds that number. Otherwise it goes into
  `ambiguous`, which is surfaced so the caller can see why a query will probably end
  in a refusal. Spans claimed by an unambiguous pattern are never re-read by a looser
  one, so a docket number cannot also be reported as a model.

---

## 2. The graph filter, applied before search

`graph_filter.filter_candidates` narrows the candidate set by traversing the graph
built from `nodes.jsonl` and `edges.jsonl`. An AD number is an exact fact, so it
should decide the candidate set outright instead of competing with similarity inside
a scorer. Order of application:

| Entity | Narrows to |
|---|---|
| explicit `revision_ids` | those revisions |
| AD number | its revisions (only the current one when `revision_scope` is `current`) |
| docket | revisions of the ADs `IN_DOCKET` |
| amendment | revisions with that amendment |
| model / typecode (only if nothing above narrowed) | revisions with a `Rule` whose value names it |
| manufacturer (only if nothing above narrowed) | revisions of ADs whose make normalizes to it |

If nothing narrows, the candidate set is the whole corpus (current revisions only,
under the default scope).

Every filter reports whether it **could** be applied. `filter_report` carries
`applied` and `unavailable` lists; a filter the graph cannot support (for example
no `Rule` nodes yet, reported as `model:no Rule nodes in graph`) is never silently
skipped and never approximated by matching strings against paragraph text, which
would re-derive, badly, what the rules engine produces properly. "Not available" and
"nothing matched" are different facts and are reported as different strings.

---

## 3. The hybrid index and fusion

`index.py` builds two arms over the same paragraphs, indexing `heading + "\n" + text`
(the heading is authoritative markup that often carries the user's whole question,
for example "Applicability").

| Arm | Implementation | Notes |
|---|---|---|
| Keyword | SQLite FTS5, `bm25` ranking, tokenizer `unicode61 tokenchars '-'` | `tokenchars '-'` keeps `2026-21-13` one token; the default tokenizer splits it into three and an AD number would match any document mentioning 2026. FTS5 also takes a `rowid IN (...)` restriction in the same statement, which is what "filter first" needs. |
| Dense | `sentence-transformers/all-MiniLM-L6-v2`, 384-dimension, L2-normalized float32 matrix in a `.npy` | Computed once at build time; only the query is embedded at search time. Normalized, so cosine similarity is a dot product. |

The model name and dimension are stored in the index and checked on load; changing
the model invalidates the index loudly instead of mixing vector spaces. The index
also stores a corpus fingerprint (`353:da5343a4213eeb3f` for the current build
corpus), and `load_index` refuses an index built for a different corpus. A missing
embedding model raises `DenseUnavailable`; building with `--no-dense` gives a
keyword-only index that says so in its meta. A degraded index is visible, never
silent.

User input cannot become FTS5 syntax: `fts5_query` wraps every token in double
quotes (a literal phrase) and ORs them. Query-side stopwords are dropped so an
all-stopword clause cannot match the whole corpus; if nothing remains the dense arm
runs alone.

Each arm returns its top 40 (`ARM_DEPTH`). They are fused with **reciprocal rank
fusion**: each paragraph scores `sum over arms of 1 / (60 + rank)`. RRF consumes
only the rank each arm assigns, so it needs no weight and no score normalization (bm25
and cosine are not on comparable scales). The constant 60 is the value from the
original paper (Cormack, Clarke and Buettcher, 2009) and was not tuned. With two arms
the maximum fused score is `2 / 61 = 0.0328`. The top 8 (`k=8`) are returned, ties
broken by corpus order.

Each `Hit` carries everything a citation needs: `paragraph_id`, `revision_id`, the
heading and role, `char_start`/`char_end`, both arm ranks, the raw dense cosine, and
`citation_id = {paragraph_id}@{char_start}-{char_end}`.

### Why the fused score is not the evidence signal

RRF saturates: it reaches its maximum whenever both arms agree on a top-1, however
poor that top-1 is. The code's measurement is that an out-of-scope query ("MEL
dispatch limit for an inoperative APU") scored the full 0.0328. So the fused score
**orders** results and says nothing about whether any of them answers the question.
The refusal gate thresholds `SearchResult.top_cosine`, the dense cosine of the best
fused hit, which is absolute and comparable across queries. When that hit is not in
the dense arm's top 40 the value is `0.0`. In my spot-check the MEL query returned
`top_cosine = 0.0`, which sits below the floor and refuses.

---

## Why no LLM sits in the retrieval path

The filter, both arms and the fusion contain no generative model call. What that
buys:

- **Reproducibility.** The same query over the same index returns the same
  paragraphs, so a wrong retrieval can be reproduced and fixed. A model-in-the-loop
  retrieval (query rewriting, LLM reranking) can differ run to run.
- **Latency you can budget.** The retrieval stage is measured in milliseconds (below);
  it does not depend on a network call or a rate limit.
- **No wrong paragraph introduced by a model.** The citations the verifier later
  checks are drawn from this set, so a model cannot enlarge the set it is checked
  against.
- **It works when the model is unavailable.** The entity pass, filter, search and
  gate all run with no API key. The planner fails closed into "no plan".
- **Identifiers are matched as facts**, not as similarity.

### Where a model does run, stated precisely

Two model calls exist in the whole request path, neither inside retrieval:

1. **Query planning** (`plan.py`, `claude-haiku-5-5`) runs *before* the search stage in
   `engine/api/server.py`. It is advisory: its schema is generated from the contract's
   `query_plan_schema` with every enum read from the contract at runtime, and on any
   failure (no API key, budget, timeout, malformed output, off-enum value) it returns
   `plan=None` with a reason and never raises. Its one effect on retrieval is the
   `revision_scope` argument (`current`/`all`/`specific`); with no plan, search uses
   `current`. The gate also reads the plan to tell `OUT_OF_SCOPE` from `NO_EVIDENCE`.
2. **The answer writer** (`MODEL_ANSWER = claude-sonnet-5-5`) runs after retrieval and
   the gate, and only if no blocking refusal fired.

The embedding model is a local encoder, not a generator.

---

## 4. The verifier

`verify.verifier.verify(sentences, retrieved)` is pure code, no model. The writer is
told to cite, but instruction is not enforcement: nothing the writer produces reaches
the screen except through here. Each sentence carries citation ids and passes four
gates, cheapest and most decisive first:

| # | Gate | Fails when | Drop reason |
|---|---|---|---|
| 0 | has a citation | no citation id | `sentence_carries_no_citation` |
| 1 | resolvable citation | not of the form `{paragraph_id}@{start}-{end}`, or the paragraph is not in **this query's** retrieved set | `citation_unparseable`, `citation_not_in_retrieved_set` |
| 2 | verbatim span | the range is empty or outside the paragraph's own `char_start..char_end`, or the text at it is not in the paragraph | `span_outside_paragraph`, `span_not_verbatim_in_paragraph` |
| 3 | numeric support | any digit-bearing term in the sentence is absent from the cited span | `numeric_term_absent_from_cited_span` |
| 4 | term coverage | share of the sentence's content terms present in the cited span is below 0.50 | `term_coverage_below_threshold` |

**The citation-resolution rule.** A citation must point at a paragraph retrieved
for *that query*. `contract.validate_citation` checks the cited paragraph id against
the query's retrieved set. A citation to a paragraph that exists in the corpus but
was not retrieved for this query is still a fabrication, and gate 1 is the gate that
catches it.

A sentence with several citations passes if any one supports it: citing two
paragraphs where one is wrong is a citation error, not a content error.

**The term-overlap check** (`terms.py`) is deliberately simple and inspectable:

- Content terms: lowercase tokens minus standard English function words. No AD-domain
  word is removed, because that would tune the test to the corpus.
- A fixed, ordered suffix stripper applied identically to both sides, so "requires"
  matches "required". It is not a real stemmer.
- Coverage is `matched / sentence terms`. A sentence with no content terms scores
  `0.0`, not `1.0`: an empty claim is not a supported claim.
- **Digit-bearing terms are required, not averaged.** A deadline, serial range, part
  number or model suffix is the content most likely to be invented and the most
  dangerous. A sentence saying "within 14 months" over a paragraph saying "within 10
  months" fails outright, whatever the overall overlap.

After per-sentence verdicts, an answer is turned into a refusal rather than shown
thinned if fewer than 60% of sentences survive (`MIN_KEPT_FRACTION`) or none do. The
refusal code used is `NO_EVIDENCE`. Rationale in `thresholds.py`: a half-verified
answer in a safety domain reads as a complete one.

### What the thresholds are, and what I could verify

| Constant | Value | Role |
|---|---|---|
| `TERM_COVERAGE_MIN` | 0.50 | minimum content-term coverage |
| `REQUIRE_NUMERIC_SUPPORT` | `True` | every digit term must be present (a rule, not a tuned number) |
| `MIN_KEPT_FRACTION` | 0.60 | below this, the answer becomes a refusal |
| `MIN_KEPT_SENTENCES` | 1 | at least this many survive |
| `NO_EVIDENCE_COSINE_MIN` | 0.30 | dense cosine floor for `NO_EVIDENCE` |

`thresholds.py` says these were tuned by sweeps over 420 labelled sentence/citation
pairs and a labelled query set at `engine/retrieval/fixtures/queries.json`, via
`python3 -m engine.retrieval.evaluate --all`, and that the measured rates are in this
document. **I could not verify that.** Neither `engine/retrieval/evaluate.py` nor
`engine/retrieval/fixtures/queries.json` exists in the repository, and no test covers
`engine/retrieval` or `engine/verify`. So I cannot report the false-refusal,
false-answer or false-drop rates at these values, and this document does not claim
any. The values are in force; their tuning evidence is not in the tree.

---

## 5. The refusal gate

`gate.evaluate_gate` is the single place that decides which retrieval-side refusal
fires, so the "who can resolve it" distinction in `docs/refusals.md` is applied
consistently. Order is authoritative-signal-first; each step is a fact rather than a
score wherever a fact exists:

| # | Check | Result | Blocks answer |
|---|---|---|---|
| 1 | An AD number, docket, amendment or revision the graph does not hold, and no identifier resolved | `NO_EVIDENCE` (a lookup miss, no threshold) | yes |
| 2 | A model or manufacturer no loaded directive concerns (distinct from "cannot filter by model yet") | `OUT_OF_SCOPE` | yes |
| 3 | Nothing retrieved | `NO_EVIDENCE` | yes |
| 4 | The plan names nothing this corpus indexes, and top cosine is below the floor | `OUT_OF_SCOPE` | yes |
| 5 | Top cosine below 0.30 | `NO_EVIDENCE` | yes |
| 6 | The rules engine's own refusal, passed through unchanged | `EXTERNAL_SOURCE_REQUIRED`, `CANNOT_DETERMINE` or `NEED_CONFIG` | yes |
| 7 | A retrieved revision has a newer one | `SUPERSEDED` | **no**; annotates an answer |

`SUPERSEDED` is appended whether or not anything above fired, because it warns and
does not withhold.

Rules for how refusals are built (`refusals.py`):

- A refusal with no evidence paragraph is a defect. `refusals.build` raises
  `EvidenceFreeRefusal` unless nothing at all was retrieved.
- If the rules engine emits a refusal with no paragraph (its "no rule extracted"
  case), `rules_adapter.repair_evidence` substitutes the paragraphs retrieved for the
  query and says so in the detail text. It repairs only that.
- The model never decides to refuse. If the writer tries to, `model_refusal_signal`
  records it as a defect (retrieval or the rules engine should have caught it first).
- Every payload is validated against the contract's `refusal` event on the way out.
  The set of codes is pinned in the contract and `tests/test_contract.py` fails the
  build for a new one.

---

## Latency

Re-measured on the full corpus (25,687 paragraphs across 2,117 ADs), 585 warm
samples over 39 corpus-generated queries, via
`python3 -m engine.retrieval.latency_bench`:

| Stage | p50 | p95 | Target |
|---|---|---|---|
| Entity pass | 0.07 ms | 0.13 ms | 5 ms |
| Retrieval (filter + both arms + fusion) | 28.42 ms | 39.25 ms | 100 ms |

The earlier figures in this section (0.04/0.13 ms and 11.96/47.64 ms) were taken
when the corpus was 353 paragraphs, and the corpus was indeed not recorded with
them — which is why the bench now prints the paragraph and AD count beside every
result. Growing the corpus 73x moved retrieval p50 from 11.96 ms to 28.42 ms and
left p95 lower than before, because the graph filter narrows to a single
revision before either arm runs.

The **first query pays a one-off cost of about 10 s** loading the embedding model
(`embedder()` caches it per process). Any first-request SLA has to account for that
or warm the model at startup.

An earlier spot-check on the 353-paragraph corpus, run while an extraction and a
harvest were competing for the same CPU, reported retrieval p95 of 527 ms and
attributed it to that contention without rerunning on a quiet machine. The
attribution looks right: the same bench on a 73x larger corpus and a quiet
machine gives p95 39.25 ms. Treat a p95 in the hundreds of milliseconds as a
signal that something else is running, not as the engine's cost.

Index load is 0.5 s and the server pays it once at startup, so no query pays it.
The embedding model itself is loaded lazily and cached per process
(`embedder()`); a process that has never embedded anything pays several seconds
on its first dense query, which is why the backend builds the index at startup
rather than on first request.

---

## Corpus and index files

Retrieval reads either the real corpus (`data/build/{nodes,edges,paragraphs}.jsonl`)
or a dev fixture built from committed Federal Register XML
(`data/build/retrieval_fixture_*.jsonl`), chosen by `AD_RETRIEVAL_CORPUS`
(`fixture` / `build` / unset = real corpus if `paragraphs.jsonl` exists). Pin it
when measuring, so a concurrent re-ingest cannot move the numbers. The fixture holds
1,368 paragraph lines at measurement; the real build 353.

A missing corpus file raises `CorpusUnavailable` naming the file and the command
that produces it; it is never treated as an empty corpus, because an empty corpus
would turn every query into a refusal and look like a tuning problem.

Build or rebuild the index: `python3 -m engine.retrieval.index --build [--fixture] [--no-dense]`.

---

## Known issues

**Open: the verifier is not wired into the API.** `engine/api/server.py` imports
`evaluate_gate` but not `verify`. After the gate it emits a hard-coded
`verification` event (`kept: len(result.hits)`, `dropped: 0`, `drop_reasons: []`,
`stage_ms: 0.0`) and no answer writer is called. The contract declares `kept` and
`dropped` as lists of sentence indexes (what `Verification.as_payload` produces);
the server sends an integer for `kept`. So the verifier is implemented but not yet
exercised end to end.

**Open: no tests for retrieval or verification.** The 203 passing tests cover
ingest, the contract, fleet and rules; `tests/` has nothing for `engine/retrieval`
or `engine/verify`. The claims in this document about those modules come from
reading the code and from my spot-check, not from a test suite.

**Open: threshold evidence is missing from the tree** (see the thresholds section).
`search.py` and `thresholds.py` both point at this document for tuning evidence that
this document cannot supply.

**Open: the built corpus is a one-month window.** The current index covers 28 ADs
and 353 paragraphs (`docs/ingest.md`). Gate behaviour such as "this AD number is not
in the corpus" is therefore corpus-bounded to that window, and the `NO_EVIDENCE`
detail text states the corpus size for that reason.

**Open: paragraph ids will change on the next ingest rebuild** (label format change,
detailed in `docs/ingest.md`). The index fingerprint is `353:<hash>`, so the index
will correctly refuse to load against a rebuilt corpus until re-indexed; rules
extracted against the old ids need re-running too.

**Limit: `top_cosine` is the cosine of the best *fused* hit**, not the best cosine in
the candidate set. A paragraph that wins on keyword rank but sits outside the dense
top 40 yields `0.0` and a refusal. That is conservative, but it can refuse a query a
looser definition would answer.

**Limit: the entity pass recognizes only what its patterns and the normalization
table know.** A model string absent from the table is not detected as a model; a
model-shaped token that is not in the table goes to `ambiguous`.
