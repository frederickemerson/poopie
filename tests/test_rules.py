"""The rules engine. Pure code, so these tests are exact, not approximate.

Covered here: every contract rule_operator, the serial-just-outside-a-range
trap, the wrong model variant, a null fleet field, an unparsed rule, external
delegation, the proof-tree shape the UI renders, and determinism.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contracts.contract import enum, validate_event  # noqa: E402
from engine.rules import matrix, serials  # noqa: E402
from engine.rules.engine import decide  # noqa: E402
from engine.rules.evaluate import FAIL, PASS, UNKNOWN, evaluate  # noqa: E402
from engine.rules.vocab import (  # noqa: E402
    DECISION_APPLIES,
    DECISION_EXCLUDED,
    DECISION_UNDETERMINED,
    REFUSAL_EXTERNAL,
    REFUSAL_NEED_CONFIG,
    REFUSAL_UNPARSED,
)

PARAGRAPH_ID = "2026-21864#(c)"


def ac(**overrides) -> dict:
    """A real-shaped Aircraft node; the four structurally absent fields are absent."""
    record = {
        "tail_number": "N701UW",
        "icao24": "a95a2f",
        "manufacturer": "Boeing",
        "model": "757-232",
        "typecode": "B752",
        "serial_number": "24729",
        "operator": "Delta Air Lines",
        "owner": "Delta Air Lines Inc",
        "engines": "P&W PW2037",
        "built_year": 1989,
        "source": "opensky",
    }
    record.update(overrides)
    return record


def rule(field: str, operator: str, value, *, index: int = 1, reason: str | None = None) -> dict:
    return {
        "rule_id": f"{PARAGRAPH_ID}/r{index:02d}",
        "revision_id": "2026-21864",
        "paragraph_id": PARAGRAPH_ID,
        "field": field,
        "operator": operator,
        "value": value,
        "source_quote": "Model 757-200 and -300 series airplanes",
        "confidence": 0.9,
        "unparsed_reason": reason,
    }


def foreign(**overrides) -> dict:
    record = {
        "revision_id": "2026-21861",
        "paragraph_id": "2026-21861#(c)",
        "role": "APPLICABILITY",
        "scope": "applicability",
        "doc_type": "ForeignAD",
        "doc_id": "EASA:2025-0208",
        "label": "EASA AD 2025-0208",
        "dated": "September 24, 2025",
        "held": False,
        "source_quote": "as identified in European Union Aviation Safety Agency (EASA) AD 2025-0208",
    }
    record.update(overrides)
    return record


# --------------------------------------------------------------------------
# 1. Every operator in the contract is exercised.
# --------------------------------------------------------------------------

OPERATOR_CASES: dict[str, tuple[dict, dict, str]] = {
    "eq": (rule("manufacturer", "eq", "The Boeing Company"), ac(), PASS),
    "neq": (rule("manufacturer", "neq", "Airbus SAS"), ac(), PASS),
    "in": (rule("typecode", "in", ["B752", "B753"]), ac(), PASS),
    "not_in": (rule("typecode", "not_in", ["B763", "B764"]), ac(), PASS),
    "model_matches": (rule("model", "model_matches", ["757-200", "757-300"]), ac(), PASS),
    "serial_in_range": (
        rule("serial_number", "serial_in_range", [{"low": "24700", "high": "24800"}]),
        ac(),
        PASS,
    ),
    "serial_not_in_range": (
        rule("serial_number", "serial_not_in_range", [{"low": "20000", "high": "21000"}]),
        ac(),
        PASS,
    ),
    "exists": (rule("equipment", "exists", "PSU-mounted video monitors"), ac(), UNKNOWN),
    "not_exists": (rule("modification", "not_exists", "STC ST01529SE"), ac(), UNKNOWN),
    "unparsed": (
        rule("model", "unparsed", "", reason="nested exception on an unseen table"),
        ac(),
        UNKNOWN,
    ),
}


def test_every_contract_operator_has_a_case():
    assert set(OPERATOR_CASES) == set(enum("rule_operator")), (
        "add a case for every rule_operator in contract.json"
    )


@pytest.mark.parametrize("operator", sorted(OPERATOR_CASES))
def test_operator_evaluates_as_expected(operator):
    rec, aircraft, expected = OPERATOR_CASES[operator]
    condition = evaluate(rec, aircraft)
    assert condition.outcome == expected, condition.reason
    assert condition.reason, "every condition must carry a human-readable reason"


def test_negated_operators_mirror_their_positive_form():
    aircraft = ac()
    for positive, negative in (("eq", "neq"), ("in", "not_in")):
        value = "The Boeing Company" if positive == "eq" else ["B752"]
        field = "manufacturer" if positive == "eq" else "typecode"
        assert evaluate(rule(field, positive, value), aircraft).outcome == PASS
        assert evaluate(rule(field, negative, value), aircraft).outcome == FAIL


# --------------------------------------------------------------------------
# 2. Serial numbers: the just-outside trap and unorderable shapes.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "serial,expected",
    [("20003", PASS), ("20407", PASS), ("20408", FAIL), ("20002", FAIL)],
)
def test_serial_range_bounds_are_inclusive_and_exact(serial, expected):
    rec = rule("serial_number", "serial_in_range", [{"low": "20003", "high": "20407"}])
    assert evaluate(rec, ac(serial_number=serial)).outcome == expected


def test_one_off_serial_decides_does_not_apply_not_cannot_determine():
    rec = rule("serial_number", "serial_in_range", [{"low": "20003", "high": "20407"}])
    result = decide(ac(serial_number="20408"), [rec], revision_id="r")
    assert result.decision == DECISION_EXCLUDED
    assert result.fired_rule_ids == (rec["rule_id"],)


@pytest.mark.parametrize(
    "serial,low,high",
    [
        ("E-3121", "3000", "3200"),      # prefixed serial against bare numbers
        ("31-7852015", "7852000", "7852100"),  # two groups against one
        ("24729A", "24000", "25000"),    # trailing letter
        ("", "1", "2"),                  # no serial at all
    ],
)
def test_unorderable_serials_are_unknown_never_guessed(serial, low, high):
    rec = rule("serial_number", "serial_in_range", [{"low": low, "high": high}])
    assert evaluate(rec, ac(serial_number=serial)).outcome == UNKNOWN


def test_serial_shapes_compare_only_within_their_own_scheme():
    assert serials.in_range("31-7852015", "31-7852000", "31-7852100") is True
    assert serials.in_range("31-7852015", "31-7851000", "31-7851999") is False
    assert serials.in_range("E-3121", "E-3000", "E-3200") is True
    assert serials.in_range("1342", "1000", "1500") is True
    assert serials.in_range("1500", "1000", "1499") is False
    assert serials.in_range("1342", "1500", "1000") is None, "inverted range is not an order"


def test_discrete_serials_ride_the_same_rule_as_ranges():
    rec = rule(
        "serial_number",
        "serial_in_range",
        [{"low": "120004", "high": "120004"}, {"low": "120006", "high": "120352"}],
    )
    assert evaluate(rec, ac(serial_number="120004")).outcome == PASS
    assert evaluate(rec, ac(serial_number="120200")).outcome == PASS
    assert evaluate(rec, ac(serial_number="120005")).outcome == FAIL


# --------------------------------------------------------------------------
# 3. Model variants.
# --------------------------------------------------------------------------

def test_wrong_model_variant_does_not_apply():
    rec = rule("model", "model_matches", ["767-300"])
    result = decide(ac(), [rec], revision_id="r")
    assert result.decision == DECISION_EXCLUDED
    assert "B752" in result.conditions[0].reason


def test_model_joins_ad_series_text_to_icao_typecode():
    rec = rule("model", "model_matches", ["737-800"])
    hit = ac(model="737-823", typecode="B738")
    assert evaluate(rec, hit).outcome == PASS
    assert evaluate(rec, ac(model="737-924ER", typecode="B739")).outcome == FAIL


def test_unlisted_variant_in_the_same_family_is_unknown_not_a_guess():
    rec = rule("model", "model_matches", ["A330-941"])
    same_family = ac(manufacturer="Airbus", model="A330-243", typecode="A332", serial_number="1389")
    other_family = ac()
    assert evaluate(rec, same_family).outcome == UNKNOWN
    assert evaluate(rec, other_family).outcome == FAIL, "a different family is a real exclusion"


# --------------------------------------------------------------------------
# 4. Null fields and unparsed rules both end in CANNOT_DETERMINE.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("field", ["category", "equipment", "modification", "part_number"])
def test_structurally_absent_fields_are_unknown_for_every_aircraft(field):
    rec = rule(field, "exists", "something the source does not record")
    result = decide(ac(), [rec], revision_id="r")
    assert result.decision == DECISION_UNDETERMINED
    assert result.unknown_fields == (field,)
    assert result.refusal["code"] == REFUSAL_NEED_CONFIG


def test_null_value_on_a_mapped_field_is_unknown():
    rec = rule("built_year", "eq", "1989")
    result = decide(ac(built_year=None), [rec], revision_id="r")
    assert result.decision == DECISION_UNDETERMINED
    assert result.refusal["code"] == REFUSAL_NEED_CONFIG
    assert "built_year" in result.refusal["detail"]


def test_unparsed_rule_refuses_cannot_determine_and_names_the_clause():
    rec = rule("model", "unparsed", "", reason="nested exception over a table we cannot see")
    result = decide(ac(), [rec], revision_id="r")
    assert result.decision == DECISION_UNDETERMINED
    assert result.refusal["code"] == REFUSAL_UNPARSED
    assert "nested exception" in result.refusal["detail"]
    assert result.refusal["evidence_paragraph_ids"] == [PARAGRAPH_ID]


def test_an_unparsed_rule_outranks_a_merely_missing_field():
    rules = [
        rule("equipment", "exists", "PSU-mounted video monitors", index=1),
        rule("model", "unparsed", "", index=2, reason="could not read the exception"),
    ]
    assert decide(ac(), rules, revision_id="r").refusal["code"] == REFUSAL_UNPARSED


def test_a_failing_rule_beats_every_unknown():
    rules = [
        rule("model", "model_matches", ["767-300"], index=1),
        rule("equipment", "exists", "video monitors", index=2),
        rule("model", "unparsed", "", index=3, reason="unreadable"),
    ]
    result = decide(ac(), rules, revision_id="r")
    assert result.decision == DECISION_EXCLUDED
    assert result.refusal is None, "a decided answer is not a refusal"


def test_no_rules_at_all_is_not_an_applies():
    result = decide(ac(), [], revision_id="r")
    assert result.decision == DECISION_UNDETERMINED
    assert result.refusal["code"] == REFUSAL_UNPARSED


def test_all_rules_pass_applies():
    rules = [
        rule("manufacturer", "eq", "The Boeing Company", index=1),
        rule("model", "model_matches", ["757-200", "757-300"], index=2),
    ]
    result = decide(ac(), rules, revision_id="r")
    assert result.decision == DECISION_APPLIES
    assert len(result.fired_rule_ids) == 2
    assert result.refusal is None


# --------------------------------------------------------------------------
# 5. External delegation (the headline refusal).
# --------------------------------------------------------------------------

def test_delegated_applicability_refuses_external_source_required():
    airbus = ac(manufacturer="Airbus", model="A330-941", typecode="A339", serial_number="1983")
    rules = [rule("model", "model_matches", ["A330-941"])]
    result = decide(airbus, rules, revision_id="2026-21861", external_applicability=[foreign()])
    assert result.decision == DECISION_UNDETERMINED
    assert result.refusal["code"] == REFUSAL_EXTERNAL
    assert "EASA AD 2025-0208" in result.refusal["detail"]
    assert result.refusal["evidence_paragraph_ids"] == ["2026-21861#(c)"]
    assert result.refusal["resolvable_by"]
    assert result.external_documents and result.external_documents[0]["doc_id"] == "EASA:2025-0208"


def test_delegation_does_not_override_a_stated_exclusion():
    rules = [rule("model", "model_matches", ["A330-941"])]
    result = decide(ac(), rules, revision_id="2026-21861", external_applicability=[foreign()])
    assert result.decision == DECISION_EXCLUDED, (
        "a foreign AD can narrow the FAA-stated set, never widen it"
    )


def test_a_held_document_does_not_block():
    rules = [rule("manufacturer", "eq", "The Boeing Company")]
    result = decide(ac(), rules, revision_id="r", external_applicability=[foreign(held=True)])
    assert result.decision == DECISION_APPLIES


def test_external_delegation_outranks_other_unknowns():
    rules = [rule("equipment", "exists", "video monitors")]
    result = decide(ac(), rules, revision_id="r", external_applicability=[foreign()])
    assert result.refusal["code"] == REFUSAL_EXTERNAL


# --------------------------------------------------------------------------
# 6. The proof tree and the SSE payloads.
# --------------------------------------------------------------------------

def test_proof_tree_is_self_contained_and_json_serializable():
    rules = [
        rule("manufacturer", "eq", "The Boeing Company", index=1),
        rule("model", "model_matches", ["757-200", "757-300"], index=2),
        rule("equipment", "exists", "PSU-mounted video monitors", index=3),
    ]
    tree = decide(ac(), rules, revision_id="2026-21864").proof_tree()
    assert json.loads(json.dumps(tree)) == tree, "must survive a JSON round trip"
    assert tree["decision"] == DECISION_UNDETERMINED
    assert tree["aircraft"]["tail_number"] == "N701UW"
    assert [c["outcome"] for c in tree["conditions"]] == [PASS, PASS, UNKNOWN]
    for condition in tree["conditions"]:
        assert set(condition) == {
            "rule_id", "field", "operator", "value", "aircraft_field",
            "aircraft_value", "outcome", "reason", "paragraph_id", "source_quote",
        }
        assert condition["paragraph_id"] and condition["source_quote"]
        assert condition["outcome"] in {PASS, FAIL, UNKNOWN}
    assert tree["refusal"]["code"] == REFUSAL_NEED_CONFIG


def test_decision_and_refusal_match_the_contract_sse_payloads():
    rules = [rule("equipment", "exists", "video monitors")]
    result = decide(ac(), rules, revision_id="r")
    validate_event("decision", result.sse_payload(stage_ms=1.5))
    validate_event("refusal", result.refusal_payload())
    assert set(result.edge_attrs()) == {"decision", "fired_rule_ids", "unknown_fields"}


# --------------------------------------------------------------------------
# 7. Determinism.
# --------------------------------------------------------------------------

def test_same_input_twice_gives_an_identical_answer():
    rules = [
        rule("manufacturer", "eq", "The Boeing Company", index=1),
        rule("serial_number", "serial_in_range", [{"low": "24700", "high": "24800"}], index=2),
        rule("equipment", "exists", "PSU-mounted video monitors", index=3),
    ]
    aircraft = ac()
    first = decide(aircraft, rules, revision_id="r", external_applicability=[])
    second = decide(aircraft, rules, revision_id="r", external_applicability=[])
    assert json.dumps(first.proof_tree(), sort_keys=True) == json.dumps(
        second.proof_tree(), sort_keys=True
    )


def test_decide_does_not_mutate_its_inputs():
    rules = [rule("manufacturer", "eq", "The Boeing Company")]
    aircraft = ac()
    before = json.dumps([aircraft, rules], sort_keys=True)
    decide(aircraft, rules, revision_id="r", external_applicability=[foreign()])
    assert json.dumps([aircraft, rules], sort_keys=True) == before


# --------------------------------------------------------------------------
# 8. The fleet x AD matrix.
# --------------------------------------------------------------------------

def test_matrix_covers_every_pair_and_is_reproducible(tmp_path):
    fleet = [
        ac(),
        ac(tail_number="N409DX", manufacturer="Airbus", model="A330-941", typecode="A339", serial_number="1983"),
        ac(tail_number="N1234X", model="767-383ER", typecode="B763", serial_number="24358"),
    ]
    rules = [
        {**rule("model", "model_matches", ["757-200", "757-300"]), "revision_id": "2026-21864"},
        {
            **rule("model", "model_matches", ["A330-941"], index=1),
            "revision_id": "2026-21861",
            "rule_id": "2026-21861#(c)/r01",
            "paragraph_id": "2026-21861#(c)",
        },
    ]
    built = matrix.build(fleet, rules, [foreign()])
    assert built["decisions"] == len(fleet) * 2
    assert built["revision_count"] == 2
    assert built["us_per_decision"] < 1_000_000, "one decision must be far under a second"
    assert built["cells"]["2026-21864"]["N701UW"]["decision"] == DECISION_APPLIES
    assert built["cells"]["2026-21861"]["N409DX"]["refusal_code"] == REFUSAL_EXTERNAL
    assert built["cells"]["2026-21861"]["N701UW"]["decision"] == DECISION_EXCLUDED

    again = matrix.build(fleet, rules, [foreign()])
    assert built["cells"] == again["cells"]
    assert built["distribution"] == again["distribution"]

    written = matrix.write(tmp_path, built)
    reloaded = json.loads(written["matrix"].read_text(encoding="utf-8"))
    assert reloaded["cells"] == built["cells"]
    assert "edges" not in reloaded
    edges = matrix.load_jsonl(written["edges"])
    assert len(edges) == built["decisions"]
    assert {e["_type"] for e in edges} == {"AFFECTED_BY"}


def test_matrix_decision_values_are_contract_values():
    allowed = set(enum("decision"))
    built = matrix.build([ac()], [rule("manufacturer", "eq", "The Boeing Company")], [])
    assert set(built["distribution"]) <= allowed
    assert set(built["refusal_codes"]) <= set(enum("refusal_code"))
