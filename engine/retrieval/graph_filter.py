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
from engine.graph.stage import (  # noqa: E402
    SOURCE_KIND_NPRM,
    SOURCE_KIND_REVISION,
    SOURCE_KIND_USER_DOCUMENT,
    may_establish_obligation,
)
from engine.retrieval.corpus import Corpus  # noqa: E402
from engine.retrieval.entities import Entities  # noqa: E402

#: rule_field values that can narrow a candidate set to a set of revisions.
_AIRCRAFT_RULE_FIELDS = frozenset({"model", "typecode", "manufacturer"})

#: **The default retrieval scope: adopted rules only.**
#:
#: Proposals are indexed and retrievable, but a caller has to ask for them by
#: name. The default is not a nicety -- the whole corpus is 431 proposals on top
#: of 2,161 adopted revisions, and a proposal's section headings are word for
#: word those of the rule it proposes ("(c) Applicability", "(f) Compliance",
#: "(g) Required Actions"). Let them into the default candidate set and a
#: question about what an operator must do starts competing against text that
#: imposes nothing, which is a straight regression on the answers that matter.
#: So the widening is opt-in, per call, and ``FilterResult.source_kinds``
#: records what was actually searched.
DEFAULT_SOURCE_KINDS: tuple[str, ...] = (SOURCE_KIND_REVISION,)
#: Every kind of document the FAA itself published: adopted rules and proposals.
#: Deliberately NOT widened to include user documents when that kind was added.
#: A caller that passes this today means "the Federal Register, all of it", and
#: quietly changing what it covers would widen every existing call site at once.
ALL_SOURCE_KINDS: tuple[str, ...] = (SOURCE_KIND_REVISION, SOURCE_KIND_NPRM)
#: Proposals only: "what has the FAA proposed about X", never "what must I do".
PROPOSALS_ONLY: tuple[str, ...] = (SOURCE_KIND_NPRM,)
#: Documents the user loaded, and nothing else. What the library search uses.
USER_DOCUMENTS_ONLY: tuple[str, ...] = (SOURCE_KIND_USER_DOCUMENT,)
#: Literally everything indexed. For a caller that has decided to show the user
#: their own material beside the FAA's, with both labelled.
EVERY_SOURCE_KIND: tuple[str, ...] = ALL_SOURCE_KINDS + USER_DOCUMENTS_ONLY

#: **Why user documents are not in the default scope.**
#:
#: Not caution for its own sake -- two concrete reasons.
#:
#: First, the same reason proposals are not: an uploaded service bulletin or
#: foreign AD uses the same vocabulary as the rule it supports ("inspect",
#: "within 500 flight hours", "applicability"), so letting it into the default
#: candidate set means a question about what an operator must do competes
#: against text that imposes nothing here. The corpus is 2,117 adopted ADs; one
#: upload that matches a query well enough can displace the directive that
#: actually answers it out of a top-8.
#:
#: Second, and decisive: the answer writer is handed the retrieved paragraphs
#: and told they are "paragraphs retrieved from adopted FAA ADs". The citation
#: verifier then checks that each quote is verbatim in a retrieved paragraph --
#: which a user document's paragraph would be. So the only thing standing
#: between an upload and a sentence that reads as law would be the writer's own
#: restraint. Keeping user documents out of the default scope makes that
#: structural instead: they cannot reach the writer unless a caller asked for
#: them by name, and ``engine.graph.stage.split_obligation_evidence`` removes
#: them even then.
#:
#: The cost of this choice is that "what does my own manual say about X" is a
#: separate request (``POST /library/search``) rather than part of /ask. That is
#: the right trade: the two questions have different answers and different
#: standing, and merging them is what would need justifying.
_DEFAULT_SCOPE_IS_OBLIGATION_BEARING = all(
    may_establish_obligation(kind, "EFFECTIVE") for kind in DEFAULT_SOURCE_KINDS
)
if not _DEFAULT_SCOPE_IS_OBLIGATION_BEARING:
    raise ValueError(
        "DEFAULT_SOURCE_KINDS holds a source_kind that cannot establish an "
        "obligation. The default retrieval scope is what a question about "
        "compliance is answered from; widen it explicitly per call instead."
    )


