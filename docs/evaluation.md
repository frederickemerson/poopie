# Evaluation: the numbers, including the ones that look bad

`docs/positioning.md` names the sharpest item in the competitive table, Gap 4:

> *These are vendor claims. Public claims about citations or "no hallucinations" do not
> independently demonstrate correctness.*

That critique applies to this project too, unless there is a measured error rate. This
document is the measurement: a labelled question set, two arms, the metrics with their
sample sizes, and every case our engine got wrong.

Code: `eval/*.py`. Outputs: `eval/results/runs.jsonl`, `eval/results/metrics.json`,
`eval/results/report.md`. Related: `docs/refusals.md` (what each refusal code means),
`docs/retrieval.md` (the gate and the verifier this measures), `docs/rules.md` (the
applicability decision).

```
python3 -m engine.retrieval.index --build      # once, if the corpus was rebuilt
python3 -m eval.run --arm both                 # ~5 min; re-runs hit the LLM cache
```

---

## 1. The two arms

| | **ours** | **baseline** |
|---|---|---|
| corpus | the built corpus | the same corpus |
| paragraph embeddings | the built index | the same index |
| k | 8 | 8 |
| answer writer | `engine.api.answer.write_answer` | **the same function** |
| entity pass | yes | no |
| query plan | yes (Haiku) | no |
| graph filter before search | yes | no |
| keyword arm + rank fusion | yes | no (cosine only) |
| rules engine / applicability | yes | no |
| citation verifier | yes | no |
| refusal gate | yes | **never refuses** |

The baseline is a strawman on purpose, but it has to be an honest one, so it differs from
the engine *only* by the missing machinery. In particular it calls the engine's own writer
rather than a copy of it: `tests/test_eval_run.py` pins
`eval.baseline.write_answer is engine.api.answer.write_answer`. Two writers, or two
prompts, would let any difference in the numbers be a difference in prompting instead of a
difference in architecture, and the comparison would be worth nothing.

The baseline never refuses, which is the behaviour being measured rather than an oversight:
a naive RAG arm that declined would not be the thing the critique describes. Nothing
inspects its answer afterwards, so it is scored on whatever the writer said.

One asymmetry is worth stating plainly: the writer's system prompt (in
`engine/api/answer.py`) already tells it to quote verbatim and never to write a sentence it
cannot quote. The baseline inherits that discipline for free. A cruder naive-RAG prompt
would look worse, so this comparison is **conservative** — it understates the gap.

## 2. The question set

`eval/questions.py` generates the set *from the built corpus* rather than writing it
against a snapshot, so the set cannot silently drift into asking about ADs that are no
longer loaded. Five classes:

| class | what it is | expected |
|---|---|---|
| `answerable` | a correct, citable answer exists | an answer |
| `applicability_trap` | looks answerable; the honest answer is a refusal | a specific refusal code |
| `revision` | supersession / which revision is current | an answer (plus a banner) |
| `out_of_scope` | not an AD question at all | `OUT_OF_SCOPE` |
| `ambiguous` | under-specified; the engine should ask | `NEED_CONFIG` |

Every label — the expected refusal code, the expected decision, the expected AD — is
written down in `eval/questions.py` before anything runs. The composition of the set that
produced the numbers below is in `eval/results/report.md`, printed from
`eval.questions.summary()` so a reader can see how many questions are traps.

## 3. How a run is recorded

The engine arm is driven through `engine.api.server._stream` — the same generator the UI
consumes — and every recorded field comes off its contract-pinned SSE events:

| record field | source |
|---|---|
| `cost_usd`, `model_calls`, `cached_calls` | the ledger rows this turn appended |
| `retrieved_paragraph_ids`, `retrieved_ad_numbers` | `retrieval` |
| `decision`, `decision_available`, `decision_unavailable_reason` | `decision` |
| `sentences[].text`, `.citation_ids` | `answer_delta` |
| `sentences[].kept`, `.drop_reason` | `verification` |
| `refusal_codes`, `refusal_details` | `refusal` |
| `answered`, `answer_status` | `done.envelope.answer_status` |
| `stage_ms`, `total_ms` | `done.stage_timings`, `done.total_ms` |

