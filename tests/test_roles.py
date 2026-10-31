"""Heading text, not paragraph letter, decides paragraph_role.

The headings below are real: they were taken from the distinct heading texts of
a 120-document sample of the corpus.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contracts.contract import enum  # noqa: E402
from engine.ingest.roles import FALLBACK_ROLE, role_for_heading  # noqa: E402

CANONICAL = [
    ("Effective Date", "EFFECTIVE_DATE"),
    ("Affected ADs", "AFFECTED_ADS"),
    ("Affected AD", "AFFECTED_ADS"),
    ("Applicability", "APPLICABILITY"),
    ("Subject", "SUBJECT"),
    ("Unsafe Condition", "UNSAFE_CONDITION"),
    ("Reason", "UNSAFE_CONDITION"),
    ("Compliance", "COMPLIANCE"),
    ("Required Actions", "REQUIRED_ACTIONS"),
    ("Requirements", "REQUIRED_ACTIONS"),
    ("New Required Actions", "REQUIRED_ACTIONS"),
    ("Actions and Compliance", "REQUIRED_ACTIONS"),
    ("Exceptions to Service Information Specifications", "EXCEPTIONS"),
    ("Exceptions to EASA AD 2025-0208", "EXCEPTIONS"),
    ("Exception to CAAI AD ISR-I-97-2022-04-9", "EXCEPTIONS"),
    ("Retained Exceptions to EASA AD 2020-0116, With No Changes", "EXCEPTIONS"),
    ("Differences From the Required Service Information", "EXCEPTIONS"),
    ("Credit for Previous Actions", "CREDIT"),
    ("Alternative Methods of Compliance (AMOCs)", "AMOC"),
    ("Alternative Methods of Compliance", "AMOC"),
    ("Additional Information", "ADDITIONAL_INFO"),
    ("Related Information", "ADDITIONAL_INFO"),
    ("Material Incorporated by Reference", "IBR"),
    ("Incorporation by Reference", "IBR"),
]


@pytest.mark.parametrize(("heading", "role"), CANONICAL)
def test_canonical_headings(heading: str, role: str):
    assert role_for_heading(heading) == role


def test_label_prefix_and_whitespace_are_ignored():
    assert role_for_heading(" (c) Applicability") == "APPLICABILITY"
    assert role_for_heading("(b)  Affected ADs") == "AFFECTED_ADS"
    assert role_for_heading("Applicability:") == "APPLICABILITY"


def test_the_letter_does_not_decide_the_role():
    """(g) is "Required Actions" in one fixture and "Requirements" in the other,
    and a 2004 AD puts "Effective Date" at (g)."""
    assert role_for_heading("Required Actions") == role_for_heading("Requirements")
    assert role_for_heading("Effective Date") == "EFFECTIVE_DATE"


def test_amoc_wins_over_the_word_compliance():
    assert role_for_heading("Alternative Methods of Compliance (AMOCs)") == "AMOC"


def test_unmappable_headings_fall_back_rather_than_guess():
    for heading in (
        "Additional AD Provisions",
        "Other FAA AD Provisions",
        "No Reporting Requirement",
        "Definitions",
        "Special Flight Permits",
        "Windshield Assembly Replacement",
        "Figure 1 to Paragraph (j)-Alternative Actions",
        "",
    ):
        assert role_for_heading(heading) == FALLBACK_ROLE


def test_every_emitted_role_is_a_contract_value():
    allowed = set(enum("paragraph_role"))
    for heading, _ in CANONICAL:
        assert role_for_heading(heading) in allowed
    assert FALLBACK_ROLE in allowed
