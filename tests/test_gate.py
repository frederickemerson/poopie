"""Which refusal code the gate picks, and why it is that one and not another.

The gate had no tests. It decides every refusal the product emits, and the
codes are the product: each one names who can clear the blocker, so emitting
the wrong one sends the engineer to the wrong place. NO_EVIDENCE in particular
is a statement about *us* -- the corpus does not hold it -- and using it for a
question the asker could fix in seconds is the most expensive mistake here.

The routing is read off the query plan's structured intent enum and the entity
pass, never off the words in the question.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contracts.contract import enum  # noqa: E402
from engine.retrieval.plan import QueryPlan  # noqa: E402
from engine.verify.gate import evaluate_gate  # noqa: E402
from engine.verify.thresholds import NO_EVIDENCE_COSINE_MIN  # noqa: E402

#: Comfortably under NO_EVIDENCE_COSINE_MIN, so "below floor" is unambiguous.
WEAK = NO_EVIDENCE_COSINE_MIN / 2
STRONG = min(1.0, NO_EVIDENCE_COSINE_MIN + 0.4)

#: Every intent the contract defines except the catch-all. These are the ones
#: that mean "this IS an airworthiness directive question".
AD_INTENTS = [i for i in enum("intent") if i != "search"]


def hit(paragraph_id: str = "2026-21332#c", revision_id: str = "2026-21332"):
    return SimpleNamespace(paragraph_id=paragraph_id, revision_id=revision_id)


def result(*, top_cosine: float, hits=None, applied=None, unavailable=None):
    return SimpleNamespace(
        hits=list(hits) if hits is not None else [hit()],
        top_cosine=top_cosine,
        filter_report={"applied": applied or [], "unavailable": unavailable or []},
    )


def entities(**overrides):
    base = {
        "has_identifier": False,
        "models": [],
        "typecodes": [],
        "ad_numbers": [],
        "ambiguous": [],
    }
    return SimpleNamespace(**{**base, **overrides})


def corpus():
    """Enough Corpus for the gate: a size, and revisions with no successor."""
    return SimpleNamespace(ad_numbers={"2026-21-33"}, revisions={})


def codes(gate) -> list[str]:
    return [r["code"] for r in gate.payloads()]


def plan(intent: str, **overrides) -> QueryPlan:
    return QueryPlan(intent=intent, **overrides)


# ------------------------------------------------------- the two empty cases


@pytest.mark.parametrize("intent", AD_INTENTS)
def test_an_ad_question_naming_nothing_asks_for_what_is_missing(intent):
    """"Does this AD apply to my aircraft?" is in scope and simply has not said
    which AD or which aircraft. The person asking can clear that in seconds, so
    the refusal has to say so rather than report an empty corpus."""
    gate = evaluate_gate(
        corpus(),
        entities(),
        result(top_cosine=WEAK),
        plan=plan(intent),
    )
    assert codes(gate) == ["NEED_CONFIG"]
    assert "NO_EVIDENCE" not in codes(gate)


def test_a_question_that_is_not_about_ads_is_out_of_scope():
    """"What is the current price of jet fuel?" names nothing either, but the
    plan's catch-all intent says it was never an AD question. Same emptiness,
    opposite refusal, and the intent enum is the only thing separating them."""
    gate = evaluate_gate(
        corpus(),
        entities(),
        result(top_cosine=WEAK),
        plan=plan("search", topic="jet fuel prices"),
    )
    assert codes(gate) == ["OUT_OF_SCOPE"]


def test_the_two_empty_cases_never_both_fire():
    for intent in enum("intent"):
        gate = evaluate_gate(
            corpus(), entities(), result(top_cosine=WEAK), plan=plan(intent)
        )
        emitted = codes(gate)
        assert len(emitted) == 1, f"{intent} emitted {emitted}"
        assert emitted[0] in {"NEED_CONFIG", "OUT_OF_SCOPE"}


# --------------------------------------------------- what must NOT be rerouted


def test_naming_a_directive_is_not_a_missing_value():
    """A question that names its AD has said what it is about. If retrieval
    still finds nothing, that is genuinely a statement about the corpus."""
    gate = evaluate_gate(
        corpus(),
        entities(has_identifier=True),
        result(top_cosine=WEAK),
        plan=plan("applicability", ad_number="2026-20-03"),
    )
    assert codes(gate) == ["NO_EVIDENCE"]


def test_naming_an_aircraft_is_not_a_missing_value():
    gate = evaluate_gate(
        corpus(),
        entities(),
        result(top_cosine=WEAK),
        plan=plan("applicability", aircraft={"tail_number": "N220CY"}),
    )
    assert codes(gate) == ["NO_EVIDENCE"]


def test_evidence_above_the_floor_is_never_refused_for_emptiness():
    gate = evaluate_gate(
        corpus(), entities(), result(top_cosine=STRONG), plan=plan("applicability")
    )
    assert "NEED_CONFIG" not in codes(gate)
    assert "NO_EVIDENCE" not in codes(gate)


def test_without_a_plan_nothing_is_rerouted_and_the_engine_says_why():
    """With no query plan there is no intent, so an out-of-scope question and an
    under-specified one are indistinguishable. The gate falls back to
    NO_EVIDENCE -- and records that it could not tell them apart, which is the
    note that used to sit below the return and could never run."""
    gate = evaluate_gate(corpus(), entities(), result(top_cosine=WEAK), plan=None)
    assert codes(gate) == ["NO_EVIDENCE"]
    assert any("OUT_OF_SCOPE could not be distinguished" in n for n in gate.notes)


def test_that_note_does_not_fire_when_the_question_named_something():
    gate = evaluate_gate(
        corpus(), entities(has_identifier=True), result(top_cosine=WEAK), plan=None
    )
    assert not any("could not be distinguished" in n for n in gate.notes)


# ------------------------------------------------------------- contract shape


def test_every_code_the_gate_emits_is_a_contract_code():
    allowed = set(enum("refusal_code"))
    for intent in enum("intent"):
        for cosine in (WEAK, STRONG):
            gate = evaluate_gate(
                corpus(), entities(), result(top_cosine=cosine), plan=plan(intent)
            )
            assert set(codes(gate)) <= allowed


def test_a_need_config_refusal_names_who_clears_it():
    gate = evaluate_gate(
        corpus(), entities(), result(top_cosine=WEAK), plan=plan("applicability")
    )
    payload = gate.payloads()[0]
    assert payload["resolvable_by"]
    assert isinstance(payload["resolvable_by"], str)