The harness decides nothing about the engine's behaviour; it records it. `answered` in
particular is the engine's own `answer_status`, not something the eval re-derives, so the
eval scores the same verdict the UI renders.

**Each refusal records where it came from.** A refusal that arrives *before* the
`verification` event was decided by the gate, before any prose existed. One that arrives
*after* it is a drafted answer that failed citation verification. Both are refusals to the
user, and both count in the metrics — but they are different claims about the system, so
the report says which is which. Being stopped by the gate is the design working; being
stopped by the verifier means the model had already written the sentence.

Two measurement details:

- **Warm-up is excluded.** The first call into `sentence-transformers` pays a one-off model
  load of seconds. `eval.run.warm_up` pays it before any timing is taken, and the report
  states what it cost, so the retrieval percentiles are not a measurement of a model loader.
- **A cached call is not a latency.** Every run records how many model calls it made and
  how many the content-hash cache served. A stage whose clock is a model call
  (`query_plan`, `answer`, and the `total` containing them) is reported only from runs that
  made at least one fresh call; otherwise it reads `n/a` with the reason. Without that
  rule a cache-served re-run would publish a 1 ms answer stage, and a call the budget
  refused would publish a 19 ms one. The local stages never call a model and stand either
  way.
- **Percentiles are nearest-rank** (`eval.metrics._percentile`): no interpolation, so every
  latency printed is one that was really observed. Each cell carries its own `n`, which
  differs per stage because stages that only run on the answer path have fewer observations.

## 4. The metrics

Each is a pure function over the recorded runs in `eval/metrics.py`, returning the
numerator and denominator alongside the ratio. `eval/results/metrics.json` is that
computation, so every number in the report is recomputable from `runs.jsonl` by anyone.

| metric | numerator | denominator |
|---|---|---|
| `wrong_answer_rate` | should have refused, answered confidently | questions whose expected code blocks an answer |
| `refusal_recall` | refused **with the expected code** | questions expecting a refusal |
| `false_refusal_rate` | refused anyway | questions expecting an answer |
| `target_ad_recall` | retrieved the AD the question named | questions naming an AD |
| `citation_precision` | cited ids resolving into that query's retrieved set | all cited ids |
| `citation_coverage` | drafted sentences carrying ≥1 citation | all drafted sentences |
| `applicability_accuracy` | decision matching the label | labelled decisions **the engine produced** |
| `latency_p50` / `p95` | — | per stage, with `n` |

Four of these deserve their reasoning stated:

**`wrong_answer_rate` is the headline.** In a safety domain a confident wrong answer is
worse than no answer, so this is the number that matters and it is the first row of the
table. `SUPERSEDED` is excluded from its denominator by construction: the contract marks it
`blocks_answer: false`, so answering there is correct.

**`refusal_recall` demands the right code.** A refusal carrying the wrong code counts as a
miss. `docs/refusals.md` is explicit about why — the code is the part that tells the user
*who can resolve the blocker*, so `NO_EVIDENCE` where `EXTERNAL_SOURCE_REQUIRED` was due
sends an engineer hunting through a corpus for a document that was never missing. Recall is
also reported per code, because the codes are not interchangeable.

**`citation_precision` is narrower than it sounds.** It asks only whether a cited paragraph
was in the retrieved set for that query, judged by `contracts.contract.validate_citation`.
That catches a fabricated or cross-query citation; it does not ask whether the span
supports the sentence. The support check is the verifier's, and its drop reasons are
reported separately — so a high citation precision beside a large verifier drop count is
not a contradiction, it is the two gates doing different jobs.

**`applicability_accuracy` excludes rather than scores.** A labelled question for which the
engine produced no decision at all is excluded and counted, not marked wrong. Marking it
wrong would blame the rules engine for a gap in rule extraction; marking it right would be
a lie. The exclusion count rides next to the rate.

**An n/a is never a 0%.** When a denominator is zero, or every case had to be excluded, the
metric reads `n/a (reason)`. `eval/metrics.py` cannot render a rate without its sample size:
three correct answers out of three print as `3/3 (100.0%)`, never as `100%`.

