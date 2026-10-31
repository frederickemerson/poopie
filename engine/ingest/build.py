"""CLI: build data/build/{nodes,edges,paragraphs}.jsonl from the real sources.

    python3 -m engine.ingest.build                       # 2021-01-01 .. today
    python3 -m engine.ingest.build --since 2015-01-01    # widen the window
    python3 -m engine.ingest.build --offline             # rebuild from the caches only

Downloads are cached (``data/raw/fr_ad`` for final-rule XML,
``data/raw/fr_nprm`` for proposal XML, ``data/raw/fr_index`` for index
responses) and never repeated, so a rebuild after the first run is local.

Two sources name the same 431 proposed rules, and each is used for what it is
authoritative about:

* ``data/reference/challenge-4-ad-index.xlsx`` (read by
  :mod:`engine.ingest.nprm_index_xlsx`) supplies ``record_id``, the derived
  ``supersedes_ad`` / ``mentions_serial_numbers`` flags and the subject text.
  ``record_id`` is the ``nprm_id``.
* the Federal Register itself supplies the publication date, the citation, the
  page range, the comment deadline and the full text. The spreadsheet's own
  ``publish_date`` is one day earlier than the Federal Register's publication
  date on 257 of the 431 rows -- the sheet's own ``citation`` string names the
  later date -- so the sheet's column is kept only as a recorded sidecar value
  under ``sheet_publish_date`` and never written as the publication date.

``--no-nprm-text`` skips the proposal harvest; the proposals are then still
nodes, with no paragraphs.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine import paths  # noqa: E402
from engine.graph.stage import PROPOSED, revision_stage  # noqa: E402
from engine.ingest.collect import Corpus, RevisionRecord, collect  # noqa: E402
from engine.ingest.emit import (  # noqa: E402
    SOURCE_KIND_NPRM,
    SOURCE_KIND_REVISION,
    GraphWriter,
    edge_type_named,
    write_jsonl,
)
from engine.ingest import nprm_text as nprm_text_mod  # noqa: E402
from engine.ingest import provenance  # noqa: E402
from engine.ingest.fr_client import FederalRegisterClient  # noqa: E402
from engine.ingest.nprm_index_xlsx import (  # noqa: E402
    IndexLoad,
    IndexRow,
    load_challenge_index,
    total_pages,
)
from engine.ingest.nprm_xlsx import SpreadsheetLoad, load_nprm_rows  # noqa: E402
from engine.ingest.supersession import (  # noqa: E402
    RevisionFacts,
    SupersessionResult,
    ad_status,
    build_chain,
)

NPRM_SOURCE = "nprm_spreadsheet"
FEDERAL_REGISTER_SOURCE = "federal_register"
EDGE_SUPERSEDES = edge_type_named("SUPERS")


def _iso(value: dt.date | None) -> str | None:
    return value.isoformat() if value else None


def _chain(corpus: Corpus) -> SupersessionResult:
    facts = [
        RevisionFacts(
            revision_id=record.revision_id,
            ad_number=record.ad_number,
            amendment=record.ids.amendment,
            publication_date=record.publication_date,
            superseded_ad_numbers=list(record.affected.superseded) if record.affected else [],
        )
        for record in corpus.revisions
    ]
    return build_chain(facts)


def _docket_titles(corpus: Corpus, load: SpreadsheetLoad) -> dict[str, str]:
    titles: dict[str, str] = {}
    for record in corpus.revisions:
        docket = record.ids.docket_id
        if docket and record.title:
            titles.setdefault(docket, record.title)
    for row in load.rows:
        for docket in row.docket_ids:
            if row.subject_heading:
                titles.setdefault(docket, row.subject_heading)
    return titles


def _sheet_by_docket(load: SpreadsheetLoad) -> dict[str, list]:
    out: dict[str, list] = defaultdict(list)
    for row in load.rows:
        for docket in row.docket_ids:
            out[docket].append(row)
    return out


def _provenance_fields(record: RevisionRecord) -> dict:
    prov = record.provenance
    if prov is None:  # no XML available: there are no source bytes to pin
        return {"content_sha256": None, "retrieved_at": None, "source_bytes": None}
    return {
        "content_sha256": prov.content_sha256,
        "retrieved_at": prov.retrieved_at,
        "source_bytes": prov.source_bytes,
    }


def _reference_fields(record: RevisionRecord) -> dict:
    """The human-readable half of a citation, from the Federal Register index.

    ``fr_client.INDEX_FIELDS`` has always requested ``citation``, ``start_page``
    and ``end_page``, and ``collect`` has always parked them on the record --
    but the Revision node never carried them, so every citation this engine
    emitted was an exact character anchor with nothing a reader could take to
    paper. These three fields are that half. They are copied, never derived:
    ``fr_citation`` is the index's own string and ``start_page``/``end_page``
    its own integers, and ``emit._check_revision_pages`` refuses the node if
    the citation and the start page disagree.
    """
    return {
        "fr_citation": record.citation,
        "start_page": record.start_page,
        "end_page": record.end_page,
    }


def _nprm_publication_date(
    row: IndexRow, harvested: nprm_text_mod.NPRMDocument | None
) -> str | None:
    """The proposal's publication date, from the Federal Register when we have it.

    Never the spreadsheet's ``publish_date``: measured across all 431 rows it
    equals the Federal Register's ``publication_date`` on 174 and is exactly one
    day earlier on the other 257, and the sheet's own ``citation`` string names
    the Federal Register's date in every one of those 257. A row we could not
    resolve to a document has no authoritative date, and ``None`` says so rather
    than substituting the one we know to be wrong 60% of the time.
    """
    if harvested is not None:
        return harvested.document.publication_date
    return None


def _earliest_revision_date(records: list[RevisionRecord]) -> dt.date | None:
    dates = [r.publication_date for r in records if r.publication_date]
    return min(dates) if dates else None


def _nprm_reference_fields(
    row: IndexRow, harvested: nprm_text_mod.NPRMDocument | None
) -> dict:
    """``citation`` and ``page_range`` for a proposal node.

    From the Federal Register index when the proposal resolved: ``citation`` is
    the index's own "91 FR 66019" string and ``page_range`` is its two page
    integers formatted, which is the shape ``engine.api.citations`` parses.

    A proposal that did not resolve falls back to the spreadsheet's strings.
    That is a real downgrade and it is deliberate: the sheet's citation is prose
    and its page cell has four different wrappers, so the page count will skip
    such a row rather than mis-attribute it. Every one of the 431 rows resolves
    today, so the fallback is unreached -- it exists so that a future row the
    register cannot confirm degrades visibly instead of inventing a citation.
    """
    if harvested is None:
        return {"citation": row.citation, "page_range": row.page_range}
    return {
        "citation": harvested.document.citation or row.citation,
        "page_range": nprm_text_mod.federal_register_page_range(harvested.document),
    }


def emit(
    corpus: Corpus,
    load: SpreadsheetLoad,
    chain: SupersessionResult,
    index_load: IndexLoad,
    harvest: nprm_text_mod.TextHarvest | None = None,
) -> dict:
    """Write the JSONL files plus the sidecars. Returns the report."""
    paths.ensure_dirs()
    titles = _docket_titles(corpus, load)
    sheet_by_docket = _sheet_by_docket(load)
    harvested = harvest.by_record_id if harvest else {}
    nprm_by_docket: dict[str, list[str]] = defaultdict(list)
    nprm_published: dict[str, dt.date] = {}
    for row in index_load.rows:
        for docket in row.docket_ids:
            nprm_by_docket[docket].append(row.nprm_id)
        published = _nprm_publication_date(row, harvested.get(row.record_id))
        parsed = dt.date.fromisoformat(published) if published else None
        if parsed:
            nprm_published[row.nprm_id] = parsed

    revisions_by_ad: dict[str, list[RevisionRecord]] = defaultdict(list)
    for record in corpus.revisions:
        revisions_by_ad[record.ad_number].append(record)
    dockets_with_final_rule = {r.ids.docket_id for r in corpus.revisions if r.ids.docket_id}

    make_aliases: dict[str, set[str]] = defaultdict(set)
    make_raw_by_node: dict[str, dict[str, str]] = {"NPRM": {}, "AD": {}}
    revision_text: list[dict] = []
    nprm_text: list[dict] = []
    delegating_revisions: dict[str, dict[str, bool]] = {}
    foreign_authorities: dict[str, int] = defaultdict(int)
    proposed_by_skipped: list[str] = []

    with GraphWriter(
        paths.NODES_JSONL,
        paths.EDGES_JSONL,
        paths.PARAGRAPHS_JSONL,
        paths.NPRM_PARAGRAPHS_JSONL,
    ) as writer:
        for docket, title in sorted(titles.items()):
            writer.node(
                "Docket",
                {
                    "docket_id": docket,
                    "title": title,
                    "has_nprm": docket in nprm_by_docket,
                    "has_final_rule": docket in dockets_with_final_rule,
                },
            )

        for row in index_load.rows:
            identifier = row.nprm_id
            document = harvested.get(row.record_id)
            writer.node(
                "NPRM",
                {
                    "nprm_id": identifier,
                    "record_id": row.record_id,
                    "docket_id": row.docket_id,
                    # Both copied off the Federal Register index response, the
                    # same way a Revision's fr_citation/start_page/end_page
                    # are, so the citation layer reads one shape for both kinds
                    # of document. The spreadsheet's own citation string and
                    # page cell are kept in the nprm_text sidecar.
                    **_nprm_reference_fields(row, document),
                    "publish_date": _nprm_publication_date(row, document),
                    "comments_due_date": (
                        nprm_text_mod.comments_due_date(document) if document else None
                    ),
                    "make": row.make,
                    "model_text": row.model_text,
                    "product_type": row.product_type,
                    "summary": row.summary,
                    # The challenge index dropped the comment-submission link
                    # column; the Federal Register page is the stable way in.
                    "comment_url": None,
                    "ad_number": row.ad_number,
                    "supersedes_ad": row.supersedes_ad,
                    "mentions_serial_numbers": row.mentions_serial_numbers,
                    "federal_register_link": row.federal_register_link,
                    "fr_document_number": (
                        document.document.document_number if document else None
                    ),
                    "full_text_xml_url": (
                        document.document.full_text_xml_url if document else None
                    ),
                    **_nprm_text_fields(document),
                    # The node is a spreadsheet row enriched from the register;
                    # the register is where its text and dates came from.
                    "source": FEDERAL_REGISTER_SOURCE if document else NPRM_SOURCE,
                },
            )
            if row.make and row.make_raw:
                make_aliases[row.make].add(row.make_raw)
                make_raw_by_node["NPRM"][identifier] = row.make_raw
            for docket in row.docket_ids:
                writer.edge("IN_DOCKET", "NPRM", identifier, "Docket", docket)
            if document is not None:
                _emit_nprm_detail(writer, row, document, nprm_text)

        for ad_number, records in sorted(revisions_by_ad.items()):
            records.sort(key=lambda r: (r.publication_date or dt.date.min, r.revision_id))
            current = chain.current_revision.get(ad_number, records[-1].revision_id)
            newest = next(r for r in records if r.revision_id == current)
            sheet_rows = sheet_by_docket.get(newest.ids.docket_id or "", [])
            product_type = next(
                (row.product_type for row in sheet_rows if row.product_type),
                newest.product_type_from_document,
            )
            writer.node(
                "AD",
                {
                    "ad_number": ad_number,
                    "docket_id": newest.ids.docket_id,
                    "current_revision_id": current,
                    "status": ad_status(ad_number, chain),
                    "make": newest.make,
                    "product_type": product_type,
                },
            )
            if newest.make and newest.make_raw:
                make_aliases[newest.make].add(newest.make_raw)
                make_raw_by_node["AD"][ad_number] = newest.make_raw
            if newest.ids.docket_id:
                writer.edge("IN_DOCKET", "AD", ad_number, "Docket", newest.ids.docket_id)
                adopted_on = _earliest_revision_date(records)
                for nprm_id in nprm_by_docket.get(newest.ids.docket_id, []):
                    # A proposal has to precede the rule it proposed. Sharing a
                    # docket is not enough: a docket outlives its first rule and
                    # gets re-noticed, so without this AD 2009-17-05 is recorded
                    # as proposed by a notice published in 2011.
                    published = nprm_published.get(nprm_id)
                    if adopted_on and published and published > adopted_on:
                        proposed_by_skipped.append(
                            f"{ad_number} (adopted {adopted_on.isoformat()}) is not "
                            f"proposed by {nprm_id} (published {published.isoformat()})"
                        )
                        continue
                    writer.edge("PROPOSED_BY", "AD", ad_number, "NPRM", nprm_id)

            for record in records:
                writer.node(
                    "Revision",
                    {
                        "revision_id": record.revision_id,
                        "ad_number": ad_number,
                        "docket_id": record.ids.docket_id,
                        "fr_document_number": record.revision_id,
                        "amendment": record.ids.amendment,
                        "publication_date": _iso(record.publication_date),
                        "effective_on": _iso(record.effective_on),
                        "full_text_xml_url": record.full_text_xml_url,
                        "is_current": chain.is_current.get(record.revision_id, False),
                        "superseded_by": chain.superseded_by.get(record.revision_id),
                        **_reference_fields(record),
                        **_provenance_fields(record),
                    },
                )
                writer.edge("HAS_REVISION", "AD", ad_number, "Revision", record.revision_id)
                _emit_revision_detail(
                    writer,
                    record,
                    revision_text,
                    delegating_revisions,
                    foreign_authorities,
                    revision_stage(
                        {
                            "revision_id": record.revision_id,
                            "effective_on": _iso(record.effective_on),
                            "superseded_by": chain.superseded_by.get(record.revision_id),
                        }
                    ),
                )

        for source, target in chain.edges:
            writer.edge(EDGE_SUPERSEDES, "Revision", source, "Revision", target)

        node_counts = dict(writer.node_counts)
        edge_counts = dict(writer.edge_counts)
        paragraph_counts = dict(writer.paragraph_counts)

    write_jsonl(paths.REVISION_TEXT_JSONL, revision_text)
    write_jsonl(paths.NPRM_TEXT_JSONL, nprm_text)
    paths.MAKE_RAW_JSON.write_text(
        json.dumps(
            {
                "note": "raw manufacturer strings; the contract has no make_raw field",
                "aliases": {k: sorted(v) for k, v in sorted(make_aliases.items())},
                "by_node": make_raw_by_node,
            },
            indent=1,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    report = _report(
        corpus, load, chain, node_counts, edge_counts, delegating_revisions, foreign_authorities
    )
    report["paragraphs_by_source_kind"] = paragraph_counts
    report["proposals"] = _nprm_report(index_load, harvest, proposed_by_skipped)
    return report


def _nprm_report(
    index_load: IndexLoad,
    harvest: nprm_text_mod.TextHarvest | None,
    proposed_by_skipped: list[str],
) -> dict:
    """What the proposal half of the build did, in numbers that can be re-checked."""
    report: dict = {
        "index": index_load.as_report(),
        "pages_from_the_index_page_column": total_pages(index_load.rows),
        "proposed_by_edges_rejected_on_date_order": proposed_by_skipped,
    }
    if harvest is None:
        report["text"] = "not harvested (--no-nprm-text)"
        return report
    with_text = nprm_text_mod.documents_with_text(harvest)
    report["text"] = {
        "resolved": len(harvest.documents),
        "resolved_via": harvest.resolution_counts(),
        "publication_date_minus_sheet_publish_date_days": nprm_text_mod.date_offsets(
            [
                nprm_text_mod.Resolution(d.row, d.document, d.via)
                for d in harvest.documents
            ]
        ),
        "structures": nprm_text_mod.structure_counts(harvest),
        "documents_with_proposed_text": len(with_text),
        "paragraphs": sum(d.paragraph_count for d in harvest.documents),
        "without_proposed_text_by_federal_register_action": {
            action: len(numbers)
            for action, numbers in sorted(harvest.without_proposed_text.items())
        },
        # From the Register's own start_page/end_page integers, bucketed by
        # volume. The spreadsheet's page cell is reported separately, under
        # pages_from_the_index_page_column, as the source's own claim.
        "pages_of_all_resolved_proposals": nprm_text_mod.federal_register_pages(
            harvest.documents
        ),
        "pages_of_documents_with_proposed_text": nprm_text_mod.federal_register_pages(
            with_text
        ),
        "unresolved": [r.row.record_id for r in harvest.unresolved],
        "xml_unavailable": harvest.xml_unavailable,
        "parse_failures": harvest.parse_failures,
        "shared_documents": harvest.shared_documents,
        "provenance_drift": harvest.provenance_drift,
    }
    return report


def _nprm_text_fields(document: nprm_text_mod.NPRMDocument | None) -> dict:
    """``plain_text`` plus the provenance of the bytes it was parsed from.

    A proposal we resolved but could not fetch, and one whose document carries
    no proposed sections, both get nulls here: an empty string would claim we
    hold text we do not.
    """
    if document is None or document.parsed is None or not document.parsed.plain_text:
        return {
            "plain_text": None,
            "content_sha256": None,
            "retrieved_at": None,
            "source_bytes": None,
        }
    prov = document.provenance
    return {
        "plain_text": document.parsed.plain_text,
        "content_sha256": prov.content_sha256 if prov else None,
        "retrieved_at": prov.retrieved_at if prov else None,
        "source_bytes": prov.source_bytes if prov else None,
    }


def _emit_nprm_detail(
    writer: GraphWriter,
    row: IndexRow,
    document: nprm_text_mod.NPRMDocument,
    nprm_text: list[dict],
) -> None:
    """Paragraphs of one proposal: staged PROPOSED, every one of them.

    There is no HAS_PARAGRAPH edge here. The contract declares that edge as
    starting at a Revision only, and the contract is pinned, so the parent link
    for a proposal's paragraph is its ``nprm_id`` field (see
    docs/contract_change_requests.md). ``paragraph_id`` is
    ``{nprm_id}#{label}``, which is the contract's format with ``record_id`` as
    the document id.
    """
    parsed = document.parsed
    if parsed is None:
        return
    nprm_text.append(
        {
            "nprm_id": row.nprm_id,
            "record_id": row.record_id,
            "fr_document_number": document.document.document_number,
            "plain_text": parsed.plain_text,
            "char_length": len(parsed.plain_text),
            "paragraph_count": len(parsed.paragraphs),
            "structure": parsed.structure,
            "resolved_via": document.via,
            "fr_action": document.document.action,
            "fr_publication_date": document.document.publication_date,
            "fr_citation": document.document.citation,
            "start_page": document.document.start_page,
            "end_page": document.document.end_page,
            # Kept for the record and clearly named: the spreadsheet's own
            # values. publish_date is one day early on 257 of the 431 rows and
            # is NOT what the NPRM node's publish_date carries; the citation is
            # prose and the page cell has four wrappers, so neither is what the
            # node's citation/page_range carry either.
            "sheet_publish_date": _iso(row.publish_date),
            "sheet_pages": row.pages_raw,
            "sheet_citation": row.citation,
            "note": document.note,
        }
    )
    for paragraph in parsed.paragraphs:
        paragraph_id = f"{row.nprm_id}#{paragraph.label}"
        writer.node(
            "Paragraph",
            {
                "paragraph_id": paragraph_id,
                "revision_id": None,
                "nprm_id": row.nprm_id,
                "source_kind": SOURCE_KIND_NPRM,
                "document_stage": PROPOSED,
                "label": paragraph.label,
                "role": paragraph.role,
                "heading": paragraph.heading,
                "text": paragraph.text,
                "char_start": paragraph.char_start,
                "char_end": paragraph.char_end,
                "ordinal": paragraph.ordinal,
            },
        )


def _emit_revision_detail(
    writer: GraphWriter,
    record: RevisionRecord,
    revision_text: list[dict],
    delegating: dict[str, dict[str, bool]],
    authorities: dict[str, int],
    stage: str,
) -> None:
    """Paragraphs of one adopted revision.

    ``stage`` is this revision's stage as at build time. It is written because
    the contract declares the field on every Paragraph, but it is a function of
    today's date -- a revision effective next week becomes EFFECTIVE with no
    rebuild -- so the retrieval layer recomputes it from the Revision node's
    own ``effective_on`` and ``superseded_by`` instead of trusting this value.
    See ``engine.retrieval.corpus._revision_paragraph_stage``.
    """
    parsed = record.parsed
    if parsed is None:
        return
    revision_text.append(
        {
            "revision_id": record.revision_id,
            "plain_text": parsed.plain_text,
            "char_length": len(parsed.plain_text),
            "paragraph_count": len(parsed.paragraphs),
            "structure": parsed.structure,
        }
    )
    for paragraph in parsed.paragraphs:
        paragraph_id = f"{record.revision_id}#{paragraph.label}"
        writer.node(
            "Paragraph",
            {
                "paragraph_id": paragraph_id,
                "revision_id": record.revision_id,
                "nprm_id": None,
                "source_kind": SOURCE_KIND_REVISION,
                "document_stage": stage,
                "label": paragraph.label,
                "role": paragraph.role,
                "heading": paragraph.heading,
                "text": paragraph.text,
                "char_start": paragraph.char_start,
                "char_end": paragraph.char_end,
                "ordinal": paragraph.ordinal,
            },
        )
        writer.edge("HAS_PARAGRAPH", "Revision", record.revision_id, "Paragraph", paragraph_id)

    refs = record.refs
    if refs is None:
        return
    for foreign in refs.foreign_ads:
        authorities[foreign.authority_raw] += 1
        writer.node(
            "ForeignAD",
            {
                "foreign_ad_id": foreign.foreign_ad_id,
                "authority": foreign.authority,
                "ad_number": foreign.ad_number,
                "dated": foreign.dated,
                "held": False,
            },
        )
        writer.edge(
            "ADOPTS_MCAI", "Revision", record.revision_id, "ForeignAD", foreign.foreign_ad_id
        )
    for bulletin in refs.service_bulletins:
        writer.node(
            "ServiceBulletin",
            {
                "sb_id": bulletin.sb_id,
                "manufacturer": bulletin.manufacturer,
                "number": bulletin.number,
                "revision": bulletin.revision,
                "dated": bulletin.dated,
                "held": False,
            },
        )
        writer.edge(
            "REFERENCES_SB", "Revision", record.revision_id, "ServiceBulletin", bulletin.sb_id
        )
    delegating[record.revision_id] = {
        "applicability": refs.delegates_applicability,
        "compliance": refs.delegates_compliance,
    }


def _report(
    corpus: Corpus,
    load: SpreadsheetLoad,
    chain: SupersessionResult,
    node_counts: dict[str, int],
    edge_counts: dict[str, int],
    delegating: dict[str, dict[str, bool]],
    authorities: dict[str, int],
) -> dict:
    current_revisions = {ad: rev for ad, rev in chain.current_revision.items()}
    ad_delegating_applicability = sum(
        1 for rev in current_revisions.values() if delegating.get(rev, {}).get("applicability")
    )
    ad_delegating_either = sum(
        1
        for rev in current_revisions.values()
        if any(delegating.get(rev, {}).get(k) for k in ("applicability", "compliance"))
    )
    total_ads = len(current_revisions)
    structures: dict[str, int] = defaultdict(int)
    for record in corpus.revisions:
        structures[record.structure] += 1
    sheet_dockets = {d for row in load.rows for d in row.docket_ids}
    final_dockets = {r.ids.docket_id for r in corpus.revisions if r.ids.docket_id}

    return {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "nodes": node_counts,
        "edges": edge_counts,
        "documents_seen": corpus.documents_seen,
        "revisions": len(corpus.revisions),
        "ads": total_ads,
        "paragraph_structures": dict(structures),
        "delegation": {
            "ads_total": total_ads,
            "ads_whose_current_revision_delegates_applicability": ad_delegating_applicability,
            "ads_whose_current_revision_delegates_applicability_or_compliance": ad_delegating_either,
            "pct_applicability": round(100 * ad_delegating_applicability / total_ads, 1)
            if total_ads
            else 0.0,
            "pct_applicability_or_compliance": round(100 * ad_delegating_either / total_ads, 1)
            if total_ads
            else 0.0,
            "revisions_delegating_applicability": sum(
                1 for v in delegating.values() if v["applicability"]
            ),
            "revisions_delegating_compliance": sum(
                1 for v in delegating.values() if v["compliance"]
            ),
        },
        "supersession": {
            "edges": len(chain.edges),
            "corrections_same_amendment": len(chain.corrections),
            "referenced_ads_outside_corpus": len(chain.dangling),
            "dangling_sample": chain.dangling[:20],
        },
        "nprm": {
            "rows": len(load.rows),
            "unique_dockets": len(sheet_dockets),
            "rows_without_comments_due_date": sum(
                1 for row in load.rows if row.comments_due_date is None
            ),
            "rows_with_multiple_dockets": load.rows_with_multiple_dockets,
            "rows_without_docket": load.rows_without_docket,
            "date_parse_failures": load.date_parse_failures,
            "dockets_joined_to_a_final_rule": len(sheet_dockets & final_dockets),
            "dockets_with_no_final_rule_yet": len(sheet_dockets - final_dockets),
        },
        "foreign_authority_tokens": dict(sorted(authorities.items(), key=lambda kv: -kv[1])),
        "skipped_non_ad_rules": len(corpus.skipped_non_ad),
        "skipped_non_ad_sample": corpus.skipped_non_ad[:10],
        "xml_unavailable": corpus.xml_unavailable,
        "parse_notes": corpus.parse_notes,
        "provenance": {
            "with_retrieved_at": sum(1 for p in (r.provenance for r in corpus.revisions) if p and p.retrieved_at),
            "hash_only_unknown_retrieved_at": sum(
                1 for p in (r.provenance for r in corpus.revisions) if p and not p.retrieved_at
            ),
            "drift": corpus.provenance_drift,
        },
        "dockets_queried_outside_window": corpus.dockets_queried,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default="2021-01-01", help="earliest publication_date")
    parser.add_argument("--until", default=dt.date.today().isoformat(), help="latest publication_date")
    parser.add_argument("--term", default="airworthiness directives")
    parser.add_argument("--offline", action="store_true", help="use the caches only")
    parser.add_argument(
        "--skip-nprm-dockets",
        action="store_true",
        help="do not look up final rules for spreadsheet dockets outside the window",
    )
    parser.add_argument("--limit", type=int, default=None, help="cap documents, for smoke runs")
    parser.add_argument(
        "--nprm-index",
        default=str(paths.NPRM_INDEX_XLSX),
        help="the challenge index workbook; source of record_id and the proposal rows",
    )
    parser.add_argument(
        "--no-nprm-text",
        action="store_true",
        help="do not fetch or parse proposal full text; proposals stay nodes with "
        "no paragraphs",
    )
    parser.add_argument(
        "--verify-provenance",
        action="store_true",
        help="re-hash cached XML against data/build/provenance.jsonl, no network; "
        "exit 1 on changed or missing files",
    )
    args = parser.parse_args(argv)
    if args.verify_provenance:
        return provenance.run_verify_cli()

    paths.ensure_dirs()
    load = load_nprm_rows(paths.NPRM_XLSX)
    index_load = load_challenge_index(Path(args.nprm_index))
    client = FederalRegisterClient(offline=args.offline)
    corpus = collect(
        client,
        load,
        args.since,
        args.until,
        term=args.term,
        follow_nprm_dockets=not args.skip_nprm_dockets,
        limit=args.limit,
    )
    chain = _chain(corpus)
    held = [r.provenance for r in corpus.revisions if r.provenance is not None]
    provenance.write_manifest(provenance.merge_manifest(provenance.read_manifest(), held))
    harvest = None if args.no_nprm_text else nprm_text_mod.harvest(client, index_load)
    report = emit(corpus, load, chain, index_load, harvest)
    report["window"] = {"since": args.since, "until": args.until}
    report["fetch"] = {
        "index_requests": client.stats.index_requests,
        "index_cache_hits": client.stats.index_cache_hits,
        "xml_downloads": client.stats.xml_downloads,
        "xml_cache_hits": client.stats.xml_cache_hits,
        "xml_failures": client.stats.xml_failures,
    }
    paths.INGEST_REPORT_JSON.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "nodes",
                    "edges",
                    "paragraphs_by_source_kind",
                    "delegation",
                    "nprm",
                    "proposals",
                )
            },
            indent=1,
        )
    )
    print(f"report -> {paths.INGEST_REPORT_JSON}")
    for note in corpus.provenance_drift:
        print(f"PROVENANCE DRIFT: {note}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
