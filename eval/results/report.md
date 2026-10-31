# Evaluation: traceable AD engine vs. plain vector RAG

Generated 2026-10-31 05:00 UTC at commit `9bcf35c`. Method and caveats: `docs/evaluation.md`.

- Corpus `build`: 25687 paragraphs, 2161 revisions, 2117 ADs
- Fleet: 478 real aircraft; 2151 revisions carry extracted rules
- Both arms: same corpus, same k=8, same writer prompt, answers written by `claude-sonnet-5-5`; the engine arm also plans with `claude-haiku-5-5`
- Spend to date: $1.9809 of the $2.00 cap; 446 of 7023 calls served from cache
- Embedding model warm-up (8858 ms) excluded from all timings

## Question set

51 questions, generated from the built corpus by `eval/questions.py`. 31 are traps where the honest answer is a refusal.

| class | n |
|---|---|
| ambiguous | 5 |
| answerable | 12 |
| applicability_trap | 19 |
| out_of_scope | 7 |
| revision | 8 |
| **expects a refusal** | **31** |

| expected refusal code | n |
|---|---|
| EXTERNAL_SOURCE_REQUIRED | 10 |
| NEED_CONFIG | 11 |
| NO_EVIDENCE | 3 |
| OUT_OF_SCOPE | 7 |

## Results

Numerator/denominator first in every cell: a rate with no sample size is not a number, and a metric with no data to compute it from reads `n/a` with the reason.

| metric | ours (n=51) | baseline (n=51) |
|---|---|---|
| wrong_answer_rate | 8/31 (25.8%) | 21/21 (100.0%) |
| refusal_recall | 8/31 (25.8%) | 0/31 (0.0%) |
| false_refusal_rate | 14/20 (70.0%) | 0/20 (0.0%) |
| target_ad_recall | 36/36 (100.0%) | 0/30 (0.0%) |
| citation_precision | 80/80 (100.0%) | 34/34 (100.0%) |
| citation_coverage | 79/79 (100.0%) | 34/56 (60.7%) |
| applicability_accuracy | 6/6 (100.0%) [10 excluded] | n/a (no decision was available for any of the 10 labelled questions) |

## Refusal recall per code

The wrong code counts as a miss: the code is what tells the user who can resolve the blocker.

| expected code | ours | baseline |
|---|---|---|
| EXTERNAL_SOURCE_REQUIRED | 0/10 (0.0%) | 0/10 (0.0%) |
| NEED_CONFIG | 4/11 (36.4%) | 0/11 (0.0%) |
| NO_EVIDENCE | 3/3 (100.0%) | 0/3 (0.0%) |
| OUT_OF_SCOPE | 1/7 (14.3%) | 0/7 (0.0%) |

## Outcomes

| outcome | ours | baseline |
|---|---|---|
| answered | 6 | 20 |
| error | 0 | 10 |
| false_refusal | 14 | 0 |
| refusal_correct | 8 | 0 |
| refusal_wrong_code | 15 | 0 |
| wrong_answer | 8 | 21 |

## Latency per stage, p50 / p95

| stage | ours | baseline |
|---|---|---|
| answer | 1 ms (n=37) / 18 ms (n=37) | 1 ms (n=51) / 19 ms (n=51) |
| applicability | 0 ms (n=51) / 0 ms (n=51) | n/a |
| entity_pass | 0 ms (n=51) / 0 ms (n=51) | n/a |
| query_plan | 1 ms (n=51) / 1037 ms (n=51) | n/a |
| retrieval | 21 ms (n=51) / 63 ms (n=51) | 11 ms (n=51) / 15 ms (n=51) |
| total | 25 ms (n=51) / 1065 ms (n=51) | 13 ms (n=51) / 32 ms (n=51) |
| verify | 0 ms (n=37) / 0 ms (n=37) | n/a |

## Failure gallery

37 of 51 questions went wrong or could not be resolved. All of them are here.

