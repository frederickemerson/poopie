"""Walk the references an AD makes, regardless of how a search ranked them.

An AD is not self-contained: it replaces earlier ADs, adopts a foreign
regulator's directive, and delegates its compliance times to a manufacturer's
service bulletin. Semantic retrieval has no way to know that -- a referenced
document either happens to rank well for the question or is simply absent from
the evidence, and an engine that answers anyway has answered without a
dependency the document named in plain text. This module follows those
references structurally, so the evidence set is decided by what the document
cites rather than by what a scorer liked, and a dependency we do not hold is
*named* instead of missed. The walk is bounded and says which nodes the bound
cut; a target already on the current path is a cycle, recorded and not followed,
while a target merely seen by another path is re-convergence and is not reported
as one. It is a pure function of the graph: no file, no network, no model, and
deterministic throughout.
"""

from __future__ import annotations

import sys
from collections import deque
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import networkx as nx

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contracts.contract import edge_types, validate_enum  # noqa: E402

from engine.graph.loader import EDGE_SUPERSEDES, ADGraph  # noqa: E402
from engine.ingest.supersession import parse_affected_ads  # noqa: E402

AnyGraph = nx.DiGraph | nx.MultiDiGraph
ParagraphLookup = Mapping[str, Mapping[str, Any]]

#: Hops from the starting revision. Three covers the deepest real chain here
#: (AD -> the AD it replaced -> the bulletin that one delegated to), plus a hop.
DEFAULT_MAX_DEPTH = 3

# Contract vocabulary, checked against contract.json at import.
COMPLETE = "COMPLETE"
BOUNDED = "BOUNDED"
CYCLE_DETECTED = "CYCLE_DETECTED"
MISSING_DOCUMENT = "MISSING_DOCUMENT"
for _outcome in (COMPLETE, BOUNDED, CYCLE_DETECTED, MISSING_DOCUMENT):
    validate_enum("traversal_outcome", _outcome)

#: Most consequential first. One outcome is reported, but ``missing``,
#: ``truncated_at`` and ``cycles`` are populated whichever of them wins.
OUTCOME_PRECEDENCE = (MISSING_DOCUMENT, BOUNDED, CYCLE_DETECTED, COMPLETE)

EDGE_ADOPTS_MCAI = "ADOPTS_MCAI"
EDGE_REFERENCES_SB = "REFERENCES_SB"
EDGE_HAS_PARAGRAPH = "HAS_PARAGRAPH"
EDGE_HAS_REVISION = "HAS_REVISION"

#: What a reference means for an answer: supersession changes which document is
#: in force, adoption hands applicability to another regulator, a plain
#: reference cites supporting material. Three different sentences in a refusal.
KIND_SUPERSESSION = "supersession"
KIND_ADOPTION = "adoption"
KIND_REFERENCE = "reference"

_KIND_BY_EDGE: dict[str, str] = {
    EDGE_SUPERSEDES: KIND_SUPERSESSION,
    EDGE_ADOPTS_MCAI: KIND_ADOPTION,
    EDGE_REFERENCES_SB: KIND_REFERENCE,
}
for _edge in (*_KIND_BY_EDGE, EDGE_HAS_PARAGRAPH, EDGE_HAS_REVISION):
    if _edge not in edge_types():
        raise ValueError(f"{_edge!r} is not in contract edge_types {sorted(edge_types())}")

#: Deterministic edge order.
FOLLOWED_EDGES: tuple[str, ...] = tuple(sorted(_KIND_BY_EDGE))

#: Not a contract edge type. ``SUPERSEDES``, ``ADOPTS_MCAI`` and
#: ``REFERENCES_SB`` come from the ingest, built from the document's own markup,
#: and are the authoritative reference set; the one exception is an AD number
#: paragraph (b) names that the corpus has no node for, because the ingest
#: resolves what it can to a ``SUPERSEDES`` edge and leaves the rest dangling,
#: so that paragraph's text is the only surviving trace. Prose-derived
#: references carry this instead of an edge type, so a consumer can tell them
#: apart; docs/contract_change_requests.md asks for the structural fix.
PROSE_AFFECTED_ADS = "affected_ads_paragraph"

