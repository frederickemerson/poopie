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
rather than a copy of it: `tests/test_eval.py` pins
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
| `retrieved_paragraph_ids`, `retrieved_ad_numbers` | `retrieval` |
| `decision`, `decision_available`, `decision_unavailable_reason` | `decision` |
| `sentences[].text`, `.citation_ids` | `answer_delta` |
| `sentences[].kept`, `.drop_reason` | `verification` |
| `refusal_codes`, `refusal_details` | `refusal` |
| `answered`, `answer_status` | `done.envelope.answer_status` |
| `stage_ms`, `total_ms` | `done.stage_timings`, `done.total_ms` |
| `cost_usd` | the `CostLedger` delta across the turn |

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

See `eval/results/report.md` for the generated tables, the per-code refusal recall, the
outcome histogram, the per-stage latencies and the full failure gallery. The summary and
the analysis of the failures are in the sections below.

## 6. What this evaluation cannot tell you

- **Small samples.** Tens of questions per class, not hundreds. Every rate is an order of
  magnitude, not a point estimate, and no confidence interval is reported because with
  these denominators it would be wider than the differences it bracketed.
- **One run, and the writer is not deterministic.** The client does not pin a temperature,
  so a fresh run can draft different sentences. The content-hash cache makes a *repeat* of
  the same run reproducible, but this is a single sample per question and the harness
  reports no variance. A second independent sample would be the honest next step.
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
