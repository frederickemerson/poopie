"""Reference traversal: bounded, cycle-safe, and loud about what it cannot read.

A correctness property, not a feature: before this existed a referenced document
was in the evidence only if it happened to rank well, and the engine could not
tell "no such dependency" from "a dependency I never looked for". Every test is
one of the four ways that goes wrong -- the walk stops early, never stops, cannot
read what it found, or silently omits it. Graphs are hand-built so the expected
reachability is a fact of the fixture, not of a build another agent is still
writing; the last two tests re-check the real corpus against the ingest's count.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import networkx as nx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contracts.contract import enum  # noqa: E402
from engine.graph.traverse import (  # noqa: E402
    BOUNDED, COMPLETE, CYCLE_DETECTED, EDGE_ADOPTS_MCAI, EDGE_HAS_PARAGRAPH,
    EDGE_REFERENCES_SB, KIND_ADOPTION, KIND_REFERENCE, KIND_SUPERSESSION,
    MISSING_DOCUMENT, PROSE_AFFECTED_ADS, REASON_NOT_IN_CORPUS,
    REASON_TEXT_NOT_HELD, UnknownStartNode, references_of, traverse,
)
from engine.graph.loader import EDGE_SUPERSEDES, load_graph  # noqa: E402

BUILD = ROOT / "data" / "build"


def _graph(nodes: dict[str, dict], edges: list[tuple[str, str, str]]) -> nx.MultiDiGraph:
    """A MultiDiGraph shaped like the loader's. Edges are added in the order
    given, so a test can re-add them differently and prove the output does not
    depend on insertion order."""
    graph = nx.MultiDiGraph()
    graph.add_nodes_from(nodes.items())
    for src, etype, dst in edges:
        graph.add_edge(src, dst, key=etype, etype=etype)
    return graph


def _revision(ad_number: str) -> dict:
    return {"ntype": "Revision", "ad_number": ad_number}


def _paragraph(revision_id: str, label: str, role: str, text: str) -> dict:
    return {
        "ntype": "Paragraph", "paragraph_id": f"{revision_id}#{label}", "label": label,
        "revision_id": revision_id, "role": role, "text": text, "ordinal": 1}


def _chain() -> nx.MultiDiGraph:
    """A -> B -> C by supersession, every document held."""
    numbers = {"rev-a": "2026-21-13", "rev-b": "2024-11-04", "rev-c": "2021-03-08"}
    return _graph(
        {node: _revision(n) for node, n in numbers.items()},
        [("rev-a", EDGE_SUPERSEDES, "rev-b"), ("rev-b", EDGE_SUPERSEDES, "rev-c")])


# --- 1. A chain we can read all of is COMPLETE. -------------------------


def test_chain_of_three_resolves_complete():
    result = traverse(_chain(), "rev-a")

    assert result.outcome == COMPLETE
    assert result.node_ids() == ("rev-a", "rev-b", "rev-c")
    assert (result.missing, result.cycles, result.truncated_at) == ((), (), ())
    assert not result.bounded
    # The route to each document is on the record, not just the fact of it.
    assert {n.node_id: n.path for n in result.reached} == {
        "rev-a": ("rev-a",),
        "rev-b": ("rev-a", "rev-b"),
        "rev-c": ("rev-a", "rev-b", "rev-c"),
    }
    assert {n.node_id: n.depth for n in result.reached} == {"rev-a": 0, "rev-b": 1, "rev-c": 2}


def test_outcome_is_always_a_contract_enum_value():
    allowed = set(enum("traversal_outcome"))
    assert {traverse(_chain(), "rev-a", max_depth=d).outcome for d in (0, 1, 2, 3)} <= allowed


# --- 2. The depth bound truncates, and says so. -------------------------


def test_depth_limit_reports_bounded_and_names_where_it_stopped():
    result = traverse(_chain(), "rev-a", max_depth=1)

    assert result.outcome == BOUNDED
    assert result.bounded
    # It stopped at rev-b, which still has a reference we did not enumerate.
    assert result.truncated_at == ("rev-b",)
    assert result.node_ids() == ("rev-a", "rev-b")


def test_the_same_chain_is_complete_once_the_bound_allows_it():
    """The BOUNDED above comes from the limit, not the graph: the only difference
    here is max_depth. rev-c appears, and reaching it at exactly the limit is not
    truncation, because it has no references left unread."""
    bounded = traverse(_chain(), "rev-a", max_depth=1)
    complete = traverse(_chain(), "rev-a", max_depth=2)

    assert "rev-c" not in bounded.node_ids()
    assert complete.node_ids()[-1] == "rev-c"
    assert complete.outcome == COMPLETE
    assert complete.truncated_at == ()


def test_depth_zero_enumerates_nothing_and_says_so():
    result = traverse(_chain(), "rev-a", max_depth=0)

    assert result.outcome == BOUNDED
    assert result.node_ids() == ("rev-a",)
    assert result.truncated_at == ("rev-a",)


# --- 3. Cycles terminate and are reported; re-convergence is not a cycle. ----


def test_a_mutual_supersession_terminates_and_reports_the_cycle():
    graph = _graph(
        {"rev-a": _revision("2026-21-13"), "rev-b": _revision("2024-11-04")},
        [("rev-a", EDGE_SUPERSEDES, "rev-b"), ("rev-b", EDGE_SUPERSEDES, "rev-a")],
    )

    result = traverse(graph, "rev-a")

    assert result.outcome == CYCLE_DETECTED
    assert result.has_cycle
    assert result.cycles == (("rev-a", "rev-b", "rev-a"),)
    assert result.node_ids() == ("rev-a", "rev-b")

    loop = _graph({"rev-a": _revision("2026-21-13")}, [("rev-a", EDGE_SUPERSEDES, "rev-a")])
    assert traverse(loop, "rev-a").cycles == (("rev-a", "rev-a"),)


def test_a_supersedes_b_which_references_a_terminates():
    """The shape the spec names: A supersedes B, and B's "Affected ADs"
    paragraph points back at A. The reference is real -- it resolves through the
    AD node to A's current revision -- so only path-based cycle detection stops
    it."""
    graph = _graph(
        {
            "rev-a": _revision("2026-21-13"),
            "rev-b": _revision("2024-11-04"),
            "2026-21-13": {"ntype": "AD", "current_revision_id": "rev-a"},
            "rev-b#(b)": _paragraph(
                "rev-b", "(b)", "AFFECTED_ADS",
                "Affected ADs\nThis AD is related to AD 2026-21-13, Amendment 39-23502.",
            ),
        },
        [("rev-a", EDGE_SUPERSEDES, "rev-b"), ("rev-b", EDGE_HAS_PARAGRAPH, "rev-b#(b)")],
    )

    result = traverse(graph, "rev-a")

    assert result.outcome == CYCLE_DETECTED
    assert result.cycles == (("rev-a", "rev-b", "rev-a"),)
    # And the reference itself was still recorded, as a plain reference: "is
    # related to" is not supersession.
    back = [r for r in result.references if r.source == "rev-b"]
    assert [(r.target, r.kind, r.edge) for r in back] == [
        ("rev-a", KIND_REFERENCE, PROSE_AFFECTED_ADS)
    ]


def test_re_convergence_is_not_a_cycle():
    """Two paths to one document is a diamond, not a loop. Reporting it as a
    cycle would make the honest outcome CYCLE_DETECTED on ordinary data."""
    graph = _graph(
        {name: _revision(f"2026-00-0{i}") for i, name in enumerate("abcd")},
        [("a", EDGE_SUPERSEDES, "b"), ("a", EDGE_SUPERSEDES, "c"),
         ("b", EDGE_SUPERSEDES, "d"), ("c", EDGE_SUPERSEDES, "d")],
    )

    result = traverse(graph, "a")

    assert result.outcome == COMPLETE
    assert result.cycles == ()
    assert result.node_ids() == ("a", "b", "c", "d")


# --- 4. A referenced document we do not hold is named, never skipped. ----


def _delegating_graph() -> nx.MultiDiGraph:
    """One revision referencing all three kinds of document we do not hold."""
    return _graph(
        {
            "rev-a": _revision("2026-21-13"),
            "EASA-2025-0208": {
                "ntype": "ForeignAD", "authority": "EASA", "ad_number": "2025-0208",
                "dated": "September 24, 2025", "held": False,
            },
            "BOEING-757-25-0320-RB-R1": {
                "ntype": "ServiceBulletin", "manufacturer": "Boeing", "held": False,
                "number": "757-25-0320 RB", "revision": "1", "dated": "August 6, 2025",
            },
            "rev-a#(b)": _paragraph(
                "rev-a", "(b)", "AFFECTED_ADS",
                "Affected ADs\nThis AD replaces AD 2009-04-13, Amendment 39-15873.",
            ),
        },
        [
            ("rev-a", EDGE_ADOPTS_MCAI, "EASA-2025-0208"),
            ("rev-a", EDGE_REFERENCES_SB, "BOEING-757-25-0320-RB-R1"),
            ("rev-a", EDGE_HAS_PARAGRAPH, "rev-a#(b)"),
        ],
    )


def test_an_unheld_foreign_ad_and_bulletin_are_reported_missing_by_name():
    result = traverse(_delegating_graph(), "rev-a")
    by_id = {m.identifier: m for m in result.missing}

    assert result.outcome == MISSING_DOCUMENT
    foreign, bulletin = by_id["EASA-2025-0208"], by_id["BOEING-757-25-0320-RB-R1"]
    assert foreign.label == "EASA AD 2025-0208, dated September 24, 2025"
    assert (foreign.kind, foreign.reason) == (KIND_ADOPTION, REASON_TEXT_NOT_HELD)
    assert bulletin.label == "Boeing 757-25-0320 RB, Revision 1, dated August 6, 2025"
    assert (bulletin.kind, bulletin.reason) == (KIND_REFERENCE, REASON_TEXT_NOT_HELD)


def test_an_ad_outside_the_corpus_is_reported_missing_with_its_identifier():
    """The replaced AD is outside the ingest window, so the graph holds no node
    for it. Its number is still what a user must go and fetch."""
    result = traverse(_delegating_graph(), "rev-a")

    outside = {m.identifier: m for m in result.missing}["2009-04-13"]
    assert outside.label == "AD 2009-04-13"
    assert outside.ntype is None
    assert outside.reason == REASON_NOT_IN_CORPUS
    assert outside.kind == KIND_SUPERSESSION
    # And it can be shown: the paragraph that names it is on the record.
    assert outside.paragraph_ids == ("rev-a#(b)",)


def test_an_edge_to_a_revision_the_corpus_lacks_is_missing_not_reached():
    graph = _graph(
        {"rev-a": _revision("2026-21-13")}, [("rev-a", EDGE_SUPERSEDES, "rev-gone")]
    )

    result = traverse(graph, "rev-a")

    assert result.outcome == MISSING_DOCUMENT
    assert result.node_ids() == ("rev-a",)
    assert [m.identifier for m in result.missing] == ["rev-gone"]
    assert result.missing[0].reason == REASON_NOT_IN_CORPUS


def test_missing_wins_over_a_cycle_in_the_reported_outcome():
    """One outcome is reported, so the order matters; the cycle is still on the
    result, which is why choosing an order hides nothing."""
    graph = _delegating_graph()
    graph.add_edge("rev-a", "rev-a", key=EDGE_SUPERSEDES, etype=EDGE_SUPERSEDES)

    result = traverse(graph, "rev-a")

    assert result.outcome == MISSING_DOCUMENT
    assert result.has_cycle and result.missing


# --- 5. The three kinds of reference stay apart. ------------------------


def test_edge_kinds_are_distinguished():
    graph = _delegating_graph()
    graph.add_node("rev-b", **_revision("2024-11-04"))
    graph.add_edge("rev-a", "rev-b", key=EDGE_SUPERSEDES, etype=EDGE_SUPERSEDES)

    kinds = {(r.target, r.kind) for r in references_of(graph, "rev-a")}

    assert kinds >= {
        ("rev-b", KIND_SUPERSESSION),
        ("EASA-2025-0208", KIND_ADOPTION),
        ("BOEING-757-25-0320-RB-R1", KIND_REFERENCE),
    }


def test_a_replaced_ad_is_supersession_and_a_related_one_is_not():
    graph = _graph(
        {
            "rev-a": _revision("2026-21-13"),
            "rev-a#(b)": _paragraph(
                "rev-a",
                "(b)",
                "AFFECTED_ADS",
                "Affected ADs\nThis AD replaces AD 2019-20-07, Amendment 39-19760. "
                "This AD affects AD 2023-26-01, Amendment 39-22644.",
            ),
        },
        [("rev-a", EDGE_HAS_PARAGRAPH, "rev-a#(b)")],
    )

    kinds = {r.target: r.kind for r in references_of(graph, "rev-a")}

    assert kinds == {"2019-20-07": KIND_SUPERSESSION, "2023-26-01": KIND_REFERENCE}

    # "None." is the commonest value of this paragraph and references nothing.
    empty = _graph(
        {
            "rev-a": _revision("2026-21-13"),
            "rev-a#(b)": _paragraph("rev-a", "(b)", "AFFECTED_ADS", "Affected ADs\nNone."),
        },
        [("rev-a", EDGE_HAS_PARAGRAPH, "rev-a#(b)")],
    )
    assert references_of(empty, "rev-a") == []
    assert traverse(empty, "rev-a").outcome == COMPLETE


# --- 6. Determinism and error handling. ---------------------------------


def test_output_does_not_depend_on_edge_insertion_order():
    nodes = dict(_delegating_graph().nodes(data=True))
    edges = [
        ("rev-a", EDGE_ADOPTS_MCAI, "EASA-2025-0208"),
        ("rev-a", EDGE_REFERENCES_SB, "BOEING-757-25-0320-RB-R1"),
        ("rev-a", EDGE_HAS_PARAGRAPH, "rev-a#(b)"),
    ]

    forward = traverse(_graph(nodes, edges), "rev-a").as_payload()
    backward = traverse(_graph(nodes, list(reversed(edges))), "rev-a").as_payload()

    assert json.dumps(forward) == json.dumps(backward)
    # And the payload is what the answer envelope needs, through JSON.
    round_tripped = json.loads(json.dumps(forward))
    assert round_tripped["outcome"] == MISSING_DOCUMENT
    assert {"start", "outcome", "max_depth", "reached", "references", "missing"} <= set(
        round_tripped
    )
    assert round_tripped["missing"][0]["label"]


def test_bad_input_raises_instead_of_returning_an_empty_result():
    with pytest.raises(UnknownStartNode, match="not in this graph"):
        traverse(_chain(), "rev-nope")
    with pytest.raises(ValueError, match="max_depth"):
        traverse(_chain(), "rev-a", max_depth=-1)


# --- 7. The real corpus, cross-checked against the ingest's own count. ----


def _ingest_report() -> dict | None:
    path = BUILD / "ingest_report.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _superseded_ads_outside_corpus(graph) -> dict[int, set[tuple[str, str]]]:
    """``(start revision, AD number)`` pairs the walk could not resolve, by hop."""
    found: dict[int, set[tuple[str, str]]] = {}
    for revision in graph.nodes_of_type("Revision"):
        for doc in traverse(graph, revision).missing:
            if doc.reason == REASON_NOT_IN_CORPUS and doc.kind == KIND_SUPERSESSION:
                found.setdefault(doc.depth, set()).add((revision, doc.identifier))
    return found


def test_real_corpus_dangling_ads_match_the_ingest_and_go_further():
    """Two claims on real data. First hop: the ingest counts, per revision, the
    AD references it could not resolve to a node, and the walk reads them back
    out of paragraph (b) independently -- the counts agreeing is evidence the
    walk reads the real reference set and not a regex of its own. Beyond the
    first hop: an AD that replaces one we hold can still depend on one we do
    not, and those are invisible to any per-revision count."""
    report = _ingest_report()
    if report is None or not (BUILD / "nodes.jsonl").exists():
        pytest.skip("no built corpus yet - run the ingest")
    expected = report.get("supersession", {}).get("referenced_ads_outside_corpus")
    if expected is None:
        pytest.skip("ingest report predates the dangling-reference count")

    by_depth = _superseded_ads_outside_corpus(load_graph())

    assert len(by_depth.get(1, set())) == expected
    beyond = {pair for depth, pairs in by_depth.items() if depth > 1 for pair in pairs}
    assert beyond - by_depth[1], (
        "no transitively-missing AD found; either the corpus has no resolvable "
        "supersession chains or the walk is not following them"
    )


def test_real_corpus_every_revision_gets_a_contract_outcome():
    if not (BUILD / "nodes.jsonl").exists():
        pytest.skip("no built corpus yet - run the ingest")
    graph = load_graph()

    outcomes = {traverse(graph, r).outcome for r in graph.nodes_of_type("Revision")}

    assert outcomes and outcomes <= set(enum("traversal_outcome"))
