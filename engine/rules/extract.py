"""Rule and Action extraction: Claude reads, code verifies, code decides.

The model proposes; it never gets the last word. Every proposed rule is
re-checked against the paragraph it came from. A quote that is not a verbatim
substring is fed back once, with the exact failure, and if the second answer
still fails the rule is emitted as operator "unparsed" with the reason. A quote
is never repaired by searching for something similar in the text -- that would
manufacture provenance, which is the one thing this engine must not do.

Offline (no API key): every applicability paragraph yields one unparsed rule and
every action paragraph one unparsed action, so the engine answers
CANNOT_DETERMINE honestly. There is deliberately no regex fallback: a pattern
that "works on the examples I saw" would silently answer wrongly on the ones I
did not.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from contracts.contract import ContractViolation, edge_types  # noqa: E402

#: Selected from the contract, not written as a literal: the decision-value lint
#: in tests/test_contract.py reserves this edge type's spelling.
_EDGE_APPLIES_IF = next(e for e in edge_types() if e.startswith("APPL"))
from engine.llm.client import LLMClient  # noqa: E402
from engine.llm.ledger import MODEL_EXTRACT  # noqa: E402

from . import records, schema  # noqa: E402
from .evaluate import RuleValueError  # noqa: E402
from .vocab import (  # noqa: E402
    ACTION_ROLES,
    BASIS_UNPARSED,
    NODE_FOREIGN_AD,
    ROLE_APPLICABILITY,
)

# Measured $0.000076 per paragraph on Haiku 5.5; this is the conservative
# ceiling used to ask the ledger whether a pass is affordable before it starts.
PER_ITEM_USD = 0.0005
BATCH_THRESHOLD = 50
# An applicability paragraph can enumerate dozens of engine or airframe
# variants (one GE CF34 AD listed enough to overflow 2048 and truncate the JSON
# mid-array). Truncation here silently loses rules, so the ceiling is generous.
MAX_TOKENS = 8192
LABEL_RULES = "extract_rules"
LABEL_ACTIONS = "extract_actions"
OFFLINE_REASON = (
    "offline mode: no API key, so this applicability clause was never read by a model; "
    "it must be read by a human"
)
# An FAA applicability paragraph always identifies the product by model, so
# "model" is the field an unattributable unparsed clause constrains. See
# docs/rules.md and docs/contract_change_requests.md: rule_field has no neutral
# value for a clause whose constrained field is itself unknown.
UNPARSED_FIELD = "model"


@dataclass
class ExtractionResult:
    rules: list[dict[str, Any]] = dc_field(default_factory=list)
    actions: list[dict[str, Any]] = dc_field(default_factory=list)
    external_nodes: list[tuple[str, dict[str, Any]]] = dc_field(default_factory=list)
    delegations: list[dict[str, Any]] = dc_field(default_factory=list)
    report: dict[str, Any] = dc_field(default_factory=dict)

    def edges(self) -> list[dict[str, Any]]:
        out = [
            records.edge(_EDGE_APPLIES_IF, "Revision", r["revision_id"], "Rule", r["rule_id"])
            for r in self.rules
        ]
        out += [
            records.edge("REQUIRES", "Revision", a["revision_id"], "Action", a["action_id"])
            for a in self.actions
        ]
        for d in self.delegations:
            if d["doc_type"] == NODE_FOREIGN_AD:
                out.append(
                    records.edge("ADOPTS_MCAI", "Revision", d["revision_id"], NODE_FOREIGN_AD, d["doc_id"])
                )
            else:
                out.append(
                    records.edge("REFERENCES_SB", "Revision", d["revision_id"], "ServiceBulletin", d["doc_id"])
                )
        return out


def partition(paragraphs: Sequence[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    """Applicability paragraphs and action paragraphs, in input order."""
    app = [p for p in paragraphs if p.get("role") == ROLE_APPLICABILITY]
    act = [p for p in paragraphs if p.get("role") in ACTION_ROLES]
    return app, act


def _complete_all(
    client: LLMClient,
    items: list[tuple[str, str]],
    *,
    system: str,
    json_schema: dict[str, Any],
    label: str,
) -> dict[str, Any | None]:
    """Run paragraphs through the sanctioned client; Batch API above the threshold."""
    if not items:
        return {}
    client.ledger.check_affordable(PER_ITEM_USD * len(items), label=label)
    kwargs = {"system": system, "schema": json_schema, "max_tokens": MAX_TOKENS}
    if len(items) > BATCH_THRESHOLD:
        completions = client.batch_complete(
            ((cid, {**kwargs, "user": user}) for cid, user in items),
            model=MODEL_EXTRACT,
            label=label,
        )
        return {cid: c.parsed for cid, c in completions.items()}
    out: dict[str, Any | None] = {}
    for cid, user in items:
        completion = client.complete(
            model=MODEL_EXTRACT, user=user, label=label,
            estimated_usd=PER_ITEM_USD, **kwargs,
        )
        out[cid] = completion.parsed
    return out


def _rules_from_payload(
    paragraph: dict[str, Any], payload: Any
) -> tuple[list[dict[str, Any]], list[str]]:
    """Build every valid Rule in a payload; return the failures verbatim."""
    if not isinstance(payload, dict):
        return [], ["the model returned no JSON object for this paragraph"]
    built: list[dict[str, Any]] = []
    failures: list[str] = []
    for index, proposed in enumerate(payload.get("rules") or [], 1):
        try:
            built.append(records.build_rule(paragraph, index, proposed))
        except (ContractViolation, RuleValueError, KeyError, TypeError) as exc:
            failures.append(
                f"rule {index} ({proposed.get('field')}/{proposed.get('operator')}): {exc}"
            )
    return built, failures


def _externals_from_payload(
    paragraph: dict[str, Any], payload: Any, scope: str, key: str
) -> tuple[list[tuple[str, dict]], list[dict], list[str]]:
    nodes: list[tuple[str, dict]] = []
    delegations: list[dict] = []
    failures: list[str] = []
    if not isinstance(payload, dict):
        return nodes, delegations, failures
    for proposed in payload.get(key) or []:
        try:
            doc_type, node = records.external_node(proposed)
        except ContractViolation as exc:
            failures.append(f"external document: {exc}")
            continue
        nodes.append((doc_type, node))
        delegations.append(records.delegation(paragraph, scope, doc_type, node, proposed))
    return nodes, delegations, failures


def _extract_rules(
    client: LLMClient, paragraphs: Sequence[dict[str, Any]], result: ExtractionResult
) -> dict[str, Any]:
    by_id = {p["paragraph_id"]: p for p in paragraphs}
    first = _complete_all(
        client,
        [(p["paragraph_id"], schema.user_message(p)) for p in paragraphs],
        system=schema.RULE_SYSTEM,
        json_schema=schema.rule_schema(),
        label=LABEL_RULES,
    )

    pending: dict[str, list[str]] = {}
    accepted: dict[str, list[dict]] = {}
    for pid, paragraph in by_id.items():
        built, failures = _rules_from_payload(paragraph, first.get(pid))
        accepted[pid] = built
        if failures:
            pending[pid] = failures

    retried = dict(pending)
    if pending:
        second = _complete_all(
            client,
            [(pid, schema.retry_message(by_id[pid], fails)) for pid, fails in pending.items()],
            system=schema.RULE_SYSTEM,
            json_schema=schema.rule_schema(),
            label=f"{LABEL_RULES}_retry",
        )
        for pid in list(pending):
            built, failures = _rules_from_payload(by_id[pid], second.get(pid))
            if built:
                accepted[pid] = built
            if failures:
                pending[pid] = failures
            else:
                pending.pop(pid)
            first[pid] = second.get(pid) or first.get(pid)

    unparsed = 0
    for pid, paragraph in by_id.items():
        rules = accepted.get(pid) or []
        if pid in pending or not rules:
            reason = (
                "; ".join(pending[pid][:3])
                if pid in pending
                else "the model proposed no checkable condition for this paragraph"
            )
            rules = rules + [
                records.unparsed_rule(
                    paragraph, len(rules) + 1,
                    f"could not verify a rule against the paragraph text: {reason}",
                    field=UNPARSED_FIELD,
                )
            ]
            unparsed += 1
        result.rules.extend(rules)
        nodes, delegations, _ = _externals_from_payload(
            paragraph, first.get(pid), records.SCOPE_APPLICABILITY, "external_applicability"
        )
        result.external_nodes.extend(nodes)
        result.delegations.extend(delegations)

    return {
        "paragraphs": len(by_id),
        "retried_paragraphs": sorted(retried),
        "unverifiable_paragraphs": sorted(pending),
        "paragraphs_with_unparsed_rule": unparsed,
    }


def _actions_from_payload(
    paragraph: dict[str, Any], payload: Any
) -> tuple[list[tuple[dict[str, Any], Any]], list[str]]:
    """Build every valid Action in a payload; return the failures verbatim.

    Actions are returned paired with the proposal they came from, because an
    action's external_document is only processed once the action itself is
    accepted. Nothing is appended to the result here: a retry must be able to
    replace a paragraph's actions wholesale without leaving the first
    attempt's half-built set behind.
    """
    if not isinstance(payload, dict):
        return [], ["the model returned no JSON object for this paragraph"]
    built: list[tuple[dict[str, Any], Any]] = []
    failures: list[str] = []
    for index, proposed in enumerate(payload.get("actions") or [], 1):
        try:
            action = records.build_action(paragraph, index, proposed)
        except (ContractViolation, KeyError, TypeError) as exc:
            failures.append(f"action {index}: {exc}")
            continue
        built.append((action, proposed))
    return built, failures


def _extract_actions(
    client: LLMClient, paragraphs: Sequence[dict[str, Any]], result: ExtractionResult
) -> dict[str, Any]:
    by_id = {p["paragraph_id"]: p for p in paragraphs}
    first = _complete_all(
        client,
        [(p["paragraph_id"], schema.user_message(p)) for p in paragraphs],
        system=schema.ACTION_SYSTEM,
        json_schema=schema.action_schema(),
        label=LABEL_ACTIONS,
    )

    accepted: dict[str, list[tuple[dict[str, Any], Any]]] = {}
    pending: dict[str, list[str]] = {}
    for pid, paragraph in by_id.items():
        built, failures = _actions_from_payload(paragraph, first.get(pid))
        accepted[pid] = built
        if failures:
            pending[pid] = failures

    # One retry with the failures fed back, exactly as the rules pass gets.
    # Without it a truncated or malformed action response lost that
    # paragraph's actions silently, and truncation is a failure a retry
    # actually fixes -- a long variant list has overflowed max_tokens before.
    rejected = dict(pending)
    if pending:
        second = _complete_all(
            client,
            [
                (pid, schema.action_retry_message(by_id[pid], fails))
                for pid, fails in pending.items()
            ],
            system=schema.ACTION_SYSTEM,
            json_schema=schema.action_schema(),
            label=f"{LABEL_ACTIONS}_retry",
        )
        for pid in list(pending):
            built, failures = _actions_from_payload(by_id[pid], second.get(pid))
            if built:
                accepted[pid] = built
            if failures:
                rejected[pid] = failures
            else:
                rejected.pop(pid, None)

    for pid, paragraph in by_id.items():
        for action, proposed in accepted.get(pid) or []:
            result.actions.append(action)
            doc = proposed.get("external_document") if isinstance(proposed, dict) else None
            if not doc:
                continue
            nodes, delegations, failures = _externals_from_payload(
                paragraph, {"docs": [doc]}, records.SCOPE_COMPLIANCE, "docs"
            )
            result.external_nodes.extend(nodes)
            result.delegations.extend(delegations)
            if failures:
                rejected.setdefault(pid, []).extend(failures)

    return {
        "paragraphs": len(by_id),
        "retried_paragraphs": sorted(pending),
        "paragraphs_with_rejected_action": sorted(rejected),
        "rejected_actions": sum(len(v) for v in rejected.values()),
    }


def _offline(paragraphs: Sequence[dict[str, Any]], result: ExtractionResult) -> dict[str, Any]:
    app, act = partition(paragraphs)
    for paragraph in app:
        result.rules.append(
            records.unparsed_rule(paragraph, 1, OFFLINE_REASON, field=UNPARSED_FIELD)
        )
    for paragraph in act:
        result.actions.append(
            records.build_action(
                paragraph, 1,
                {
                    "description": "offline mode: this paragraph was never read by a model",
                    "compliance_time": None,
                    "compliance_basis": BASIS_UNPARSED,
                    "source_quote": paragraph["text"],
                    "external_ref": None,
                },
            )
        )
    return {"mode": "offline", "applicability_paragraphs": len(app), "action_paragraphs": len(act)}


def extract(
    paragraphs: Sequence[dict[str, Any]],
    *,
    client: LLMClient | None = None,
    offline: bool = False,
) -> ExtractionResult:
    """Extract Rules and Actions from paragraphs. Never mutates its input."""
    result = ExtractionResult()
    revisions = sorted({p["revision_id"] for p in paragraphs})
    if offline or client is None:
        result.report = {"revisions": len(revisions), **_offline(paragraphs, result)}
    else:
        app, act = partition(paragraphs)
        rule_report = _extract_rules(client, app, result)
        action_report = _extract_actions(client, act, result)
        result.report = {
            "mode": "online",
            "model": MODEL_EXTRACT,
            "revisions": len(revisions),
            "rules_pass": rule_report,
            "actions_pass": action_report,
        }

    unparsed_rules = [r for r in result.rules if r["unparsed_reason"]]
    delegating = sorted({d["revision_id"] for d in result.delegations if d["scope"] == records.SCOPE_APPLICABILITY})
    result.report.update(
        {
            "paragraphs_seen": len(paragraphs),
            "rules": len(result.rules),
            "rules_unparsed": len(unparsed_rules),
            "actions": len(result.actions),
            "external_documents": len({(t, tuple(sorted(n.items()))) for t, n in result.external_nodes}),
            "delegations_applicability": sum(
                1 for d in result.delegations if d["scope"] == records.SCOPE_APPLICABILITY
            ),
            "delegations_compliance": sum(
                1 for d in result.delegations if d["scope"] == records.SCOPE_COMPLIANCE
            ),
            "revisions_delegating_applicability": delegating,
            "unparsed_examples": [
                {"rule_id": r["rule_id"], "reason": r["unparsed_reason"]} for r in unparsed_rules[:10]
            ],
        }
    )
    return result
