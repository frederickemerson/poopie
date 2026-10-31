"""The recorders: the baseline arm, the SSE reader, the CLI and the report.

Split from ``tests/test_eval.py``, which covers the metric arithmetic. These
tests cover the parts that *record* a run -- the strawman arm, the SSE frames
``eval.run`` reads off ``engine.api.server._stream``, the per-turn ledger
accounting, and the markdown ``eval.report`` renders from the records. Still no
network and no model: every engine frame here is a hand-written string, so the
test proves what the harness does with a frame rather than what the model said.

The record makers are imported from ``test_eval`` rather than copied, so both
files always test the same record shape.
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
sys.path.insert(0, str(Path(__file__).resolve().parent))

from contracts.contract import enum  # noqa: E402
from eval import baseline as B  # noqa: E402
from eval import metrics as M  # noqa: E402
from eval import report as RP  # noqa: E402
from eval import run as R  # noqa: E402
from eval.questions import Question as Q  # noqa: E402
from test_eval import record  # noqa: E402


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
        ledger=_fake_harness().ledger,
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


def _fake_harness(ledger_path: Path | None = None):
    """A harness with just the two things the recorders read off it."""
    return SimpleNamespace(
        ledger=SimpleNamespace(
            spent_usd=lambda: 0.0,
            path=ledger_path or Path("/nonexistent/cost_ledger.jsonl"),
        )
    )


def test_a_turn_is_billed_from_the_ledger_rows_it_appended(tmp_path):
    """Cost and cache status both come off the ledger's own append-only rows."""
    led = tmp_path / "cost_ledger.jsonl"
    led.write_text(json.dumps({"label": "earlier", "cost_usd": 9.0}) + "\n", encoding="utf-8")
    harness = _fake_harness(led)
    offset = led.stat().st_size
    with led.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"label": "answer", "cost_usd": 0.004, "cached_hit": False}) + "\n")
        fh.write(json.dumps({"label": "query_plan", "cost_usd": 0.0, "cached_hit": True}) + "\n")
        fh.write("{torn\n")
    record = {}
    R._bill(record, R._ledger_rows_since(harness, offset)[1])
    assert record == {"cost_usd": 0.004, "model_calls": 2, "cached_calls": 1}, (
        "the earlier $9 row and the torn line must not be billed to this turn"
    )


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
