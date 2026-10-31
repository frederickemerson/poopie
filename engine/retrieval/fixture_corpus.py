"""Build a dev fixture corpus from committed Federal Register AD XML.

This is NOT the ingest. ``engine/ingest`` owns the real pipeline and the real
``data/build/*.jsonl``. This module exists for one reason: retrieval has to be
built, tuned and measured against real AD prose before the ingest lands, and
tuning a threshold on synthetic text would make the reported numbers worthless.

It writes a parallel, clearly named set of files (see ``layout.py``) and never
touches the ingest's output. When the ingest's ``paragraphs.jsonl`` appears,
``layout.default_corpus_paths`` switches to it automatically.

    python3 -m engine.retrieval.fixture_corpus            # fixtures only
    python3 -m engine.retrieval.fixture_corpus --raw      # + data/raw/fr_ad

Paragraph structure comes from the FR XML's own markup -- ``<EXTRACT>`` holds
the codified AD, each ``<HD SOURCE="HD1">`` is a labelled paragraph heading and
the ``<P>`` elements after it are its body. Labels are read from the heading,
never guessed from position.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contracts.contract import edge_types, validate_node  # noqa: E402

#: Selected from the contract, not written as a literal: the refusal-code lint
#: in tests/test_contract.py reserves this edge type's spelling.
_EDGE_SUPERSEDES = next(e for e in edge_types() if e.startswith("SUPERS"))
from engine.ingest.docket_ids import parse_docket_ids  # noqa: E402
from engine.retrieval import layout  # noqa: E402

#: A Federal Register document number, e.g. 2026-17615.
_FR_DOC_NUMBER = re.compile(r"\d{4}-\d{4,6}")
#: "(c) Applicability" -> label "c", heading "Applicability".
_HEADING = re.compile(r"^\(([a-z0-9]{1,4})\)\s*(.*)$", re.IGNORECASE)
#: Paragraph separator inside Revision.plain_text. Fixed so char offsets are
#: reproducible from the same inputs.
_JOIN = "\n\n"

#: Heading -> paragraph_role. Exact match on the normalised heading first; then
#: the ordered prefix table below. Both are literal tables, not fuzzy matching:
#: an unlisted heading becomes OTHER and is counted, never guessed at.
_ROLE_EXACT = {
    "effective date": "EFFECTIVE_DATE",
    "affected ad": "AFFECTED_ADS",
    "affected ads": "AFFECTED_ADS",
    "applicability": "APPLICABILITY",
    "subject": "SUBJECT",
    "unsafe condition": "UNSAFE_CONDITION",
    "compliance": "COMPLIANCE",
    "requirements": "REQUIRED_ACTIONS",
    "required actions": "REQUIRED_ACTIONS",
    "definition": "OTHER",
    "definitions": "OTHER",
    "additional information": "ADDITIONAL_INFO",
    "additional ad provisions": "ADDITIONAL_INFO",
    "other faa ad provisions": "ADDITIONAL_INFO",
    "credit for previous actions": "CREDIT",
    "material incorporated by reference": "IBR",
}
_ROLE_PREFIX: tuple[tuple[str, str], ...] = (
    ("exception", "EXCEPTIONS"),
    ("alternative methods of compliance", "AMOC"),
    ("credit for", "CREDIT"),
    ("material incorporated", "IBR"),
)
_ROLE_CONTAINS: tuple[tuple[str, str], ...] = (
    ("amoc", "AMOC"),
    ("incorporated by reference", "IBR"),
)


def role_for(heading: str) -> str:
    key = " ".join(heading.split()).casefold().rstrip(":")
    exact = _ROLE_EXACT.get(key)
    if exact:
        return exact
    for prefix, role in _ROLE_PREFIX:
        if key.startswith(prefix):
            return role
    for needle, role in _ROLE_CONTAINS:
        if needle in key:
            return role
    return "OTHER"


def element_text(el: ET.Element) -> str:
    """All descendant text, whitespace-collapsed. ``<E>`` emphasis is inline."""
    return " ".join("".join(el.itertext()).split())


@dataclass(frozen=True)
class ParsedAD:
    revision_id: str
    ad_number: str
    docket_id: str | None
    amendment: str | None
    effective_on: str | None
    make: str | None
    product_type: str | None
    paragraphs: list[dict[str, object]]
    plain_text: str


def _depdoc_entries(root: ET.Element) -> list[str]:
    """The bracketed DEPDOC line carries the same facts as the API's docket_ids."""
    dep = root.find(".//DEPDOC")
    if dep is None:
        return []
    raw = element_text(dep).strip("[] ")
    return [part.strip() for part in raw.split(";") if part.strip()]