**No threshold was tuned here.** `engine/verify/thresholds.py` states that its values are
reasoned defaults that have never been swept, and asks for exactly the pair of numbers this
harness produces: the false-refusal rate and the wrong-answer rate at the chosen value.
This run is the first measurement at those defaults. Nothing was adjusted to improve a
number and then reported as if it had been held out.

## 5. Results

One run of 51 questions through both arms, on the 25,687-paragraph corpus (2,117 ADs;
2,151 of 2,161 revisions carry extracted rules). `eval/results/report.md` carries the
generated tables, the outcome histogram, the per-stage latencies and the full gallery;
`metrics.json` carries the same numbers as data. Sample sizes are in every cell because
with 51 questions they are the difference between a result and an anecdote.

| metric | ours | baseline |
|---|---|---|
| **`wrong_answer_rate`** | **8/31 (25.8%)** | **21/21 (100.0%)** |
| `refusal_recall` | 8/31 (25.8%) | 0/21 (0.0%) |
| `false_refusal_rate` | 14/20 (70.0%) | 0/20 (0.0%) |
| `target_ad_recall` | 36/36 (100.0%) | 0/36 (0.0%) |
| `citation_precision` | 80/80 (100.0%) | 34/34 (100.0%) |
| `citation_coverage` | 79/79 (100.0%) | 34/56 (60.7%) |
| `applicability_accuracy` | 6/6 (100.0%) [10 excluded] | n/a (no decision was available for any of the 10 labelled questions) |

Refusal recall per code, because the codes are not interchangeable:

| expected code | ours | baseline |
|---|---|---|
| `EXTERNAL_SOURCE_REQUIRED` | 0/10 (0.0%) | 0/10 (0.0%) |
| `NEED_CONFIG` | 4/11 (36.4%) | 0/1 (0.0%) |
| `NO_EVIDENCE` | 3/3 (100.0%) | 0/3 (0.0%) |
| `OUT_OF_SCOPE` | 1/7 (14.3%) | 0/7 (0.0%) |

**What the engine buys.** On the 31 questions where the honest answer is a refusal, the
baseline answered confidently every single time it could be funded (21/21) and the engine
did so 8 times out of 31. Both arms use the same model and the same writer prompt, so that
gap is the machinery, not the prompt. The sharpest number is `target_ad_recall`: asked
*"what is the unsafe condition addressed by AD 2001-25-05?"*, cosine-only top-8 retrieval
over 25,687 paragraphs retrieved the named AD **0 times out of 36**, while the
graph-filtered arm retrieved it 36/36. Embeddings do not encode a docket number, so the
baseline returns paragraphs that are *about* unsafe conditions — and the same few ADs
recur across unrelated questions. Every citation it then produces is real and resolvable
(34/34): it is citing the wrong directive correctly, which is the failure mode that reads
best and misleads hardest. The engine's advantage here is not a better model, it is
knowing the question names an entity and filtering candidates to it.

**What it costs.** `false_refusal_rate` is 14/20 (70.0%) — worse than either earlier pass,
and the most important negative number in this document. 12 of those 14 came from the
citation verifier, not the refusal gate, and **7 of the 12 had already verified a cited
sentence** and threw it away: the kept fraction was 1 of 2 or 1 of 3 drafted sentences,
below `MIN_KEPT_FRACTION = 0.60`, so a partly-supported answer became a flat
`NO_EVIDENCE`. Across the arm, 41 of 79 drafted sentences survived verification, dropped
for `numeric_term_absent_from_cited_span` (19) and `term_coverage_below_threshold` (21).
This is the pair of numbers `engine/verify/thresholds.py` asked for, at the untuned
defaults, and it says the kept-fraction rule is far too blunt for short answers: one
dropped sentence out of two flips a correct, citable answer into a refusal. Nothing was
re-tuned to improve the table — fixing it is the next change, and it needs a fresh
measurement afterwards, not this one.

