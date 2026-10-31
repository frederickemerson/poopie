"""The challenge organizers' AD index, and what is actually in its columns.

Reads the committed workbook; no network. The point of these tests is the gap
between a column's fill rate and its usability: ``federal_register_link`` is
non-empty on 406 of 431 rows, and only 237 of those cells contain a Federal
Register URL at all.
"""

from __future__ import annotations

import datetime as dt
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.ingest.nprm_index_xlsx import (  # noqa: E402
    HEADER_ROW_INDEX,
    IndexRow,
    federal_register_document_numbers,
    load_challenge_index,
    page_numbers,
    publish_year_range,
    total_pages,
)
from engine.ingest.nprm_xlsx import SpreadsheetError  # noqa: E402
from engine.paths import NPRM_INDEX_XLSX, NPRM_XLSX  # noqa: E402
from engine.ingest.nprm_xlsx import load_nprm_rows  # noqa: E402


@pytest.fixture(scope="module")
def load():
    return load_challenge_index(NPRM_INDEX_XLSX)


# ------------------------------------------------------------------- shape

def test_every_row_is_read_and_every_iso_date_parses(load):
    """The FAA export is %m/%d/%Y; this file is ISO. Both must parse fully."""
    assert len(load.rows) == 431
    assert load.date_parse_failures == []
    assert load.rows_without_docket == []
    assert all(isinstance(r.publish_date, dt.date) for r in load.rows)
    assert all(isinstance(r.issue_date, dt.date) for r in load.rows)


def test_the_header_is_not_on_the_first_row(load):
    """Row 0 is a banner and row 1 is blank; reading row 0 as the header would
    look like a file with one unnamed column and 433 data rows."""
    assert HEADER_ROW_INDEX == 2
    assert load.rows[0].row_number == HEADER_ROW_INDEX + 2


def test_record_id_is_unique_and_is_the_node_key(load):
    ids = [r.record_id for r in load.rows]
    assert len(set(ids)) == 431
    assert ids[0] == "NPRM-001"
    assert all(r.nprm_id == r.record_id for r in load.rows)


def test_the_node_key_carries_no_at_sign(load):
    """A citation id is ``{paragraph_id}@{start}-{end}`` and is split on its
    first ``@``, so an id containing one truncates every citation built on it."""
    assert all("@" not in r.nprm_id for r in load.rows)


def test_a_wrong_sheet_name_is_an_error_not_an_empty_load(tmp_path):
    with pytest.raises(SpreadsheetError):
        load_challenge_index(NPRM_XLSX)


# ------------------------------------------------- the same rows, two files

def test_it_covers_exactly_the_dockets_of_the_faa_export(load):
    """Same 431 notices, so switching the build's NPRM source loses no docket."""
    export = load_nprm_rows(NPRM_XLSX)
    assert len(export.rows) == len(load.rows) == 431
    mine = {d for r in load.rows for d in r.docket_ids}
    theirs = {d for r in export.rows for d in r.docket_ids}
    assert mine == theirs
    assert len(mine) == 322


def test_two_cells_still_name_two_dockets_each(load):
    assert len(load.rows_with_multiple_dockets) == 2
    for row in load.rows:
        if row.record_id in load.rows_with_multiple_dockets:
            assert len(row.docket_ids) > 1
            assert row.docket_id == row.docket_ids[0]


def test_make_is_normalized_but_the_raw_string_is_kept(load):
    by_make: dict[str, set[str]] = {}
    for row in load.rows:
        if row.make:
            by_make.setdefault(row.make, set()).add(row.make_raw or "")
    assert {"Boeing", "The Boeing Company"} <= by_make["Boeing"]
    assert "Airbus Helicopters" in by_make


def test_the_dropped_columns_are_absent_not_silently_empty(load):
    """The organizers removed Comments Due Date and the comment-submission
    link. Carrying a stale value for either would be worse than carrying none:
    the comment deadline now comes from the Federal Register document."""
    assert all(r.comments_due_date is None for r in load.rows)
    assert all(r.comment_url is None for r in load.rows)


def test_ad_number_is_the_final_number_not_the_proposed_one(load):
    """21 rows here against 431 in the FAA export: different facts, not a
    regression. The export numbers the proposal; this file names the final AD
    where one exists."""
    assert sum(1 for r in load.rows if r.ad_number) == 21


def test_the_derived_columns_match_the_sheet_s_own_notes(load):
    report = load.as_report()
    assert report["mentions_serial_numbers_yes"] == 16
    assert report["with_supersedes_ad"] == 62
    assert report["with_model"] == 86
    assert load.unexpected_serial_number_flags == []
    assert set(Counter(r.mentions_serial_numbers for r in load.rows)) == {True, False}


