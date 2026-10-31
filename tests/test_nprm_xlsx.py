"""The NPRM spreadsheet, including the re-notice case.

99 of the 323 docket values in the real file appear on more than one row. Those
rows are legitimate re-notices and supplemental NPRMs: one node per ROW, keyed
on docket + Federal Register citation. Collapsing them to one node per docket
would delete the comment periods of the earlier notices.

Reads the committed spreadsheet; no network.
"""

from __future__ import annotations

import datetime as dt
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.paths import NPRM_XLSX  # noqa: E402
from engine.ingest.nprm_xlsx import load_nprm_rows, nprm_id_for  # noqa: E402


@pytest.fixture(scope="module")
def load():
    return load_nprm_rows(NPRM_XLSX)


def test_every_row_is_read_and_every_date_parses(load):
    assert len(load.rows) == 431
    assert load.date_parse_failures == []
    assert load.rows_without_docket == []


def test_text_dates_become_real_dates(load):
    row = load.rows[0]
    assert isinstance(row.publish_date, dt.date)
    assert isinstance(row.issue_date, dt.date)
    assert all(
        isinstance(r.comments_due_date, dt.date)
        for r in load.rows
        if r.comments_due_date is not None
    )


def test_the_four_rows_without_a_comments_due_date_are_kept(load):
    missing = [r for r in load.rows if r.comments_due_date is None]
    assert len(missing) == 4
    assert all(r.docket_ids for r in missing)


def test_re_noticed_dockets_produce_one_node_per_row(load):
    """The unique key is docket + citation, not docket."""
    per_docket = Counter(r.docket_id for r in load.rows)
    re_noticed = {docket: n for docket, n in per_docket.items() if n > 1}
    assert len(re_noticed) >= 90, "the real file re-notices around a hundred dockets"

    docket = max(re_noticed, key=lambda d: re_noticed[d])
    rows = [r for r in load.rows if r.docket_id == docket]
    assert len(rows) > 1
    assert len({r.citation for r in rows}) == len(rows), "re-notices differ by FR citation"

    taken: set[str] = set()
    ids = []
    for row in load.rows:
        identifier = nprm_id_for(row, taken)
        taken.add(identifier)
        ids.append(identifier)
    assert len(set(ids)) == len(load.rows) == 431
    assert len({i for i, r in zip(ids, load.rows) if r.docket_id == docket}) == len(rows)


def test_make_is_normalized_but_the_raw_string_is_kept(load):
    by_make: dict[str, set[str]] = {}
    for row in load.rows:
        if row.make:
            by_make.setdefault(row.make, set()).add(row.make_raw or "")
    assert {"Boeing", "The Boeing Company"} <= by_make["Boeing"]
    assert {"Airbus", "Airbus SAS"} <= by_make["Airbus"]
    # distinct manufacturers are not merged
    assert "Airbus Helicopters" in by_make
    assert all(row.make_raw for row in load.rows if row.make)


def test_page_range_is_stripped_of_its_wrapper(load):
    assert all(
        not (row.page_range or "").startswith("(") for row in load.rows if row.page_range
    )


def test_a_cell_naming_two_dockets_keeps_both(load):
    multi = [r for r in load.rows if len(r.docket_ids) > 1]
    assert multi, "the real file has rows whose docket cell names two dockets"
    for row in multi:
        assert row.docket_id == row.docket_ids[0]
        assert len(set(row.docket_ids)) == len(row.docket_ids)
