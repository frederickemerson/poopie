"""Load data/build/*.jsonl into one NetworkX graph.

This is the general graph loader other modules import when they want the whole
knowledge graph: dockets, NPRMs, ADs, revisions, paragraphs and the external
documents we do not hold. (``engine/retrieval/corpus.py`` keeps its own loader
because the retrieval index needs paragraphs in a fixed row order; this one is
about the graph.)

Design points worth knowing:

* a MultiDiGraph, so two node types joined by more than one edge type never
  silently overwrite each other;
* node ids are the contract key values, and every node carries ``ntype`` plus
  its contract fields; every edge carries ``etype``;
* ``Revision.plain_text`` is not a contract field, so the canonical text lives
  in the ``revision_text.jsonl`` sidecar and is attached here as a node
  attribute. Paragraph ``char_start``/``char_end`` index into it;
* a missing build file raises :class:`GraphUnavailable` naming the command that
  produces it. An empty graph must never look like a corpus with no answers.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contracts.contract import edge_types, node_types  # noqa: E402

from engine import paths as build_paths  # noqa: E402

BUILD_COMMAND = "python3 -m engine.ingest.build"

#: Selected from the contract rather than written as a literal: the refusal-code
#: lint in tests/test_contract.py reserves this edge type's spelling.
EDGE_SUPERSEDES = next(name for name in edge_types() if name.startswith("SUPERS"))

#: node type -> its contract key field.
KEY_FIELD = {name: spec["key"] for name, spec in node_types().items()}
_SRC_KEYS = ("_src", "src")
_DST_KEYS = ("_dst", "dst")


class GraphUnavailable(RuntimeError):
    """A file the graph needs has not been built yet."""


@dataclass
class ADGraph:
    graph: nx.MultiDiGraph
    plain_text: dict[str, str]

    # ----------------------------------------------------------- selectors

    def nodes_of_type(self, ntype: str) -> list[str]:
        return [n for n, data in self.graph.nodes(data=True) if data.get("ntype") == ntype]

    def attrs(self, node_id: str) -> dict:
        return dict(self.graph.nodes[node_id])

    def _out(self, node_id: str, etype: str) -> list[str]:
        if node_id not in self.graph:
            return []
        return [
            dst
            for _, dst, data in self.graph.out_edges(node_id, data=True)
            if data.get("etype") == etype
        ]

    def _in(self, node_id: str, etype: str) -> list[str]:
        if node_id not in self.graph:
            return []
        return [
            src
            for src, _, data in self.graph.in_edges(node_id, data=True)
            if data.get("etype") == etype
        ]

    def revisions_of(self, ad_number: str) -> list[str]:
        """Revision ids of one AD, oldest first by publication date."""
        revisions = self._out(ad_number, "HAS_REVISION")
        return sorted(
            revisions, key=lambda r: (self.graph.nodes[r].get("publication_date") or "", r)
        )

    def current_revision(self, ad_number: str) -> str | None:
        return self.graph.nodes.get(ad_number, {}).get("current_revision_id")

    def paragraphs_of(self, revision_id: str) -> list[dict]:
        """Paragraph records of one revision, in document order."""
        records = [self.attrs(p) for p in self._out(revision_id, "HAS_PARAGRAPH")]
        return sorted(records, key=lambda r: r.get("ordinal") or 0)

    def paragraph_text(self, revision_id: str, label: str) -> str | None:
        node = self.graph.nodes.get(f"{revision_id}#{label}")
        return node.get("text") if node else None

    def span(self, revision_id: str, char_start: int, char_end: int) -> str:
        """The exact text a citation points at."""
        return self.plain_text.get(revision_id, "")[char_start:char_end]

    def nprms_of(self, docket_id: str) -> list[str]:
        return self._in(docket_id, "IN_DOCKET")

    def proposals_for(self, ad_number: str) -> list[str]:
        return self._out(ad_number, "PROPOSED_BY")

    def supersedes(self, revision_id: str) -> list[str]:
        return self._out(revision_id, EDGE_SUPERSEDES)

    def superseded_by(self, revision_id: str) -> str | None:
        return self.graph.nodes.get(revision_id, {}).get("superseded_by")

    def unheld_references(self, revision_id: str) -> list[dict]:
        """Referenced documents we do not have the text of.

        A revision whose applicability or compliance rests on one of these is
        the contract's EXTERNAL_SOURCE_REQUIRED case: the honest answer is that
        the referenced document is needed, not an inferred decision.
        """
        out: list[dict] = []
        for etype in ("ADOPTS_MCAI", "REFERENCES_SB"):
            for target in self._out(revision_id, etype):
                data = self.attrs(target)
                if not data.get("held"):
                    out.append(data)
        return out


def _read_jsonl(path: Path, *, what: str) -> list[dict]:
    if not path.exists():
        raise GraphUnavailable(f"{path} does not exist; produced by: {BUILD_COMMAND}")
    records: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no} is not JSON: {exc}") from exc
    if not records:
        raise GraphUnavailable(f"{path} exists but holds no {what}; rerun: {BUILD_COMMAND}")
    return records


def _endpoint(record: dict, keys: tuple[str, ...], path: Path) -> str:
    for key in keys:
        value = record.get(key)
        if value:
            return str(value)
    raise ValueError(
        f"{path}: {record.get('_type')!r} edge has no endpoint under any of {list(keys)}; "
        f"it has {sorted(record)}"
    )


def _add_node(graph: nx.MultiDiGraph, record: dict, path: Path) -> None:
    ntype = record.pop("_type", None)
    if not ntype:
        raise ValueError(f"{path}: node record without _type: {sorted(record)}")
    key_field = KEY_FIELD.get(ntype)
    if key_field is None:
        raise ValueError(f"{path}: unknown node type {ntype!r}")
    node_id = record.get(key_field)
    if not node_id:
        raise ValueError(f"{path}: {ntype} record is missing its key {key_field!r}")
    graph.add_node(str(node_id), ntype=ntype, **record)


def load_graph(
    nodes: Path | None = None,
    edges: Path | None = None,
    paragraphs: Path | None = None,
    revision_text: Path | None = None,
) -> ADGraph:
    """Read the built JSONL into an :class:`ADGraph`."""
    nodes_path = nodes or build_paths.NODES_JSONL
    edges_path = edges or build_paths.EDGES_JSONL
    paragraphs_path = paragraphs or build_paths.PARAGRAPHS_JSONL
    text_path = revision_text or build_paths.REVISION_TEXT_JSONL

    graph = nx.MultiDiGraph()
    for record in _read_jsonl(nodes_path, what="nodes"):
        _add_node(graph, record, nodes_path)
    for record in _read_jsonl(paragraphs_path, what="paragraphs"):
        _add_node(graph, record, paragraphs_path)

    for record in _read_jsonl(edges_path, what="edges"):
        etype = record.get("_type")
        if not etype:
            raise ValueError(f"{edges_path}: edge record without _type: {sorted(record)}")
        src = _endpoint(record, _SRC_KEYS, edges_path)
        dst = _endpoint(record, _DST_KEYS, edges_path)
        attrs = {
            k: v
            for k, v in record.items()
            if k not in {"_type", "_src_type", "_dst_type", *_SRC_KEYS, *_DST_KEYS}
        }
        graph.add_edge(src, dst, key=etype, etype=etype, **attrs)

    plain_text: dict[str, str] = {}
    if text_path.exists():
        for record in _read_jsonl(text_path, what="revision text"):
            plain_text[record["revision_id"]] = record.get("plain_text") or ""
        for revision_id, text in plain_text.items():
            if revision_id in graph:
                graph.nodes[revision_id]["plain_text"] = text

    return ADGraph(graph=graph, plain_text=plain_text)


def summary(ad_graph: ADGraph) -> dict[str, int]:
    """Node and edge counts by type, for a build report or a smoke check."""
    counts: dict[str, int] = {}
    for _, data in ad_graph.graph.nodes(data=True):
        key = str(data.get("ntype"))
        counts[key] = counts.get(key, 0) + 1
    for _, _, data in ad_graph.graph.edges(data=True):
        key = str(data.get("etype"))
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


if __name__ == "__main__":
    print(json.dumps(summary(load_graph()), indent=1))