# --------------------------------------------------------- the link column

def test_the_link_column_fill_rate_overstates_its_usability(load):
    """406 of 431 cells are non-empty; 169 of those hold no URL at all."""
    non_empty = 431 - len(load.rows_without_link)
    assert non_empty == 406
    assert len(load.rows_without_link) == 25
    assert len(load.rows_with_link_but_no_document_number) == 169
    usable = non_empty - len(load.rows_with_link_but_no_document_number)
    assert usable == 237
    assert len(load.rows_with_several_document_numbers) == 15


def test_all_three_federal_register_permalink_shapes_are_read():
    long_form = (
        "https://www.federalregister.gov/documents/2026/10/19/2026-21387/"
        "airworthiness-directives-airbus-helicopters"
    )
    assert federal_register_document_numbers(long_form) == ["2026-21387"]
    assert federal_register_document_numbers(
        "https://www.federalregister.gov/d/2021-21050"
    ) == ["2021-21050"]
    assert federal_register_document_numbers(
        "https://federalregister.gov/a/2016-10735"
    ) == ["2016-10735"]


def test_a_cell_holding_two_links_keeps_both_in_order():
    cell = (
        'https://www.federalregister.gov/d/2021-07164"Withdrawal: "'
        "https://www.federalregister.gov/d/2021-19355"
    )
    assert federal_register_document_numbers(cell) == ["2021-07164", "2021-19355"]


def test_pasted_document_prose_yields_no_document_number():
    """169 cells hold rule text instead of a link. Deriving a number from that
    prose is the one thing this must never do."""
    prose = (
        "The Withdrawal\n\n    Accordingly, we withdraw the NPRM, Docket No. "
        "FAA-2005-21236, Directorate Identifier 2005-NM-011-AD, and the "
        "compliance time of 25 hours time-in-service it proposed."
    )
    assert federal_register_document_numbers(prose) == []
    assert federal_register_document_numbers(None) == []
    assert federal_register_document_numbers("") == []


def test_a_correction_document_number_is_not_rejected():
    """R1- and E9- prefixes are real Federal Register document numbers."""
    assert federal_register_document_numbers(
        "https://www.federalregister.gov/d/R1-2022-22698"
    ) == ["R1-2022-22698"]
    assert federal_register_document_numbers(
        "https://www.federalregister.gov/d/E9-14356"
    ) == ["E9-14356"]


# -------------------------------------------------------------- the pages

def test_every_page_cell_yields_numbers_despite_four_wrappers(load):
    assert load.rows_without_page_numbers == []
    assert page_numbers("(Pages 66019-66022)") == (66019, 66022)
    assert page_numbers("Pages 45118-45119") == (45118, 45119)
    assert page_numbers("(Page 10504)") == (10504, 10504)
    # One real cell has a doubled closing paren.
    assert page_numbers("(Page 14293))") == (14293, 14293)
    assert page_numbers("Page 3865-3867") == (3865, 3867)
    assert page_numbers(None) == (None, None)
    assert page_numbers("no pages here") == (None, None)


def test_the_page_total_clears_the_thousand_page_bar(load):
    """The organizers' note: summaries are ~150 pages, full documents 1,000+."""
    pages = total_pages(load.rows)
    assert pages["rows"] == 431
    assert pages["rows_without_pages"] == 0
    assert pages["summed_pages"] == 1341
    # Notices share pages, so the union is smaller than the sum. Both are
    # reported; neither is presented as the other.
    assert pages["distinct_pages"] == 1285
    assert pages["distinct_pages"] <= pages["summed_pages"]
    assert pages["distinct_pages"] > 1000


def test_a_single_page_notice_counts_as_one_page():
    row = IndexRow(
        row_number=1,
        docket_ids=["FAA-2020-0001"],
        docket_raw="FAA-2020-0001",
        subject_heading=None,
        issue_date=None,
        ad_number=None,
        publish_date=dt.date(2020, 1, 1),
        comments_due_date=None,
        make=None,
        make_raw=None,
        model_text=None,
        product_type=None,
        comment_url=None,
        citation=None,
        page_range=None,
        summary=None,
        record_id="NPRM-000",
        start_page=10,
        end_page=10,
    )
    assert total_pages([row])["summed_pages"] == 1


def test_the_publication_years_span_the_whole_file(load):
    assert publish_year_range(load.rows) == (2001, 2026)