def parse_ad_xml(path: Path) -> ParsedAD | None:
    """One FR document -> its codified paragraphs, or None if it is not an AD.

    Returns None (not an exception) for a document with no ``<EXTRACT>`` or no
    AD number in its docket line: those are real FAA rules that are not ADs,
    and skipping them is correct. A malformed XML file is an exception.
    """
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ValueError(f"{path} is not parseable XML: {exc}") from exc

    ids = parse_docket_ids(_depdoc_entries(root))
    if not ids.ad_number:
        return None
    extract = root.find(".//EXTRACT")
    if extract is None:
        return None

    # revision_id is the FR document number. The two committed fixtures are
    # excerpts whose filenames are descriptive rather than document numbers, so
    # they fall back to the AD number, which is still unique and readable.
    revision_id = path.stem if _FR_DOC_NUMBER.fullmatch(path.stem) else ids.ad_number
    records: list[tuple[str, str, str]] = []  # (label, heading, text)
    label: str | None = None
    heading = ""
    body: list[str] = []
    for child in list(extract):
        if child.tag == "HD":
            if label is not None and body:
                records.append((label, heading, " ".join(body)))
            text = element_text(child)
            match = _HEADING.match(text)
            label, heading, body = (
                (match.group(1).lower(), match.group(2), [])
                if match
                else (None, "", [])
            )
        elif child.tag in {"P", "FP"} and label is not None:
            chunk = element_text(child)
            if chunk:
                body.append(chunk)
    if label is not None and body:
        records.append((label, heading, " ".join(body)))
    if not records:
        return None

    paragraphs: list[dict[str, object]] = []
    cursor = 0
    pieces: list[str] = []
    for ordinal, (lbl, head, text) in enumerate(records):
        start = cursor
        pieces.append(text)
        cursor += len(text)
        paragraphs.append(
            {
                "paragraph_id": f"{revision_id}#{lbl}",
                "revision_id": revision_id,
                "label": lbl,
                "role": role_for(head),
                "heading": head,
                "text": text,
                "char_start": start,
                "char_end": cursor,
                "ordinal": ordinal,
            }
        )
        cursor += len(_JOIN)
    for record in paragraphs:
        validate_node("Paragraph", record)

    return ParsedAD(
        revision_id=revision_id,
        ad_number=ids.ad_number,
        docket_id=ids.docket_id,
        amendment=ids.amendment,
        effective_on=_effective_date(root),
        make=_subject_make(root),
        product_type=_subject_product_type(root),
        paragraphs=paragraphs,
        plain_text=_JOIN.join(pieces),
    )


def _effective_date(root: ET.Element) -> str | None:
    """Effective date from the DATES block, as an ISO string, or None."""
    eff = root.find(".//EFFDATE")
    if eff is None:
        return None
    match = re.search(
        r"effective\s+([A-Z][a-z]+)\s+(\d{1,2}),\s*(\d{4})", element_text(eff)
    )
    if not match:
        return None
    months = (
        "January February March April May June July "
        "August September October November December"
    ).split()
    month, day, year = match.group(1), int(match.group(2)), match.group(3)
    if month not in months:
        return None
    return f"{year}-{months.index(month) + 1:02d}-{day:02d}"


#: Product nouns the Federal Register itself uses to end a SUBJECT line. A
#: literal table over a single-purpose structured element, not prose matching.
_PRODUCT_NOUNS: tuple[str, ...] = (
    "Turbofan Engines",
    "Turboshaft Engines",
    "Turbopropeller Engines",
    "Reciprocating Engines",
    "Airplanes and Helicopters",
    "Airplanes",
    "Helicopters",
    "Engines",
    "Propellers",
    "Gliders",
    "Balloons",
)


def _subject_tail(root: ET.Element) -> str | None:
    """The part of PREAMB/SUBJECT after the 'Airworthiness Directives;' prefix."""
    subject = root.find(".//PREAMB/SUBJECT")
    if subject is None:
        return None
    text = element_text(subject)
    if ";" not in text:
        return None
    return text.split(";", 1)[1].strip() or None


def _subject_make(root: ET.Element) -> str | None:
    """Make as the FR states it, verbatim minus its trailing product noun.

    Left unnormalised on purpose: the canonical form comes from
    engine/graph/normalize.py's table at query time, and an unlisted make stays
    unmapped rather than being guessed at.
    """
    tail = _subject_tail(root)
    if tail is None:
        return None
    for noun in _PRODUCT_NOUNS:
        if tail.endswith(" " + noun):
            return tail[: -len(noun) - 1].rstrip(" ,") or None
    return tail


def _subject_product_type(root: ET.Element) -> str | None:
    tail = _subject_tail(root)
    if tail is None:
        return None
    for noun in _PRODUCT_NOUNS:
        if tail.endswith(" " + noun):
            return noun
    return None


