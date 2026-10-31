"""Build and persist contract-shaped Rule / Action / external-document records.

Everything written here is validated against contracts/contract.json before it
reaches disk: the node must carry exactly the declared fields, the enums must
be contract values, and a Rule's source_quote must be a verbatim substring of
its paragraph. A record that fails is never written -- it becomes an unparsed
rule instead, which the engine turns into an honest CANNOT_DETERMINE.

Outputs (data/build by default):
  rules.jsonl          Rule nodes
  actions.jsonl        Action nodes
  nodes.rules.jsonl    ForeignAD + ServiceBulletin nodes
  edges.rules.jsonl    APPLIES_IF / REQUIRES / ADOPTS_MCAI / REFERENCES_SB
  externals.jsonl      sidecar: which delegation blocks which scope (see
                       docs/contract_change_requests.md -- Rule has no
                       external_ref field and ADOPTS_MCAI carries no scope)
  extraction_report.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from contracts.contract import (  # noqa: E402
    ContractViolation,
    validate_edge,
    validate_enum,
    validate_node,
    validate_rule,
)

from .evaluate import RuleValueError, as_items, as_ranges  # noqa: E402
from .vocab import (  # noqa: E402
    LIST_OPERATORS,
    NODE_FOREIGN_AD,
    NODE_SERVICE_BULLETIN,
    OP_EQ,
    OP_EXISTS,
    OP_NOT_EXISTS,
    OP_UNPARSED,
    RANGE_OPERATORS,
)

SCOPE_APPLICABILITY = "applicability"
SCOPE_COMPLIANCE = "compliance"


def rule_id(paragraph_id: str, index: int) -> str:
    return f"{paragraph_id}/r{index:02d}"


def action_id(paragraph_id: str, index: int) -> str:
    return f"{paragraph_id}/a{index:02d}"


def check_value_shape(operator: str, value: Any) -> None:
    """A value has to match the shape its operator will be evaluated with."""
    if operator == OP_UNPARSED:
        return
    if operator in RANGE_OPERATORS:
        as_ranges(value)
        return
    if operator in (OP_EXISTS, OP_NOT_EXISTS):
        if value is not None and not isinstance(value, str):
            raise RuleValueError(f"{operator} takes a naming string, got {value!r}")
        return
    items = as_items(value)
    if operator == OP_EQ and len(items) > 1:
        raise RuleValueError(f"{OP_EQ} takes one value, got {len(items)}")
    if operator in LIST_OPERATORS and len(items) < 1:
        raise RuleValueError(f"{operator} needs at least one value")


def build_rule(paragraph: dict[str, Any], index: int, payload: dict[str, Any]) -> dict[str, Any]:
    """Assemble a Rule node from an extraction payload. Raises on any violation."""
    record = {
        "rule_id": rule_id(paragraph["paragraph_id"], index),
        "revision_id": paragraph["revision_id"],
        "paragraph_id": paragraph["paragraph_id"],
        "field": payload.get("field"),
        "operator": payload.get("operator"),
        "value": payload.get("value"),
        "source_quote": (payload.get("source_quote") or "").strip(),
        "confidence": payload.get("confidence"),
        "unparsed_reason": payload.get("unparsed_reason"),
    }
    validate_rule(record, paragraph["text"])
    check_value_shape(record["operator"], record["value"])
    return record


def unparsed_rule(
    paragraph: dict[str, Any], index: int, reason: str, *, field: str, quote: str | None = None
) -> dict[str, Any]:
    """A rule we refuse to guess at. The quote is the clause, verbatim.

    When no verbatim clause survived verification the whole paragraph is the
    quote: it is still a verbatim substring of itself, and the UI needs the
    text a human has to read.
    """
    record = {
        "rule_id": rule_id(paragraph["paragraph_id"], index),
        "revision_id": paragraph["revision_id"],
        "paragraph_id": paragraph["paragraph_id"],
        "field": field,
        "operator": OP_UNPARSED,
        "value": "",
        "source_quote": (quote or paragraph["text"]).strip(),
        "confidence": 0.0,
        "unparsed_reason": reason,
    }
    validate_rule(record, paragraph["text"])
    return record


def build_action(paragraph: dict[str, Any], index: int, payload: dict[str, Any]) -> dict[str, Any]:
    """Assemble an Action node. Raises on any contract violation."""
    quote = (payload.get("source_quote") or "").strip()
    record = {
        "action_id": action_id(paragraph["paragraph_id"], index),
        "revision_id": paragraph["revision_id"],
        "paragraph_id": paragraph["paragraph_id"],
        "description": (payload.get("description") or "").strip(),
        "compliance_time": payload.get("compliance_time"),
        "compliance_basis": payload.get("compliance_basis"),
        "source_quote": quote,
        "external_ref": payload.get("external_ref"),
    }
    validate_node("Action", record)
    validate_enum("compliance_basis", record["compliance_basis"])
    if not record["description"]:
        raise ContractViolation(f"Action {record['action_id']} has no description")
    if not quote:
        raise ContractViolation(f"Action {record['action_id']} has no source_quote")
    if _norm(quote) not in _norm(paragraph["text"]):
        raise ContractViolation(
            f"Action {record['action_id']} source_quote is not verbatim in "
            f"{paragraph['paragraph_id']}"
        )
    return record


def _norm(s: str) -> str:
    return " ".join(s.split()).lower()


def external_node(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """(node_type, node) for one referenced document. held is false by design."""
    doc_type = payload.get("document_type")
    number = (payload.get("number") or "").strip()
    if not number:
        raise ContractViolation("external document has no number")
    if doc_type == NODE_FOREIGN_AD:
        authority = payload.get("authority")
        validate_enum("authority", authority)
        node = {
            "foreign_ad_id": f"{authority}:{number}",
            "authority": authority,
            "ad_number": number,
            "dated": payload.get("dated"),
            "held": False,
        }
    elif doc_type == NODE_SERVICE_BULLETIN:
        manufacturer = (payload.get("manufacturer") or "").strip() or None
        revision = (payload.get("revision") or "").strip() or None
        node = {
            "sb_id": ":".join(p for p in (manufacturer or "?", number, revision) if p),
            "manufacturer": manufacturer,
            "number": number,
            "revision": revision,
            "dated": payload.get("dated"),
            "held": False,
        }
        doc_type = NODE_SERVICE_BULLETIN
    else:
        raise ContractViolation(f"unknown external document_type {doc_type!r}")
    validate_node(doc_type, node)
    return doc_type, node


def delegation(
    paragraph: dict[str, Any], scope: str, doc_type: str, node: dict[str, Any], payload: dict[str, Any]
) -> dict[str, Any]:
    """Sidecar record the rules engine consumes as external_applicability."""
    key = "foreign_ad_id" if doc_type == NODE_FOREIGN_AD else "sb_id"
    return {
        "revision_id": paragraph["revision_id"],
        "paragraph_id": paragraph["paragraph_id"],
        "role": paragraph["role"],
        "scope": scope,
        "doc_type": doc_type,
        "doc_id": node[key],
        "label": (payload.get("label") or "").strip() or node[key],
        "dated": node.get("dated"),
        "held": False,
        "source_quote": (payload.get("source_quote") or "").strip(),
    }


def edge(edge_type: str, src_type: str, src: str, dst_type: str, dst: str) -> dict[str, Any]:
    validate_edge(edge_type, src_type, dst_type)
    return {
        "_type": edge_type,
        "_src_type": src_type,
        "_src": src,
        "_dst_type": dst_type,
        "_dst": dst,
    }


def write_jsonl(path: Path, records: Iterable[dict[str, Any]], *, node_type: str | None = None) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            out = dict(record)
            if node_type:
                out = {"_type": node_type, **out}
            fh.write(json.dumps(out, ensure_ascii=False) + "\n")
            count += 1
    return count


def merge_nodes(typed: Iterable[tuple[str, dict[str, Any]]]) -> list[tuple[str, dict[str, Any]]]:
    """One node per key. The same document cited twice fills in each other's nulls.

    A second mention that disagrees on a non-null value does not overwrite the
    first: it is kept as-is and the disagreement is visible in the paragraph
    that produced it, rather than being silently resolved here.
    """
    from contracts.contract import node_types

    merged: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    for node_type, node in typed:
        key = (node_type, str(node[node_types()[node_type]["key"]]))
        if key not in merged:
            merged[key] = dict(node)
            order.append(key)
            continue
        current = merged[key]
        for field_name, value in node.items():
            if current.get(field_name) in (None, "") and value not in (None, ""):
                current[field_name] = value
    return [(key[0], merged[key]) for key in order]


def write_nodes(path: Path, typed: Iterable[tuple[str, dict[str, Any]]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as fh:
        for node_type, node in merge_nodes(typed):
            validate_node(node_type, node)
            fh.write(json.dumps({"_type": node_type, **node}, ensure_ascii=False) + "\n")
            count += 1
    return count
