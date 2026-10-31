"""Extraction: schema enums, the verbatim-quote invariant, the retry, offline.

No test here touches the network. Two mechanisms enforce that: the LLMClient
``client`` property is monkeypatched to raise, and every response is either a
recorded payload handed to a duck-typed client or a seeded entry in the real
client's on-disk cache.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contracts.contract import ContractViolation, enum, validate_node  # noqa: E402
from engine.llm.client import Completion, LLMClient  # noqa: E402
from engine.llm.ledger import MODEL_EXTRACT, CostLedger, Usage  # noqa: E402
from engine.rules import cli, extract as extract_mod, records, schema  # noqa: E402
from engine.rules.engine import decide  # noqa: E402
from engine.rules.vocab import (  # noqa: E402
    BASIS_EXTERNAL,
    BASIS_UNPARSED,
    DECISION_UNDETERMINED,
    NODE_FOREIGN_AD,
    NODE_SERVICE_BULLETIN,
    OP_UNPARSED,
    REFUSAL_UNPARSED,
)

FIXTURE_PARAGRAPHS = ROOT / "data" / "fixtures" / "paragraphs_sample.jsonl"
BOEING_APPLICABILITY = "2026-21864#(c)"
AIRBUS_APPLICABILITY = "2026-21861#(c)"
BOEING_ACTION = "2026-21864#(g)(1)"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any attempt to reach the Anthropic SDK fails the test loudly."""

    def forbidden(self):
        raise AssertionError("a test tried to open a real API connection")

    monkeypatch.setattr(LLMClient, "client", property(forbidden))


@pytest.fixture
def paragraphs() -> list[dict]:
    assert FIXTURE_PARAGRAPHS.exists(), "the committed paragraph fixture is missing"
    return [json.loads(line) for line in FIXTURE_PARAGRAPHS.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture
def by_id(paragraphs) -> dict[str, dict]:
    return {p["paragraph_id"]: p for p in paragraphs}


def ledger(tmp_path, cap: float = 1.0) -> CostLedger:
    """A ledger that never touches the project's real spend record."""
    return CostLedger(cap_usd=cap, path=tmp_path / "ledger.jsonl")


def _paragraph_id(user: str) -> str:
    revision = re.search(r"^AD revision: (.+)$", user, re.M).group(1).strip()
    label = re.search(r"^Paragraph label: (.+)$", user, re.M).group(1).strip()
    return f"{revision}#{label}"


class RecordedClient:
    """Duck-types the two LLMClient methods extraction uses, from recordings."""

    def __init__(self, cost_ledger: CostLedger, responses: dict[tuple[str, str], dict]):
        self.ledger = cost_ledger
        self.responses = responses
        self.calls: list[tuple[str, str, str]] = []

    def complete(self, *, model, user, label, system="", max_tokens=4096, schema=None, effort="low", estimated_usd=0.0):
        paragraph_id = _paragraph_id(user)
        self.calls.append((label, paragraph_id, user))
        payload = self.responses.get((label, paragraph_id))
        return Completion(
            text=json.dumps(payload) if payload is not None else "",
            parsed=payload,
            usage=Usage(),
            cost_usd=0.0,
            cached_hit=True,
            model=model,
        )

    def batch_complete(self, requests, *, model, label, poll_seconds=20):
        return {cid: self.complete(model=model, label=label, **kw) for cid, kw in requests}

    def users_for(self, label: str) -> list[str]:
        return [user for called, _, user in self.calls if called == label]


def rule_payload(*rules, external=()) -> dict:
    return {"rules": list(rules), "external_applicability": list(external)}


def proposed(field, operator, value, quote, *, confidence=0.9, reason=None) -> dict:
    return {
        "field": field,
        "operator": operator,
        "value": value,
        "source_quote": quote,
        "confidence": confidence,
        "unparsed_reason": reason,
    }


# --------------------------------------------------------------------------
# 1. The schema pins the contract's vocabulary.
# --------------------------------------------------------------------------

def test_rule_schema_pins_field_and_operator_enums_from_the_contract():
    item = schema.rule_schema()["properties"]["rules"]["items"]["properties"]
    assert item["field"]["enum"] == enum("rule_field")
    assert item["operator"]["enum"] == enum("rule_operator")
    assert item["field"]["enum"] and item["operator"]["enum"], "an empty enum pins nothing"


def test_action_schema_pins_compliance_basis_and_authority_enums():
    item = schema.action_schema()["properties"]["actions"]["items"]["properties"]
    assert item["compliance_basis"]["enum"] == enum("compliance_basis")
    doc = item["external_document"]["anyOf"][0]["properties"]
    assert doc["authority"]["enum"] == enum("authority")
    assert doc["document_type"]["enum"] == [NODE_FOREIGN_AD, NODE_SERVICE_BULLETIN]


def test_every_schema_object_forbids_undeclared_properties():
    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False, node.get("properties", {}).keys()
                assert set(node.get("required", [])) == set(node.get("properties", {}))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema.rule_schema())
    walk(schema.action_schema())


