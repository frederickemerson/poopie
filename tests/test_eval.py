"""The eval harness, tested on hand-built records. No network, no model, no corpus.

Every metric is a pure function over run records, so each one is tested against
records written out by hand here. That is the point of the shape: if these tests
pass, the numbers in eval/results/report.md are recomputable from
eval/results/runs.jsonl by anybody, without re-running the engine.

The cases that matter and are therefore pinned:

* a refusal with the *wrong* code counts as a miss, not a hit;
* SUPERSEDED does not count as withholding an answer, because the contract says
  it does not block one;
* a metric with nothing to measure reports n/a with a reason, never 0% or 100%;
* a labelled decision the engine could not produce is excluded, not scored;
* percentiles are nearest-rank, so every reported latency was really observed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contracts.contract import enum  # noqa: E402
from eval import baseline as B  # noqa: E402
from eval import metrics as M  # noqa: E402
from eval import report as RP  # noqa: E402
from eval.questions import Question as Q  # noqa: E402
from eval import run as R  # noqa: E402


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


# ------------------------------------------------------------------- baseline


class _FakeIndex:
    def __init__(self, embeddings, paragraphs):
        self.embeddings = embeddings
        self.corpus = type("C", (), {"paragraphs": paragraphs})()


def _passage(pid: str = "r1#(c)", text: str = "This AD applies to Model 757-200 airplanes.") -> B.Passage:
    return B.Passage(
        paragraph_id=pid,
        revision_id="r1",
        ad_number="2026-20-15",
        label="(c)",
        role="APPLICABILITY",
        heading="Applicability",
        text=text,
        char_start=0,
        char_end=len(text),
        score=0.5,
    )


def test_both_arms_share_one_writer_by_construction_not_by_copy():
    """The fairness invariant: the baseline calls the engine's own writer.

    A second writer, or a second prompt, would let a difference in the numbers
    be a difference in prompting rather than in architecture.
    """
    from engine.api import answer as engine_answer

    assert B.write_answer is engine_answer.write_answer


def test_baseline_hands_its_cosine_passages_to_that_writer(monkeypatch):
    seen: dict = {}

    def fake_writer(client, question, hits, **kwargs):
        seen.update(question=question, hits=hits, label=kwargs.get("label"))
        return SimpleNamespace(sentences=[], unresolved=[], stage_ms=1.0, reason=None,
                               available=False)

    monkeypatch.setattr(B, "write_answer", fake_writer)
    monkeypatch.setattr(B, "top_k_by_cosine", lambda index, q, k=8: [_passage()])
    out = B.run_baseline(_FakeIndex(None, []), object(), "does it apply?")
    assert seen["question"] == "does it apply?"
    assert [h.paragraph_id for h in seen["hits"]] == ["r1#(c)"]
    assert seen["label"] == B.LABEL, "the arms' spend must be separable in the ledger"
    assert out.citation_ids == [] and out.stage_ms["answer"] == 1.0


def test_a_writer_that_produced_nothing_is_recorded_as_a_reason_not_an_exception(
    monkeypatch,
):
    """The engine's writer never raises -- it reports a reason -- and an arm that
    said nothing must be distinguishable from an arm that crashed."""
    from eval.questions import Question

    monkeypatch.setattr(
        B, "top_k_by_cosine", lambda index, q, k=8: [_passage()]
    )
    monkeypatch.setattr(
        B,
        "write_answer",
        lambda *a, **k: SimpleNamespace(
            sentences=[], unresolved=[], stage_ms=1.0,
            reason="no paragraphs retrieved", available=False,
        ),
    )
    harness = SimpleNamespace(
        index=_FakeIndex(None, []), client=object(),
        ledger=SimpleNamespace(spent_usd=lambda: 0.0),
    )
    run = R.run_baseline_arm(Question("b1", "why?", "answerable"), harness)
    assert run["answered"] is False
    assert "no paragraphs retrieved" in run["error"]


def test_a_passage_adapts_an_sse_retrieval_payload_without_importing_hit():
    payload = {
        "paragraph_id": "r1#(c)", "revision_id": "r1", "ad_number": "2026-20-15",
        "label": "(c)", "role": "APPLICABILITY", "heading": "Applicability",
        "text": "abc", "char_start": 10, "char_end": 13, "score": 0.4,
    }
    passage = B.Passage.from_hit(payload)
    assert passage.citation_id == "r1#(c)@10-13" and passage.text == "abc"


def test_baseline_ranks_by_cosine_alone(monkeypatch):
    from engine.retrieval.corpus import Paragraph

    paragraphs = [
        Paragraph(f"r1#({chr(97 + i)})", "r1", f"({chr(97 + i)})", "OTHER", "", "text", 0, 4, i)
        for i in range(3)
    ]
    embeddings = np.array([[1.0, 0.0], [0.0, 1.0], [0.7, 0.7]], dtype=np.float32)
    monkeypatch.setattr(
        "engine.retrieval.index.embed", lambda texts: np.array([[0.0, 1.0]], dtype=np.float32)
    )
    top = B.top_k_by_cosine(_FakeIndex(embeddings, paragraphs), "q", k=2)
    assert [p.paragraph_id for p in top] == ["r1#(b)", "r1#(c)"]
    assert top[0].score > top[1].score


def test_baseline_refuses_to_run_without_a_dense_arm():
    with pytest.raises(B.DenseArmMissing):
        B.top_k_by_cosine(_FakeIndex(None, []), "q")


# ------------------------------------------------------------------ SSE + CLI


def test_events_parses_the_engines_sse_frames():
    frames = [
        'event: retrieval\ndata: {"paragraphs": [], "scores": [], "stage_ms": 1.0}\n\n',
        'event: done\ndata: {"total_ms": 2.0, "stage_timings": {}}\n\n',
    ]
    parsed = list(R.events(frames))
    assert [name for name, _ in parsed] == ["retrieval", "done"]
    assert parsed[1][1]["total_ms"] == 2.0


def test_events_raises_on_a_frame_it_cannot_read():
    with pytest.raises(ValueError, match="malformed SSE"):
        list(R.events(["data: {}\n\n"]))


def test_label_audit_discloses_a_label_the_corpus_does_not_support():
    """Only when the decision was computed on the AD the question named."""
    runs = [
        record("cfg-01", arm="ours", expect_refusal="NEED_CONFIG", expect_ad="2026-20-13",
               retrieved_ads=("2026-20-13",), decision="DOES_NOT_APPLY", answered=True),
    ]
    notes = RP._label_audit(runs)
    assert any("cfg-01" in n and "not supported by the corpus" in n for n in notes)


def test_label_audit_stays_quiet_when_a_different_ad_was_retrieved():
    runs = [
        record("cfg-09", arm="ours", expect_refusal="NEED_CONFIG", expect_ad="2026-20-13",
               retrieved_ads=("2026-21-04",), decision="DOES_NOT_APPLY", answered=True),
    ]
    assert not any("cfg-09" in n for n in RP._label_audit(runs))


def test_label_audit_names_refusals_that_came_from_the_verifier_not_the_gate():
    runs = [
        {
            **record("rev-02", arm="ours", codes=("NO_EVIDENCE",)),
            "refusal_details": [{"code": "NO_EVIDENCE", "source": RP.FROM_VERIFIER}],
        }
    ]
    assert any("rev-02" in n and "citation verification" in n for n in RP._label_audit(runs))


def test_gallery_lists_the_failure_rather_than_summarising_it_away():
    runs = [record("trap-01", arm="ours", expect_refusal="EXTERNAL_SOURCE_REQUIRED", answered=True)]
    text = RP._gallery(runs, "ours")
    assert "trap-01" in text and "EXTERNAL_SOURCE_REQUIRED" in text


def test_gallery_says_where_each_refusal_came_from():
    runs = [
        {
            **record("x", arm="ours", codes=("NO_EVIDENCE",)),
            "refusal_details": [{"code": "NO_EVIDENCE", "source": RP.FROM_VERIFIER}],
        }
    ]
    assert "NO_EVIDENCE (verifier)" in RP._gallery(runs, "ours")


def test_a_run_that_raised_is_disclosed_as_excluded_not_quietly_dropped():
    """An error shrinks a denominator, so the report has to say it happened."""
    runs = [
        record("amb-05", arm="baseline", error="writer produced nothing: cap reached"),
        record("ans-01", arm="ours"),
    ]
    notes = " ".join(RP._label_audit(runs))
    assert "excluded from every rate above" in notes and "amb-05" in notes
    assert "baseline: 1" in notes


def test_a_run_cut_short_by_the_budget_says_so_at_the_top_of_the_report():
    """A prefix of the set must never be presented as the whole set."""
    runs = [{**record("ans-01", arm="ours"), "refusal_details": []}]
    questions = [
        Q(qid=f"ans-{i:02d}", text="q", kind="answerable")
        for i in range(3)
    ]
    out = RP.report(
        runs, questions,
        SimpleNamespace(
            corpus=SimpleNamespace(kind="build", paragraphs=[], revisions=[], ad_numbers=[]),
            ledger=SimpleNamespace(
                summary=lambda: {"spent_usd": 0.1, "cap_usd": 2.0, "cache_hits": 0, "calls": 1}
            ),
        ),
        SimpleNamespace(aircraft=[], rules_by_revision={}),
        arms=("ours",), warm_up_ms=1.0,
    )
    assert "**This run is incomplete**" in out and "ours (1 of 3)" in out


def test_every_expected_refusal_code_is_in_the_contract():
    """The eval cannot label a question with a code the engine may not emit."""
    from eval.questions import AMBIGUOUS, NO_EVIDENCE, OUT_OF_SCOPE

    allowed = set(enum("refusal_code"))
    for question in [*AMBIGUOUS, *NO_EVIDENCE, *OUT_OF_SCOPE]:
        assert question.expect_refusal in allowed


# ------------------------------------------- recording the engine's own stages


def test_sentence_rows_mark_an_arm_that_ran_no_verifier_as_unknown_not_dropped():
    rows = R._sentence_rows([{"index": 0, "text": "a", "citation_ids": ["r1#(c)@0-3"]}], None)
    assert rows[0]["kept"] is None and rows[0]["drop_reason"] is None


def test_sentence_rows_take_the_verdict_from_the_verification_event():
    verification = {
        "kept": [0],
        "dropped": [1],
        "drop_reasons": [{"index": 1, "reason": "term_coverage_below_threshold",
                          "detail": "coverage 0.20 < 0.50"}],
    }
    rows = R._sentence_rows(
        [
            {"index": 0, "text": "kept", "citation_ids": ["r1#(c)@0-3"]},
            {"index": 1, "text": "dropped", "citation_ids": ["r1#(c)@0-3"]},
        ],
        verification,
    )
    assert rows[0]["kept"] is True and rows[1]["kept"] is False
    assert rows[1]["drop_reason"] == "term_coverage_below_threshold"


def _frames(*pairs: tuple[str, dict]) -> list[str]:
    return [f"event: {n}\ndata: {json.dumps(p)}\n\n" for n, p in pairs]


def _fake_harness():
    return SimpleNamespace(ledger=SimpleNamespace(spent_usd=lambda: 0.0))


def _retrieval_payload():
    return {
        "paragraphs": [
            {"paragraph_id": "r1#(c)", "revision_id": "r1", "ad_number": "2026-20-15",
             "label": "(c)", "role": "APPLICABILITY", "heading": "", "text": "text",
             "char_start": 0, "char_end": 4, "score": 0.5}
        ],
        "scores": [0.5], "stage_ms": 1.0,
    }


def test_a_refusal_before_verification_is_recorded_as_the_gates(monkeypatch):
    from eval.questions import Question

    frames = _frames(
        ("retrieval", _retrieval_payload()),
        ("decision", {"decision": None, "fired_rule_ids": [], "unknown_fields": [],
                      "proof_tree": {"unavailable": "no aircraft"}, "stage_ms": 0.1}),
        ("refusal", {"code": "NO_EVIDENCE", "detail": "not in corpus",
                     "resolvable_by": "none", "evidence_paragraph_ids": ["r1#(c)"]}),
        ("done", {"total_ms": 10.0, "stage_timings": {"retrieval": 1.0},
                  "envelope": {"answer_status": "REFUSED"}}),
    )
    monkeypatch.setattr(R.server, "_stream", lambda q, tail: iter(frames))
    run = R.run_ours(Question("q1", "why?", "answerable"), _fake_harness())
    assert run["refusal_details"][0]["source"] == R.FROM_GATE
    assert run["answered"] is False and run["answer_status"] == "REFUSED"
    assert run["retrieved_ad_numbers"] == ["2026-20-15"]


def test_a_refusal_after_verification_is_recorded_as_the_verifiers(monkeypatch):
    from eval.questions import Question

    frames = _frames(
        ("retrieval", _retrieval_payload()),
        ("decision", {"decision": "APPLIES", "fired_rule_ids": ["r1"],
                      "unknown_fields": [], "proof_tree": {}, "stage_ms": 0.1}),
        ("answer_delta", {"sentence": "A claim.", "citation_ids": ["r1#(c)@0-4"], "index": 0}),
        ("verification", {"kept": [], "dropped": [0],
                          "drop_reasons": [{"index": 0, "reason": "numeric_term_absent_from_cited_span"}],
                          "stage_ms": 0.2}),
        ("refusal", {"code": "NO_EVIDENCE", "detail": "0 of 1 survived",
                     "resolvable_by": "none", "evidence_paragraph_ids": ["r1#(c)"]}),
        ("done", {"total_ms": 10.0, "stage_timings": {}, "envelope": {"answer_status": "REFUSED"}}),
    )
    monkeypatch.setattr(R.server, "_stream", lambda q, tail: iter(frames))
    run = R.run_ours(Question("q2", "why?", "answerable"), _fake_harness())
    assert run["refusal_details"][0]["source"] == R.FROM_VERIFIER
    assert run["sentences"][0]["kept"] is False
    assert run["decision"] == "APPLIES" and run["decision_available"] is True


def test_the_engines_own_answer_status_decides_whether_it_answered(monkeypatch):
    from eval.questions import Question

    frames = _frames(
        ("retrieval", _retrieval_payload()),
        ("decision", {"decision": None, "fired_rule_ids": [], "unknown_fields": [],
                      "proof_tree": {}, "stage_ms": 0.1}),
        ("answer_delta", {"sentence": "A claim.", "citation_ids": ["r1#(c)@0-4"], "index": 0}),
        ("verification", {"kept": [0], "dropped": [], "drop_reasons": [], "stage_ms": 0.2}),
        ("done", {"total_ms": 9.0, "stage_timings": {}, "envelope": {"answer_status": "PARTIAL"}}),
    )
    monkeypatch.setattr(R.server, "_stream", lambda q, tail: iter(frames))
    run = R.run_ours(Question("q3", "why?", "answerable"), _fake_harness())
    assert run["answered"] is True and run["citation_ids"] == ["r1#(c)@0-4"]


def test_an_engine_error_event_is_recorded_not_swallowed(monkeypatch):
    from eval.questions import Question

    frames = _frames(("error", {"message": "corpus not loaded"}))
    monkeypatch.setattr(R.server, "_stream", lambda q, tail: iter(frames))
    run = R.run_ours(Question("q4", "why?", "answerable"), _fake_harness())
    assert run["error"] == "corpus not loaded" and M.outcome(run) == M.OUTCOME_ERROR