ROLE_AFFECTED_ADS = "AFFECTED_ADS"
validate_enum("paragraph_role", ROLE_AFFECTED_ADS)

#: Why a referenced document cannot serve as evidence: no node at all, or a
#: node whose ``held`` field says the text is not ours.
REASON_NOT_IN_CORPUS = "not_in_corpus"
REASON_TEXT_NOT_HELD = "text_not_held"


class UnknownStartNode(KeyError):
    """The walk was asked to start from a node the graph does not hold."""


@dataclass(frozen=True)
class Reference:
    """One explicit reference. ``edge`` is a contract edge type or
    :data:`PROSE_AFFECTED_ADS`; ``resolved`` is True when we hold the target."""

    source: str
    target: str
    edge: str
    kind: str
    resolved: bool
    paragraph_id: str | None = None
    quote: str | None = None


@dataclass(frozen=True)
class ReachedNode:
    """A node reached, and the route to it. ``kind`` is that of the edge which
    first reached it, empty for the start node."""

    node_id: str
    ntype: str | None
    label: str
    kind: str
    depth: int
    path: tuple[str, ...]
    edges: tuple[str, ...]


@dataclass(frozen=True)
class MissingDocument:
    """A document this AD depends on and we cannot read. ``label`` is written to
    be shown: the contract's EXTERNAL_SOURCE_REQUIRED refusal must name the
    document that would resolve it, and "a referenced document" is not a name."""

    identifier: str
    label: str
    ntype: str | None
    kind: str
    reason: str
    referenced_by: str
    paragraph_ids: tuple[str, ...]
    depth: int


def payload_of(record: Any) -> dict[str, Any]:
    """Dataclass -> JSON-ready dict in field order; ``asdict`` recurses, so a
    nested dataclass comes back as a dict."""
    return {k: list(v) if isinstance(v, tuple) else v for k, v in asdict(record).items()}


@dataclass(frozen=True)
class TraversalResult:
    """Everything the answer layer needs about one walk."""

    start: str
    outcome: str
    max_depth: int
    reached: tuple[ReachedNode, ...]
    references: tuple[Reference, ...]
    missing: tuple[MissingDocument, ...]
    cycles: tuple[tuple[str, ...], ...]
    truncated_at: tuple[str, ...]

    @property
    def bounded(self) -> bool:
        return bool(self.truncated_at)

    @property
    def has_cycle(self) -> bool:
        return bool(self.cycles)

    def node_ids(self, *, ntype: str | None = None) -> tuple[str, ...]:
        return tuple(n.node_id for n in self.reached if ntype is None or n.ntype == ntype)

    def as_payload(self) -> dict[str, Any]:
        """The contract's ``answer_envelope.traversal``: the outcome, the
        references followed, and any document that was missing."""
        return payload_of(self)


# ------------------------------------------------------------------- helpers


def _as_nx(graph: AnyGraph | ADGraph) -> AnyGraph:
    """Accept the loader's ADGraph or a bare networkx graph. Checked by type, not
    by looking for ``.graph``: every networkx graph has one of those too (its
    attribute dict), so duck typing would silently traverse an empty dict."""
    return graph.graph if isinstance(graph, ADGraph) else graph


def _out(graph: AnyGraph, node: str, etype: str) -> list[str]:
    if node not in graph:
        return []
    edges = graph.out_edges(node, data=True)
    return sorted({str(dst) for _, dst, data in edges if data.get("etype") == etype})