def test_an_operator_outside_the_enum_is_rejected_not_stored(by_id):
    """The live failure this schema exists to prevent: operator 'equipped with'."""
    paragraph = by_id[BOEING_APPLICABILITY]
    with pytest.raises(ContractViolation):
        records.build_rule(
            paragraph,
            1,
            proposed(
                "equipment",
                "equipped with",
                "video monitors",
                "equipped with passenger service unit (PSU)-mounted video monitors",
            ),
        )


def test_off_enum_operator_becomes_an_unparsed_rule_not_a_dropped_one(tmp_path, by_id):
    paragraph = by_id[BOEING_APPLICABILITY]
    bad = proposed(
        "equipment", "equipped with", "video monitors",
        "equipped with passenger service unit (PSU)-mounted video monitors",
    )
    client = RecordedClient(
        ledger(tmp_path),
        {
            (extract_mod.LABEL_RULES, BOEING_APPLICABILITY): rule_payload(bad),
            (f"{extract_mod.LABEL_RULES}_retry", BOEING_APPLICABILITY): rule_payload(bad),
        },
    )
    result = extract_mod.extract([paragraph], client=client)
    assert [r["operator"] for r in result.rules] == [OP_UNPARSED]
    assert "equipped with" in result.rules[0]["unparsed_reason"]
    assert decide(
        {"tail_number": "N1", "typecode": "B752", "model": "757-232"}, result.rules
    ).decision == DECISION_UNDETERMINED


# --------------------------------------------------------------------------
# 2. The verbatim-quote invariant, and the single retry.
# --------------------------------------------------------------------------

def test_a_paraphrased_quote_is_retried_once_with_the_failure_fed_back(tmp_path, by_id):
    paragraph = by_id[BOEING_APPLICABILITY]
    paraphrased = proposed(
        "model", "model_matches", ["757-200", "757-300"],
        "Model 757-200 and 757-300 series airplanes",  # the AD says "and -300"
    )
    verbatim = proposed(
        "model", "model_matches", ["757-200", "757-300"],
        "Model 757-200 and -300 series airplanes",
    )
    client = RecordedClient(
        ledger(tmp_path),
        {
            (extract_mod.LABEL_RULES, BOEING_APPLICABILITY): rule_payload(paraphrased),
            (f"{extract_mod.LABEL_RULES}_retry", BOEING_APPLICABILITY): rule_payload(verbatim),
        },
    )
    result = extract_mod.extract([paragraph], client=client)

    retries = client.users_for(f"{extract_mod.LABEL_RULES}_retry")
    assert len(retries) == 1, "exactly one retry, never a loop"
    assert "rejected" in retries[0] and "verbatim" in retries[0]
    assert "source_quote is not a verbatim substring" in retries[0]
    assert [r["source_quote"] for r in result.rules] == ["Model 757-200 and -300 series airplanes"]
    assert result.report["rules_pass"]["retried_paragraphs"] == [BOEING_APPLICABILITY]
    assert result.report["rules_pass"]["unverifiable_paragraphs"] == []
    assert result.rules[0]["source_quote"] in paragraph["text"]


def test_a_quote_that_fails_twice_is_emitted_unparsed_and_never_repaired(tmp_path, by_id):
    paragraph = by_id[BOEING_APPLICABILITY]
    paraphrased = proposed(
        "model", "model_matches", ["757-200"], "Boeing 757-200 and 757-300 aeroplanes"
    )
    client = RecordedClient(
        ledger(tmp_path),
        {
            (extract_mod.LABEL_RULES, BOEING_APPLICABILITY): rule_payload(paraphrased),
            (f"{extract_mod.LABEL_RULES}_retry", BOEING_APPLICABILITY): rule_payload(paraphrased),
        },
    )
    result = extract_mod.extract([paragraph], client=client)

    assert len(result.rules) == 1
    rule = result.rules[0]
    assert rule["operator"] == OP_UNPARSED
    assert "verbatim" in rule["unparsed_reason"]
    assert rule["source_quote"] == paragraph["text"], "the clause a human must read"
    assert paraphrased["source_quote"] not in rule["source_quote"], "no quote was repaired"
    assert result.report["rules_pass"]["unverifiable_paragraphs"] == [BOEING_APPLICABILITY]


