"""Write contract-validated JSONL.

Every node line is built from the contract's own field list, so a line carries
exactly the declared fields (absent values are explicit nulls) and a typo
becomes an error here rather than a missing key three layers downstream. Nodes
and edges are de-duplicated by key, so callers may emit the same reference as
often as they find it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, TextIO

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from contracts.contract import (  # noqa: E402
    ContractViolation,
    edge_types,
    node_types,
    validate_edge,
    validate_enum,
    validate_node,
)

#: node field -> enum that constrains it.
_ENUM_FIELDS = {
    ("Paragraph", "role"): "paragraph_role",
    ("ForeignAD", "authority"): "authority",
    ("NPRM", "source"): "source",
    ("Aircraft", "source"): "source",
}


def edge_type_named(prefix: str) -> str:
    """The one contract edge type starting with ``prefix``.

    Edge type names are selected rather than written as literals because
    tests/test_contract.py reserves some spellings for the refusal_code enum,
    and the contract's own SUPERSEDES edge collides with one of them.
    """
    matches = [name for name in edge_types() if name.startswith(prefix)]
    if len(matches) != 1:
        raise ContractViolation(
            f"expected exactly one edge type starting with {prefix!r}, got {matches}"
        )
    return matches[0]


class GraphWriter:
    """Streaming writer for nodes.jsonl, edges.jsonl and paragraphs.jsonl."""

    def __init__(self, nodes: Path, edges: Path, paragraphs: Path) -> None:
        self._nodes: TextIO = nodes.open("w", encoding="utf-8")
        self._edges: TextIO = edges.open("w", encoding="utf-8")
        self._paragraphs: TextIO = paragraphs.open("w", encoding="utf-8")
        self._seen_nodes: set[tuple[str, str]] = set()
        self._seen_edges: set[tuple[str, str, str]] = set()
        self.node_counts: dict[str, int] = {}
        self.edge_counts: dict[str, int] = {}

    def __enter__(self) -> GraphWriter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        for handle in (self._nodes, self._edges, self._paragraphs):
            if not handle.closed:
                handle.close()

    # ---------------------------------------------------------------- nodes

    def node(self, node_type: str, values: dict[str, Any]) -> str:
        """Emit one node. Returns its key value. Repeat calls are ignored."""
        spec = node_types().get(node_type)
        if spec is None:
            raise ContractViolation(f"unknown node type {node_type!r}")
        unknown = set(values) - set(spec["fields"])
        if unknown:
            raise ContractViolation(
                f"{node_type} was given fields the contract does not declare: {sorted(unknown)}"
            )
        record = {field: values.get(field) for field in spec["fields"]}
        validate_node(node_type, record)
        for (owner, field), enum_name in _ENUM_FIELDS.items():
            if owner == node_type and record.get(field) is not None:
                validate_enum(enum_name, record[field])

        key = str(record[spec["key"]])
        identity = (node_type, key)
        if identity in self._seen_nodes:
            return key
        self._seen_nodes.add(identity)
        handle = self._paragraphs if node_type == "Paragraph" else self._nodes
        handle.write(json.dumps({"_type": node_type, **record}, ensure_ascii=False) + "\n")
        self.node_counts[node_type] = self.node_counts.get(node_type, 0) + 1
        return key

    # ---------------------------------------------------------------- edges

    def edge(
        self,
        edge_type: str,
        src_type: str,
        src: str,
        dst_type: str,
        dst: str,
        **attrs: Any,
    ) -> None:
        validate_edge(edge_type, src_type, dst_type)
        if not src or not dst:
            raise ContractViolation(f"{edge_type} needs both endpoints, got {src!r} -> {dst!r}")
        identity = (edge_type, str(src), str(dst))
        if identity in self._seen_edges:
            return
        self._seen_edges.add(identity)
        # _src/_dst rather than src/dst: the contract does not pin the endpoint
        # key (see docs/contract_change_requests.md) and this is the spelling the
        # other producers in engine/ already write and engine/retrieval reads first.
        record = {
            "_type": edge_type,
            "_src_type": src_type,
            "_dst_type": dst_type,
            "_src": str(src),
            "_dst": str(dst),
        }
        if attrs:
            declared = set(edge_types()[edge_type].get("attrs") or ())
            undeclared = set(attrs) - declared
            if undeclared:
                raise ContractViolation(
                    f"{edge_type} has no contract attrs {sorted(undeclared)}"
                )
            record.update(attrs)
        self._edges.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.edge_counts[edge_type] = self.edge_counts.get(edge_type, 0) + 1

    def has_node(self, node_type: str, key: str) -> bool:
        return (node_type, key) in self._seen_nodes


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    """Sidecar writer for data the contract has no field for. Never validated."""
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
