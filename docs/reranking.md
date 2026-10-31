# Cross-encoder reranking: measured, and left off

**Result:** reranking is implemented, tested and available behind a flag
(`search(..., rerank=True)`), but `RERANK_DEFAULT = False`. On this corpus it
shows no demonstrable quality gain, and it breaches the 100 ms retrieval target
by roughly 3x at p50 and 5x at p95.

## Method

* Model: `cross-encoder/ms-marco-MiniLM-L6-v2` via `sentence_transformers.CrossEncoder`,
  loaded once per process and cached (a failed load is cached too, so an offline
  laptop pays the timeout once). Text scored is `heading + "\n" + text`, the same
  string that is indexed.
* Pipeline: graph filter, FTS5 + dense, RRF, then the top **24** fused candidates
  are rescored and the top **8** returned. Ties keep RRF order, so output is
  deterministic.
* Measured with `python3 -m engine.retrieval.rerank_bench` against the real
  index (353 paragraphs, 28 ADs, `corpus.kind == "build"`), 25 queries:
  9 name an AD number, 16 are topical. Each query is run with and without
  reranking and the top 8 are compared.
* Latency: 25 queries x 15 runs = 375 samples per arm, wall time of the whole
  `search()` call (graph filter included), model and embedder warmed first, 4
  CPU threads, one laptop. Entity pass and query planning are excluded.

### Labels (the weak part)

Gold labels are my hand judgement, in `QUERIES` in `rerank_bench.py`.
* Named-AD queries: gold is the paragraph *role* that answers the question
  (e.g. "compliance time for AD X" -> `COMPLIANCE`).
* Topical queries: gold is the set of ADs whose text really covers the topic,
  found by grepping the corpus. "fuel pump wiring inspection" has no matching
  text anywhere (no "fuel pump" or "wiring" in any paragraph); I labelled
  AD 2026-21-03 (ATA 28 Fuel) as gold, which is a generous reading.

## Quality results (25 queries)

| Metric | RRF only | + rerank |
|---|---|---|
| Top-1 paragraph changed | - | **9 / 25** (2/9 named, 7/16 topical) |
| Top-8 *set* changed | - | 23 / 25 |
| Named AD in top 3 (9 named queries) | 9 / 9 | 9 / 9, **0 moved in** |
| Right paragraph role at rank 1 (9 named) | 5 / 9 | 4 / 9 |
| Right paragraph role in top 3 (9 named) | 7 / 9 | 7 / 9 |
| Gold AD at rank 1 (16 topical) | 13 / 16 | 13 / 16 |
| Gold AD in top 3 (16 topical) | 14 / 16 | 15 / 16 |
| MRR of first gold AD (16 topical) | 0.862 | 0.885 |

Reading these honestly:

* **"AD number moved into the top 3" is 0, and could not be otherwise.** When
  the query names an AD, the graph filter narrows candidates to that AD's
  ~12 paragraphs, so all of them are already the right AD. Reranking only
  reorders within one AD there. The graph filter, not the reranker, carries
  AD-number precision.
* Within-AD ordering (named queries) got **slightly worse** at rank 1
  (5 -> 4 of 9). The cross-encoder was trained on web passages (MS MARCO) and
  does not know that `COMPLIANCE` is the section that answers "compliance time".
  The paragraph roles come from the document structure and the indexed heading
  already carries that signal into BM25 and the dense arm.
* Topical queries: one more gold AD in the top 3 (14 -> 15 of 16) and a
  0.862 -> 0.885 MRR change. That is one query. It is not distinguishable from
  noise at n=16 and I do not claim it as a win.
* Top-1 changed 9 times, but a changed top-1 is not an improvement: of those 9,
  the gold-based metrics above show net zero at rank 1 (topical) and net -1
  (named).

**Finding: no measurable improvement at this corpus size.** 353 paragraphs
across 28 ADs, with only ~12 candidates once an AD is named, leaves little for a
reranker to fix; the top-1 gold rate is already 13/16 before reranking.

## Latency (contract target: retrieval < 100 ms)

| Arm | p50 | p95 | max | n |
|---|---|---|---|---|
| RRF only | 12.5 ms | 15.3 ms | 24.7 ms | 375 |
| RRF + rerank, window 24 | **311.5 ms** | **560.4 ms** | 893.5 ms | 375 |

Added: about **+299 ms p50, +545 ms p95**. This **breaches the 100 ms target**
(about 3x at p50, 5.6x at p95). Scoring 24 pairs alone takes ~281 ms median on
CPU. I did not change the target.

Window sweep (same 25 queries, 8 runs each), to see whether a smaller window
would fit:

| Window | p50 | p95 |
|---|---|---|
| 8 (reorders the existing top 8 only) | 108.6 ms | 219.5 ms |
| 12 | 146.0 ms | 224.7 ms |
| 16 | 213.9 ms | 317.7 ms |
| 24 | 312.3 ms | 511.0 ms |

No window that can pull in new paragraphs fits under 100 ms on this machine,
and even window 8 misses at p50. (The overall 12.5 ms baseline above is in line
with the p50 12 ms the contract notes record; the p95 there was 48 ms, mine was
15 ms because this run has a warm, quiet machine and a corpus this size.)

## Behaviour and safety

* **Default is off** (`RERANK_DEFAULT` in `engine/retrieval/search.py`) because
  of the breach and the absence of a quality win.
* **Graceful degradation.** If the model cannot be imported, downloaded or run,
  `search()` keeps the RRF order, sets `result.rerank_status = "fallback"` with
  `rerank_reason`, and logs a warning (once per distinct reason). Callers that
  never asked for reranking see `"off"`.
* **Filter guarantee.** Reranking only permutes candidates the graph filter and
  fusion produced. In addition, if the query names an AD that had a paragraph in
  the pre-rerank results, the best of its paragraphs is kept in the final top 8.
* **Refusal signal unchanged.** `top_cosine` stays anchored to the RRF winner,
  so the NO_EVIDENCE threshold does not shift when reranking is toggled. Each
  `Hit` gains `rerank_score` (None when not reranked).

## Recommendation

Keep it off. Revisit if (a) the corpus grows by an order of magnitude so that
fusion has far more near-ties to break, (b) retrieval latency is budgeted
separately (for instance run it concurrently with the plan call, which has
a 1000 ms budget), or (c) a gold set larger than 25 hand-labelled queries is
built. The harness (`rerank_bench.py`) re-runs the whole comparison in about
two minutes, and the three-line change to enable it is `RERANK_DEFAULT = True`.

## Caveats

* One machine, one corpus snapshot, labels by one person; 25 queries cannot
  detect a small effect, and the confidence intervals on 14/16 vs 15/16 are
  wide.
* The latency figures include whatever else the CPU was doing; rerun on the
  demo laptop before drawing a conclusion about that machine.
