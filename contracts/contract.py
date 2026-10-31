"""Loader and validators for contracts/contract.json.

Every module that produces or consumes graph data, SSE events or eval records
imports from here. Nothing re-declares a node type, edge type or enum value
locally; if it is not in contract.json it does not exist.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

CONTRACT_PATH = Path(__file__).with_name("contract.json")


class ContractViolation(ValueError):
    """Raised when data does not match contracts/contract.json."""


@lru_cache(maxsize=1)
def contract() -> dict[str, Any]:
    with CONTRACT_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def node_types() -> dict[str, Any]:
    return contract()["node_types"]


def edge_types() -> dict[str, Any]:
    return contract()["edge_types"]


def enum(name: str) -> list[str]:
    enums = contract()["enums"]
    if name not in enums:
        raise ContractViolation(f"unknown enum {name!r}; contract has {sorted(enums)}")
    return enums[name]


def sse_events() -> dict[str, Any]:
    return contract()["sse_events"]


def validate_node(node_type: str, record: dict[str, Any]) -> None:
    """Reject an unknown node type or a field the contract does not declare."""
    types = node_types()
    if node_type not in types:
        raise ContractViolation(f"unknown node type {node_type!r}; contract has {sorted(types)}")
    allowed = set(types[node_type]["fields"])
    extra = set(record) - allowed
    if extra:
        raise ContractViolation(
            f"{node_type} has fields absent from the contract: {sorted(extra)}. "
            f"Add them to contracts/contract.json or drop them."
        )
    key = types[node_type]["key"]
    if not record.get(key):
        raise ContractViolation(f"{node_type} is missing its key field {key!r}")


def validate_edge(edge_type: str, src_type: str, dst_type: str) -> None:
    edges = edge_types()
    if edge_type not in edges:
        raise ContractViolation(f"unknown edge type {edge_type!r}; contract has {sorted(edges)}")
    spec = edges[edge_type]
    if src_type not in spec["from"]:
        raise ContractViolation(f"{edge_type} cannot start at {src_type}; allowed {spec['from']}")
    if dst_type != spec["to"]:
        raise ContractViolation(f"{edge_type} must end at {spec['to']}, got {dst_type}")


def validate_enum(enum_name: str, value: str) -> None:
    allowed = enum(enum_name)
    if value not in allowed:
        raise ContractViolation(f"{value!r} is not a valid {enum_name}; allowed {allowed}")


def validate_rule(rule: dict[str, Any], paragraph_text: str) -> None:
    """Enforce the invariant that a Rule's source_quote is really in its paragraph."""
    validate_node("Rule", rule)
    validate_enum("rule_field", rule["field"])
    validate_enum("rule_operator", rule["operator"])
    quote = (rule.get("source_quote") or "").strip()
    if not quote:
        raise ContractViolation(f"Rule {rule['rule_id']} has no source_quote")
    if _norm(quote) not in _norm(paragraph_text):
        raise ContractViolation(
            f"Rule {rule['rule_id']} source_quote is not a verbatim substring of "
            f"paragraph {rule['paragraph_id']}"
        )


def validate_event(name: str, payload: dict[str, Any]) -> None:
    events = sse_events()
    if name not in events:
        raise ContractViolation(f"unknown SSE event {name!r}; contract has {sorted(events)}")
    required = set(events[name]["payload"])
    missing = required - set(payload)
    extra = set(payload) - required
    if missing:
        raise ContractViolation(f"SSE {name} is missing payload keys {sorted(missing)}")
    if extra:
        raise ContractViolation(f"SSE {name} has undeclared payload keys {sorted(extra)}")


def validate_citation(citation_id: str, retrieved_paragraph_ids: set[str]) -> None:
    """A citation must point at a paragraph this query actually retrieved."""
    para_id = citation_id.split("@", 1)[0]
    if para_id not in retrieved_paragraph_ids:
        raise ContractViolation(
            f"citation {citation_id!r} cites {para_id!r}, which was not retrieved for this query"
        )


def _norm(s: str) -> str:
    return " ".join(s.split()).lower()
