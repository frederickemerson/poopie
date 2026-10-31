"""CLI: build data/build/{nodes,edges,paragraphs}.jsonl from the real sources.

    python3 -m engine.ingest.build                       # 2021-01-01 .. today
    python3 -m engine.ingest.build --since 2015-01-01    # widen the window
    python3 -m engine.ingest.build --offline             # rebuild from the caches only

Downloads are cached (``data/raw/fr_ad`` for XML, ``data/raw/fr_index`` for index
responses) and never repeated, so a rebuild after the first run is local.
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
from engine.ingest.collect import Corpus, RevisionRecord, collect  # noqa: E402
from engine.ingest.emit import GraphWriter, edge_type_named, write_jsonl  # noqa: E402
from engine.ingest.fr_client import FederalRegisterClient  # noqa: E402
from engine.ingest.nprm_xlsx import SpreadsheetLoad, load_nprm_rows, nprm_id_for  # noqa: E402
from engine.ingest.supersession import (  # noqa: E402
    RevisionFacts,
    SupersessionResult,
    ad_status,
    build_chain,
)

NPRM_SOURCE = "nprm_spreadsheet"
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


def _nprm_ids(load: SpreadsheetLoad) -> list[tuple[str, object]]:
    taken: set[str] = set()
    out = []
    for row in load.rows:
        identifier = nprm_id_for(row, taken)
        taken.add(identifier)
        out.append((identifier, row))
    return out


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


def emit(corpus: Corpus, load: SpreadsheetLoad, chain: SupersessionResult) -> dict:
    """Write all three JSONL files plus the sidecars. Returns the report."""
    paths.ensure_dirs()
    nprm_rows = _nprm_ids(load)
    titles = _docket_titles(corpus, load)
    sheet_by_docket = _sheet_by_docket(load)
    nprm_by_docket: dict[str, list[str]] = defaultdict(list)
    for identifier, row in nprm_rows:
        for docket in row.docket_ids:
            nprm_by_docket[docket].append(identifier)

    revisions_by_ad: dict[str, list[RevisionRecord]] = defaultdict(list)
    for record in corpus.revisions:
        revisions_by_ad[record.ad_number].append(record)
    dockets_with_final_rule = {r.ids.docket_id for r in corpus.revisions if r.ids.docket_id}

    make_aliases: dict[str, set[str]] = defaultdict(set)
    make_raw_by_node: dict[str, dict[str, str]] = {"NPRM": {}, "AD": {}}
    revision_text: list[dict] = []
    delegating_revisions: dict[str, dict[str, bool]] = {}
    foreign_authorities: dict[str, int] = defaultdict(int)

    with GraphWriter(paths.NODES_JSONL, paths.EDGES_JSONL, paths.PARAGRAPHS_JSONL) as writer:
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

        for identifier, row in nprm_rows:
            writer.node(
                "NPRM",
                {
                    "nprm_id": identifier,
                    "docket_id": row.docket_id,
                    "citation": row.citation,
                    "page_range": row.page_range,
                    "publish_date": _iso(row.publish_date),
                    "comments_due_date": _iso(row.comments_due_date),
                    "make": row.make,
                    "model_text": row.model_text,
                    "product_type": row.product_type,
                    "summary": row.summary,
                    "comment_url": row.comment_url,
                    "source": NPRM_SOURCE,
                },
            )
            if row.make and row.make_raw:
                make_aliases[row.make].add(row.make_raw)
                make_raw_by_node["NPRM"][identifier] = row.make_raw
            for docket in row.docket_ids:
                writer.edge("IN_DOCKET", "NPRM", identifier, "Docket", docket)

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
                for nprm_id in nprm_by_docket.get(newest.ids.docket_id, []):
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
                    },
                )
                writer.edge("HAS_REVISION", "AD", ad_number, "Revision", record.revision_id)
                _emit_revision_detail(
                    writer, record, revision_text, delegating_revisions, foreign_authorities
                )

        for source, target in chain.edges:
            writer.edge(EDGE_SUPERSEDES, "Revision", source, "Revision", target)

        node_counts = dict(writer.node_counts)
        edge_counts = dict(writer.edge_counts)

    write_jsonl(paths.REVISION_TEXT_JSONL, revision_text)
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
    return _report(
        corpus, load, chain, node_counts, edge_counts, delegating_revisions, foreign_authorities
    )


def _emit_revision_detail(
    writer: GraphWriter,
    record: RevisionRecord,
    revision_text: list[dict],
    delegating: dict[str, dict[str, bool]],
    authorities: dict[str, int],
) -> None:
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
    args = parser.parse_args(argv)

    paths.ensure_dirs()
    load = load_nprm_rows(paths.NPRM_XLSX)
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
    report = emit(corpus, load, chain)
    report["window"] = {"since": args.since, "until": args.until}
    report["fetch"] = {
        "index_requests": client.stats.index_requests,
        "index_cache_hits": client.stats.index_cache_hits,
        "xml_downloads": client.stats.xml_downloads,
        "xml_cache_hits": client.stats.xml_cache_hits,
        "xml_failures": client.stats.xml_failures,
    }
    paths.INGEST_REPORT_JSON.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("nodes", "edges", "delegation", "nprm")}, indent=1))
    print(f"report -> {paths.INGEST_REPORT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
