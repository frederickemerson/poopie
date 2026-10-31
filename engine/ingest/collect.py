"""Collect the corpus: Federal Register index -> cached XML -> parsed revisions.

Two passes build the final-rule set:

1. every FAA final rule published in the requested window;
2. every document filed under a docket that appears in the NPRM spreadsheet,
   whatever its publication date, so the NPRM -> final-rule join is as complete
   as the sources allow. The spreadsheet spans 2001-2026, so this pass reaches
   final rules two decades older than the window.

A document is treated as an AD exactly when its structured ``docket_ids`` names
an AD number. Rules that merely match the search term (BasicMed updates,
airworthiness criteria, miscellaneous amendments) are recorded as skipped with
their title, never guessed at from prose.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from engine.graph.pages import page_number
from engine.graph.pages import page_range as fr_page_range
from engine.ingest.ad_xml import ParsedAD, parse_ad_xml
from engine.ingest.docket_ids import DocketIds, parse_docket_ids
from engine.ingest import provenance
from engine.ingest.fr_client import FederalRegisterClient
from engine.ingest.make_normalize import normalize_make
from engine.ingest.nprm_xlsx import SpreadsheetLoad
from engine.ingest.refs import RevisionRefs, extract_refs
from engine.ingest.supersession import AffectedADs, parse_affected_ads

#: PREAMB/SUBJECT suffix -> the spreadsheet's Product Type vocabulary.
_PRODUCT_TYPE_BY_WORD = {
    "Airplanes": "Aircraft",
    "Helicopters": "Aircraft",
    "Gliders": "Aircraft",
    "Balloons": "Aircraft",
    "Airships": "Aircraft",
    "Aircraft": "Aircraft",
    "Engines": "Engine",
    "Propellers": "Propeller",
}


@dataclass
class RevisionRecord:
    revision_id: str
    ids: DocketIds
    publication_date: dt.date | None
    effective_on: dt.date | None
    full_text_xml_url: str | None
    title: str | None
    #: Federal Register citation exactly as the index gives it, e.g. "91 FR 66019".
    citation: str | None
    #: First and last Federal Register page, from the index's own start_page /
    #: end_page integers. Never parsed out of the citation string or the prose.
    start_page: int | None
    end_page: int | None
    in_window: bool
    parsed: ParsedAD | None = None
    refs: RevisionRefs | None = None
    affected: AffectedADs | None = None
    provenance: provenance.Provenance | None = None

    @property
    def page_range(self) -> str | None:
        """The page range as ``start-end``, or the start page alone when it is one page.

        Derived, never stored: a stored copy could disagree with the integers
        it came from, and the integers are the authoritative pair. Formatted by
        ``engine.graph.pages``, which is the engine's only page formatter, so
        the shape here cannot drift from the shape a citation renders.
        """
        return fr_page_range(self.start_page, self.end_page)

    @property
    def ad_number(self) -> str:
        assert self.ids.ad_number is not None
        return self.ids.ad_number

    @property
    def structure(self) -> str:
        return self.parsed.structure if self.parsed else "unavailable"

    @property
    def make_raw(self) -> str | None:
        if self.parsed and self.parsed.manufacturer_raw:
            return self.parsed.manufacturer_raw
        if self.title and ";" in self.title:
            tail = self.title.split(";", 1)[1].strip()
            for word, _ in _PRODUCT_TYPE_BY_WORD.items():
                if tail.endswith(word):
                    return tail[: -len(word)].strip() or None
            return tail or None
        return None

    @property
    def make(self) -> str | None:
        return normalize_make(self.make_raw)

    @property
    def product_type_from_document(self) -> str | None:
        if self.parsed and self.parsed.product_word:
            return _PRODUCT_TYPE_BY_WORD.get(self.parsed.product_word)
        for word, product in _PRODUCT_TYPE_BY_WORD.items():
            if (self.title or "").endswith(word):
                return product
        return None


@dataclass
class Corpus:
    revisions: list[RevisionRecord] = field(default_factory=list)
    skipped_non_ad: list[dict[str, str]] = field(default_factory=list)
    xml_unavailable: list[str] = field(default_factory=list)
    parse_notes: list[str] = field(default_factory=list)
    dockets_queried: int = 0
    documents_seen: int = 0
    provenance_drift: list[str] = field(default_factory=list)


def _date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def _record(document: dict, in_window: bool) -> RevisionRecord:
    return RevisionRecord(
        revision_id=document["document_number"],
        ids=parse_docket_ids(document.get("docket_ids")),
        publication_date=_date(document.get("publication_date")),
        effective_on=_date(document.get("effective_on")),
        full_text_xml_url=document.get("full_text_xml_url"),
        title=document.get("title"),
        citation=document.get("citation"),
        start_page=page_number(document.get("start_page")),
        end_page=page_number(document.get("end_page")),
        in_window=in_window,
    )


def collect(
    client: FederalRegisterClient,
    nprm: SpreadsheetLoad,
    since: str,
    until: str,
    *,
    term: str = "airworthiness directives",
    follow_nprm_dockets: bool = True,
    limit: int | None = None,
) -> Corpus:
    corpus = Corpus()
    seen: dict[str, RevisionRecord] = {}

    def consider(document: dict, in_window: bool) -> None:
        number = document.get("document_number")
        if not number or number in seen:
            return
        corpus.documents_seen += 1
        record = _record(document, in_window)
        if not record.ids.is_airworthiness_directive:
            corpus.skipped_non_ad.append(
                {
                    "document_number": number,
                    "title": document.get("title") or "",
                    "reason": "docket_ids names no AD number",
                }
            )
            return
        seen[number] = record

    for document in client.final_rules_between(since, until, term=term):
        consider(document, in_window=True)

    if follow_nprm_dockets:
        covered = {r.ids.docket_id for r in seen.values()}
        wanted = {d for row in nprm.rows for d in row.docket_ids}
        for docket in sorted(wanted - covered):
            corpus.dockets_queried += 1
            for document in client.documents_for_docket(docket):
                if (document.get("type") or "").lower() != "rule":
                    continue
                published = document.get("publication_date") or ""
                consider(document, in_window=bool(since <= published <= until))

    records = sorted(seen.values(), key=lambda r: (r.publication_date or dt.date.min, r.revision_id))
    if limit is not None:
        records = records[:limit]

    client.prefetch_xml([(r.revision_id, r.full_text_xml_url or "") for r in records])

    prior_manifest = provenance.read_manifest()

    for record in records:
        if record.full_text_xml_url:
            path = client.document_xml(record.revision_id, record.full_text_xml_url)
        else:
            path = None
        if path is None:
            corpus.xml_unavailable.append(record.revision_id)
            corpus.revisions.append(record)
            continue
        record.provenance, drift = provenance.reconcile(
            record.revision_id,
            record.full_text_xml_url,
            path,
            client.fetched.get(record.revision_id),
            prior_manifest.get(record.revision_id),
        )
        if drift:
            corpus.provenance_drift.append(drift)
        parsed = parse_ad_xml(path, record.revision_id)
        record.parsed = parsed
        corpus.parse_notes.extend(parsed.notes)
        paragraphs = [(p.label, p.role, p.text) for p in parsed.paragraphs]
        record.refs = extract_refs(paragraphs)
        affected = [p for p in parsed.paragraphs if p.role == "AFFECTED_ADS"]
        if affected:
            record.affected = parse_affected_ads(affected[0].text)
        corpus.revisions.append(record)

    return corpus
