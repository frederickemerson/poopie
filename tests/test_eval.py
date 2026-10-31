"""The metrics, tested on hand-built records. No network, no model, no corpus.

Every metric is a pure function over run records, so each one is tested against
records written out by hand here. That is the point of the shape: if these tests
pass, the numbers in eval/results/report.md are recomputable from
eval/results/runs.jsonl by anybody, without re-running the engine. The recorders
that produce those records -- the baseline arm, the SSE reader, the CLI and the
report -- are covered in ``tests/test_eval_run.py``.

The cases that matter and are therefore pinned:

* a refusal with the *wrong* code counts as a miss, not a hit;
* SUPERSEDED does not count as withholding an answer, because the contract says
  it does not block one;
* a metric with nothing to measure reports n/a with a reason, never 0% or 100%;
* a labelled decision the engine could not produce is excluded, not scored;
* percentiles are nearest-rank, so every reported latency was really observed.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval import metrics as M  # noqa: E402


# --------------------------------------------------------------- record makers


def record(
    qid: str,
    *,
    arm: str = "ours",
    expect_refusal: str | None = None,
    expect_decision: str | None = None,
    expect_ad: str | None = None,
    codes: tuple[str, ...] = (),
    answered: bool = False,
    decision: str | None = None,
    retrieved: tuple[str, ...] = ("r1#(c)",),
    retrieved_ads: tuple[str, ...] = (),
    sentences: tuple[dict, ...] = (),
    citations: tuple[str, ...] = (),
    stage_ms: dict | None = None,
    total_ms: float | None = None,
    error: str | None = None,
) -> dict:
    return {
        "qid": qid,
        "arm": arm,
        "kind": "answerable",
        "question": f"question {qid}",
        "expected": {
            "refusal": expect_refusal,
            "decision": expect_decision,
            "ad_number": expect_ad,
            "paragraph_roles": [],
            "must_mention": [],
        },
        "refusal_codes": list(codes),
        "decision": decision,
        "decision_available": decision is not None,
        "decision_unavailable_reason": None if decision else "no rules extracted",
        "retrieved_paragraph_ids": list(retrieved),
        "retrieved_ad_numbers": list(retrieved_ads),
        "answered": answered,
        "sentences": list(sentences),
        "citation_ids": list(citations),
        "stage_ms": stage_ms or {},
        "total_ms": total_ms,
        "cost_usd": 0.0,
        "error": error,
    }


def sentence(text: str, citations: tuple[str, ...] = (), kept: bool | None = True) -> dict:
    return {
        "index": 0,
        "text": text,
        "citation_ids": list(citations),
        "kept": kept,
        "drop_reason": None,
        "drop_detail": None,
    }


# ----------------------------------------------------------------------- Rate


def test_rate_prints_sample_size_before_percentage():
    assert M.Rate("x", 7, 9).as_text().startswith("7/9")


def test_rate_with_no_cases_is_na_with_a_reason_not_zero():
    rate = M.Rate("x", 0, 0, reason="no such question in the set")
    assert rate.rate is None
    assert rate.as_text() == "n/a (no such question in the set)"


def test_rate_reports_exclusions_alongside_the_ratio():
    assert "[2 excluded]" in M.Rate("x", 1, 1, excluded=2).as_text()


# ------------------------------------------------------------- refusal recall


def test_refusal_recall_counts_only_the_correct_code():
    runs = [
        record("a", expect_refusal="EXTERNAL_SOURCE_REQUIRED", codes=("EXTERNAL_SOURCE_REQUIRED",)),
        record("b", expect_refusal="EXTERNAL_SOURCE_REQUIRED", codes=("NO_EVIDENCE",)),
        record("c", expect_refusal="NEED_CONFIG", answered=True),
    ]
    rate = M.refusal_recall(runs)
    assert (rate.numerator, rate.denominator) == (1, 3)


def test_refusal_with_wrong_code_is_a_miss_not_a_hit():
    run = record("b", expect_refusal="EXTERNAL_SOURCE_REQUIRED", codes=("NO_EVIDENCE",))
    assert M.outcome(run) == M.OUTCOME_REFUSAL_WRONG_CODE
    assert "who can resolve" in M.reason(run)


def test_refusal_recall_ignores_questions_with_no_expected_refusal():
    rate = M.refusal_recall([record("a", answered=True)])
    assert rate.rate is None and "expects a refusal" in (rate.reason or "")


def test_refusal_recall_by_code_is_reported_per_code():
    runs = [
        record("a", expect_refusal="NO_EVIDENCE", codes=("NO_EVIDENCE",)),
        record("b", expect_refusal="NO_EVIDENCE", answered=True),
        record("c", expect_refusal="OUT_OF_SCOPE", codes=("OUT_OF_SCOPE",)),
    ]
    by_code = M.refusal_recall_by_code(runs)
    assert by_code["NO_EVIDENCE"].as_text().startswith("1/2")
    assert by_code["OUT_OF_SCOPE"].as_text().startswith("1/1")


# ---------------------------------------------------------- false refusals


def test_false_refusal_rate_counts_blocking_refusals_on_answerable_questions():
    runs = [
        record("a", codes=("NO_EVIDENCE",)),
        record("b", answered=True),
        record("c", answered=True),
    ]
    assert M.false_refusal_rate(runs).as_text().startswith("1/3")


def test_superseded_is_not_a_false_refusal_because_it_does_not_block():
    run = record("a", codes=("SUPERSEDED",), answered=True)
    assert M.blocking_refusal_codes(run) == []
    assert M.false_refusal_rate([run]).numerator == 0
    assert M.outcome(run) == M.OUTCOME_ANSWERED


# ---------------------------------------------------------- wrong answers


def test_wrong_answer_rate_counts_confident_answers_where_a_refusal_was_due():
    runs = [
        record("a", expect_refusal="EXTERNAL_SOURCE_REQUIRED", answered=True),
        record("b", expect_refusal="NEED_CONFIG", codes=("NEED_CONFIG",)),
        record("c", answered=True),
    ]
    rate = M.wrong_answer_rate(runs)
    assert (rate.numerator, rate.denominator) == (1, 2)


def test_wrong_answer_rate_excludes_a_non_blocking_expected_code():
    runs = [record("a", expect_refusal="SUPERSEDED", answered=True)]
    rate = M.wrong_answer_rate(runs)
    assert rate.rate is None and rate.excluded == 1


def test_a_silent_miss_is_not_counted_as_a_wrong_answer():
    run = record("a", expect_refusal="NEED_CONFIG", answered=False)
    assert M.outcome(run) == M.OUTCOME_MISSED_REFUSAL_SILENT
    assert M.wrong_answer_rate([run]).numerator == 0


# ------------------------------------------------------------------ citations


def test_citation_precision_rejects_an_id_outside_the_retrieved_set():
    runs = [
        record(
            "a",
            retrieved=("r1#(c)", "r1#(e)"),
            citations=("r1#(c)@0-10", "r9#(z)@0-10"),
        )
    ]
    rate = M.citation_precision(runs)
    assert (rate.numerator, rate.denominator) == (1, 2)


def test_citation_precision_is_na_when_an_arm_cited_nothing():
    rate = M.citation_precision([record("a")])
    assert rate.rate is None and "no citations" in (rate.reason or "")


def test_citation_coverage_counts_sentences_carrying_a_citation():
    runs = [
        record(
            "a",
            sentences=(
                sentence("cited", ("r1#(c)@0-5",)),
                sentence("uncited"),
            ),
        )
    ]
    assert M.citation_coverage(runs).as_text().startswith("1/2")


def test_citation_coverage_is_na_when_there_is_no_prose():
    rate = M.citation_coverage([record("a", codes=("NO_EVIDENCE",))])
    assert rate.rate is None and "no answer prose" in (rate.reason or "")


# -------------------------------------------------------------- applicability


def test_applicability_accuracy_scores_only_available_decisions():
    runs = [
        record("a", expect_decision="APPLIES", decision="APPLIES"),
        record("b", expect_decision="APPLIES", decision="DOES_NOT_APPLY"),
        record("c", expect_decision="CANNOT_DETERMINE"),
    ]
    rate = M.applicability_accuracy(runs)
    assert (rate.numerator, rate.denominator, rate.excluded) == (1, 2, 1)


def test_applicability_accuracy_is_na_when_no_decision_was_available():
    rate = M.applicability_accuracy([record("a", expect_decision="APPLIES")])
    assert rate.rate is None
    assert "no decision was available" in (rate.reason or "")
    assert rate.excluded == 1


def test_target_ad_recall_checks_the_arm_retrieved_the_ad_it_was_asked_about():
    runs = [
        record("a", expect_ad="2026-20-15", retrieved_ads=("2026-20-15",)),
        record("b", expect_ad="2026-20-15", retrieved_ads=("2026-21-04", "2026-21-07")),
    ]
    assert M.target_ad_recall(runs).as_text().startswith("1/2")


def test_target_ad_recall_still_counts_a_run_whose_writer_ran_out_of_budget():
    """Retrieval ran before the model, so its result is a real observation."""
    runs = [
        record("a", expect_ad="2026-20-03", retrieved_ads=("2026-20-03",),
               error="writer produced nothing: cap reached"),
        record("b", expect_ad="2026-20-05", retrieved_ads=("1999-01-01",)),
    ]
    assert M.target_ad_recall(runs).as_text() == "1/2 (50.0%)"


def test_target_ad_recall_excludes_a_run_that_retrieved_nothing_at_all():
    runs = [record("a", expect_ad="2026-20-03", retrieved=(), retrieved_ads=())]
    got = M.target_ad_recall(runs)
    assert got.rate is None and got.excluded == 1 and "retrieved" in (got.reason or "")


# ------------------------------------------------------------------- latency


def test_percentiles_are_nearest_rank_so_every_number_was_observed():
    observed = [10.0, 20.0, 30.0, 40.0]
    assert M._percentile(observed, 50) == 20.0
    assert M._percentile(observed, 95) == 40.0
    assert M._percentile([7.0], 95) == 7.0


def test_latency_is_reported_per_stage_with_its_sample_size():
    runs = [
        record("a", stage_ms={"retrieval": 10.0, "answer": 100.0}, total_ms=110.0),
        record("b", stage_ms={"retrieval": 30.0}, total_ms=40.0),
    ]
    p50 = M.latency_p50(runs)
    assert p50["retrieval"].ms == 10.0 and p50["retrieval"].n == 2
    assert p50["answer"].n == 1 and "n=1" in p50["answer"].as_text()
    assert p50["total"].n == 2


def test_latency_is_na_when_nothing_was_timed():
    p95 = M.latency_p95([record("a")])
    assert p95["total"].ms is None and "nothing was timed" in p95["total"].as_text()


def test_a_cache_served_run_does_not_report_a_model_latency():
    """A cached call returns in ~1 ms; publishing that as a latency is a lie."""
    cold = {**record("a", stage_ms={"retrieval": 20.0, "answer": 2600.0}, total_ms=2700.0),
            "model_calls": 2, "cached_calls": 1}
    warm = {**record("b", stage_ms={"retrieval": 18.0, "answer": 1.0}, total_ms=20.0),
            "model_calls": 2, "cached_calls": 2}
    refused = {**record("c", stage_ms={"retrieval": 19.0, "answer": 19.0}, total_ms=30.0),
               "model_calls": 0, "cached_calls": 0,
               "error": "writer produced nothing: cap reached"}
    both = M.latency_p50([cold, warm, refused])
    assert both["answer"].as_text() == "2600 ms (n=1)", (
        "only the run with a fresh call timed the model"
    )
    assert both["retrieval"].as_text() == "19 ms (n=3)", "local stages are unaffected"
    for run in (warm, refused):
        got = M.latency_p50([run])
        assert got["answer"].ms is None and got["total"].ms is None
        assert "fresh model call" in (got["answer"].reason or "")
        assert got["retrieval"].ms is not None, "retrieval still ran"

# ------------------------------------------------------------------- outcomes


def test_every_outcome_branch_is_reachable_and_labelled():
    cases = {
        M.OUTCOME_ERROR: record("a", error="boom"),
        M.OUTCOME_REFUSAL_CORRECT: record("b", expect_refusal="NO_EVIDENCE", codes=("NO_EVIDENCE",)),
        M.OUTCOME_REFUSAL_WRONG_CODE: record("c", expect_refusal="NEED_CONFIG", codes=("NO_EVIDENCE",)),
        M.OUTCOME_WRONG_ANSWER: record("d", expect_refusal="NEED_CONFIG", answered=True),
        M.OUTCOME_MISSED_REFUSAL_SILENT: record("e", expect_refusal="NEED_CONFIG"),
        M.OUTCOME_FALSE_REFUSAL: record("f", codes=("OUT_OF_SCOPE",)),
        M.OUTCOME_ANSWERED: record("g", answered=True),
        M.OUTCOME_NO_ANSWER: record("h"),
    }
    for label, run in cases.items():
        assert M.outcome(run) == label
        if label != M.OUTCOME_REFUSAL_CORRECT and label != M.OUTCOME_ANSWERED:
            assert M.reason(run), f"{label} must carry a one-line reason"


def test_failure_gallery_holds_every_failure_of_that_arm_and_nothing_else():
    runs = [
        record("a", arm="ours", answered=True),
        record("b", arm="ours", expect_refusal="NEED_CONFIG", answered=True),
        record("c", arm="baseline", expect_refusal="NEED_CONFIG", answered=True),
    ]
    assert [r["qid"] for r in M.failures(runs, arm="ours")] == ["b"]


def test_summarise_covers_every_metric_named_in_the_report_order():
    summary = M.summarise([record("a", arm="ours", answered=True)], arm="ours")
    assert set(M.METRIC_ORDER) <= set(summary.rates)
    assert summary.n == 1


def test_summarise_only_reads_its_own_arm():
    runs = [record("a", arm="ours", answered=True), record("b", arm="baseline")]
    assert M.summarise(runs, arm="baseline").n == 1