def test_every_emitted_rule_satisfies_the_contract_invariant(tmp_path, by_id):
    from contracts.contract import validate_rule

    paragraph = by_id[BOEING_APPLICABILITY]
    mixed = rule_payload(
        proposed("manufacturer", "eq", "The Boeing Company", "The Boeing Company Model 757-200"),
        proposed("model", "model_matches", ["757-200"], "invented text not in the paragraph"),
    )
    client = RecordedClient(
        ledger(tmp_path),
        {
            (extract_mod.LABEL_RULES, BOEING_APPLICABILITY): mixed,
            (f"{extract_mod.LABEL_RULES}_retry", BOEING_APPLICABILITY): mixed,
        },
    )
    result = extract_mod.extract([paragraph], client=client)
    for rule in result.rules:
        validate_rule({k: v for k, v in rule.items()}, paragraph["text"])
    assert OP_UNPARSED in {r["operator"] for r in result.rules}


def test_a_paraphrased_action_quote_is_rejected(by_id):
    paragraph = by_id[BOEING_ACTION]
    with pytest.raises(ContractViolation):
        records.build_action(
            paragraph,
            1,
            {
                "description": "Do the bulletin",
                "compliance_time": "as specified",
                "compliance_basis": BASIS_EXTERNAL,
                "source_quote": "at the times specified in the Compliance paragraph",
                "external_ref": "Boeing 757-25-0320 RB",
            },
        )


# --------------------------------------------------------------------------
# 3. External delegation.
# --------------------------------------------------------------------------

def test_delegated_applicability_emits_a_foreign_ad_and_blocks_the_decision(tmp_path, by_id):
    paragraph = by_id[AIRBUS_APPLICABILITY]
    payload = rule_payload(
        proposed("model", "model_matches", ["A330-941"], "Model A330-941 airplanes"),
        external=[
            {
                "document_type": NODE_FOREIGN_AD,
                "authority": "EASA",
                "manufacturer": None,
                "number": "2025-0208",
                "revision": None,
                "dated": "September 24, 2025",
                "label": "EASA AD 2025-0208",
                "source_quote": "as identified in European Union Aviation Safety Agency (EASA) AD 2025-0208, dated September 24, 2025",
            }
        ],
    )
    client = RecordedClient(ledger(tmp_path), {(extract_mod.LABEL_RULES, AIRBUS_APPLICABILITY): payload})
    result = extract_mod.extract([paragraph], client=client)

    assert result.report["revisions_delegating_applicability"] == ["2026-21861"]
    kinds = [t for t, _ in result.external_nodes]
    assert kinds == [NODE_FOREIGN_AD]
    node = result.external_nodes[0][1]
    validate_node(NODE_FOREIGN_AD, node)
    assert node == {
        "foreign_ad_id": "EASA:2025-0208",
        "authority": "EASA",
        "ad_number": "2025-0208",
        "dated": "September 24, 2025",
        "held": False,
    }
    delegation = result.delegations[0]
    assert delegation["scope"] == records.SCOPE_APPLICABILITY
    assert delegation["source_quote"] in paragraph["text"]
    assert {e["_type"] for e in result.edges()} == {"APPLIES_IF", "ADOPTS_MCAI"}

    a339 = {"tail_number": "N409DX", "manufacturer": "Airbus", "model": "A330-941", "typecode": "A339"}
    outcome = decide(
        a339, result.rules, revision_id="2026-21861", external_applicability=result.delegations
    )
    assert outcome.refusal["code"] == enum("refusal_code")[-1]  # EXTERNAL_SOURCE_REQUIRED


def test_a_deadline_in_a_service_bulletin_becomes_an_external_action(tmp_path, by_id):
    paragraph = by_id[BOEING_ACTION]
    quote = (
        "at the applicable times specified in the “Compliance” paragraph of Boeing "
        "Special Attention Requirements Bulletin 757-25-0320 RB, Revision 1, dated August 6, 2025"
    )
    assert quote in paragraph["text"], "the fixture must carry the real clause"
    payload = {
        "actions": [
            {
                "description": "Do all applicable actions in the Accomplishment Instructions.",
                "compliance_time": quote,
                "compliance_basis": BASIS_EXTERNAL,
                "source_quote": quote,
                "external_ref": "Boeing Special Attention Requirements Bulletin 757-25-0320 RB, Revision 1, dated August 6, 2025",
                "external_document": {
                    "document_type": NODE_SERVICE_BULLETIN,
                    "authority": "UNKNOWN",
                    "manufacturer": "Boeing",
                    "number": "757-25-0320 RB",
                    "revision": "1",
                    "dated": "August 6, 2025",
                    "label": "Boeing Special Attention Requirements Bulletin 757-25-0320 RB, Revision 1",
                    "source_quote": quote,
                },
            }
        ]
    }
    client = RecordedClient(ledger(tmp_path), {(extract_mod.LABEL_ACTIONS, BOEING_ACTION): payload})
    result = extract_mod.extract([paragraph], client=client)

    assert len(result.actions) == 1
    action = result.actions[0]
    validate_node("Action", action)
    assert action["compliance_basis"] == BASIS_EXTERNAL
    assert action["external_ref"].startswith("Boeing Special Attention")
    assert [t for t, _ in result.external_nodes] == [NODE_SERVICE_BULLETIN]
    assert result.delegations[0]["scope"] == records.SCOPE_COMPLIANCE
    assert result.report["delegations_applicability"] == 0, (
        "a deadline in a bulletin must not block applicability"
    )


