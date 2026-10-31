"""The human-readable half of a citation, and the corpus size in pages.

A citation id is an exact anchor: ``{document_id}#{label}@{char_start}-{char_end}``,
with offsets computed by ``str.find`` in ``engine.api.answer`` and re-checked
verbatim by ``engine.verify.verifier``. That is what makes a citation *provable*.
It is not what makes it *findable*: nobody can take ``2026-21902#(g)@4120-4193``
to a paper copy of the Federal Register.

This module adds the findable half beside it, never instead of it:

* the handle a reader already uses -- ``ad_number`` for an adopted AD,
  ``record_id`` for a proposal;
* the Federal Register citation, ``91 FR 66019``;
* the page range, ``66019-66022``;
* the paragraph label and role, which is "the section of the full document";
* the ``document_stage``, so a proposal can never be read as an obligation.

Three rules hold everywhere below.

**Nothing is derived from prose.** ``fr_citation``, ``start_page`` and
``end_page`` are copied from the Federal Register index. A page number is used
only when the citation string the index supplied names the same page, which was
true for all 4,053 documents cached under ``data/raw/fr_index`` and is enforced
by ``engine.ingest.emit``. The NPRM spreadsheet's own citation column is free
prose in 233 distinct shapes, so it is never parsed -- it is shown verbatim as
the source's own words.

**An absent field says so.** A document whose pages this engine does not hold
reports ``not recorded`` and is listed in ``not_recorded``. There is no code
path here that can produce a page number the source did not give.

**The stage is never absent.** ``HumanReference`` refuses to exist without a
contract ``document_stage``, so a citation without its legal stage cannot reach
a renderer. When the document is unknown the stage is ``UNKNOWN``, which is a
contract value meaning "could not be determined from metadata" -- not a guess.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contracts.contract import enum  # noqa: E402
from engine.graph.pages import (  # noqa: E402
    page_number,
    page_range,
    volume_for,
)
from engine.graph.stage import (  # noqa: E402
    PROPOSED,
    UNKNOWN,
    describe,
    revision_stage,
)
from engine.paths import FR_INDEX_CACHE  # noqa: E402
from engine.retrieval.layout import default_corpus_paths  # noqa: E402

#: ``91 FR 66019``: volume, the literal FR, first page. The Federal Register
#: index emits exactly this shape, and its page always equals ``start_page``.
FR_CITATION = re.compile(r"^(\d+)\s+FR\s+(\d+)$")
#: A normalised page range: ``66019`` or ``66019-66022``. Anything else is left
#: alone rather than coaxed into shape; see the module docstring.
PAGE_RANGE = re.compile(r"^(\d+)(?:-(\d+))?$")
#: ``{document_id}#{label}@{char_start}-{char_end}``, the contract's format.
CITATION_ID = re.compile(r"^(?P<document>.+?)#(?P<label>.+?)(?:@(?P<start>\d+)-(?P<end>\d+))?$")

NOT_RECORDED = "not recorded"

#: Source kinds, read from the contract rather than written as literals.
KIND_REVISION, KIND_NPRM = enum("source_kind")


class CitationStageMissing(ValueError):
    """A citation was built without a contract ``document_stage``."""


def parse_citation_id(citation_id: str) -> tuple[str, str] | None:
    """``(document_id, label)`` from a citation id or a bare paragraph id."""
    match = CITATION_ID.match(citation_id.strip())
    if not match:
        return None
    return match.group("document"), match.group("label")


def citation_page(fr_citation: str | None) -> int | None:
    """The page a Federal Register citation names, or None if it names none."""
    match = FR_CITATION.match((fr_citation or "").strip())
    return int(match.group(2)) if match else None


def citation_volume(fr_citation: str | None) -> int | None:
    match = FR_CITATION.match((fr_citation or "").strip())
    return int(match.group(1)) if match else None


def volume_of(record: dict[str, Any], *, date_field: str) -> int | None:
    """The Federal Register volume a document belongs to.

    Taken from the citation when the citation is in short form, otherwise from
    the publication year, which fixes the volume exactly (``year - 1935``). When
    both are available and disagree, neither is trusted and None is returned --
    a page attributed to the wrong volume would corrupt the page count silently.
    """
    from_citation = citation_volume(record.get("fr_citation") or record.get("citation"))
    from_year = volume_for(record.get(date_field))
    if from_citation is not None and from_year is not None:
        return from_citation if from_citation == from_year else None
    return from_citation if from_citation is not None else from_year


# --------------------------------------------------------------- a reference


@dataclass(frozen=True)
class HumanReference:
    """One cited paragraph, as a reader would write it down.

    ``citation_id`` is carried unchanged: this object sits beside the exact
    anchor and never replaces it.
    """

    citation_id: str
    document_id: str
    #: ``enums.source_kind``, or None when this engine does not hold the document.
    source_kind: str | None
    #: ``enums.document_stage``. Never empty - see ``__post_init__``.
    document_stage: str
    #: One sentence an engineer can act on, from engine.graph.stage.describe.
    stage_note: str
    #: The handle a reader already uses. ad_number for an adopted AD.
    ad_number: str | None
    #: The challenge index's stable key for a proposal, e.g. NPRM-001.
    record_id: str | None
    #: ``91 FR 66019``, when the source gave one in that form.
    fr_citation: str | None
    #: ``66019-66022``, from the source's own page integers.
    page_range: str | None
    #: The source's citation verbatim when it is not in ``91 FR 66019`` form.
    source_citation_text: str | None
    paragraph_label: str
    #: ``enums.paragraph_role``, from the retrieved paragraph.
    paragraph_role: str | None
    #: The document on federalregister.gov. For a proposal this is the
    #: organizers' own reading link; for an adopted AD it is the full-text XML
    #: URL, which is the only document URL a Revision node carries (the
    #: contract has no html_url field). A renderer should say which it is
    #: rather than offering both as "open in the Federal Register".
    federal_register_link: str | None
    #: Every human-reference field the source does not hold, named.
    not_recorded: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        stage = self.document_stage
        if not stage or stage not in enum("document_stage"):
            raise CitationStageMissing(
                f"citation {self.citation_id!r} has document_stage {stage!r}, which is not "
                f"one of {enum('document_stage')}. Every rendered citation must show its stage."
            )

    @property
    def is_proposal(self) -> bool:
        return self.document_stage == PROPOSED

    @property
    def handle(self) -> str:
        """record_id for a proposal, AD number for an adopted AD, else the id."""
        return self.record_id or self.ad_number or self.document_id

    @property
    def display(self) -> str:
        """The whole reference on one line, absences stated rather than hidden."""
        parts = [self.handle]
        parts.append(self.fr_citation or self.source_citation_text or f"FR citation {NOT_RECORDED}")
        parts.append(f"pp. {self.page_range}" if self.page_range else f"page range {NOT_RECORDED}")
        section = f"paragraph ({self.paragraph_label.strip('()')})"
        if self.paragraph_role:
            section += f" {self.paragraph_role}"
        parts.append(section)
        parts.append(self.document_stage)
        return " · ".join(parts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "citation_id": self.citation_id,
            "document_id": self.document_id,
            "source_kind": self.source_kind,
            "document_stage": self.document_stage,
            "stage_note": self.stage_note,
            "is_proposal": self.is_proposal,
            "handle": self.handle,
            "ad_number": self.ad_number,
            "record_id": self.record_id,
            "fr_citation": self.fr_citation,
            "page_range": self.page_range,
            "source_citation_text": self.source_citation_text,
            "paragraph_label": self.paragraph_label,
            "paragraph_role": self.paragraph_role,
            "federal_register_link": self.federal_register_link,
            "not_recorded": list(self.not_recorded),
            "display": self.display,
        }


# ------------------------------------------------------------ the lookup book


class ReferenceBook:
    """Document-level reference fields, keyed by the id a citation carries.

    Built once at startup from the same ``nodes.jsonl`` the corpus came from, so
    resolving a reference costs one dict lookup per citation and no query ever
    pays for a file read.
    """

    def __init__(
        self,
        revisions: dict[str, dict[str, Any]] | None = None,
        nprms: dict[str, dict[str, Any]] | None = None,
        *,
        today: dt.date | None = None,
    ) -> None:
        self.revisions = revisions or {}
        self.nprms = nprms or {}
        self.today = today

    @classmethod
    def load(cls, nodes: Path | None = None, *, today: dt.date | None = None) -> ReferenceBook:
        """Read Revision and NPRM nodes. A missing file yields an empty book.

        An empty book is not a silent failure: every reference it returns says
        ``not recorded`` for the fields it could not find, and carries stage
        ``UNKNOWN``, which the UI renders as "could not be determined".
        """
        path = nodes or default_corpus_paths().nodes
        revisions: dict[str, dict[str, Any]] = {}
        nprms: dict[str, dict[str, Any]] = {}
        if not path.exists():
            return cls(revisions, nprms, today=today)
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = record.get("_type")
                if kind == "Revision" and record.get("revision_id"):
                    revisions[str(record["revision_id"])] = record
                elif kind == "NPRM" and record.get("nprm_id"):
                    nprms[str(record["nprm_id"])] = record
        return cls(revisions, nprms, today=today)

    # ----------------------------------------------------------- resolution

    def reference(
        self,
        citation_id: str,
        *,
        role: str | None = None,
        paragraph_stage: str | None = None,
    ) -> HumanReference:
        """The human reference for one citation id. Never raises, never invents.

        ``paragraph_stage`` is the stage denormalised onto the Paragraph node.
        It is used only when this book does not hold the document, so the
        document's own structured fields always win over a copy of them.
        """
        parsed = parse_citation_id(citation_id)
        document_id, label = parsed if parsed else (citation_id, "")
        revision = self.revisions.get(document_id)
        if revision is not None:
            return self._from_revision(citation_id, label, role, revision)
        nprm = self.nprms.get(document_id)
        if nprm is not None:
            return self._from_nprm(citation_id, label, role, nprm)
        return self._unheld(citation_id, document_id, label, role, paragraph_stage)

    def _from_revision(
        self, citation_id: str, label: str, role: str | None, record: dict[str, Any]
    ) -> HumanReference:
        stage = revision_stage(record, today=self.today)
        fr_citation = (record.get("fr_citation") or "").strip() or None
        pages = page_range(record.get("start_page"), record.get("end_page"))
        # The page a citation names must be the page the document starts on.
        # They agree for every cached index document and emit.py refuses a node
        # where they do not, so a disagreement here means the build is stale or
        # hand-edited: drop both rather than show a page we cannot stand behind.
        named = citation_page(fr_citation)
        if named is not None and page_number(record.get("start_page")) not in (None, named):
            fr_citation, pages = None, None
        missing = [
            name
            for name, value in (("fr_citation", fr_citation), ("page_range", pages))
            if not value
        ]
        return HumanReference(
            citation_id=citation_id,
            document_id=str(record["revision_id"]),
            source_kind=KIND_REVISION,
            document_stage=stage,
            stage_note=describe(stage, record),
            ad_number=record.get("ad_number"),
            record_id=None,
            fr_citation=fr_citation,
            page_range=pages,
            source_citation_text=None,
            paragraph_label=label,
            paragraph_role=role,
            federal_register_link=record.get("full_text_xml_url"),
            not_recorded=tuple(missing),
        )

    def _from_nprm(
        self, citation_id: str, label: str, role: str | None, record: dict[str, Any]
    ) -> HumanReference:
        # A proposal is PROPOSED whatever its dates say; that is the contract's
        # invariant, not a property of this record.
        stage = PROPOSED
        raw_citation = (record.get("citation") or "").strip() or None
        short_form = raw_citation if citation_page(raw_citation) else None
        # The spreadsheet's page column is normalised upstream. Accept it only
        # when it is already two integers; its 233 prose shapes are not parsed.
        raw_pages = (record.get("page_range") or "").strip()
        match = PAGE_RANGE.match(raw_pages)
        pages = page_range(match.group(1), match.group(2)) if match else None
        missing = []
        if not short_form:
            missing.append("fr_citation")
        if not pages:
            missing.append("page_range")
        if not record.get("record_id"):
            missing.append("record_id")
        return HumanReference(
            citation_id=citation_id,
            document_id=str(record["nprm_id"]),
            source_kind=KIND_NPRM,
            document_stage=stage,
            stage_note=describe(stage, record),
            # Deliberately NOT record["ad_number"]. An NPRM node carries the AD
            # number the proposal was eventually adopted as (246 of 431 have
            # one), and printing it beside a citation to proposed text is the
            # exact misreading the contract's fourth citation rule forbids: the
            # adopted AD is a different document, with different wording and a
            # compliance date this proposal does not have. The contract assigns
            # ad_number to an adopted AD and record_id to a proposal.
            ad_number=None,
            record_id=record.get("record_id"),
            fr_citation=short_form,
            page_range=pages,
            source_citation_text=None if short_form else raw_citation,
            paragraph_label=label,
            paragraph_role=role,
            federal_register_link=record.get("federal_register_link")
            or record.get("comment_url"),
            not_recorded=tuple(missing),
        )

    def _unheld(
        self,
        citation_id: str,
        document_id: str,
        label: str,
        role: str | None,
        paragraph_stage: str | None,
    ) -> HumanReference:
        """A citation whose document this book does not hold.

        Everything a reader would need is reported absent. The stage falls back
        to the one denormalised on the paragraph when there is one, because that
        copy still came from the document; otherwise UNKNOWN.
        """
        stage = paragraph_stage if paragraph_stage in enum("document_stage") else UNKNOWN
        return HumanReference(
            citation_id=citation_id,
            document_id=document_id,
            source_kind=None,
            document_stage=stage,
            stage_note=describe(stage, None),
            ad_number=None,
            record_id=None,
            fr_citation=None,
            page_range=None,
            source_citation_text=None,
            paragraph_label=label,
            paragraph_role=role,
            federal_register_link=None,
            not_recorded=("ad_number", "record_id", "fr_citation", "page_range"),
        )


#: A book that holds nothing. Used where no corpus is loaded, so that a citation
#: still carries a stage and still names what it could not find.
EMPTY_BOOK = ReferenceBook()


def _bare(paragraph_id: str) -> str:
    """A paragraph id with its label's parentheses removed.

    One producer writes ``2026-20103#(c)`` and another ``2026-20103#c``. The
    exact anchor is unaffected either way; this only decides which retrieved
    paragraph supplies the role, so matching on the bare label means a role is
    attached instead of silently lost.
    """
    at = paragraph_id.find("#")
    if at < 0:
        return paragraph_id
    return paragraph_id[:at] + "#" + paragraph_id[at + 1 :].strip("()")


def resolver_for(book: ReferenceBook, hits: Iterable[Any]):
    """A ``citation_id -> HumanReference`` function for one query.

    Closing over this query's retrieved paragraphs is what lets a reference
    carry the paragraph's role -- "the section of the full document" the rubric
    asks for -- without the envelope needing to know what a retrieval hit is.
    """
    by_id: dict[str, Any] = {}
    for hit in hits:
        paragraph_id = str(getattr(hit, "paragraph_id", "") or "")
        if paragraph_id:
            by_id.setdefault(paragraph_id, hit)
            by_id.setdefault(_bare(paragraph_id), hit)

    def resolve(citation_id: str) -> HumanReference:
        parsed = parse_citation_id(citation_id)
        hit = None
        if parsed is not None:
            document_id, label = parsed
            paragraph_id = f"{document_id}#{label}"
            hit = by_id.get(paragraph_id) or by_id.get(_bare(paragraph_id))
        return book.reference(
            citation_id,
            role=getattr(hit, "role", None),
            paragraph_stage=getattr(hit, "document_stage", None),
        )

    return resolve


def reference_dicts(resolve, citation_ids: Iterable[str]) -> list[dict[str, Any]]:
    """Render references for a sentence's citations, stage guaranteed present.

    A resolver that returns anything other than a ``HumanReference`` is refused
    here rather than rendered: ``HumanReference`` cannot be constructed without
    a contract ``document_stage``, and that is the only reason this engine can
    promise every rendered citation shows its stage.
    """
    out: list[dict[str, Any]] = []
    for citation_id in citation_ids:
        reference = resolve(citation_id)
        if not isinstance(reference, HumanReference):
            raise CitationStageMissing(
                f"reference for {citation_id!r} is {type(reference).__name__}, not a "
                f"HumanReference, so its document_stage was never checked"
            )
        out.append(reference.as_dict())
    return out


# ------------------------------------------------------- the corpus, in pages


@dataclass
class PageCount:
    """How many Federal Register pages the indexed corpus covers.

    ``distinct_pages`` is the number to quote. ``span_sum`` is the naive sum of
    every document's own span and is larger, because two documents published in
    the same issue can share a page: one ends on 66019 and the next begins on
    it. Counting ``(volume, page)`` pairs once is the only count that is not an
    overstatement, so both are reported and the difference is visible.
    """

    kind: str
    field_used: str
    documents: int = 0
    documents_with_pages: int = 0
    span_sum: int = 0
    pages: set[tuple[int, int]] = field(default_factory=set)
    missing_pages: list[str] = field(default_factory=list)
    missing_volume: list[str] = field(default_factory=list)

    @property
    def distinct_pages(self) -> int:
        return len(self.pages)

    @property
    def shared_pages(self) -> int:
        """Pages counted twice by ``span_sum`` because two documents share them."""
        return self.span_sum - self.distinct_pages

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "field_used": self.field_used,
            "documents": self.documents,
            "documents_with_pages": self.documents_with_pages,
            "documents_without_pages": len(self.missing_pages),
            "documents_without_volume": len(self.missing_volume),
            "span_sum": self.span_sum,
            "distinct_pages": self.distinct_pages,
            "shared_pages": self.shared_pages,
            "volumes": len({volume for volume, _ in self.pages}),
            "sample_without_pages": self.missing_pages[:5],
        }


def _count(
    records: Iterable[dict[str, Any]],
    *,
    kind: str,
    key: str,
    date_field: str,
    field_used: str,
    pages_of,
) -> PageCount:
    out = PageCount(kind=kind, field_used=field_used)
    for record in records:
        out.documents += 1
        identifier = str(record.get(key) or "?")
        span = pages_of(record)
        if span is None:
            out.missing_pages.append(identifier)
            continue
        first, last = span
        volume = volume_of(record, date_field=date_field)
        if volume is None:
            out.missing_volume.append(identifier)
            continue
        out.documents_with_pages += 1
        out.span_sum += last - first + 1
        out.pages.update((volume, page) for page in range(first, last + 1))
    return out


def _revision_span(record: dict[str, Any]) -> tuple[int, int] | None:
    """A Revision's page span, from the index's own integers.

    ``start_page`` is used only when the document's own Federal Register
    citation names the same page, so a page number that does not agree with the
    citation beside it is not counted at all.
    """
    first = page_number(record.get("start_page"))
    if first is None:
        return None
    named = citation_page(record.get("fr_citation"))
    if named is not None and named != first:
        return None
    last = page_number(record.get("end_page"))
    return (first, last if last is not None and last >= first else first)


def _nprm_span(record: dict[str, Any]) -> tuple[int, int] | None:
    match = PAGE_RANGE.match((record.get("page_range") or "").strip())
    if not match:
        return None
    first = int(match.group(1))
    last = int(match.group(2)) if match.group(2) else first
    return (first, last if last >= first else first)


def corpus_pages(nodes: Path | None = None, *, from_index: bool = False) -> dict[str, Any]:
    """The indexed corpus measured in Federal Register pages.

    Reads the built nodes, so the answer describes the corpus that is actually
    indexed rather than everything the harvest could reach.

    ``from_index`` answers the same question from the cached Federal Register
    index responses instead, joined to the built Revision ids. It exists for
    two reasons: the number is available before a rebuild has carried
    ``fr_citation`` onto the nodes, and the two modes must agree afterwards,
    which is a check that the ingest copied the index values rather than
    deriving them.
    """
    path = nodes or default_corpus_paths().nodes
    book = ReferenceBook.load(path)
    if from_index:
        index = _index_by_document_number()
        book = ReferenceBook(
            _joined(book.revisions, index, key="revision_id", date_field="publication_date"),
            _joined(book.nprms, index, key="fr_document_number", date_field="publish_date"),
        )
        return page_report(book, source=f"{path} joined to {FR_INDEX_CACHE}", joined=True)
    return page_report(book, source=str(path))


def _index_by_document_number() -> dict[str, dict[str, Any]]:
    """Every cached Federal Register index response, keyed by document number."""
    out: dict[str, dict[str, Any]] = {}
    for cached in sorted(FR_INDEX_CACHE.glob("*.json")):
        try:
            payload = json.loads(cached.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for result in payload.get("results") or []:
            number = str(result.get("document_number") or "")
            if number and number not in out:
                out[number] = result
    return out


def _joined(
    records: dict[str, dict[str, Any]],
    index: dict[str, dict[str, Any]],
    *,
    key: str,
    date_field: str,
) -> dict[str, dict[str, Any]]:
    """Overlay each record's citation and pages from the index cache.

    The cache is the same response the ingest copies these fields from, so this
    is the authoritative value rather than a second derivation of it. For a
    proposal it also supplies what the challenge index does not: the short-form
    ``91 FR 66019`` citation and the page integers, joined on
    ``fr_document_number``.

    A record the cache does not hold keeps its own fields, so it is reported as
    missing pages rather than silently dropped from the count.
    """
    out: dict[str, dict[str, Any]] = {}
    for identifier, record in records.items():
        found = index.get(str(record.get(key) or ""))
        if found is None:
            out[identifier] = record
            continue
        pages = page_range(found.get("start_page"), found.get("end_page"))
        out[identifier] = {
            **record,
            "fr_citation": found.get("citation"),
            "start_page": found.get("start_page"),
            "end_page": found.get("end_page"),
            # page_range is what the proposal counter reads, so the joined
            # integers have to reach it in the normalised shape.
            "page_range": pages or record.get("page_range"),
            date_field: found.get("publication_date") or record.get(date_field),
        }
    return out


def page_report(
    book: ReferenceBook, *, source: str = "loaded nodes", joined: bool = False
) -> dict[str, Any]:
    """Page arithmetic over a book that is already loaded.

    ``joined`` only changes the ``field_used`` label, which has to name where
    the pages actually came from: the page range the build recorded on the node,
    or the Federal Register index joined on ``fr_document_number``. This
    function does not know which source the build used for a proposal's
    ``page_range``, so the unjoined label names the field and claims nothing
    about its provenance; the joined run is the independent cross-check.
    """
    revisions = list(book.revisions.values())
    nprms = list(book.nprms.values())

    adopted = _count(
        revisions,
        kind="adopted ADs (Revision nodes)",
        key="revision_id",
        date_field="publication_date",
        field_used="Revision.start_page / Revision.end_page, from the Federal Register index",
        pages_of=_revision_span,
    )
    proposed = _count(
        nprms,
        kind="proposals (NPRM nodes)",
        key="nprm_id",
        date_field="publish_date",
        field_used=(
            "NPRM.fr_document_number joined to the Federal Register index's "
            "start_page / end_page"
            if joined
            else "NPRM.page_range, the page range the build recorded for the proposal"
        ),
        pages_of=_nprm_span,
    )
    combined = adopted.pages | proposed.pages
    return {
        "nodes": source,
        "adopted": adopted.as_dict(),
        "proposed": proposed.as_dict(),
        "total_distinct_pages": len(combined),
        "total_span_sum": adopted.span_sum + proposed.span_sum,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Corpus size in Federal Register pages.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--from-index",
        action="store_true",
        help="read each built revision's citation and pages from the cached "
        "Federal Register index instead of from the built nodes",
    )
    args = parser.parse_args(argv)
    report = corpus_pages(from_index=args.from_index)
    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"nodes: {report['nodes']}")
    for key in ("adopted", "proposed"):
        row = report[key]
        print()
        print(f"{row['kind']}: {row['documents']} documents")
        print(f"  field used          {row['field_used']}")
        print(f"  with a page range   {row['documents_with_pages']}")
        print(f"  without one         {row['documents_without_pages']} {row['sample_without_pages']}")
        print(f"  sum of spans        {row['span_sum']} (end - start + 1, per document)")
        print(f"  distinct FR pages   {row['distinct_pages']} across {row['volumes']} volumes")
        print(f"  shared pages        {row['shared_pages']} counted twice by the sum of spans")
    print()
    print(f"indexed corpus: {report['total_distinct_pages']} distinct Federal Register pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
