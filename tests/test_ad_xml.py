"""Paragraph extraction and the character-offset invariant.

Both committed fixtures are parsed; no test here touches the network.

The offset round-trip is the load-bearing assertion of the whole ingest: every
citation is a character span into the revision's plain_text, so an offset that
is off by one silently corrupts every citation built on that revision.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.ingest.ad_xml import assert_offsets_round_trip, parse_ad_xml  # noqa: E402

BOEING = ROOT / "data" / "fixtures" / "ad_boeing_757_psu.xml"
AIRBUS = ROOT / "data" / "fixtures" / "ad_airbus_a330_easa_delegated.xml"

#: A 2004-era AD: the HD1 heading carries only the topic and the label opens the
#: paragraph text. Shape taken from Federal Register document 04-6499.
LEGACY_XML = b"""<RULE>
 <PREAMB>
  <DEPDOC>[Docket No. FAA-2003-16645; Amendment 39-13533; AD 2004-06-07]</DEPDOC>
  <SUBJECT>Airworthiness Directives; EMBRAER Airplanes</SUBJECT>
 </PREAMB>
 <SUPLINF>
  <HD SOURCE="HD1">Adoption of the Amendment</HD>
  <REGTEXT TITLE="14" PART="39">
   <AMDPAR>2. Section 39.13 is amended by adding the following new airworthiness directive:</AMDPAR>
   <EXTRACT>
    <FP SOURCE="FP-2"><E T="04">2004-06-07 Empresa Brasileira de Aeronautica S.A. (EMBRAER):</E>
     Amendment 39-13533. Docket 2003-NM-113-AD.</FP>
    <HD SOURCE="HD1">Applicability</HD>
    <P>(a) This AD applies to EMBRAER Model EMB-120 series airplanes.</P>
    <P>(1) For airplanes with wiring not previously inspected.</P>
    <HD SOURCE="HD1">Alternative Methods of Compliance</HD>
    <P>(b) In accordance with 14 CFR 39.19, the Manager is authorized to approve AMOCs.</P>
    <HD SOURCE="HD1">Incorporation by Reference</HD>
    <P>(c) The actions shall be done in accordance with EMBRAER Service Bulletin
     120-30-0030, Change 01, dated November 28, 2000.</P>
    <HD SOURCE="HD1">Effective Date</HD>
    <P>(d) This amendment becomes effective on April 29, 2004.</P>
   </EXTRACT>
  </REGTEXT>
 </SUPLINF>
</RULE>"""


@pytest.mark.parametrize("fixture", [BOEING, AIRBUS])
def test_offsets_round_trip_for_every_paragraph(fixture: Path):
    parsed = parse_ad_xml(fixture, fixture.stem)
    assert parsed.paragraphs
    for paragraph in parsed.paragraphs:
        assert (
            parsed.plain_text[paragraph.char_start : paragraph.char_end] == paragraph.text
        ), f"{paragraph.label} span does not round-trip"
    assert_offsets_round_trip(parsed)


@pytest.mark.parametrize("fixture", [BOEING, AIRBUS])
def test_spans_do_not_overlap_and_advance(fixture: Path):
    parsed = parse_ad_xml(fixture, fixture.stem)
    previous_end = -1
    for paragraph in parsed.paragraphs:
        assert paragraph.char_start > previous_end
        assert paragraph.char_end > paragraph.char_start
        previous_end = paragraph.char_end
    assert previous_end <= len(parsed.plain_text)


def test_boeing_fixture_labels_and_roles():
    parsed = parse_ad_xml(BOEING, "2026-21864")
    assert parsed.structure == "labelled_headings"
    labels = [p.label for p in parsed.paragraphs]
    assert labels == list("abcdefghijkl")
    roles = {p.label: p.role for p in parsed.paragraphs}
    assert roles["a"] == "EFFECTIVE_DATE"
    assert roles["c"] == "APPLICABILITY"
    assert roles["g"] == "REQUIRED_ACTIONS"
    assert roles["l"] == "IBR"
    assert parsed.ad_number_in_text == "2026-21-12"
    assert parsed.manufacturer_raw == "The Boeing Company"


def test_airbus_fixture_keeps_its_own_letters_and_headings():
    """The same role sits at a different letter, and (g) is "Requirements" here."""
    parsed = parse_ad_xml(AIRBUS, "2026-21861")
    roles = {p.label: p.role for p in parsed.paragraphs}
    headings = {p.label: p.heading for p in parsed.paragraphs}
    assert headings["g"] == "Requirements"
    assert roles["g"] == "REQUIRED_ACTIONS"
    assert headings["k"] == "Material Incorporated by Reference"
    assert roles["k"] == "IBR"
    assert roles["h"] == "EXCEPTIONS"  # "Exceptions to EASA AD 2025-0208"
    assert parsed.manufacturer_raw == "Airbus SAS"


def test_no_paragraph_is_dropped_even_when_the_heading_is_unmappable():
    parsed = parse_ad_xml(AIRBUS, "2026-21861")
    unmapped = [p for p in parsed.paragraphs if p.role == "OTHER"]
    assert [p.heading for p in unmapped] == ["Additional AD Provisions"]
    assert all(p.text for p in parsed.paragraphs)


def test_legacy_inline_label_structure():
    parsed = parse_ad_xml(LEGACY_XML, "04-6499")
    assert parsed.structure == "inline_labels"
    assert [p.label for p in parsed.paragraphs] == list("abcd")
    roles = {p.label: p.role for p in parsed.paragraphs}
    assert roles == {
        "a": "APPLICABILITY",
        "b": "AMOC",
        "c": "IBR",
        "d": "EFFECTIVE_DATE",
    }
    # the "(1)" sub-item stays inside its parent paragraph
    assert "(1) For airplanes with wiring not previously inspected." in parsed.paragraphs[0].text
    assert_offsets_round_trip(parsed)


def test_a_document_with_no_ad_structure_reports_it_instead_of_failing():
    parsed = parse_ad_xml(b"<RULE><PREAMB><SUBJECT>Not an AD</SUBJECT></PREAMB></RULE>", "x")
    assert parsed.structure == "none"
    assert parsed.paragraphs == []