def describe(data: Mapping[str, Any] | None, node_id: str) -> str:
    """A document name fit to show a user, built from the node's own fields."""
    ntype = (data or {}).get("ntype")
    if not data or not ntype:
        return node_id
    dated = f", dated {data['dated']}" if data.get("dated") else ""
    if ntype == "ForeignAD":
        return f"{data.get('authority') or ''} AD {data.get('ad_number') or node_id}{dated}".strip()
    if ntype == "ServiceBulletin":
        name = " ".join(str(p) for p in (data.get("manufacturer"), data.get("number")) if p)
        revision = f", Revision {data['revision']}" if data.get("revision") else ""
        return f"{name or node_id}{revision}{dated}"
    if ntype == "Revision" and data.get("ad_number"):
        return f"AD {data['ad_number']} revision {node_id}"
    return f"AD {node_id}" if ntype == "AD" else node_id


def _held(graph: AnyGraph, node_id: str) -> bool:
    """Do we hold this document's text? Both ways of not holding it are read from
    structured data: no node at all (an AD outside the ingest window, whose edge
    endpoint networkx materialised attribute-less), or a node whose ``held`` is
    false -- every ForeignAD and ServiceBulletin in this build."""
    data = graph.nodes.get(node_id)
    if not data or not data.get("ntype"):
        return False
    held = data.get("held")
    return True if held is None else bool(held)


def _paragraphs_of(
    graph: AnyGraph, node: str, paragraphs: ParagraphLookup | None
) -> list[tuple[str, Mapping[str, Any]]]:
    """``(paragraph_id, record)`` for one revision, in document order.

    ``paragraphs`` exists because the two graph builds here differ: the loader
    attaches the whole Paragraph record to the node, while the retrieval corpus
    keeps the text in its own row-ordered list and puts only the id in the graph.
    The latter kind of caller passes the lookup in, rather than this module
    guessing where the text lives."""
    found: list[tuple[str, Mapping[str, Any]]] = []
    for paragraph_id in _out(graph, node, EDGE_HAS_PARAGRAPH):
        record = (
            paragraphs.get(paragraph_id)
            if paragraphs is not None
            else graph.nodes.get(paragraph_id)
        )
        if record:
            found.append((paragraph_id, record))
    return sorted(found, key=lambda item: (item[1].get("ordinal") or 0, item[0]))


def _prose_targets(graph: AnyGraph, ad_number: str) -> list[str]:
    """What a referenced AD number resolves to: its current revision when the node
    says which that is, else every revision it has, else the bare number, which
    is then a document outside the corpus."""
    if (graph.nodes.get(ad_number) or {}).get("ntype") != "AD":
        return [ad_number]
    current = (graph.nodes.get(ad_number) or {}).get("current_revision_id")
    if current and current in graph:
        return [str(current)]
    return _out(graph, ad_number, EDGE_HAS_REVISION) or [ad_number]


def references_of(
    graph: AnyGraph | ADGraph, node: str, *, paragraphs: ParagraphLookup | None = None
) -> list[Reference]:
    """Every document one node explicitly points at: edges first, then prose."""
    nx_graph = _as_nx(graph)
    out: list[Reference] = []
    seen: set[str] = set()
    for edge in FOLLOWED_EDGES:
        for target in _out(nx_graph, node, edge):
            if target in seen:
                continue
            seen.add(target)
            out.append(
                Reference(node, target, edge, _KIND_BY_EDGE[edge], _held(nx_graph, target))
            )
    for paragraph_id, record in _paragraphs_of(nx_graph, node, paragraphs):
        if record.get("role") != ROLE_AFFECTED_ADS:
            continue
        parsed = parse_affected_ads(str(record.get("text") or ""))
        for numbers, kind in (
            (parsed.superseded, KIND_SUPERSESSION),
            (parsed.related, KIND_REFERENCE),
        ):
            for ad_number in numbers:
                for target in _prose_targets(nx_graph, ad_number):
                    if target in seen or target == node:
                        continue
                    seen.add(target)
                    out.append(
                        Reference(
                            node, target, PROSE_AFFECTED_ADS, kind,
                            _held(nx_graph, target), paragraph_id, parsed.quote or None,
                        )
                    )
    return out


