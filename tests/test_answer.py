"""The answer writer's one structural claim: code computes every offset.

The writer is never trusted with a character offset. It offers a quote; these
tests pin that a quote present character for character becomes a citation whose
offsets really bound it in the paragraph, and that a quote which is not present
becomes no citation at all rather than a near match.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contracts.contract import enum, sse_events  # noqa: E402
from engine.api.answer import (  # noqa: E402
    QUOTE_EMPTY,
    QUOTE_NOT_VERBATIM,
    QUOTE_UNKNOWN_PARAGRAPH,
    build_envelope,
    resolve_quotes,
)
from engine.verify.verifier import verify  # noqa: E402


@dataclass
class FakeHit:
    paragraph_id: str
    text: str
    char_start: int
    char_end: int
    ad_number: str = "2026-20103"
    label: str = "g"
    role: str = "REQUIRED_ACTIONS"
    heading: str = "Required Actions"


def hit(text: str, *, base: int = 500) -> FakeHit:
    return FakeHit(
        paragraph_id="2026-20103#g", text=text, char_start=base, char_end=base + len(text)
    )


PARA = (
    "Within 30 days after the effective date of this AD, inspect the left-hand "
    "engine mount for cracking in accordance with the Accomplishment "
    "Instructions of Boeing Alert Service Bulletin 757-53A0122."
)


# ------------------------------------------------------- offsets are computed


def test_a_verbatim_quote_becomes_a_citation_whose_offsets_bound_it():
    # Arrange
    h = hit(PARA, base=500)
    quote = "Within 30 days after the effective date of this AD"

    # Act
    sentences, unresolved = resolve_quotes(
        [{"text": "Inspection is due within 30 days.", "quotes": [
            {"paragraph_number": 1, "quote": quote}]}],
        [h],
    )

    # Assert
    assert not unresolved
    citation_id = sentences[0].citation_ids[0]
    paragraph_id, _, span = citation_id.partition("@")
    start, end = (int(x) for x in span.split("-"))
    assert paragraph_id == "2026-20103#g"
    # The offsets are absolute in the revision's plain text, so they are
    # relative to the paragraph's own char_start.
    assert h.text[start - h.char_start : end - h.char_start] == quote


def test_offsets_are_not_taken_from_the_model():
    """A model-supplied offset must have no route into a citation id."""
    h = hit(PARA)
    sentences, _ = resolve_quotes(
        [
            {
                "text": "Inspect the engine mount.",
                # These keys are deliberately junk: the resolver must ignore
                # anything offset-shaped the writer attaches to a quote.
                "quotes": [
                    {
                        "paragraph_number": 1,
                        "quote": "inspect the left-hand engine mount",
                        "char_start": 999999,
                        "char_end": 1000000,
                    }
                ],
            }
        ],
        [h],
    )
    start, end = (int(x) for x in sentences[0].citation_ids[0].split("@")[1].split("-"))
    assert (start, end) != (999999, 1000000)
    assert h.text[start - h.char_start : end - h.char_start] == "inspect the left-hand engine mount"


def test_a_quote_broken_across_a_line_resolves_to_the_real_span():
    """Source XML carries newlines; the same characters in order still count."""
    h = hit("Within 30 days after the\n   effective date of this AD, inspect.")
    sentences, unresolved = resolve_quotes(
        [{"text": "The interval is 30 days.", "quotes": [
            {"paragraph_number": 1, "quote": "Within 30 days after the effective date"}]}],
        [h],
    )
    assert not unresolved
    start, end = (int(x) for x in sentences[0].citation_ids[0].split("@")[1].split("-"))
    spanned = h.text[start - h.char_start : end - h.char_start]
    assert spanned.split() == "Within 30 days after the effective date".split()


# --------------------------------------------------------- failures are named


@pytest.mark.parametrize(
    "quote,reason",
    [
        ("Within 45 days after the effective date", QUOTE_NOT_VERBATIM),
        ("WITHIN 30 DAYS AFTER THE EFFECTIVE DATE", QUOTE_NOT_VERBATIM),
        ("", QUOTE_EMPTY),
    ],
)
def test_a_quote_that_is_not_in_the_paragraph_yields_no_citation(quote, reason):
    sentences, unresolved = resolve_quotes(
        [{"text": "Something.", "quotes": [{"paragraph_number": 1, "quote": quote}]}],
        [hit(PARA)],
    )
    assert sentences[0].citation_ids == []
    assert [u.reason for u in unresolved] == [reason]


def test_a_quote_naming_an_unretrieved_paragraph_is_rejected():
    sentences, unresolved = resolve_quotes(
        [{"text": "Something.", "quotes": [{"paragraph_number": 7, "quote": "inspect"}]}],
        [hit(PARA)],
    )
    assert sentences[0].citation_ids == []
    assert unresolved[0].reason == QUOTE_UNKNOWN_PARAGRAPH


def test_an_uncitable_sentence_is_dropped_by_the_verifier():
    """The two stages compose: no citation here, dropped there."""
    h = hit(PARA)
    sentences, _ = resolve_quotes(
        [{"text": "The deadline is 90 days.", "quotes": [
            {"paragraph_number": 1, "quote": "Within 90 days"}]}],
        [h],
    )
    result = verify(sentences, {h.paragraph_id: h})
    assert result.dropped
    assert result.dropped[0].reason == "sentence_carries_no_citation"


def test_a_fabricated_number_is_dropped_even_with_a_real_quote():
    h = hit(PARA)
    sentences, unresolved = resolve_quotes(
        [{"text": "Inspection is due within 45 days of the effective date.", "quotes": [
            {"paragraph_number": 1, "quote": "after the effective date of this AD"}]}],
        [h],
    )
    assert not unresolved  # the quote itself is real
    result = verify(sentences, {h.paragraph_id: h})
    assert result.dropped[0].reason == "numeric_term_absent_from_cited_span"


# ------------------------------------------------------------------ envelope


def test_envelope_carries_every_declared_field_and_a_real_stage():
    h = hit(PARA)
    sentences, _ = resolve_quotes(
        [{"text": "Inspect the left-hand engine mount for cracking.", "quotes": [
            {"paragraph_number": 1, "quote": "inspect the left-hand engine mount for cracking"}]}],
        [h],
    )
    result = verify(sentences, {h.paragraph_id: h})
    envelope = build_envelope(
        answer_status="ANSWERED",
        document_stage="ADOPTED_NOT_YET_EFFECTIVE",
        decision=None,
        decision_unavailable="no aircraft resolved",
        verification=result,
        answer=None,
        revision_id="2026-20103",
        superseded_by=None,
        refusals=[],
        traversal=None,
        unreviewed_rules=3,
    )
    assert envelope["answer_status"] in enum("answer_status")
    assert envelope["document_stage"] in enum("document_stage")
    assert envelope["citations"], "a kept sentence must appear in citations"
    # The two limitations that must never be left implicit.
    joined = " ".join(envelope["limitations"])
    assert "not yet effective" in joined
    assert "machine-extracted" in joined
    assert envelope["evaluated_conditions"] == {"unavailable": "no aircraft resolved"}
    assert envelope["traversal"]["outcome"] is None


def test_envelope_rejects_an_off_contract_status():
    with pytest.raises(ValueError):
        build_envelope(
            answer_status="PROBABLY_FINE",
            document_stage="EFFECTIVE",
            decision=None,
            decision_unavailable=None,
            verification=None,
            answer=None,
            revision_id=None,
            superseded_by=None,
            refusals=[],
            traversal=None,
            unreviewed_rules=0,
        )


def test_the_envelope_is_declared_on_the_terminal_event():
    """The envelope is the finished result, so it rides on `done`.

    It is deliberately NOT its own event: every SSE event names a distinct
    pipeline stage, and the envelope is not a stage.
    """
    assert "envelope" in sse_events()["done"]["payload"]
    assert "answer_envelope" not in sse_events()
