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

import networkx as nx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contracts.contract import enum  # noqa: E402
from engine.retrieval.graph_filter import series_covering  # noqa: E402
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
        "tail_numbers": [],
        "serial_numbers": [],
    }
    return SimpleNamespace(**{**base, **overrides})


def corpus(rule_values=()):
    """Enough Corpus for the gate: a size, revisions with no successor, and a
    graph carrying the aircraft Rule nodes ``series_covering`` reads. With no
    rule values the graph holds no aircraft rules at all, which is the "cannot
    tell" case rather than the "nothing covers it" one.
    """
    graph = nx.DiGraph()
    for i, value in enumerate(rule_values):
        graph.add_node(
            f"rule-{i}", ntype="Rule", field="model",
            revision_id="2026-21332", value=[value],
        )
    return SimpleNamespace(ad_numbers={"2026-21-33"}, revisions={}, graph=graph)


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


def test_naming_nothing_is_refused_however_well_it_retrieves():
    """The regression test for the conjunction that let six traps through.

    Whether the dense retriever liked a passage is a statement about the corpus;
    naming no directive and no aircraft is a statement about the question, and
    stays true at every score. "What is the compliance time?" names no directive
    and still retrieves a real compliance paragraph from an arbitrary one at
    cosine 0.54 -- so requiring a *low* score before asking what the question
    meant let the high-scoring half through, and a confident, correctly cited
    answer to a question nobody asked is the worst outcome available here.
    """
    for cosine in (WEAK, STRONG):
        gate = evaluate_gate(
            corpus(), entities(), result(top_cosine=cosine), plan=plan("applicability")
        )
        assert codes(gate) == ["NEED_CONFIG"], f"cosine={cosine}"


def test_a_question_that_names_something_is_not_refused_for_emptiness():
    """The converse, so the rule above cannot be satisfied by refusing everything."""
    gate = evaluate_gate(
        corpus(),
        entities(has_identifier=True),
        result(top_cosine=STRONG),
        plan=plan("applicability", ad_number="2026-20-03"),
    )
    assert codes(gate) == []


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


# ------------------------ an applicability question with no airframe in it


def test_a_model_only_applicability_question_asks_which_airframe():
    """"Is my 767 affected?" names a type, not an aircraft. Applicability is
    decided per airframe, against that aircraft's serial number, so a
    designation covering five series and several hundred airframes leaves
    nothing to decide -- however well the question retrieves, which is why this
    is not gated on the similarity floor either."""
    gate = evaluate_gate(
        corpus(["767-200", "767-300", "767-400er"]),
        entities(),
        result(top_cosine=STRONG),
        plan=plan("applicability", aircraft={"model": "767"}),
    )
    assert codes(gate) == ["NEED_CONFIG"]
    detail = gate.payloads()[0]["detail"]
    assert "767-300" in detail, "the refusal should name what it does cover"


def test_a_model_no_loaded_directive_covers_is_out_of_scope():
    """The other half of the same question, separated by a corpus fact rather
    than by the wording: nothing here is a Superjet, so saying so is true."""
    gate = evaluate_gate(
        corpus(["767-300", "a330-941"]),
        entities(),
        result(top_cosine=STRONG),
        plan=plan("applicability", aircraft={"model": "Superjet 100"}),
    )
    assert codes(gate) == ["OUT_OF_SCOPE"]


def test_a_partial_designation_must_end_at_the_series_separator():
    """"7" is a character prefix of "767-300" and names nothing. Without the
    separator the engine would claim to cover every Boeing from one digit."""
    assert series_covering(corpus(["767-300"]), "7") == []
    assert series_covering(corpus(["767-300"]), "76") == []
    assert series_covering(corpus(["767-300"]), "767") == ["767-300"]
    assert series_covering(corpus(["767-300"]), "767-300") == ["767-300"]


def test_absence_is_never_claimed_from_a_graph_with_no_aircraft_rules():
    """``[]`` means no loaded directive covers it; ``None`` means the filter
    cannot tell. Conflating them would state absence from an unbuilt graph --
    the same false-absence mistake the model filter already guards against."""
    assert series_covering(corpus(), "767") is None
    gate = evaluate_gate(
        corpus(),
        entities(),
        result(top_cosine=STRONG),
        plan=plan("applicability", aircraft={"model": "767"}),
    )
    assert codes(gate) == []


def test_fleet_impact_legitimately_takes_a_model():
    """A fleet question is *about* the type, so a type is not missing information."""
    gate = evaluate_gate(
        corpus(["767-300"]),
        entities(),
        result(top_cosine=STRONG),
        plan=plan("fleet_impact", aircraft={"model": "767"}),
    )
    assert "NEED_CONFIG" not in codes(gate)


def test_an_airframe_already_named_is_not_asked_for_again():
    gate = evaluate_gate(
        corpus(["767-300"]),
        entities(),
        result(top_cosine=STRONG),
        plan=plan("applicability", aircraft={"model": "767", "tail_number": "N220CY"}),
    )
    assert codes(gate) == []


def test_a_delegation_refusal_is_not_demoted_to_a_question_about_the_aircraft():
    """Ordering regression. "Which ADs apply to my A330-941?" is model-only, but
    when the revision delegates applicability to a document this engine does not
    hold, EXTERNAL_SOURCE_REQUIRED is the more specific truth and has to win:
    naming a tail number would not resolve it, so asking for one misleads."""
    decision = SimpleNamespace(
        refusal={
            "code": "EXTERNAL_SOURCE_REQUIRED",
            "detail": "EASA AD 2025-0208 decides applicability.",
            "evidence_paragraph_ids": ["2026-21332#c"],
            "resolvable_by": "the operator obtains the referenced document",
        }
    )
    gate = evaluate_gate(
        corpus(["a330-941"]),
        entities(),
        result(top_cosine=STRONG),
        plan=plan("applicability", aircraft={"model": "A330-941"}),
        rules_decision=decision,
    )
    assert codes(gate) == ["EXTERNAL_SOURCE_REQUIRED"]