# ----------------------------------------------------------------- the walk


def traverse(
    graph: AnyGraph | ADGraph,
    start: str,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
    paragraphs: ParagraphLookup | None = None,
) -> TraversalResult:
    """Breadth-first over reference edges from ``start``, so the path recorded to
    each document is the shortest one and the depth bound cuts a whole ring of
    references rather than one arbitrary branch of a depth-first descent. A node
    is *reached* at depth d and expanded only while d < ``max_depth``; a node at
    the bound keeps its references un-enumerated and is named in
    ``truncated_at``."""
    if max_depth < 0:
        raise ValueError(f"max_depth must be >= 0, got {max_depth}")
    nx_graph = _as_nx(graph)
    if start not in nx_graph:
        raise UnknownStartNode(
            f"{start!r} is not in this graph ({nx_graph.number_of_nodes()} nodes); "
            f"a walk starts from a document the corpus holds"
        )

    root = nx_graph.nodes.get(start) or {}
    reached = {
        start: ReachedNode(start, root.get("ntype"), describe(root, start), "", 0, (start,), ())
    }
    references: list[Reference] = []
    missing: dict[str, MissingDocument] = {}
    cycles: list[tuple[str, ...]] = []
    truncated: list[str] = []

    queue: deque[tuple[tuple[str, ...], tuple[str, ...]]] = deque([((start,), ())])
    while queue:
        path, edges = queue.popleft()
        node, depth = path[-1], len(path)
        found = references_of(nx_graph, node, paragraphs=paragraphs)
        if depth - 1 >= max_depth:
            # The bound stopped us here. Name the node, rather than returning a
            # result that looks like it saw everything.
            if found:
                truncated.append(node)
            continue
        references.extend(found)
        for ref in found:
            if not ref.resolved:
                _record_missing(nx_graph, missing, ref, depth)
            elif ref.target in path:
                cycles.append((*path, ref.target))
            elif ref.target not in reached:
                attrs = nx_graph.nodes.get(ref.target) or {}
                route, trail = (*path, ref.target), (*edges, ref.edge)
                reached[ref.target] = ReachedNode(
                    ref.target, attrs.get("ntype"), describe(attrs, ref.target),
                    ref.kind, depth, route, trail,
                )
                queue.append((route, trail))

    seen = {
        MISSING_DOCUMENT: bool(missing),
        BOUNDED: bool(truncated),
        CYCLE_DETECTED: bool(cycles),
        COMPLETE: True,
    }
    return TraversalResult(
        start=start,
        outcome=next(outcome for outcome in OUTCOME_PRECEDENCE if seen[outcome]),
        max_depth=max_depth,
        reached=tuple(sorted(reached.values(), key=lambda n: (n.depth, n.node_id))),
        references=tuple(references),
        missing=tuple(sorted(missing.values(), key=lambda m: m.identifier)),
        cycles=tuple(sorted(cycles)),
        truncated_at=tuple(sorted(set(truncated))),
    )


def _record_missing(
    graph: AnyGraph, missing: dict[str, MissingDocument], ref: Reference, depth: int
) -> None:
    """Record one unreadable document. Breadth-first order makes the first
    sighting the shallowest, so the first wins; ``references`` keeps every later
    sighting, so de-duplicating here loses no evidence."""
    if ref.target in missing:
        return
    attrs = graph.nodes.get(ref.target) or {}
    ntype = attrs.get("ntype")
    prose = ref.edge == PROSE_AFFECTED_ADS
    missing[ref.target] = MissingDocument(
        identifier=ref.target,
        label=describe(attrs, ref.target) if ntype else (f"AD {ref.target}" if prose else ref.target),
        ntype=ntype,
        kind=ref.kind,
        reason=REASON_TEXT_NOT_HELD if ntype else REASON_NOT_IN_CORPUS,
        referenced_by=ref.source,
        paragraph_ids=(ref.paragraph_id,) if ref.paragraph_id else (),
        depth=depth,
    )