**Latency is not in the table above.** `eval/results/report.md` reports every
model-backed stage as `n/a (cache-served: no fresh model call to time)`, because the
published run was re-rendered from the content-hash LLM cache, where an answer "takes"
about a millisecond. `eval/metrics.py` drops those timings rather than print them. The
local stages are real: retrieval p50 21 ms / p95 67 ms for the engine (the graph filter
plus the keyword arm plus fusion) against 11 ms / 15 ms for cosine-only. The one cold pass
whose wall clock measured fresh model calls ran the earlier 49-question set, and recorded
`answer` p50 2684 ms / p95 5949 ms and end-to-end p50 2874 ms / p95 7060 ms for the engine,
against `answer` p50 1991 ms / p95 5441 ms and end-to-end p50 2043 ms / p95 5453 ms for the
baseline — so the machinery costs roughly 0.8 s per question, nearly all of it the Haiku
query plan. Those four numbers are **not** recomputable from the published `runs.jsonl`:
the cold records were overwritten by the warm re-render before being copied, and the
budget was then exhausted, so they cannot be re-measured. They are quoted here with that
provenance rather than left out or silently refreshed from a cached run.

### Failure gallery: the three that matter

`eval/results/report.md` lists all 37 of the engine's failures. These are the three
patterns behind them.

