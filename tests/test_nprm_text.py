"""Resolving a proposal to its Federal Register document, and parsing it.

Everything here reads the committed workbook and the cached index/XML under
``data/raw``. No network.

The two findings these pin:

* the index's ``publish_date`` is one day earlier than the Federal Register's
  ``publication_date`` on 257 of 431 rows, so it is a window and not a key;
* NPRM XML carries the *same* ``<HD SOURCE="HD1">(c) Applicability</HD>``
  markup as an adopted AD, so :func:`parse_ad_xml` parses a proposal unchanged.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import paths  # noqa: E402
from engine.ingest import nprm_text as T  # noqa: E402
from engine.ingest.ad_xml import assert_offsets_round_trip, parse_ad_xml  # noqa: E402
from engine.ingest.fr_client import FederalRegisterClient  # noqa: E402
from engine.ingest.nprm_index_xlsx import IndexRow, load_challenge_index  # noqa: E402

NPRM_XML = paths.FR_NPRM_XML_CACHE
#: 91 FR 66019, the first row of the index. Committed to the cache by the
#: harvest; these tests skip rather than download.
SAMPLE = "2026-21387"


def _row(**over) -> IndexRow:
    base = dict(
        row_number=4,
        docket_ids=["FAA-2026-11814"],
        docket_raw="FAA-2026-11814",
        subject_heading="Airworthiness Directives; Airbus Helicopters",
        issue_date=dt.date(2026, 10, 15),
        ad_number=None,
        publish_date=dt.date(2026, 10, 19),
        comments_due_date=None,
        make="Airbus Helicopters",
        make_raw="Airbus Helicopters",
        model_text=None,
        product_type="Aircraft",
        comment_url=None,
        citation="Federal Register, Volume 91 Number 200",
        page_range="66019-66022",
        summary=None,
        record_id="NPRM-001",
        start_page=66019,
        end_page=66022,
    )
    base.update(over)
    return IndexRow(**base)


def _doc(**over) -> T.IndexedDocument:
    base = dict(
        document_number=SAMPLE,
        publication_date="2026-10-19",
        start_page=66019,
        end_page=66022,
        citation="91 FR 66019",
        docket_id="FAA-2026-11814",
        full_text_xml_url="https://example.invalid/x.xml",
        html_url=None,
        comments_close_on="2026-12-03",
        type=T.PROPOSED_RULE_TYPE,
        action="Notice of proposed rulemaking (NPRM).",
    )
    base.update(over)
    return T.IndexedDocument(**base)


def _index(*docs: T.IndexedDocument) -> T.ProposalIndex:
    index = T.ProposalIndex()
    for doc in docs:
        index.add(
            {
                "document_number": doc.document_number,
                "publication_date": doc.publication_date,
                "start_page": doc.start_page,
                "end_page": doc.end_page,
                "citation": doc.citation,
                "docket_ids": [f"Docket No. {doc.docket_id}"] if doc.docket_id else [],
                "full_text_xml_url": doc.full_text_xml_url,
                "html_url": doc.html_url,
                "comments_close_on": doc.comments_close_on,
                "type": doc.type,
                "action": doc.action,
            }
        )
    return index


# ---------------------------------------------------------- the date window

def test_a_publication_date_one_day_later_than_the_sheet_still_resolves():
    """The failure this prevents: 257 of 431 rows silently unresolved."""
    row = _row(publish_date=dt.date(2021, 9, 29), start_page=54135, end_page=54136)
    doc = _doc(
        document_number="2021-21050",
        publication_date="2021-09-30",
        start_page=54135,
        end_page=54136,
        docket_id="FAA-2010-0427",
    )
    resolution = T.resolve_row(
        _row(
            publish_date=row.publish_date,
            start_page=row.start_page,
            end_page=row.end_page,
            docket_ids=["FAA-2010-0427"],
        ),
        _index(doc),
    )
    assert resolution.resolved
    assert resolution.document.document_number == "2021-21050"


def test_a_date_outside_the_window_does_not_resolve():
    """The window is slack for a one-day export artifact, not a free-for-all."""
    doc = _doc(publication_date="2026-12-19")
    assert not T.resolve_row(_row(), _index(doc)).resolved


def test_the_page_number_is_the_identity_not_the_date():
    """Same date, wrong page, unrelated docket: not this notice.

    The docket is spelled differently on purpose. With a matching docket the
    ``docket_date`` fallback would -- correctly -- claim this row, and that
    would test the fallback rather than the page path.
    """
    doc = _doc(start_page=66030, end_page=66033, docket_id="FAA-2026-99999")
    assert not T.resolve_row(_row(), _index(doc)).resolved


def test_the_docket_fallback_takes_over_when_the_page_does_not_match():
    """And when it does fire, it says so, so the report can distinguish them."""
    doc = _doc(start_page=66030, end_page=66033)
    resolution = T.resolve_row(_row(), _index(doc))
    assert resolution.via == T.VIA_DOCKET_DATE


def test_a_final_rule_is_never_resolved_as_a_proposal():
    assert not T.resolve_row(_row(), _index(_doc(type="Rule"))).resolved


# ------------------------------------------------------- picking the right one

def test_a_link_cell_with_two_numbers_picks_the_one_on_the_row_s_page():
    """One cell holds the notice and its later withdrawal. The page decides."""
    notice = _doc(document_number="2021-19355", publication_date="2021-09-09",
                  start_page=50484, end_page=50485, docket_id="FAA-2021-0255")
    earlier = _doc(document_number="2021-07164", publication_date="2021-04-07",
                   start_page=17993, end_page=17994, docket_id="FAA-2021-0255")
    row = _row(
        publish_date=dt.date(2021, 9, 8),
        start_page=50484,
        end_page=50485,
        docket_ids=["FAA-2021-0255"],
        link_document_numbers=["2021-07164", "2021-19355"],
    )
    resolution = T.resolve_row(row, _index(earlier, notice))
    assert resolution.via == T.VIA_LINK
    assert resolution.document.document_number == "2021-19355"


def test_two_notices_starting_on_one_page_are_told_apart():
    """70 FR 14599 carries a GROB-WERKE proposal (14599-14601) and a McDonnell
    Douglas withdrawal (14599). Without the tiebreak both rows resolve to one
    of them and the other notice is never fetched."""
    grob = _doc(document_number="05-5707", publication_date="2005-03-23",
                start_page=14599, end_page=14601, docket_id="FAA-2004-19473")
    mcdonnell = _doc(document_number="05-5700", publication_date="2005-03-23",
                     start_page=14599, end_page=14599, docket_id="2002-NM-306-AD")
    index = _index(mcdonnell, grob)

    grob_row = _row(publish_date=dt.date(2005, 3, 22), start_page=14599,
                    end_page=14601, docket_ids=["FAA-2004-19473"],
                    link_document_numbers=[])
    other_row = _row(publish_date=dt.date(2005, 3, 22), start_page=14599,
                     end_page=14599, docket_ids=["2002-NM-306-AD"],
                     link_document_numbers=[])
    assert T.resolve_row(grob_row, index).document.document_number == "05-5707"
    assert T.resolve_row(other_row, index).document.document_number == "05-5700"


def test_an_ambiguous_docket_match_refuses_rather_than_guessing():
    a = _doc(document_number="x-1", start_page=1, end_page=2, docket_id="FAA-2026-11814")
    b = _doc(document_number="x-2", start_page=3, end_page=4, docket_id="FAA-2026-11814")
    resolution = T.resolve_row(_row(start_page=999, end_page=999), _index(a, b))
    assert not resolution.resolved
    assert "x-1" in resolution.note and "x-2" in resolution.note


def test_an_unresolvable_row_says_why():
    empty = T.resolve_row(_row(federal_register_link=None), T.ProposalIndex())
    assert not empty.resolved
    assert "no federal_register_link" in empty.note
    prose = T.resolve_row(
        _row(federal_register_link="The Withdrawal ...", link_document_numbers=[]),
        T.ProposalIndex(),
    )
    assert "no Federal Register URL" in prose.note


# ------------------------------------------------------ against the real file

@pytest.fixture(scope="module")
def resolutions():
    load = load_challenge_index(paths.NPRM_INDEX_XLSX)
    client = FederalRegisterClient(offline=True)
    try:
        index = T.build_proposal_index(client, load.rows)
    except Exception as exc:  # noqa: BLE001 - no cached proposal index yet
        pytest.skip(f"no cached proposal index: {exc}")
    return T.resolve_all(load.rows, index)


def test_every_row_of_the_real_file_resolves(resolutions):
    unresolved = [r.row.record_id for r in resolutions if not r.resolved]
    assert unresolved == [], f"{len(unresolved)} proposals unresolved: {unresolved[:5]}"
    assert len(resolutions) == 431


def test_no_two_rows_resolve_to_the_same_document(resolutions):
    numbers = [r.document.document_number for r in resolutions if r.resolved]
    assert len(set(numbers)) == len(numbers)


def test_the_measured_date_discrepancy_is_zero_or_one_day(resolutions):
    """The evidence for the window. If this ever shows a 2 the window is hiding
    a real mismatch rather than an export artifact."""
    offsets = T.date_offsets(resolutions)
    assert set(offsets) == {"0", "1"}
    assert offsets["0"] == 174
    assert offsets["1"] == 257
    assert sum(offsets.values()) == 431


def test_most_rows_resolve_without_help_from_the_link_column(resolutions):
    """The link column tops out at 237 usable cells; the Federal Register page
    carries the rest."""
    via = {}
    for resolution in resolutions:
        via[resolution.via] = via.get(resolution.via, 0) + 1
    assert via[T.VIA_LINK] == 234
    assert via[T.VIA_CITATION] + via[T.VIA_DOCKET_DATE] == 197


# ---------------------------------------------- the markup, against final ADs

@pytest.mark.skipif(
    not (NPRM_XML / f"{SAMPLE}.xml").exists(), reason="proposal XML not harvested"
)
def test_proposal_xml_carries_the_same_labelled_headings_as_a_final_ad():
    """The load-bearing structural finding. If this fails, proposal paragraphs
    would have to come from prose, and they do not."""
    parsed = parse_ad_xml(NPRM_XML / f"{SAMPLE}.xml", SAMPLE)
    assert parsed.structure == "labelled_headings"
    labels = [p.label for p in parsed.paragraphs]
    assert labels[:4] == ["a", "b", "c", "d"]
    roles = {p.label: p.role for p in parsed.paragraphs}
    assert roles["c"] == "APPLICABILITY"
    assert roles["f"] == "COMPLIANCE"
    assert roles["g"] == "REQUIRED_ACTIONS"


@pytest.mark.skipif(
    not (NPRM_XML / f"{SAMPLE}.xml").exists(), reason="proposal XML not harvested"
)
def test_the_first_section_is_a_comment_deadline_not_an_effective_date():
    """A final rule opens "(a) Effective Date"; a proposal opens "(a) Comments
    Due Date". ``roles`` has no enum value for the latter and answers OTHER,
    which is its documented behaviour for an unknown heading -- not a guess."""
    parsed = parse_ad_xml(NPRM_XML / f"{SAMPLE}.xml", SAMPLE)
    first = parsed.paragraphs[0]
    assert first.label == "a"
    assert first.heading == "Comments Due Date"
    assert first.role == "OTHER"
    assert not any(p.role == "EFFECTIVE_DATE" for p in parsed.paragraphs)


@pytest.mark.skipif(
    not (NPRM_XML / f"{SAMPLE}.xml").exists(), reason="proposal XML not harvested"
)
def test_proposal_offsets_round_trip_exactly():
    """Every citation into a proposal rests on these offsets."""
    assert_offsets_round_trip(parse_ad_xml(NPRM_XML / f"{SAMPLE}.xml", SAMPLE))


@pytest.mark.skipif(
    not (NPRM_XML / f"{SAMPLE}.xml").exists(), reason="proposal XML not harvested"
)
def test_a_proposal_has_no_ad_number_header_line():
    """A proposal has no AD number yet, so the FP header line a final rule
    carries is absent. Handled, not worked around."""
    parsed = parse_ad_xml(NPRM_XML / f"{SAMPLE}.xml", SAMPLE)
    assert parsed.ad_number_in_text is None
    assert parsed.header_line is None
    assert parsed.subject.startswith("Airworthiness Directives")


# --------------------------------------------------------- the page arithmetic

def _resolved(**over) -> T.NPRMDocument:
    return T.NPRMDocument(row=_row(), document=_doc(**over), via=T.VIA_LINK)


def test_a_page_is_only_unique_inside_its_volume():
    """Two notices printed on page 66019 of two different years are two pages.
    Dropping the volume would silently merge them and under-count the corpus."""
    same_page_different_years = [
        _resolved(document_number="a", publication_date="2025-10-19",
                  start_page=66019, end_page=66019),
        _resolved(document_number="b", publication_date="2026-10-19",
                  start_page=66019, end_page=66019),
    ]
    pages = T.federal_register_pages(same_page_different_years)
    assert pages["summed_pages"] == 2
    assert pages["distinct_pages"] == 2


def test_two_notices_sharing_a_page_are_summed_twice_but_counted_once():
    sharing = [
        _resolved(document_number="a", start_page=66019, end_page=66022),
        _resolved(document_number="b", start_page=66022, end_page=66024),
    ]
    pages = T.federal_register_pages(sharing)
    assert pages["summed_pages"] == 4 + 3
    assert pages["distinct_pages"] == 6  # 66019..66024


def test_a_one_page_notice_counts_as_one_page():
    pages = T.federal_register_pages([_resolved(start_page=14293, end_page=None)])
    assert pages["summed_pages"] == 1
    assert pages["distinct_pages"] == 1


def test_a_document_the_register_gave_no_pages_for_is_reported_not_guessed():
    pages = T.federal_register_pages(
        [_resolved(start_page=None, end_page=None), _resolved(publication_date=None)]
    )
    assert pages["documents"] == 2
    assert pages["documents_without_pages"] == 2
    assert pages["summed_pages"] == 0


def test_the_page_count_does_not_read_the_spreadsheet_page_cell():
    """The sheet's cell and the Register's integers disagree for a few rows, and
    the Register wins. A row whose cell says nothing still contributes its
    pages, which is the whole reason this does not go through the sheet."""
    doc = T.NPRMDocument(
        row=_row(start_page=None, end_page=None, pages_raw="(Pages 1-2))"),
        document=_doc(start_page=66019, end_page=66022),
        via=T.VIA_LINK,
    )
    assert T.federal_register_pages([doc])["summed_pages"] == 4


def test_the_built_page_count_matches_what_the_citation_layer_reads_back():
    """Two layers count the corpus in pages: this one off the harvest, and
    engine.api.citations off the built nodes. A disagreement means one of them is
    quoting a number the other cannot reproduce, which is the number we publish."""
    import json

    from engine.api.citations import corpus_pages

    report = paths.BUILD / "ingest_report.json"
    if not report.exists() or not paths.NODES_JSONL.exists():
        pytest.skip("no built report yet")
    built = json.loads(report.read_text(encoding="utf-8"))
    pages = built.get("proposals", {}).get("text", {}).get(
        "pages_of_all_resolved_proposals"
    )
    if not isinstance(pages, dict):
        pytest.skip("proposal pages not in this report")
    from_nodes = corpus_pages()["proposed"]
    assert pages["summed_pages"] == from_nodes["span_sum"]
    assert pages["distinct_pages"] == from_nodes["distinct_pages"]


# --------------------------------------------- the citation the node carries

def test_the_page_range_is_the_shape_the_citation_layer_parses():
    """Two modules format this string; a disagreement silently drops pages from
    the corpus page count, which is exactly the number we quote. So the two are
    pinned against each other rather than each being pinned to a literal."""
    from engine.api.citations import PAGE_RANGE, page_range as citation_page_range

    cases = [(66019, 66022), (10504, 10504), (3865, 3867), (14293, None), (1, 0)]
    for start, end in cases:
        mine = T.federal_register_page_range(_doc(start_page=start, end_page=end))
        theirs = citation_page_range(start, end)
        assert mine == theirs, f"({start}, {end}): {mine!r} != {theirs!r}"
        assert mine is None or PAGE_RANGE.match(mine)


def test_a_notice_with_no_page_numbers_states_no_range():
    assert T.federal_register_page_range(_doc(start_page=None, end_page=None)) is None
    assert T.federal_register_page_range(_doc(start_page=0, end_page=5)) is None


def test_the_built_nodes_carry_a_parsable_citation_and_page_range():
    """Against the real artifact: every proposal node must state its pages in
    integers, or the corpus page count quietly under-reports."""
    import json

    from engine.api.citations import FR_CITATION, PAGE_RANGE

    if not paths.NODES_JSONL.exists():
        pytest.skip("no built nodes yet")
    nprms = [
        json.loads(line)
        for line in paths.NODES_JSONL.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line).get("_type") == "NPRM"
    ]
    if not nprms:
        pytest.skip("no built proposals yet")
    assert len(nprms) == 431
    bad_pages = [n["nprm_id"] for n in nprms if not PAGE_RANGE.match(n["page_range"] or "")]
    assert not bad_pages, f"proposal page_range not normalised: {bad_pages[:5]}"
    bad_cite = [n["nprm_id"] for n in nprms if not FR_CITATION.match(n["citation"] or "")]
    assert not bad_cite, f"proposal citation not in '91 FR 66019' form: {bad_cite[:5]}"


def test_the_volume_from_the_citation_agrees_with_the_publication_year():
    """``volume == year - 1935``. It only holds because publish_date is the
    Federal Register's publication date; with the sheet's one-day-early value a
    notice published on 1 January would land in the previous volume and its
    pages would be dropped as unattributable."""
    import json

    from engine.api.citations import volume_of

    if not paths.NODES_JSONL.exists():
        pytest.skip("no built nodes yet")
    mismatched = []
    for line in paths.NODES_JSONL.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("_type") != "NPRM":
            continue
        if volume_of(record, date_field="publish_date") is None:
            mismatched.append(record["nprm_id"])
    assert not mismatched, (
        f"proposals whose citation volume and publication year disagree: "
        f"{mismatched[:5]}"
    )


# ------------------------------------------------------- the comment deadline

def test_the_comment_deadline_comes_from_the_register_not_the_sheet():
    document = T.NPRMDocument(row=_row(), document=_doc(), via=T.VIA_LINK)
    assert T.comments_due_date(document) == "2026-12-03"
    assert T.comments_due_date(
        T.NPRMDocument(row=_row(), document=_doc(comments_close_on=None), via=T.VIA_LINK)
    ) is None
    assert T.comments_due_date(
        T.NPRMDocument(
            row=_row(), document=_doc(comments_close_on="not-a-date"), via=T.VIA_LINK
        )
    ) is None