**ans-02** (answerable) — What is the unsafe condition addressed by AD 2001-25-05?

- expected: an answer
- returned: NO_EVIDENCE (verifier)
- outcome: `false_refusal`
- reason: refused NO_EVIDENCE on an answerable question

**ans-04** (answerable) — What is the unsafe condition addressed by AD 2004-06-07?

- expected: an answer
- returned: NO_EVIDENCE (verifier)
- outcome: `false_refusal`
- reason: refused NO_EVIDENCE on an answerable question

**ans-05** (answerable) — What is the unsafe condition addressed by AD 2004-12-17?

- expected: an answer
- returned: NO_EVIDENCE (verifier)
- outcome: `false_refusal`
- reason: refused NO_EVIDENCE on an answerable question

**ans-07** (answerable) — What is the unsafe condition addressed by AD 2004-25-15?

- expected: an answer
- returned: NO_EVIDENCE (verifier)
- outcome: `false_refusal`
- reason: refused NO_EVIDENCE on an answerable question

**ans-09** (answerable) — What is the unsafe condition addressed by AD 2009-17-05?

- expected: an answer
- returned: NO_EVIDENCE (verifier)
- outcome: `false_refusal`
- reason: refused NO_EVIDENCE on an answerable question

**ans-10** (answerable) — What is the unsafe condition addressed by AD 2009-20-02?

- expected: an answer
- returned: NO_EVIDENCE (verifier)
- outcome: `false_refusal`
- reason: refused NO_EVIDENCE on an answerable question

**ans-12** (answerable) — What is the unsafe condition addressed by AD 2010-09-11?

- expected: an answer
- returned: NO_EVIDENCE (verifier)
- outcome: `false_refusal`
- reason: refused NO_EVIDENCE on an answerable question

**trap-01** (applicability_trap) — Does AD 2026-20-03 apply to my aircraft?

- expected: EXTERNAL_SOURCE_REQUIRED, decision CANNOT_DETERMINE
- returned: answered: The applicability paragraph lists Airbus Helicopters models AS350B, AS350BA, AS350B1, AS350B2, AS350B3, AS350D, AS355E, AS355F, AS355F1, AS355F2, AS355N, AS355NP, EC120B, and EC130B4, certificated in any category.
- outcome: `wrong_answer`
- reason: answered confidently where EXTERNAL_SOURCE_REQUIRED was expected; no decision was available (No specific aircraft identified. Applicability needs a tail number or serial number; a model alone matches many aircraft.)

**trap-02** (applicability_trap) — Does AD 2026-20-05 apply to my aircraft?

- expected: EXTERNAL_SOURCE_REQUIRED, decision CANNOT_DETERMINE
- returned: answered: The AD is stated to be effective November 5, 2026, and the documents are adopted but not yet effective.
- outcome: `wrong_answer`
- reason: answered confidently where EXTERNAL_SOURCE_REQUIRED was expected; no decision was available (No specific aircraft identified. Applicability needs a tail number or serial number; a model alone matches many aircraft.)

**trap-03** (applicability_trap) — Does AD 2026-20-07 apply to my aircraft?

- expected: EXTERNAL_SOURCE_REQUIRED, decision CANNOT_DETERMINE
- returned: answered: The applicability paragraph identifies the affected helicopters by reference to EASA AD 2026-0165, dated August 18, 2026.
- outcome: `wrong_answer`
- reason: answered confidently where EXTERNAL_SOURCE_REQUIRED was expected; no decision was available (No specific aircraft identified. Applicability needs a tail number or serial number; a model alone matches many aircraft.)

**trap-04** (applicability_trap) — Does AD 2026-20-09 apply to my aircraft?

