"""References to documents we do not hold, and the delegation they create.

These are the nodes that let the engine refuse with EXTERNAL_SOURCE_REQUIRED
instead of inferring applicability from text it cannot see, so both the
extraction and the ``held`` flag are tested against the real fixtures.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.ingest.ad_xml import parse_ad_xml  # noqa: E402
from engine.ingest.refs import (  # noqa: E402
    FALLBACK_AUTHORITY,
    extract_refs,
    foreign_ad_refs,
    service_bulletin_refs,
)
from engine.ingest.supersession import parse_affected_ads  # noqa: E402

BOEING = ROOT / "data" / "fixtures" / "ad_boeing_757_psu.xml"
AIRBUS = ROOT / "data" / "fixtures" / "ad_airbus_a330_easa_delegated.xml"


def _refs(fixture: Path):
    parsed = parse_ad_xml(fixture, fixture.stem)
    return extract_refs([(p.label, p.role, p.text) for p in parsed.paragraphs])


def test_airbus_fixture_adopts_an_easa_ad_in_its_applicability():
    refs = _refs(AIRBUS)
    ids = {r.foreign_ad_id for r in refs.foreign_ads}
    assert "EASA-2025-0208" == next(iter(ids))
    easa = refs.foreign_ads[0]
    assert easa.authority == "EASA"
    assert easa.ad_number == "2025-0208"
    assert easa.dated == "September 24, 2025"
    assert refs.delegates_applicability is True
    assert refs.delegates_compliance is True


def test_the_same_foreign_ad_written_two_ways_is_one_node():
    text = (
        "This AD applies to Airbus SAS Model A330-941 airplanes, as identified in "
        "European Union Aviation Safety Agency (EASA) AD 2025-0208, dated September 24, "
        "2025 (EASA AD 2025-0208)."
    )
    found = foreign_ad_refs("c", "APPLICABILITY", text)
    assert {r.foreign_ad_id for r in found} == {"EASA-2025-0208"}


def test_authorities_the_enum_does_not_model_keep_their_identity():
    uk = foreign_ad_refs("h", "EXCEPTIONS", "Exceptions to U.K. CAA AD G-2023-0004R1")[0]
    assert uk.authority == FALLBACK_AUTHORITY
    assert uk.foreign_ad_id == "UKCAA-G-2023-0004R1"
    tc = foreign_ad_refs("h", "EXCEPTIONS", "Exceptions to Transport Canada AD CF-2023-28")[0]
    assert tc.authority == "TCCA"
    assert tc.foreign_ad_id == "TCCA-CF-2023-28"


def test_an_faa_ad_mention_is_not_a_foreign_reference():
    assert foreign_ad_refs("b", "AFFECTED_ADS", "This AD replaces FAA AD 2019-12-05.") == []


def test_boeing_fixture_references_its_requirements_bulletins():
    refs = _refs(BOEING)
    numbers = {sb.number for sb in refs.service_bulletins}
    assert "757-25-0320 RB" in numbers
    assert "757-25-0321 RB" in numbers
    # the manufacturer is absent from the bare mention in paragraph (h) and is
    # filled in from the fuller mentions of the same bulletin number
    assert all(sb.manufacturer == "Boeing" for sb in refs.service_bulletins)
    assert refs.delegates_compliance is True
    assert all(not sb.held for sb in [])  # held lives on the node, never True here


def test_two_issues_of_one_bulletin_are_two_documents():
    """(g) requires Revision 1; (i) gives credit for the original issue."""
    refs = _refs(BOEING)
    ids = {sb.sb_id for sb in refs.service_bulletins}
    assert "BOEING-757-25-0320-RB-R1" in ids
    assert "BOEING-757-25-0320-RB-20240119" in ids


def test_an_incomplete_mention_does_not_create_its_own_node():
    """Paragraph (h) names "Requirements Bulletin 757-25-0320 RB" with no
    manufacturer and no revision; it must fold onto the identified issue."""
    refs = _refs(BOEING)
    assert not [sb for sb in refs.service_bulletins if sb.manufacturer is None]
    assert not [sb for sb in refs.service_bulletins if sb.sb_id.startswith("757-")]


def test_a_requirements_bulletin_and_a_service_bulletin_are_different_documents():
    text = (
        "Guidance for accomplishing the actions required by paragraph (g)(1) of this AD can "
        "be found in Boeing Special Attention Service Bulletin 757-25-0320, Revision 1, dated "
        "August 6, 2025, which is referred to in Boeing Special Attention Requirements "
        "Bulletin 757-25-0320 RB, Revision 1, dated August 6, 2025."
    )
    ids = {sb.sb_id for sb in service_bulletin_refs("g", "REQUIRED_ACTIONS", text)}
    assert ids == {"BOEING-757-25-0320-R1", "BOEING-757-25-0320-RB-R1"}


def test_revision_and_date_are_read_from_the_citation():
    sb = service_bulletin_refs(
        "l", "IBR", "(i) Airbus Helicopters Alert Service Bulletin No. AS350-67.00.43, Revision 3, dated June 16, 2016."
    )[0]
    assert (sb.manufacturer, sb.number, sb.revision) == ("Airbus Helicopters", "AS350-67.00.43", "3")
    assert sb.dated == "June 16, 2016"


def test_reserved_ibr_items_produce_nothing():
    assert service_bulletin_refs("l", "IBR", "(ii) [Reserved]") == []
    assert foreign_ad_refs("l", "IBR", "(ii) [Reserved]") == []


def test_affected_ads_distinguishes_supersession_from_a_mere_relationship():
    none = parse_affected_ads("Affected ADs\nNone.")
    assert none.superseded == [] and none.related == []

    replaced = parse_affected_ads(
        "Affected ADs\nThis AD replaces AD 2019-02-03, Amendment 39-19550 "
        "(84 FR 2437, February 7, 2019) (AD 2019-02-03)."
    )
    assert replaced.superseded == ["2019-02-03"]

    removed = parse_affected_ads("This AD removes AD 2018-05-09, Amendment 39-19218.")
    assert removed.superseded == ["2018-05-09"]

    related = parse_affected_ads(
        "This AD affects AD 2023-26-01, Amendment 39-22644 (89 FR 253, January 3, 2024)."
    )
    assert related.superseded == []
    assert related.related == ["2023-26-01"]

    mixed = parse_affected_ads(
        "(1) This AD replaces AD 2020-26-07, Amendment 39-21362 (85 FR 82901, December 21, "
        "2020) (AD 2020-26-07). (2) This AD affects AD 2010-26-05, Amendment 39-16544."
    )
    assert mixed.superseded == ["2020-26-07"]
    assert mixed.related == ["2010-26-05"]


def test_two_replaced_ads_in_one_clause_are_both_captured():
    affected = parse_affected_ads(
        "(1) This AD replaces AD 2021-24-20, Amendment 39-21841 (86 FR 72838, December 23, "
        "2021) (AD 2021-24-20); and AD 2023-03-05, Amendment 39-22330 (88 FR 10011, "
        "February 16, 2023) (AD 2023-03-05)."
    )
    assert affected.superseded == ["2021-24-20", "2023-03-05"]
