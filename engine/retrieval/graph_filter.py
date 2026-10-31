"""Narrow the candidate paragraph set by graph traversal, before any scoring.

Order matters and is the point: an AD number is an exact fact, so it should
decide the candidate set outright rather than compete with semantic similarity
inside a scorer. Filtering first also means the search arms do less work, which
is where most of the latency budget is saved on identifier queries.

Every filter reports whether it could be applied. A filter the graph cannot
support (no ``Rule`` nodes yet, so no model-level narrowing) is reported as
unavailable, never silently skipped and never approximated by matching strings
against paragraph text -- that would re-derive, badly, what the rules engine
produces properly.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.graph.normalize import normalize_manufacturer  # noqa: E402
from engine.retrieval.corpus import Corpus  # noqa: E402
from engine.retrieval.entities import Entities  # noqa: E402

#: rule_field values that can narrow a candidate set to a set of revisions.
_AIRCRAFT_RULE_FIELDS = frozenset({"model", "typecode", "manufacturer"})


@dataclass
class FilterResult:
    """The surviving paragraph ids plus an audit trail of how we got there."""

    paragraph_ids: list[str]
    applied: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)
    revision_ids: list[str] = field(default_factory=list)
    narrowed: bool = False

    def as_report(self) -> dict[str, object]:
        return {
            "candidates": len(self.paragraph_ids),
            "applied": self.applied,
            "unavailable": self.unavailable,
            "revisions": len(self.revision_ids),
            "narrowed": self.narrowed,
        }


def _out(corpus: Corpus, node: str, etype: str) -> list[str]:
    graph = corpus.graph
    if node not in graph:
        return []
    return [d for _, d, data in graph.out_edges(node, data=True) if data.get("etype") == etype]


def _in(corpus: Corpus, node: str, etype: str) -> list[str]:
    graph = corpus.graph
    if node not in graph:
        return []
    return [s for s, _, data in graph.in_edges(node, data=True) if data.get("etype") == etype]


def revisions_of_ad(corpus: Corpus, ad_number: str, *, current_only: bool) -> list[str]:
    revisions = _out(corpus, ad_number, "HAS_REVISION")
    if not current_only:
        return revisions
    current = [r for r in revisions if corpus.revisions[r].is_current] if revisions else []
    return current or revisions


def _revisions_for_manufacturer(corpus: Corpus, canonical: str) -> list[str]:
    """Revisions of every AD whose make normalises to this manufacturer."""
    out: list[str] = []
    for node, data in corpus.graph.nodes(data=True):
        if data.get("ntype") != "AD":
            continue
        if data.get("make_canonical") == canonical:
            out.extend(_out(corpus, node, "HAS_REVISION"))
    return out


def _revisions_for_models(corpus: Corpus, models: list[str], typecodes: list[str]) -> list[str] | None:
    """Revisions whose Rule nodes name one of these models or typecodes.

    Returns None when the graph holds no aircraft-scoped Rule nodes at all: that
    is "this filter is not available", which is a different fact from "nothing
    matched" and must not be conflated with it.
    """
    wanted = {m.casefold() for m in models} | {t.casefold() for t in typecodes}
    if not wanted:
        return None
    any_rules = False
    hits: set[str] = set()
    for _, data in corpus.graph.nodes(data=True):
        if data.get("ntype") != "Rule":
            continue
        if data.get("field") not in _AIRCRAFT_RULE_FIELDS:
            continue
        any_rules = True
        value = data.get("value")
        if isinstance(value, str) and value.casefold() in wanted:
            revision = data.get("revision_id")
            if revision:
                hits.add(str(revision))
        elif isinstance(value, list):
            if {str(v).casefold() for v in value} & wanted:
                revision = data.get("revision_id")
                if revision:
                    hits.add(str(revision))
    if not any_rules:
        return None
    return sorted(hits)


def filter_candidates(
    corpus: Corpus,
    entities: Entities,
    *,
    revision_scope: str = "current",
    revision_ids: list[str] | None = None,
) -> FilterResult:
    """Candidate paragraph ids after graph filtering.

    ``revision_scope`` follows the contract's query plan: ``current`` keeps only
    the latest revision of each matched AD, ``all`` keeps every revision, and
    ``specific`` means the caller passed explicit ``revision_ids``.
    """
    applied: list[str] = []
    unavailable: list[str] = []
    current_only = revision_scope == "current"
    selected: set[str] = set()
    narrowed = False

    if revision_ids:
        known = [r for r in revision_ids if r in corpus.revisions]
        missing = [r for r in revision_ids if r not in corpus.revisions]
        if known:
            selected.update(known)
            applied.append("revision")
            narrowed = True
        if missing:
            unavailable.append(f"revision:{','.join(sorted(missing))}")

    for ad in entities.ad_numbers:
        revisions = revisions_of_ad(corpus, ad, current_only=current_only)
        if revisions:
            selected.update(revisions)
            applied.append(f"ad:{ad}")
            narrowed = True
        else:
            unavailable.append(f"ad:{ad}")

    for docket in entities.docket_ids:
        ads = _in(corpus, docket, "IN_DOCKET")
        revisions = [
            r
            for ad in ads
            for r in revisions_of_ad(corpus, ad, current_only=current_only)
        ]
        if revisions:
            selected.update(revisions)
            applied.append(f"docket:{docket}")
            narrowed = True
        else:
            unavailable.append(f"docket:{docket}")

    for amendment in entities.amendments:
        revisions = [
            rid for rid, meta in corpus.revisions.items()
            if _amendment_of(corpus, rid) == amendment
        ]
        if revisions:
            selected.update(revisions)
            applied.append(f"amendment:{amendment}")
            narrowed = True
        else:
            unavailable.append(f"amendment:{amendment}")

    if not narrowed and (entities.models or entities.typecodes):
        by_model = _revisions_for_models(corpus, entities.models, entities.typecodes)
        if by_model is None:
            unavailable.append("model:no Rule nodes in graph")
        elif by_model:
            selected.update(by_model)
            applied.append("model")
            narrowed = True
        else:
            unavailable.append("model:no matching Rule")

    if not narrowed and entities.manufacturers:
        for raw in entities.manufacturers:
            canonical = normalize_manufacturer(raw) or raw
            revisions = _revisions_for_manufacturer(corpus, canonical)
            if revisions:
                selected.update(revisions)
                applied.append(f"manufacturer:{canonical}")
                narrowed = True
            else:
                unavailable.append(f"manufacturer:{canonical}")

    if not narrowed:
        paragraph_ids = (
            [p.paragraph_id for p in corpus.paragraphs]
            if not current_only
            else [p.paragraph_id for p in corpus.paragraphs if p.is_current_revision]
        )
        return FilterResult(
            paragraph_ids=paragraph_ids,
            applied=applied,
            unavailable=unavailable,
            revision_ids=sorted({p.split("#", 1)[0] for p in paragraph_ids}),
            narrowed=False,
        )

    paragraph_ids = [
        p.paragraph_id for p in corpus.paragraphs if p.revision_id in selected
    ]
    return FilterResult(
        paragraph_ids=paragraph_ids,
        applied=applied,
        unavailable=unavailable,
        revision_ids=sorted(selected),
        narrowed=True,
    )


def _amendment_of(corpus: Corpus, revision_id: str) -> str | None:
    data = corpus.graph.nodes.get(revision_id) or {}
    return data.get("amendment")