- expected: EXTERNAL_SOURCE_REQUIRED, decision CANNOT_DETERMINE
- returned: answered: The AD's stated applicability covers Bombardier, Inc., Model BD-700-2A12 airplanes as identified in Transport Canada AD CF-2025-49, dated October 1, 2025.
- outcome: `wrong_answer`
- reason: answered confidently where EXTERNAL_SOURCE_REQUIRED was expected; no decision was available (No specific aircraft identified. Applicability needs a tail number or serial number; a model alone matches many aircraft.)

**trap-05** (applicability_trap) — Does AD 2026-20-10 apply to my aircraft?

- expected: EXTERNAL_SOURCE_REQUIRED, decision CANNOT_DETERMINE
- returned: answered: The AD's stated applicability is by reference to a Boeing requirements bulletin, Issue 002 dated November 25, 2024.
- outcome: `wrong_answer`
- reason: answered confidently where EXTERNAL_SOURCE_REQUIRED was expected; no decision was available (No specific aircraft identified. Applicability needs a tail number or serial number; a model alone matches many aircraft.)

**trap-06** (applicability_trap) — Does AD 2026-20-10 apply to my aircraft?

- expected: EXTERNAL_SOURCE_REQUIRED, decision CANNOT_DETERMINE
- returned: answered: The AD's stated applicability is by reference to a Boeing requirements bulletin, Issue 002 dated November 25, 2024.
- outcome: `wrong_answer`
- reason: answered confidently where EXTERNAL_SOURCE_REQUIRED was expected; no decision was available (No specific aircraft identified. Applicability needs a tail number or serial number; a model alone matches many aircraft.)

**trap-07** (applicability_trap) — Does AD 2026-20-12 apply to my aircraft?

- expected: EXTERNAL_SOURCE_REQUIRED, decision CANNOT_DETERMINE
- returned: answered: The AD is effective October 23, 2026.
- outcome: `wrong_answer`
- reason: answered confidently where EXTERNAL_SOURCE_REQUIRED was expected; no decision was available (No specific aircraft identified. Applicability needs a tail number or serial number; a model alone matches many aircraft.)

**trap-08** (applicability_trap) — Does AD 2026-20-14 apply to my aircraft?

- expected: EXTERNAL_SOURCE_REQUIRED, decision CANNOT_DETERMINE
- returned: NO_EVIDENCE (verifier)
- outcome: `refusal_wrong_code`
- reason: refused NO_EVIDENCE where EXTERNAL_SOURCE_REQUIRED was expected; the code is what tells the user who can resolve the blocker, so the wrong code is a miss

**trap-09** (applicability_trap) — Does AD 2026-21-07 apply to my aircraft?

- expected: EXTERNAL_SOURCE_REQUIRED, decision CANNOT_DETERMINE
- returned: NO_EVIDENCE (verifier)
- outcome: `refusal_wrong_code`
- reason: refused NO_EVIDENCE where EXTERNAL_SOURCE_REQUIRED was expected; the code is what tells the user who can resolve the blocker, so the wrong code is a miss

**trap-10** (applicability_trap) — Does AD 2026-21-08 apply to my aircraft?

- expected: EXTERNAL_SOURCE_REQUIRED, decision CANNOT_DETERMINE
- returned: NO_EVIDENCE (verifier)
- outcome: `refusal_wrong_code`
- reason: refused NO_EVIDENCE where EXTERNAL_SOURCE_REQUIRED was expected; the code is what tells the user who can resolve the blocker, so the wrong code is a miss

**cfg-04** (applicability_trap) — Does AD 2020-26-16 apply to N220CY?

- expected: NEED_CONFIG, decision CANNOT_DETERMINE
- returned: CANNOT_DETERMINE (gate)
- outcome: `refusal_wrong_code`
- reason: refused CANNOT_DETERMINE where NEED_CONFIG was expected; the code is what tells the user who can resolve the blocker, so the wrong code is a miss

**cfg-06** (applicability_trap) — Does AD 2021-02-01 apply to N220CY?

