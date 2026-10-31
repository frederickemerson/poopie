"""docket_ids is the authoritative source for docket, amendment and AD number.

Every case here is a real ``docket_ids`` list or spreadsheet cell taken from the
corpus, including the eight shapes that are not the common one.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.ingest.docket_ids import (  # noqa: E402
    normalize_sheet_docket,
    parse_docket_ids,
)


def test_parses_the_common_four_entry_shape():
    ids = parse_docket_ids(
        [
            "Docket No. FAA-2026-2723",
            "Project Identifier AD-2024-00429-A",
            "Amendment 39-23502",
            "AD 2026-21-13",
        ]
    )
    assert ids.docket_id == "FAA-2026-2723"
    assert ids.amendment == "39-23502"
    assert ids.ad_number == "2026-21-13"
    assert ids.project_identifier == "AD-2024-00429-A"
    assert ids.is_airworthiness_directive


def test_project_identifier_is_not_mistaken_for_the_ad_number():
    """'AD-2024-00429-A' is a project id, not an AD number; only the AD entry is."""
    ids = parse_docket_ids(
        ["Docket No. FAA-2025-0003", "Project Identifier AD-2024-00110-T", "Amendment 39-23501"]
    )
    assert ids.ad_number is None
    assert ids.project_identifier == "AD-2024-00110-T"
    assert not ids.is_airworthiness_directive


def test_amendment_and_ad_number_sharing_one_entry():
    ids = parse_docket_ids(
        [
            "Docket No. FAA-2021-0375",
            "Project Identifier MCAI-2020-01245-R",
            "Amendment 39-21656 AD 2021-15-09",
        ]
    )
    assert (ids.amendment, ids.ad_number) == ("39-21656", "2021-15-09")


def test_two_digit_year_and_spaced_revision_suffix():
    ids = parse_docket_ids(
        ["Docket No. FAA-2023-0434", "Product Identifier 91-NM-255-AD", "AD 92-02-14 R1"]
    )
    assert ids.ad_number == "92-02-14"
    assert ids.ad_revision_suffix == "R1"


def test_unspaced_revision_suffix_and_trailing_dash_amendment():
    ids = parse_docket_ids(["Docket FAA-2023-2234", "Amendment 39-21749-", "AD 2021-03-16R1"])
    assert (ids.docket_id, ids.amendment) == ("FAA-2023-2234", "39-21749")
    assert (ids.ad_number, ids.ad_revision_suffix) == ("2021-03-16", "R1")


def test_hyphenated_ad_token_and_bare_ad_number():
    assert parse_docket_ids(["AD-2025-05-15"]).ad_number == "2025-05-15"
    assert parse_docket_ids(["2026-08-11"]).ad_number == "2026-08-11"


def test_docket_and_project_in_the_same_entry():
    ids = parse_docket_ids(["Docket No. FAA-2022-0992 Project Identifier MCAI-2022-00173-R"])
    assert ids.docket_id == "FAA-2022-0992"
    assert ids.project_identifier == "MCAI-2022-00173-R"


def test_non_ad_rule_yields_no_ad_number():
    """A part-61/91 rule matches the search term but is not an AD."""
    ids = parse_docket_ids(["Docket No.: FAA-2021-0419", "Amdt. Nos. 119-21, 21-108, 5-2, 91-374"])
    assert ids.ad_number is None
    assert ids.amendment is None  # part 39 only; 91-374 is not an AD amendment
    assert not ids.is_airworthiness_directive


def test_legacy_directorate_docket():
    assert parse_docket_ids(["Docket No. 2002-NM-352-AD"]).docket_id == "2002-NM-352-AD"


def test_sheet_docket_normalization():
    assert normalize_sheet_docket("FAA-2026-11814")[0] == ["FAA-2026-11814"]
    assert normalize_sheet_docket("FAA 2022-0460")[0] == ["FAA-2022-0460"]
    assert normalize_sheet_docket("FAA-2021-1078R1")[0] == ["FAA-2021-1078"]
    assert normalize_sheet_docket("FAA-2025-0199_S")[0] == ["FAA-2025-0199"]
    assert normalize_sheet_docket("FAA-2009-0555-W")[0] == ["FAA-2009-0555"]
    assert normalize_sheet_docket("2002-NM-352-AD")[0] == ["2002-NM-352-AD"]
    assert normalize_sheet_docket("FAA Rules 95-CE-35-AD")[0] == ["95-CE-35-AD"]
    assert normalize_sheet_docket("99-NE-46")[0] == ["99-NE-46"]


def test_sheet_cell_naming_two_dockets_keeps_both_in_order():
    dockets, raw = normalize_sheet_docket("2002-CE-05-AD, 2002-CE-57-AD")
    assert dockets == ["2002-CE-05-AD", "2002-CE-57-AD"]
    assert raw == "2002-CE-05-AD, 2002-CE-57-AD"