**1. "Does this AD apply to my aircraft?" is answered instead of refused — 7 of the 8
wrong answers.** `trap-01` … `trap-07` all ask that question with no aircraft named, about
ADs whose applicability is delegated to an external document (an EASA AD, a Transport
Canada AD, a manufacturer's requirements bulletin). Expected: `EXTERNAL_SOURCE_REQUIRED`.
Recall for that code is **0/10**. The root cause is a sequencing bug, not a missing rule:
the rules engine returns no decision at all ("No specific aircraft identified. Applicability
needs a tail number or serial number"), the refusal gate therefore never sees a decision to
reason about, and the writer answers from the applicability paragraph. So `trap-01` replies
with the AS350/AS355 model list and `trap-05` with *"the AD's stated applicability is by
reference to a Boeing requirements bulletin, Issue 002 dated November 25, 2024"* — both
true sentences about the *document*, offered as answers to a question about an *aircraft*.
Whether a revision delegates its applicability is a property of the revision, knowable with
zero aircraft information; it has to be checked before the aircraft resolves, not after.
This is the worst failure in the set: it is the product's core question, and the answer is
fluent, cited and wrong.

**2. Right instinct, wrong code — 15 refusals.** The engine withheld an answer but named
the wrong blocker: `NEED_CONFIG` → `NO_EVIDENCE` (5), `OUT_OF_SCOPE` → `NO_EVIDENCE` (4),
`EXTERNAL_SOURCE_REQUIRED` → `NO_EVIDENCE` (3), `NEED_CONFIG` → `CANNOT_DETERMINE` (2),
and one `OUT_OF_SCOPE` answered with `SUPERSEDED` + `NO_EVIDENCE`. 23 of the engine's 38
refusals carried `NO_EVIDENCE` from the verifier, which is the code that means *the corpus
does not contain this*. For a question like *"how do I file a service difficulty report?"*
(`OUT_OF_SCOPE`) or an under-specified one (`NEED_CONFIG`) that is a false statement about
the corpus, and per `docs/refusals.md` it sends the user to the wrong remedy: hunting for a
document instead of supplying a tail number or asking somewhere else. `NO_EVIDENCE` is
acting as a catch-all, and the verifier can only ever produce that one code — the
information needed to pick a better one exists upstream, at the gate.

**3. Verified answers discarded — 14 false refusals, 12 from the verifier.** `ans-02`,
`ans-05`, `ans-09`, `ans-12`, `rev-02`, `rev-07` each kept exactly one verified, cited
sentence and still returned `NO_EVIDENCE`, because one dropped sentence out of two or three
put them under `MIN_KEPT_FRACTION`. `rev-03` and `rev-04` never drafted anything: the gate
refused on the `NO_EVIDENCE_COSINE_MIN = 0.30` cosine floor although retrieval had the
right AD in hand (`target_ad_recall` is 36/36). A system that verifies a sentence and then
withholds it is strictly worse than one that shows the verified sentence and marks what it
dropped, and the fix is in the gate's arithmetic rather than in the model.

## 6. What this evaluation cannot tell you

- **Small samples.** Tens of questions per class, not hundreds. Every rate is an order of
  magnitude, not a point estimate, and no confidence interval is reported because with
  these denominators it would be wider than the differences it bracketed.
- **Ten of the baseline's 51 runs were never funded.** The project ledger reached $1.9809
  of its $2.00 cap during the run, so the writer call for `cfg-01`…`cfg-06` and
  `amb-02`…`amb-05` was refused by the budget. Those runs are recorded as errors and
  excluded from every rate except `target_ad_recall`, which measures retrieval and
  therefore still counts them — which is why the baseline's `wrong_answer_rate`
  denominator is 21 where the engine's is 31. The budget is now spent, so this cannot be
  completed without raising the cap.
- **The configuration changed under the harness.** An earlier pass of this same code
  measured the engine when only 29 of 2,161 revisions carried extracted rules; rule
  extraction finished mid-task and the published run has 2,151. The question set is
  generated from the graph, so it grew from 49 questions to 51 at the same time. Numbers
  from the earlier passes are not comparable and are not reported here, except for the
  four latency figures in §5 that are labelled with that provenance.
- **One question is duplicated.** `trap-05` and `trap-06` are both "Does AD 2026-20-10
  apply to my aircraft?", so the 10 `EXTERNAL_SOURCE_REQUIRED` cases cover 9 distinct
  questions. The duplicate is counted, not dropped, and both runs failed the same way.
- **One run, and the writer is not deterministic.** The client does not pin a temperature,
  so a fresh run can draft different sentences. The content-hash cache makes a *repeat* of
  the same run reproducible, but this is a single sample per question and the harness
  reports no variance. A second independent sample would be the honest next step.
- **A repeat is reproducible but not re-measured.** Re-running `eval.run` after a pass
  replays the cache: the verdicts are identical and free, which is how the published
  report was re-rendered, but no model stage is timed again. `eval/metrics.py` treats a
  model-stage timing as admissible only from a run that made a fresh call, so after a
  warm re-render the latency table says `n/a` rather than claiming a 1 ms answer. That
  check cannot recover a wall clock that was never recorded: the only cold timings this
  project has are the four quoted in §5.
- **No model judges the prose.** `answer_correctness` from the contract's `eval_metrics` is
  not implemented here: scoring whether a sentence truly answers the question needs either
  hand labels for every answer or an LLM judge, and an LLM judge would reintroduce exactly
  the unmeasured claim this document exists to avoid. `target_ad_recall` is the objective
  part of it — an arm that never retrieved the directive it was asked about cannot have
  answered from it — and the verifier's drop reasons cover citation support. Whether the
  remaining prose is *useful* is unmeasured.
- **The labels come from the same corpus as the answers.** `eval/questions.py` reads the
  built graph to decide what to ask and what to expect, so a systematic ingest error would
  produce a matching question and a matching expectation and go undetected. The set tests
  the engine against its own corpus, not against the Federal Register.
- **Generated labels are not hand-checked.** Where the generator's expectation turns out not
  to be supported by the corpus, the report's label-audit notes say so and the question is
  still counted against us. It is disclosed, not dropped.
- **The corpus is a moving target.** The numbers belong to one commit and one corpus
  fingerprint, both printed in the report header. A re-ingest changes the question set, so
  numbers from different corpora are not comparable.
- **The cost cap is project-wide.** `CostLedger` is one append-only ledger for the whole
  project, so `cap_usd=2.0` in the harness means "total project spend must stay under $2",
  not "the eval may spend $2". A concurrent ingest or rule extraction consumes the same
  budget and can make the eval refuse to run — which is the ledger behaving correctly.
- **The baseline is one baseline.** Cosine-only top-8 with the engine's writer. A different
  naive arm — BM25, a reranker, a bigger k, a cruder prompt — would score differently. The
  claim here is not "this beats all naive RAG"; it is "these specific missing components
  account for this specific difference on this set".