- expected: NEED_CONFIG, decision CANNOT_DETERMINE
- returned: CANNOT_DETERMINE (gate)
- outcome: `refusal_wrong_code`
- reason: refused CANNOT_DETERMINE where NEED_CONFIG was expected; the code is what tells the user who can resolve the blocker, so the wrong code is a miss

**rev-01** (revision) — Is AD 2000-09-05 the current revision, or has it been superseded?

- expected: an answer
- returned: NO_EVIDENCE (verifier)
- outcome: `false_refusal`
- reason: refused NO_EVIDENCE on an answerable question

**rev-02** (revision) — Is AD 2001-25-05 the current revision, or has it been superseded?

- expected: an answer
- returned: NO_EVIDENCE (verifier)
- outcome: `false_refusal`
- reason: refused NO_EVIDENCE on an answerable question

**rev-03** (revision) — Is AD 2004-05-25 the current revision, or has it been superseded?

- expected: an answer
- returned: NO_EVIDENCE (gate)
- outcome: `false_refusal`
- reason: refused NO_EVIDENCE on an answerable question

**rev-04** (revision) — Is AD 2004-06-07 the current revision, or has it been superseded?

- expected: an answer
- returned: NO_EVIDENCE (gate)
- outcome: `false_refusal`
- reason: refused NO_EVIDENCE on an answerable question

**rev-05** (revision) — Is AD 2004-12-17 the current revision, or has it been superseded?

- expected: an answer
- returned: NO_EVIDENCE (verifier)
- outcome: `false_refusal`
- reason: refused NO_EVIDENCE on an answerable question

**rev-07** (revision) — Is AD 2004-25-15 the current revision, or has it been superseded?

- expected: an answer
- returned: NO_EVIDENCE (verifier)
- outcome: `false_refusal`
- reason: refused NO_EVIDENCE on an answerable question

**rev-08** (revision) — Is AD 2005-01-04 the current revision, or has it been superseded?

- expected: an answer
- returned: NO_EVIDENCE (verifier)
- outcome: `false_refusal`
- reason: refused NO_EVIDENCE on an answerable question

**oos-01** (out_of_scope) — What is the MEL dispatch limit for an inoperative APU?

- expected: OUT_OF_SCOPE
- returned: NO_EVIDENCE (verifier)
- outcome: `refusal_wrong_code`
- reason: refused NO_EVIDENCE where OUT_OF_SCOPE was expected; the code is what tells the user who can resolve the blocker, so the wrong code is a miss

**oos-02** (out_of_scope) — Who is the CEO of Boeing?

- expected: OUT_OF_SCOPE
- returned: SUPERSEDED (gate), NO_EVIDENCE (verifier)
- outcome: `refusal_wrong_code`
- reason: refused SUPERSEDED, NO_EVIDENCE where OUT_OF_SCOPE was expected; the code is what tells the user who can resolve the blocker, so the wrong code is a miss

**oos-03** (out_of_scope) — Write me a pre-flight checklist for a Cessna 172.

- expected: OUT_OF_SCOPE
- returned: NO_EVIDENCE (gate)
- outcome: `refusal_wrong_code`
- reason: refused NO_EVIDENCE where OUT_OF_SCOPE was expected; the code is what tells the user who can resolve the blocker, so the wrong code is a miss

**oos-04** (out_of_scope) — What is the current price of jet fuel?

- expected: OUT_OF_SCOPE
- returned: NO_EVIDENCE (verifier)
- outcome: `refusal_wrong_code`
- reason: refused NO_EVIDENCE where OUT_OF_SCOPE was expected; the code is what tells the user who can resolve the blocker, so the wrong code is a miss

**oos-05** (out_of_scope) — Which ADs apply to my Sukhoi Superjet 100?

- expected: OUT_OF_SCOPE
- returned: NO_EVIDENCE (verifier)
- outcome: `refusal_wrong_code`
- reason: refused NO_EVIDENCE where OUT_OF_SCOPE was expected; the code is what tells the user who can resolve the blocker, so the wrong code is a miss

