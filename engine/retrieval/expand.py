"""Add the paragraphs an AD explicitly points at, whatever the scorer thought.

Retrieval ranks paragraphs by resemblance to the question. A document the AD
*names* -- the AD it replaced, the EASA directive it adopts, the bulletin
holding its compliance times -- has no reason to resemble the question, so it
can rank anywhere, including nowhere. Dropping it is not a ranking miss, it is a
missing dependency, and the engine has no way to notice from the scores alone.

So after the semantic pass this layer walks the reference graph from the top
hits (see ``engine.graph.traverse``) and adds the referenced documents'
paragraphs regardless of score. Three properties make that safe:

* **Marked, not smuggled.** Every paragraph carries ``origin``: ``semantic``
  when a search arm ranked it, ``reference`` when this layer pulled it in. The
  UI can label it and the verifier can hold reference-derived evidence to
  whatever standard it chooses; neither has to guess where a paragraph came from.
* **Capped.** An AD citing fifty bulletins cannot drown the evidence. The caps
  are on documents, on paragraphs per document, and on paragraphs in total; when
  one bites, ``capped`` is set and ``cap_reason`` says which, so a truncated
  evidence set is never silent. Within a document the cap keeps the paragraphs
  that carry obligations first, ordered by the ingest's own ``role``.
* **Loud about what is missing.** A referenced document we do not hold cannot be
  added at all, and that is the contract's EXTERNAL_SOURCE_REQUIRED case rather
  than a gap to answer around. ``missing`` names each one, so the answer layer
  can refuse with the document named instead of answering without it.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contracts.contract import validate_enum  # noqa: E402

from engine.graph.traverse import (  # noqa: E402
    COMPLETE,
    OUTCOME_PRECEDENCE,
    MissingDocument,
    TraversalResult,
    payload_of,
    traverse,
)
from engine.retrieval.corpus import Corpus, Paragraph  # noqa: E402
from engine.retrieval.search import Hit, SearchResult  # noqa: E402

#: Where a paragraph in the evidence set came from. The distinction is the
#: point of this layer, so it is a field on every paragraph, not an inference.
ORIGIN_SEMANTIC = "semantic"
ORIGIN_REFERENCE = "reference"

#: How many top hits seed the walk. The hits below these are usually other
#: paragraphs of the same revisions, so going deeper adds mostly duplicates.
DEFAULT_SEED_HITS = 3
#: One hop by default: the documents the hits themselves cite. Deeper walks are
#: for a revision-history question, which asks for them explicitly.
DEFAULT_EXPAND_DEPTH = 1
DEFAULT_MAX_DOCUMENTS = 6
DEFAULT_MAX_PER_DOCUMENT = 4
DEFAULT_MAX_ADDED = 12

#: The contract code the answer layer raises from ``missing``. Named here so
#: the hand-off is explicit and cannot drift to an invented spelling.
REFUSAL_CODE = "EXTERNAL_SOURCE_REQUIRED"
validate_enum("refusal_code", REFUSAL_CODE)

#: Which paragraphs of a referenced document matter most when the cap bites.
#: Decided by the ingest's structured ``role``, not by scanning text: these
#: three are the ones that impose an obligation or decide applicability.
ROLE_PRIORITY = ("APPLICABILITY", "COMPLIANCE", "REQUIRED_ACTIONS")
for _role in ROLE_PRIORITY:
    validate_enum("paragraph_role", _role)
_ROLE_RANK = {role: rank for rank, role in enumerate(ROLE_PRIORITY)}
#: Every other role sorts after all three, and then by document order.
_ROLE_FALLBACK = len(ROLE_PRIORITY)

CAP_DOCUMENTS = "max_documents"
CAP_PER_DOCUMENT = "max_per_document"
CAP_TOTAL = "max_added"


class ParagraphFields(Mapping[str, Mapping[str, Any]]):
    """Read-only view letting the traversal read role/text off corpus records.

    The retrieval corpus keeps paragraph text in its own row-ordered list rather
    than on the graph node, so the walk is handed this instead of copying the
    whole corpus into a dict on every query.
    """

    def __init__(self, corpus: Corpus) -> None:
        self._by_id = corpus.by_id

    def __getitem__(self, key: str) -> Mapping[str, Any]:
        record = self._by_id[key]
        return {"role": record.role, "text": record.text, "ordinal": record.ordinal}

    def __iter__(self) -> Iterator[str]:
        return iter(self._by_id)

    def __len__(self) -> int:
        return len(self._by_id)


@dataclass(frozen=True)
class EvidenceParagraph:
    """One paragraph in the evidence set, and how it got there."""

    paragraph_id: str
    revision_id: str
    ad_number: str | None
    label: str
    role: str
    heading: str
    text: str
    char_start: int
    char_end: int
    origin: str
    #: Fused retrieval score; None for a reference-derived paragraph, which was
    #: never ranked and must not be compared against one that was.
    score: float | None = None
    #: For a reference-derived paragraph: which retrieved document cited it,
    #: by which edge kind, and how many hops away.
    referenced_by: str | None = None
    kind: str | None = None
    depth: int = 0

    @property
    def citation_id(self) -> str:
        return f"{self.paragraph_id}@{self.char_start}-{self.char_end}"

    def as_payload(self) -> dict[str, Any]:
        """Everything but the body text, which the caller already holds in the
        paragraph it cites; matches ``Hit.as_payload``."""
        fields = {k: v for k, v in payload_of(self).items() if k != "text"}
        return {**fields, "citation_id": self.citation_id}

    @classmethod
    def from_hit(cls, hit: Hit) -> EvidenceParagraph:
        return cls(
            paragraph_id=hit.paragraph_id,
            revision_id=hit.revision_id,
            ad_number=hit.ad_number,
            label=hit.label,
            role=hit.role,
            heading=hit.heading,
            text=hit.text,
            char_start=hit.char_start,
            char_end=hit.char_end,
            origin=ORIGIN_SEMANTIC,
            score=hit.score,
        )

    @classmethod
    def from_reference(
        cls, record: Paragraph, *, referenced_by: str, kind: str, depth: int
    ) -> EvidenceParagraph:
        return cls(
            paragraph_id=record.paragraph_id,
            revision_id=record.revision_id,
            ad_number=record.ad_number,
            label=record.label,
            role=record.role,
            heading=record.heading,
            text=record.text,
            char_start=record.char_start,
            char_end=record.char_end,
            origin=ORIGIN_REFERENCE,
            score=None,
            referenced_by=referenced_by,
            kind=kind,
            depth=depth,
        )


@dataclass(frozen=True)
class ExpansionResult:
    """The evidence set after reference expansion, with its own audit trail."""

    retrieved: tuple[EvidenceParagraph, ...]
    added: tuple[EvidenceParagraph, ...]
    missing: tuple[MissingDocument, ...]
    outcome: str
    traversals: tuple[TraversalResult, ...]
    seeds: tuple[str, ...]
    documents: tuple[str, ...]
    capped: bool
    #: Counted separately: documents never opened, and paragraphs left behind in
    #: the documents that were. One number mixing the two would be unreadable.
    dropped_documents: int
    dropped_paragraphs: int
    cap_reasons: tuple[str, ...]

    @property
    def paragraphs(self) -> tuple[EvidenceParagraph, ...]:
        """Retrieved paragraphs first, then the reference-derived ones."""
        return (*self.retrieved, *self.added)

    def paragraph_ids(self) -> set[str]:
        return {p.paragraph_id for p in self.paragraphs}

    def reference_paragraph_ids(self) -> set[str]:
        return {p.paragraph_id for p in self.added}

    @property
    def requires_external_source(self) -> bool:
        return bool(self.missing)

    def external_documents(self) -> tuple[dict[str, Any], ...]:
        """One entry per document we must load, ready for a
        :data:`REFUSAL_CODE` refusal: the document named, and the retrieved
        paragraphs that show why it is needed.

        The evidence is the delegating revision's own retrieved paragraphs when
        the reference came from an edge, because a contract ``ADOPTS_MCAI`` or
        ``REFERENCES_SB`` edge does not record which paragraph delegated (see
        docs/contract_change_requests.md); a prose reference names its paragraph
        exactly, and that one is used.
        """
        out: list[dict[str, Any]] = []
        for document in self.missing:
            evidence = list(document.paragraph_ids) or [
                p.paragraph_id
                for p in self.paragraphs
                if p.revision_id == document.referenced_by
            ]
            out.append(
                {
                    "code": REFUSAL_CODE,
                    "identifier": document.identifier,
                    "label": document.label,
                    "kind": document.kind,
                    "reason": document.reason,
                    "referenced_by": document.referenced_by,
                    "evidence_paragraph_ids": sorted(dict.fromkeys(evidence)),
                }
            )
        return tuple(out)

    def as_payload(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "seeds": list(self.seeds),
            "documents": list(self.documents),
            "retrieved": len(self.retrieved),
            "added": [p.as_payload() for p in self.added],
            "missing": [payload_of(m) for m in self.missing],
            "external_source_required": self.external_documents(),
            "capped": self.capped,
            "dropped_documents": self.dropped_documents,
            "dropped_paragraphs": self.dropped_paragraphs,
            "cap_reasons": list(self.cap_reasons),
            "traversals": [t.as_payload() for t in self.traversals],
        }


def _by_revision(corpus: Corpus) -> dict[str, list[Paragraph]]:
    """Corpus paragraphs grouped by revision, keeping the corpus row order."""
    grouped: dict[str, list[Paragraph]] = {}
    for record in corpus.paragraphs:
        grouped.setdefault(record.revision_id, []).append(record)
    return grouped


def _ordered(records: list[Paragraph]) -> list[Paragraph]:
    """Obligation-bearing roles first, then document order. Deterministic."""
    return sorted(
        records,
        key=lambda r: (_ROLE_RANK.get(r.role, _ROLE_FALLBACK), r.ordinal, r.paragraph_id),
    )


def expand(
    result: SearchResult,
    corpus: Corpus,
    *,
    seed_hits: int = DEFAULT_SEED_HITS,
    max_depth: int = DEFAULT_EXPAND_DEPTH,
    max_documents: int = DEFAULT_MAX_DOCUMENTS,
    max_per_document: int = DEFAULT_MAX_PER_DOCUMENT,
    max_added: int = DEFAULT_MAX_ADDED,
) -> ExpansionResult:
    """Follow the top hits' references and add what they point at.

    Raises ``ValueError`` on a limit below one, or on a hit whose revision this
    corpus does not hold -- that means the result came from a different build,
    which would silently expand against the wrong graph.
    """
    for name, value in (
        ("seed_hits", seed_hits),
        ("max_documents", max_documents),
        ("max_per_document", max_per_document),
        ("max_added", max_added),
    ):
        if value < 1:
            raise ValueError(f"{name} must be >= 1, got {value}")
    if max_depth < 0:
        raise ValueError(f"max_depth must be >= 0, got {max_depth}")

    retrieved = tuple(EvidenceParagraph.from_hit(h) for h in result.hits)
    seeds: list[str] = []
    for hit in result.hits[:seed_hits]:
        if hit.revision_id not in corpus.graph:
            raise ValueError(
                f"hit {hit.paragraph_id!r} names revision {hit.revision_id!r}, which is "
                f"not in corpus {corpus.kind}/{corpus.fingerprint}; the search result and "
                f"the corpus are from different builds"
            )
        if hit.revision_id not in seeds:
            seeds.append(hit.revision_id)

    view = ParagraphFields(corpus)
    traversals = tuple(
        traverse(corpus.graph, seed, max_depth=max_depth, paragraphs=view) for seed in seeds
    )

    # Which documents to read, shallowest first, seeds and duplicates removed.
    wanted: dict[str, tuple[str, int]] = {}
    for walk in traversals:
        for node in walk.reached:
            if node.depth == 0 or node.ntype != "Revision" or node.node_id in seeds:
                continue
            wanted.setdefault(node.node_id, (node.kind, node.depth))
    documents = sorted(wanted, key=lambda node_id: (wanted[node_id][1], node_id))

    cap_reasons: list[str] = []
    dropped_documents = 0
    dropped_paragraphs = 0
    if len(documents) > max_documents:
        dropped_documents = len(documents) - max_documents
        cap_reasons.append(CAP_DOCUMENTS)
        documents = documents[:max_documents]

    grouped = _by_revision(corpus)
    already = result.paragraph_ids()
    added: list[EvidenceParagraph] = []
    for node_id in documents:
        kind, depth = wanted[node_id]
        candidates = [p for p in _ordered(grouped.get(node_id, [])) if p.paragraph_id not in already]
        keep = candidates[:max_per_document]
        if len(candidates) > len(keep):
            dropped_paragraphs += len(candidates) - len(keep)
            if CAP_PER_DOCUMENT not in cap_reasons:
                cap_reasons.append(CAP_PER_DOCUMENT)
        for record in keep:
            if len(added) >= max_added:
                dropped_paragraphs += 1
                if CAP_TOTAL not in cap_reasons:
                    cap_reasons.append(CAP_TOTAL)
                continue
            already.add(record.paragraph_id)
            added.append(
                EvidenceParagraph.from_reference(
                    record, referenced_by=node_id, kind=kind, depth=depth
                )
            )

    missing: dict[str, MissingDocument] = {}
    for walk in traversals:
        for document in walk.missing:
            missing.setdefault(document.identifier, document)
    outcomes = {walk.outcome for walk in traversals}

    return ExpansionResult(
        retrieved=retrieved,
        added=tuple(added),
        missing=tuple(sorted(missing.values(), key=lambda m: m.identifier)),
        # No hits means no walk: COMPLETE, with no traversal and nothing missing.
        outcome=next((o for o in OUTCOME_PRECEDENCE if o in outcomes), COMPLETE),
        traversals=traversals,
        seeds=tuple(seeds),
        documents=tuple(documents),
        capped=bool(cap_reasons),
        dropped_documents=dropped_documents,
        dropped_paragraphs=dropped_paragraphs,
        cap_reasons=tuple(cap_reasons),
    )