@dataclass
class FilterResult:
    """The surviving paragraph ids plus an audit trail of how we got there."""

    paragraph_ids: list[str]
    applied: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)
    revision_ids: list[str] = field(default_factory=list)
    narrowed: bool = False
    #: Which source kinds this filter was allowed to return. Reported so a
    #: caller can show "adopted rules only" rather than leave it implied.
    source_kinds: tuple[str, ...] = DEFAULT_SOURCE_KINDS
    nprm_ids: list[str] = field(default_factory=list)
    user_document_ids: list[str] = field(default_factory=list)

    def as_report(self) -> dict[str, object]:
        return {
            "candidates": len(self.paragraph_ids),
            "applied": self.applied,
            "unavailable": self.unavailable,
            "revisions": len(self.revision_ids),
            "narrowed": self.narrowed,
            "source_kinds": list(self.source_kinds),
            "proposals": len(self.nprm_ids),
            "user_documents": len(self.user_document_ids),
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


@dataclass
class _NodeIndex:
    """Inverted indexes over the graph's node attributes, built once per corpus.

    Both of the filters below used to walk every node on every query. That was
    free while no ``Rule`` node was ever loaded and the model filter could not
    fire; once the 6,397 extracted rules joined the graph it became a ~45,000
    node scan inside a 100 ms budget, and measured p95 went from 39 ms to
    71 ms. These dicts are built once and reused, which is the same answer in
    one hash lookup.
    """

    #: casefolded rule value -> revision ids whose Rule nodes name it
    revisions_by_rule_value: dict[str, set[str]] = field(default_factory=dict)
    #: False when the graph holds no aircraft-scoped Rule node at all, which is
    #: "this filter is unavailable" and not "nothing matched".
    has_aircraft_rules: bool = False
    revisions_by_make: dict[str, list[str]] = field(default_factory=dict)
    nprms_by_make: dict[str, list[str]] = field(default_factory=dict)


#: Memoised per Corpus instance. The corpus is immutable once loaded (its
#: paragraph order is fingerprinted and checked against the index), so one
#: build per instance is correct.
_INDEX_ATTR = "_graph_filter_node_index"


def _node_index(corpus: Corpus) -> _NodeIndex:
    cached = getattr(corpus, _INDEX_ATTR, None)
    if cached is not None:
        return cached
    index = _NodeIndex()
    for node, data in corpus.graph.nodes(data=True):
        ntype = data.get("ntype")
        if ntype == "Rule":
            if data.get("field") not in _AIRCRAFT_RULE_FIELDS:
                continue
            index.has_aircraft_rules = True
            revision = data.get("revision_id")
            if not revision:
                continue
            value = data.get("value")
            values = value if isinstance(value, list) else [value]
            for item in values:
                if isinstance(item, str) and item:
                    index.revisions_by_rule_value.setdefault(
                        item.casefold(), set()
                    ).add(str(revision))
        elif ntype == "AD":
            canonical = data.get("make_canonical")
            if canonical:
                index.revisions_by_make.setdefault(canonical, []).extend(
                    _out(corpus, node, "HAS_REVISION")
                )
        elif ntype == "NPRM":
            canonical = data.get("make_canonical")
            if canonical:
                index.nprms_by_make.setdefault(canonical, []).append(node)
    setattr(corpus, _INDEX_ATTR, index)
    return index


def _revisions_for_manufacturer(corpus: Corpus, canonical: str) -> list[str]:
    """Revisions of every AD whose make normalises to this manufacturer."""
    return list(_node_index(corpus).revisions_by_make.get(canonical, []))


def _nprms_for_manufacturer(corpus: Corpus, canonical: str) -> list[str]:
    return list(_node_index(corpus).nprms_by_make.get(canonical, []))


def _nprms_in_docket(corpus: Corpus, docket: str) -> list[str]:
    return [
        node
        for node in _in(corpus, docket, "IN_DOCKET")
        if (corpus.graph.nodes.get(node) or {}).get("ntype") == "NPRM"
    ]


def _revisions_for_models(corpus: Corpus, models: list[str], typecodes: list[str]) -> list[str] | None:
    """Revisions whose Rule nodes name one of these models or typecodes.

    Returns None when the graph holds no aircraft-scoped Rule nodes at all: that
    is "this filter is not available", which is a different fact from "nothing
    matched" and must not be conflated with it.
    """
    wanted = {m.casefold() for m in models} | {t.casefold() for t in typecodes}
    if not wanted:
        return None
    index = _node_index(corpus)
    if not index.has_aircraft_rules:
        return None
    hits: set[str] = set()
    for value in wanted:
        hits |= index.revisions_by_rule_value.get(value, set())
    return sorted(hits)


def series_covering(corpus: Corpus, designation: str) -> list[str] | None:
    """The series this corpus holds directives for under ``designation``.

    The planner returns whatever designation the engineer typed -- "767",
    "Superjet 100" -- while the graph indexes the exact series the directives
    name: 767-200, 767-2C, 767-300, 767-300F, 767-400ER. A partial designation
    is therefore a *prefix* of the series it covers, and testing equality alone
    reports a 767 as absent while five 767 series sit in the index. That would
    make the engine state "no directive here concerns 767", which is false and
    worse than saying nothing.

    The prefix has to end at the series separator, so "7" cannot claim "767-300"
    and "767" cannot claim "7670-1" if such a type were ever added.

    Returns ``None`` when the graph holds no aircraft-scoped Rule nodes at all,
    because "cannot tell" is not "absent", and ``[]`` when the designation is
    genuinely unknown to every loaded directive.
    """
    key = designation.strip().casefold()
    if not key:
        return None
    index = _node_index(corpus)
    if not index.has_aircraft_rules:
        return None
    return sorted(
        value
        for value in index.revisions_by_rule_value
        if value == key or value.startswith(f"{key}-")
    )


def filter_candidates(
    corpus: Corpus,
    entities: Entities,
    *,
    revision_scope: str = "current",
    revision_ids: list[str] | None = None,
    source_kinds: tuple[str, ...] = DEFAULT_SOURCE_KINDS,
    nprm_ids: list[str] | None = None,
) -> FilterResult:
    """Candidate paragraph ids after graph filtering.

    ``revision_scope`` follows the contract's query plan: ``current`` keeps only
    the latest revision of each matched AD, ``all`` keeps every revision, and
    ``specific`` means the caller passed explicit ``revision_ids``.

    ``source_kinds`` defaults to adopted rules only -- see
    :data:`DEFAULT_SOURCE_KINDS`. Pass :data:`ALL_SOURCE_KINDS` to search
    proposals as well, :data:`PROPOSALS_ONLY` to search only proposals, or
    :data:`USER_DOCUMENTS_ONLY` to search only what the user loaded. No
    identifier filter can reach a user document: an AD number, a docket, an
    amendment and a model all belong to the Federal Register, and a user
    document has none of them, so it is reachable by subject alone.
    An AD number, an amendment or an explicit revision id narrows to adopted
    revisions and never pulls in a proposal: those identifiers belong to an
    adopted rule, and the graph already records the proposal that preceded it
    through its docket.
    """
    applied: list[str] = []
    unavailable: list[str] = []
    current_only = revision_scope == "current"
    selected: set[str] = set()
    selected_nprms: set[str] = set()
    want_proposals = SOURCE_KIND_NPRM in source_kinds
    narrowed = False

    if nprm_ids:
        known = [n for n in nprm_ids if n in corpus.nprms]
        missing = [n for n in nprm_ids if n not in corpus.nprms]
        if known and want_proposals:
            selected_nprms.update(known)
            applied.append("proposal")
            narrowed = True
        elif known:
            unavailable.append("proposal:source_kinds excludes proposals")
        if missing:
            unavailable.append(f"proposal:{','.join(sorted(missing))}")

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
        proposals = _nprms_in_docket(corpus, docket) if want_proposals else []
        if revisions or proposals:
            selected.update(revisions)
            selected_nprms.update(proposals)
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
            proposals = (
                _nprms_for_manufacturer(corpus, canonical) if want_proposals else []
            )
            if revisions or proposals:
                selected.update(revisions)
                selected_nprms.update(proposals)
                applied.append(f"manufacturer:{canonical}")
                narrowed = True
            else:
                unavailable.append(f"manufacturer:{canonical}")

    if not narrowed:
        kept = [p for p in corpus.paragraphs if p.source_kind in source_kinds]
        # ``current`` means the latest revision of each AD, so it applies to a
        # paragraph of an adopted revision and to nothing else. A proposal has
        # no revision chain to be current in -- the newest notice in a
        # re-noticed docket is not a "current revision" -- and neither has a
        # document the user loaded. Asked as "is it a proposal OR is it
        # current", this read correctly only while those were the only two
        # kinds; asked of the revision itself it stays correct as kinds are
        # added.
        if current_only:
            kept = [p for p in kept if not p.is_adopted_revision or p.is_current_revision]
        paragraph_ids = [p.paragraph_id for p in kept]
        return FilterResult(
            paragraph_ids=paragraph_ids,
            applied=applied,
            unavailable=unavailable,
            revision_ids=sorted(
                {p.document_id for p in kept if p.is_adopted_revision}
            ),
            narrowed=False,
            source_kinds=source_kinds,
            nprm_ids=sorted({p.document_id for p in kept if p.is_proposal}),
            user_document_ids=sorted(
                {p.document_id for p in kept if p.is_user_document}
            ),
        )

    wanted = selected | selected_nprms
    kept = [
        p
        for p in corpus.paragraphs
        if p.source_kind in source_kinds and p.document_id in wanted
    ]
    return FilterResult(
        paragraph_ids=[p.paragraph_id for p in kept],
        applied=applied,
        unavailable=unavailable,
        revision_ids=sorted(selected),
        narrowed=True,
        source_kinds=source_kinds,
        nprm_ids=sorted(selected_nprms),
    )


def _amendment_of(corpus: Corpus, revision_id: str) -> str | None:
    data = corpus.graph.nodes.get(revision_id) or {}
    return data.get("amendment")