**oos-07** (out_of_scope) — How do I file a service difficulty report?

- expected: OUT_OF_SCOPE
- returned: answered: As an example of an AD-specific report, one AD requires submitting the report to Boeing Service Engineering by sending a service request using the Boeing Communication System (BCS).
- outcome: `wrong_answer`
- reason: answered confidently where OUT_OF_SCOPE was expected; no decision was available (No specific aircraft identified. Applicability needs a tail number or serial number; a model alone matches many aircraft.)

**amb-01** (ambiguous) — Does this AD apply to my aircraft?

- expected: NEED_CONFIG
- returned: NO_EVIDENCE (gate)
- outcome: `refusal_wrong_code`
- reason: refused NO_EVIDENCE where NEED_CONFIG was expected; the code is what tells the user who can resolve the blocker, so the wrong code is a miss

**amb-02** (ambiguous) — What do I need to do?

- expected: NEED_CONFIG
- returned: NO_EVIDENCE (verifier)
- outcome: `refusal_wrong_code`
- reason: refused NO_EVIDENCE where NEED_CONFIG was expected; the code is what tells the user who can resolve the blocker, so the wrong code is a miss

**amb-03** (ambiguous) — Is my 767 affected?

- expected: NEED_CONFIG
- returned: NO_EVIDENCE (verifier)
- outcome: `refusal_wrong_code`
- reason: refused NO_EVIDENCE where NEED_CONFIG was expected; the code is what tells the user who can resolve the blocker, so the wrong code is a miss

**amb-04** (ambiguous) — When is it due?

- expected: NEED_CONFIG
- returned: NO_EVIDENCE (verifier)
- outcome: `refusal_wrong_code`
- reason: refused NO_EVIDENCE where NEED_CONFIG was expected; the code is what tells the user who can resolve the blocker, so the wrong code is a miss

**amb-05** (ambiguous) — Which revision should I be reading?

- expected: NEED_CONFIG
- returned: NO_EVIDENCE (verifier)
- outcome: `refusal_wrong_code`
- reason: refused NO_EVIDENCE where NEED_CONFIG was expected; the code is what tells the user who can resolve the blocker, so the wrong code is a miss


## What this evaluation cannot tell you

- 10 question(s) carry a labelled decision the engine could not produce at all; they are excluded from `applicability_accuracy` rather than scored, and each record says why.
- 10 run(s) raised instead of returning a verdict (baseline: 10) and are **excluded from every rate above**, so a denominator can be smaller than the class it came from. Each record carries the exception text; the commonest cause is the shared cost ledger refusing a call (amb-02, amb-03, amb-04, amb-05, cfg-01, cfg-02, cfg-03, cfg-04, cfg-05, cfg-06).
- 22 of our refusals came from the verifier dropping too much of a drafted answer, not from the gate deciding up front. That is a later and weaker kind of save: the model had already written the sentence and only citation verification stopped it (ans-02, ans-04, ans-05, ans-07, ans-09, ans-10, ans-12, trap-08, trap-09, trap-10, rev-01, rev-02, rev-05, rev-07, rev-08, oos-01, oos-04, oos-05, amb-02, amb-03, amb-04, amb-05).
- Small sample: 51 questions, 31 of them traps. Read every rate as an order of magnitude, not a point estimate.
- No threshold was tuned for this run, and none has been tuned at all: `engine/verify/thresholds.py` states that its values are untuned defaults (term coverage 0.5, kept fraction 0.6, NO_EVIDENCE cosine floor 0.3). The false-refusal and wrong-answer rates above are the pair selecting them requires, measured at those defaults.
- `citation_precision` asks only whether a cited paragraph was retrieved for that query, so it catches fabricated ids, not weak support; the verifier's drops are the support measure.

Full records: `runs.jsonl` and `metrics.json`.
