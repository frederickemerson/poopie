"""Map an AD paragraph heading to the ``paragraph_role`` enum.

The paragraph letter is NOT the role: letters shift between ADs (the Boeing
fixture's (g) is "Required Actions", the Airbus fixture's (g) is "Requirements",
and a 2004 AD puts "Effective Date" at (g)). The heading text is the signal, so
the literal letter is kept verbatim in ``Paragraph.label`` and the heading is
classified here.

The rule set below was built from the 176 distinct heading texts found in a
120-document sample of the real corpus. It is deliberately conservative:
a heading that does not match a rule becomes OTHER rather than being guessed
into a role. OTHER is a legitimate role, not a dropped paragraph.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from contracts.contract import enum  # noqa: E402

ROLES = enum("paragraph_role")
FALLBACK_ROLE = "OTHER"

# (predicate on the normalized heading, role). First match wins, so the
# specific patterns must precede the general ones.
_RULES: list[tuple[re.Pattern[str], str]] = [
    # "Alternative Methods of Compliance (AMOCs)" must be tested before the
    # bare word "compliance", and "Exceptions to ..." before everything that
    # names a service document.
    (re.compile(r"alternative method|amoc"), "AMOC"),
    (re.compile(r"^(retained )?exceptions? to|^differences from"), "EXCEPTIONS"),
    (re.compile(r"credit for previous"), "CREDIT"),
    (re.compile(r"material incorporated by reference|^incorporation by reference"), "IBR"),
    (re.compile(r"effective date"), "EFFECTIVE_DATE"),
    (re.compile(r"^affected ads?$|^affected ad\b"), "AFFECTED_ADS"),
    (re.compile(r"^applicability"), "APPLICABILITY"),
    (re.compile(r"^subject$"), "SUBJECT"),
    (re.compile(r"^unsafe condition|^reason$"), "UNSAFE_CONDITION"),
    (re.compile(r"^compliance$|^compliance times?$"), "COMPLIANCE"),
    (re.compile(r"^(new |retained )?require(d|ments)\b|^actions and compliance"), "REQUIRED_ACTIONS"),
    (re.compile(r"^additional information$|^related information$"), "ADDITIONAL_INFO"),
]


def normalize_heading(heading: str) -> str:
    """Lowercase, collapse whitespace, strip the trailing colon and the label."""
    text = " ".join((heading or "").split())
    text = re.sub(r"^\(\s*[A-Za-z0-9]{1,3}\s*\)\s*", "", text)
    return text.strip().rstrip(":").strip().lower()


def role_for_heading(heading: str) -> str:
    """Return a ``paragraph_role`` enum value for this heading text."""
    text = normalize_heading(heading)
    if not text:
        return FALLBACK_ROLE
    for pattern, role in _RULES:
        if pattern.search(text):
            return role
    return FALLBACK_ROLE


def _self_check() -> None:
    """Every role this module can emit must exist in the contract."""
    emitted = {role for _, role in _RULES} | {FALLBACK_ROLE}
    unknown = emitted - set(ROLES)
    if unknown:
        raise ValueError(f"roles.py emits values absent from the contract: {sorted(unknown)}")


_self_check()
