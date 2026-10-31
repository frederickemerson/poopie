"""Resolve each proposal to a Federal Register document, fetch it, parse it.

An NPRM is an ordinary Federal Register document. It has a document number, a
``full_text_xml_url`` and -- the finding that made this cheap -- the *same*
``<HD SOURCE="HD1">(c) Applicability</HD>`` markup as an adopted AD. So
:func:`engine.ingest.ad_xml.parse_ad_xml` parses a proposal with no changes and
no prose regex: the section boundaries come from the document's own markup,
exactly as they do for a final rule. The only structural difference measured
across the corpus is the first section, ``(a) Comments Due Date`` where a final
rule has ``(a) Effective Date``; ``engine.ingest.roles`` classifies it OTHER,
which is its honest answer for a heading it has no enum value for.

Resolving the document number
-----------------------------

The index's ``federal_register_link`` column cannot be trusted on its own: 169
of its 431 cells hold pasted prose instead of a URL and 15 hold two URLs (the
notice and its later withdrawal). So a document number is only accepted once
the Federal Register's own index confirms it, and three resolution paths are
tried in order, each using a structured field and none reading prose:

``link``
    A number parsed from the link cell's URL path which the index confirms is
    an FAA proposed rule printed on the row's Federal Register start page. When
    a cell holds two numbers this is what picks the notice over the withdrawal.
``citation``
    No usable link: match on ``start_page`` within the date window below. The
    start page *is* the Federal Register citation, so it identifies the notice.
``docket_date``
    No page match: match on the row's normalized docket inside the same window.

A row that none of the three resolves is reported unresolved and nothing is
invented for it.

Why the date is a window and not an equality test
-------------------------------------------------

``publish_date`` in the index does not always equal the Federal Register's
``publication_date``: on most rows it is one day earlier, and the sheet's own
``citation`` column names the later date ("(Pages 54135-54136)" of
"Volume 86, Number 187 (Thursday, September 30, 2021)" carries
``publish_date`` 2021-09-29). Treating it as the publication date resolved 174
of 431 rows and silently dropped the rest. The page number is the fact that
does hold: Federal Register pages run continuously through an annual volume, so
a start page plus a few days of slack names one notice. ``DATE_WINDOW_DAYS``
is that slack, and :func:`date_offsets` reports the measured distribution of
the discrepancy rather than assuming it is always one day.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from engine import paths
from engine.graph import pages as fr_pages
from engine.ingest import provenance
from engine.ingest.ad_xml import ParsedAD, parse_ad_xml
from engine.ingest.docket_ids import parse_docket_ids
from engine.ingest.fr_client import FederalRegisterClient
from engine.ingest.nprm_index_xlsx import IndexLoad, IndexRow, publish_year_range

#: Resolution paths, most authoritative first. Recorded per document so the
#: report says how each of the 431 was identified rather than just how many.
VIA_LINK = "link"
VIA_CITATION = "citation"
VIA_DOCKET_DATE = "docket_date"
VIA_NONE = "unresolved"

#: The ``type`` string the Federal Register index uses for a proposal. Checked
#: rather than assumed: it is the field that tells a proposal from a final rule.
PROPOSED_RULE_TYPE = "Proposed Rule"

#: How far the index's ``publish_date`` may sit from the Federal Register's
#: ``publication_date`` before a candidate is rejected. See the module
#: docstring: the measured discrepancy is 0 or 1 day, and the window is kept
#: small so it cannot reach into a neighbouring notice.
DATE_WINDOW_DAYS = 7



@dataclass(frozen=True)
class IndexedDocument:
    """One Federal Register index record, keyed the ways we need to look it up."""

    document_number: str
    publication_date: str | None
    start_page: int | None
    end_page: int | None
    citation: str | None
    docket_id: str | None
    full_text_xml_url: str | None
    html_url: str | None
    comments_close_on: str | None
    type: str | None
    #: The Federal Register's own ACTION line, e.g. "Notice of proposed
    #: rulemaking (NPRM)." or "Proposed rule; withdrawal.". It is the
    #: authoritative statement of what the document does, and it is what
    #: explains a document that contains no proposed regulatory text.
    action: str | None = None

    @property
    def is_proposal(self) -> bool:
        return self.type == PROPOSED_RULE_TYPE


@dataclass
class ProposalIndex:
    """The FAA proposed-rule index for the years the spreadsheet covers."""

    by_number: dict[str, IndexedDocument] = field(default_factory=dict)
    by_page: dict[int, list[IndexedDocument]] = field(
        default_factory=lambda: defaultdict(list)
    )
    by_docket: dict[str, list[IndexedDocument]] = field(
        default_factory=lambda: defaultdict(list)
    )

    def add(self, record: dict) -> None:
        number = record.get("document_number")
        if not number:
            return
        docket = parse_docket_ids(record.get("docket_ids")).docket_id
        doc = IndexedDocument(
            document_number=str(number),
            publication_date=record.get("publication_date"),
            start_page=record.get("start_page"),
            end_page=record.get("end_page"),
            citation=record.get("citation"),
            docket_id=docket,
            full_text_xml_url=record.get("full_text_xml_url"),
            html_url=record.get("html_url"),
            comments_close_on=record.get("comments_close_on"),
            type=record.get("type"),
            action=(record.get("action") or "").strip() or None,
        )
        self.by_number[doc.document_number] = doc
        if doc.start_page is not None:
            self.by_page[int(doc.start_page)].append(doc)
        if doc.docket_id:
            self.by_docket[doc.docket_id].append(doc)

    def __len__(self) -> int:
        return len(self.by_number)


def build_proposal_index(
    client: FederalRegisterClient, rows: list[IndexRow]
) -> ProposalIndex:
    """One index request per publication year the spreadsheet touches.

    Measured 2001..2026 the busiest FAA proposal year is 446 documents, well
    under the API's 1000-row page cap, so no year needs splitting;
    ``proposed_rules_between`` raises rather than truncate if that ever changes.
    """
    span = publish_year_range(rows)
    index = ProposalIndex()
    if span is None:
        return index
    first, last = span
    for year in range(first, last + 1):
        for record in client.proposed_rules_between(f"{year}-01-01", f"{year}-12-31"):
            index.add(record)
    return index


# --------------------------------------------------------------- resolution


@dataclass(frozen=True)
class Resolution:
    row: IndexRow
    document: IndexedDocument | None
    via: str
    note: str | None = None

    @property
    def resolved(self) -> bool:
        return self.document is not None


def _as_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _within_window(doc: IndexedDocument, row: IndexRow) -> bool:
    published = _as_date(doc.publication_date)
    if published is None or row.publish_date is None:
        return False
    return abs((published - row.publish_date).days) <= DATE_WINDOW_DAYS


def _matches_row(doc: IndexedDocument, row: IndexRow) -> bool:
    """Does this index record describe the notice this row names?

    It must be a proposal, it must sit inside the date window, and its start
    page must be the row's start page. The page is the discriminating fact: it
    is what rules out an earlier notice or a withdrawal filed under the same
    docket.
    """
    if not doc.is_proposal or not _within_window(doc, row):
        return False
    if row.start_page is None or doc.start_page is None:
        return False
    return int(doc.start_page) == int(row.start_page)


def _agreement(doc: IndexedDocument, row: IndexRow) -> tuple[bool, bool]:
    """How well a page-matched candidate agrees with the row. Higher is better.

    Two notices can begin on the same Federal Register page -- 70 FR 14599
    carries both the GROB-WERKE proposal (14599-14601) and a McDonnell Douglas
    withdrawal (14599 alone) -- so the start page alone is not always decisive.
    The docket and the end page break the tie, both structured fields.
    """
    return (
        doc.docket_id in row.docket_ids,
        row.end_page is not None
        and doc.end_page is not None
        and int(doc.end_page) == int(row.end_page),
    )


def _best(candidates: list[IndexedDocument], row: IndexRow) -> IndexedDocument | None:
    matching = [doc for doc in candidates if _matches_row(doc, row)]
    if not matching:
        return None
    return max(matching, key=lambda doc: _agreement(doc, row))


def resolve_row(row: IndexRow, index: ProposalIndex) -> Resolution:
    linked = [
        doc
        for number in row.link_document_numbers
        if (doc := index.by_number.get(number)) is not None
    ]
    chosen = _best(linked, row)
    if chosen is not None:
        return Resolution(row, chosen, VIA_LINK)

    if row.start_page is not None:
        chosen = _best(index.by_page.get(int(row.start_page), []), row)
        if chosen is not None:
            return Resolution(row, chosen, VIA_CITATION)

    for docket in row.docket_ids:
        candidates = [
            doc
            for doc in index.by_docket.get(docket, [])
            if doc.is_proposal and _within_window(doc, row)
        ]
        if len(candidates) == 1:
            return Resolution(row, candidates[0], VIA_DOCKET_DATE)
        if len(candidates) > 1:
            return Resolution(
                row,
                None,
                VIA_NONE,
                f"{len(candidates)} proposals on docket {docket} fall inside "
                f"{DATE_WINDOW_DAYS} days of {row.publish_date}: "
                + ", ".join(sorted(d.document_number for d in candidates)),
            )

    if not row.federal_register_link:
        hint = "no federal_register_link"
    elif not row.link_document_numbers:
        hint = "link cell holds no Federal Register URL"
    else:
        hint = (
            "no FAA proposal starts on Federal Register page "
            f"{row.start_page} near {row.publish_date}"
        )
    return Resolution(row, None, VIA_NONE, hint)


def date_offsets(resolutions: list[Resolution]) -> dict[str, int]:
    """Measured ``publication_date - publish_date`` in days, per resolved row.

    Reported rather than assumed: this is the evidence for treating the index's
    ``publish_date`` as approximate. Keys are the offsets as strings.
    """
    counts: dict[str, int] = defaultdict(int)
    for resolution in resolutions:
        if not resolution.resolved:
            continue
        published = _as_date(resolution.document.publication_date)
        if published is None or resolution.row.publish_date is None:
            counts["unknown"] += 1
            continue
        counts[str((published - resolution.row.publish_date).days)] += 1
    return dict(sorted(counts.items(), key=lambda kv: kv[0]))


def resolve_all(rows: list[IndexRow], index: ProposalIndex) -> list[Resolution]:
    return [resolve_row(row, index) for row in rows]


# ------------------------------------------------------------ fetch + parse


@dataclass
class NPRMDocument:
    """One resolved, fetched and parsed proposal."""

    row: IndexRow
    document: IndexedDocument
    via: str
    parsed: ParsedAD | None = None
    provenance: provenance.Provenance | None = None
    note: str | None = None

    @property
    def nprm_id(self) -> str:
        return self.row.nprm_id

    @property
    def paragraph_count(self) -> int:
        return len(self.parsed.paragraphs) if self.parsed else 0


@dataclass
class TextHarvest:
    documents: list[NPRMDocument] = field(default_factory=list)
    unresolved: list[Resolution] = field(default_factory=list)
    xml_unavailable: list[str] = field(default_factory=list)
    parse_failures: list[str] = field(default_factory=list)
    #: Resolved documents that carry no proposed regulatory text, grouped by
    #: the Federal Register's own ACTION line. Not a failure list: most of
    #: these are withdrawals and comment-period extensions, which have no AD
    #: sections to find. The grouping is a plain group-by on an authoritative
    #: field, so reading it tells you which of them is actually anomalous.
    without_proposed_text: dict[str, list[str]] = field(default_factory=dict)
    parse_notes: list[str] = field(default_factory=list)
    provenance_drift: list[str] = field(default_factory=list)
    #: record_ids sharing one Federal Register document, e.g. a row the index
    #: lists twice. Reported because it means two nodes, one source document.
    shared_documents: list[str] = field(default_factory=list)

    @property
    def by_record_id(self) -> dict[str, NPRMDocument]:
        return {doc.row.record_id: doc for doc in self.documents}

    def resolution_counts(self) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for doc in self.documents:
            counts[doc.via] += 1
        counts[VIA_NONE] = len(self.unresolved)
        return dict(counts)


def harvest(
    client: FederalRegisterClient,
    load: IndexLoad,
    *,
    cache_dir: Path | None = None,
    manifest_path: Path | None = None,
    workers: int = 6,
) -> TextHarvest:
    """Resolve, download and parse every proposal the index names.

    Downloads are cached and never repeated, so a second run is local. Nothing
    is skipped silently: an unresolved row, a missing XML and a document that
    could not be sectioned are three distinct lists on the result.
    """
    directory = cache_dir or paths.FR_NPRM_XML_CACHE
    directory.mkdir(parents=True, exist_ok=True)
    manifest = manifest_path or paths.NPRM_PROVENANCE_JSONL

    index = build_proposal_index(client, load.rows)
    resolutions = resolve_all(load.rows, index)
    result = TextHarvest(unresolved=[r for r in resolutions if not r.resolved])

    wanted: dict[str, str] = {}
    seen_by_number: dict[str, str] = {}
    for resolution in resolutions:
        if not resolution.resolved:
            continue
        doc = resolution.document
        assert doc is not None
        owner = seen_by_number.setdefault(doc.document_number, resolution.row.record_id)
        if owner != resolution.row.record_id:
            result.shared_documents.append(
                f"{resolution.row.record_id} and {owner} both resolve to "
                f"{doc.document_number}"
            )
        if doc.full_text_xml_url:
            wanted[doc.document_number] = doc.full_text_xml_url

    client.prefetch_xml(sorted(wanted.items()), workers=workers, cache_dir=directory)

    prior = provenance.read_manifest(manifest)
    current: list[provenance.Provenance] = []
    for resolution in resolutions:
        if not resolution.resolved:
            continue
        doc = resolution.document
        assert doc is not None
        record = NPRMDocument(row=resolution.row, document=doc, via=resolution.via)
        path = directory / f"{doc.document_number}.xml"
        if not doc.full_text_xml_url:
            record.note = "the index record carries no full_text_xml_url"
            result.xml_unavailable.append(doc.document_number)
        elif not path.is_file() or path.stat().st_size == 0:
            record.note = "XML not in the cache and not downloaded"
            result.xml_unavailable.append(doc.document_number)
        else:
            entry, drift = provenance.reconcile(
                doc.document_number,
                doc.full_text_xml_url,
                path,
                client.fetched.get(doc.document_number),
                prior.get(doc.document_number),
            )
            record.provenance = entry
            current.append(entry)
            if drift:
                result.provenance_drift.append(drift)
            try:
                record.parsed = parse_ad_xml(path, doc.document_number)
            except (ValueError, OSError) as exc:
                record.note = f"parse failed: {exc}"
                result.parse_failures.append(f"{doc.document_number}: {exc}")
            else:
                if record.parsed.structure == "none":
                    reason = doc.action or "no ACTION line in the index record"
                    result.without_proposed_text.setdefault(reason, []).append(
                        doc.document_number
                    )
                for note in record.parsed.notes:
                    result.parse_notes.append(note)
        result.documents.append(record)

    provenance.write_manifest(
        provenance.merge_manifest(prior, current), manifest
    )
    return result


def documents_with_text(result: TextHarvest) -> list[NPRMDocument]:
    """Resolved documents that actually carry proposed regulatory sections."""
    return [d for d in result.documents if d.paragraph_count]


def structure_counts(result: TextHarvest) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for doc in result.documents:
        counts[doc.parsed.structure if doc.parsed else "not_parsed"] += 1
    return dict(counts)


def federal_register_pages(documents: list[NPRMDocument]) -> dict[str, object]:
    """The page count over resolved proposals, from the Register's own integers.

    This is the number to quote for corpus size. It does **not** read the
    spreadsheet's ``pages`` cell, for two reasons that both change the answer:

    * the cell is a string in four different wrappers, and 207 of the 431 do not
      parse into integers at all (see ``federal_register_page_range``);
    * the volume a page belongs to is fixed by the publication *year*, and the
      sheet's ``publish_date`` is one day early for 257 of the 431 rows, so a
      notice published on 1 January would be bucketed into the previous volume
      and counted as a page that no other document could share.

    ``summed`` is the inclusive span per document, which double counts the pages
    two notices share. ``distinct`` is the size of the union of ``(volume, page)``
    pairs and is the honest figure; both are reported rather than one being
    presented as the other. A document whose pages the Register did not state is
    counted in ``documents_without_pages`` and contributes nothing, so both
    totals are floors.
    """
    summed = 0
    touched: set[tuple[int, int]] = set()
    without = 0
    for doc in documents:
        occupied = fr_pages.pages_touched(
            doc.document.start_page,
            doc.document.end_page,
            doc.document.publication_date,
        )
        if not occupied:
            without += 1
            continue
        summed += len(occupied)
        touched.update(occupied)
    return {
        "documents": len(documents),
        "documents_without_pages": without,
        "summed_pages": summed,
        "distinct_pages": len(touched),
    }


def comments_due_date(doc: NPRMDocument) -> str | None:
    """The proposal's comment deadline, from the index's own structured field."""
    value = doc.document.comments_close_on
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        return None


def federal_register_page_range(doc: IndexedDocument) -> str | None:
    """``start-end``, or the start alone for a one-page notice, from integers.

    The shape is the normalised one the citation layer parses
    (``engine.api.citations.PAGE_RANGE``), and nothing is parsed out of a string
    to produce it: both numbers come from the index response. The spreadsheet's
    own page cell is NOT used -- its wrapper varies four ways across the file
    ("(Pages 1-2)", "Pages 1-2", "(Page 1)", and one doubled closing paren), so
    207 of its 431 cells do not match that shape and would be silently dropped
    from a page count. ``tests/test_nprm_text.py`` pins this against the
    citation layer's own formatter.

    The arithmetic itself lives in ``engine.graph.pages``, which is also what
    ``engine.retrieval.corpus`` formats an adopted AD's range with, so a
    proposal and a final rule cannot print their pages two different ways.
    """
    return fr_pages.page_range(doc.start_page, doc.end_page)