# --------------------------------------------------------------------------
# 4. Offline mode degrades honestly.
# --------------------------------------------------------------------------

def test_offline_emits_one_unparsed_rule_per_applicability_paragraph(paragraphs):
    result = extract_mod.extract(paragraphs, client=None, offline=True)
    applicability, actions = extract_mod.partition(paragraphs)
    assert len(result.rules) == len(applicability) == 3
    assert {r["operator"] for r in result.rules} == {OP_UNPARSED}
    assert all("offline" in r["unparsed_reason"] for r in result.rules)
    assert {a["compliance_basis"] for a in result.actions} == {BASIS_UNPARSED}
    assert len(result.actions) == len(actions)
    assert result.report["mode"] == "offline"


def test_offline_rules_make_every_aircraft_cannot_determine(paragraphs):
    result = extract_mod.extract(paragraphs, offline=True)
    boeing = [r for r in result.rules if r["revision_id"] == "2026-21864"]
    outcome = decide(
        {"tail_number": "N701UW", "model": "757-232", "typecode": "B752", "manufacturer": "Boeing"},
        boeing,
        revision_id="2026-21864",
    )
    assert outcome.decision == DECISION_UNDETERMINED
    assert outcome.refusal["code"] == REFUSAL_UNPARSED
    assert outcome.refusal["evidence_paragraph_ids"] == [BOEING_APPLICABILITY]


def test_offline_quotes_stay_verbatim(paragraphs):
    from contracts.contract import validate_rule

    by_id = {p["paragraph_id"]: p for p in paragraphs}
    for rule in extract_mod.extract(paragraphs, offline=True).rules:
        validate_rule(rule, by_id[rule["paragraph_id"]]["text"])


def test_offline_cli_writes_contract_valid_artifacts(tmp_path):
    code = cli.main(
        [
            "extract",
            "--offline",
            "--paragraphs", str(FIXTURE_PARAGRAPHS),
            "--out-dir", str(tmp_path),
        ]
    )
    assert code == 0
    report = json.loads((tmp_path / "extraction_report.json").read_text(encoding="utf-8"))
    assert report["mode"] == "offline"
    assert report["run_cost_usd"] == 0.0, "offline mode must not spend anything"

    for name, node_type in (("rules.jsonl", "Rule"), ("actions.jsonl", "Action")):
        lines = (tmp_path / name).read_text(encoding="utf-8").splitlines()
        assert lines
        for line in lines:
            record = json.loads(line)
            assert record.pop("_type") == node_type
            validate_node(node_type, record)


# --------------------------------------------------------------------------
# 5. The real client, served from a recorded on-disk cache.
# --------------------------------------------------------------------------

def test_real_client_path_runs_from_cache_without_spending(tmp_path, by_id):
    paragraph = by_id[BOEING_APPLICABILITY]
    payload = rule_payload(
        proposed("model", "model_matches", ["757-200", "757-300"], "Model 757-200 and -300 series airplanes")
    )
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    key = LLMClient._key(
        {
            "model": MODEL_EXTRACT,
            "system": schema.RULE_SYSTEM,
            "user": schema.user_message(paragraph),
            "schema": schema.rule_schema(),
            "effort": "low",
            "max_tokens": extract_mod.MAX_TOKENS,
        }
    )
    (cache_dir / f"{key}.json").write_text(
        json.dumps(
            {
                "text": json.dumps(payload),
                "parsed": payload,
                "usage": Usage(input_tokens=900, output_tokens=120).__dict__,
                "model": MODEL_EXTRACT,
            }
        ),
        encoding="utf-8",
    )
    cost_ledger = ledger(tmp_path)
    client = LLMClient(ledger=cost_ledger, cache_dir=cache_dir)

    result = extract_mod.extract([paragraph], client=client)
    assert [r["operator"] for r in result.rules] == ["model_matches"]
    assert cost_ledger.spent_usd() == 0.0, "a cache hit is free"
    assert result.report["mode"] == "online"


def test_the_cap_stops_a_run_it_cannot_afford(tmp_path, paragraphs):
    from engine.llm.ledger import BudgetExceeded

    cost_ledger = ledger(tmp_path, cap=0.0)
    client = LLMClient(ledger=cost_ledger, cache_dir=tmp_path / "cache")
    with pytest.raises(BudgetExceeded):
        extract_mod.extract(paragraphs, client=client)