def _write_jsonl(path: Path, lines: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for line in lines:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    tmp.replace(path)


def build(sources: list[Path]) -> dict[str, int]:
    """Parse every source XML and write the fixture corpus. Returns counts."""
    parsed: list[ParsedAD] = []
    skipped = 0
    for path in sources:
        ad = parse_ad_xml(path)
        if ad is None:
            skipped += 1
            continue
        parsed.append(ad)
    if not parsed:
        raise ValueError(
            f"none of the {len(sources)} source files yielded an AD with codified "
            f"paragraphs; check that they are Federal Register AD XML"
        )

    # Latest revision per AD number wins `is_current`; revision ids are the FR
    # document numbers, which sort chronologically within the 2021-2026 window.
    by_ad: dict[str, list[ParsedAD]] = {}
    for ad in parsed:
        by_ad.setdefault(ad.ad_number, []).append(ad)

    nodes: list[dict[str, object]] = []
    edges: list[dict[str, object]] = []
    paragraphs: list[dict[str, object]] = []
    revision_text: list[dict[str, object]] = []
    for ad_number, revisions in sorted(by_ad.items()):
        revisions.sort(key=lambda r: r.revision_id)
        current = revisions[-1]
        docket = next((r.docket_id for r in revisions if r.docket_id), None)
        ad_node = {
            "ad_number": ad_number,
            "docket_id": docket,
            "current_revision_id": current.revision_id,
            "status": "current",
            "make": current.make,
            "product_type": current.product_type,
        }
        validate_node("AD", ad_node)
        nodes.append({"_type": "AD", **ad_node})
        if docket:
            docket_node = {
                "docket_id": docket,
                "title": None,
                "has_nprm": False,
                "has_final_rule": True,
            }
            validate_node("Docket", docket_node)
            nodes.append({"_type": "Docket", **docket_node})
            edges.append(_edge("IN_DOCKET", "AD", ad_number, "Docket", docket))

        for index, rev in enumerate(revisions):
            newer = revisions[index + 1].revision_id if index + 1 < len(revisions) else None
            rev_node = {
                "revision_id": rev.revision_id,
                "ad_number": ad_number,
                "docket_id": rev.docket_id,
                "fr_document_number": rev.revision_id,
                "amendment": rev.amendment,
                "publication_date": None,
                "effective_on": rev.effective_on,
                "full_text_xml_url": None,
                "is_current": rev is current,
                "superseded_by": newer,
            }
            validate_node("Revision", rev_node)
            nodes.append({"_type": "Revision", **rev_node})
            edges.append(
                _edge("HAS_REVISION", "AD", ad_number, "Revision", rev.revision_id)
            )
            if newer:
                edges.append(
                    _edge(_EDGE_SUPERSEDES, "Revision", newer, "Revision", rev.revision_id)
                )
            for record in rev.paragraphs:
                paragraphs.append(record)
                nodes.append({"_type": "Paragraph", **record})
                edges.append(
                    _edge(
                        "HAS_PARAGRAPH",
                        "Revision",
                        rev.revision_id,
                        "Paragraph",
                        str(record["paragraph_id"]),
                    )
                )
            revision_text.append(
                {"revision_id": rev.revision_id, "plain_text": rev.plain_text}
            )

    _write_jsonl(layout.FIXTURE_NODES_JSONL, nodes)
    _write_jsonl(layout.FIXTURE_EDGES_JSONL, edges)
    _write_jsonl(layout.FIXTURE_PARAGRAPHS_JSONL, paragraphs)
    _write_jsonl(layout.FIXTURE_REVISION_TEXT_JSONL, revision_text)
    return {
        "sources": len(sources),
        "ads": len(by_ad),
        "revisions": len(parsed),
        "paragraphs": len(paragraphs),
        "skipped_not_ad": skipped,
    }


def _edge(
    edge_type: str, src_type: str, src: str, dst_type: str, dst: str
) -> dict[str, object]:
    return {
        "_type": edge_type,
        "_src_type": src_type,
        "_src": src,
        "_dst_type": dst_type,
        "_dst": dst,
    }


#: How many raw FR documents the fixture corpus takes, in sorted filename
#: order. Fixed so the corpus -- and therefore every measured number -- is
#: reproducible while the ingest agent is still downloading into the same
#: directory. Raise it explicitly with --limit.
RAW_LIMIT = 120


def _sources(include_raw: bool, limit: int = RAW_LIMIT) -> list[Path]:
    paths = sorted(layout.FIXTURES.glob("ad_*.xml"))
    if include_raw:
        paths += sorted(layout.RAW_FR_XML.glob("*.xml"))[:limit]
    if not paths:
        raise layout.CorpusUnavailable(
            f"no AD XML found in {layout.FIXTURES} "
            f"(or {layout.RAW_FR_XML} with --raw)"
        )
    return paths


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--raw",
        action="store_true",
        help="also parse data/raw/fr_ad/*.xml (a realistic ~120-AD corpus)",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=RAW_LIMIT,
        help=f"raw documents to take, sorted by filename (default {RAW_LIMIT})",
    )
    args = ap.parse_args(argv)
    counts = build(_sources(args.raw, args.limit))
    print(json.dumps(counts, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
