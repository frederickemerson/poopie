"""Normalize a manufacturer name without inventing an alias table.

Neither source has a structured manufacturer field: the spreadsheet's ``Make``
column is hand-typed ("Boeing" and "The Boeing Company" both occur, 92 distinct
values over 431 rows) and the Federal Register gives only the AD's own citation
line and subject. So normalization is unavoidable here, and it is kept to
mechanical, reversible edits:

* drop a leading "The"
* drop parentheticals, which carry type-certificate history
  ("(Type Certificate Previously Held by ...)", "(AHD)")
* drop trailing legal-entity tokens (Company, Inc., GmbH, SAS, Ltd, ...)
* collapse whitespace and trailing punctuation

What it deliberately does NOT do is merge names that mean the same company
today: "Eurocopter France" and "Airbus Helicopters" stay distinct, because the
type certificate holder named in an AD is itself a fact about that AD. Merging
them would be a curated judgement, not a normalization, and the raw string is
preserved alongside every normalized value (see docs/ingest.md).
"""

from __future__ import annotations

import re

_PARENTHETICAL = re.compile(r"\s*\([^)]*\)")
_MULTI_VALUE = "|"

_LEGAL_SUFFIX_TOKENS = frozenset(
    {
        "company",
        "companies",
        "co",
        "inc",
        "incorporated",
        "ltd",
        "limited",
        "llc",
        "lp",
        "gmbh",
        "mbh",
        "sas",
        "sa",
        "spa",
        "nv",
        "bv",
        "kg",
        "ag",
        "oy",
        "ab",
        "plc",
        "corporation",
        "corp",
        "partnership",
        "a/s",
        "s.p.a",
        "s.a",
        "s.a.s",
        "n.v",
        "b.v",
        "&",
    }
)


def _normalize_one(raw: str) -> str:
    text = _PARENTHETICAL.sub("", raw or "")
    text = " ".join(text.replace(",", " ").split())
    if text.lower().startswith("the "):
        text = text[4:]
    tokens = text.split()
    while tokens and tokens[-1].lower().rstrip(".") in _LEGAL_SUFFIX_TOKENS:
        tokens.pop()
    return " ".join(tokens).strip(" .,;&")


def normalize_make(raw: str | None) -> str | None:
    """Canonical manufacturer name, or ``None`` when the input carries nothing."""
    if not raw or not raw.strip():
        return None
    parts = [p for p in (_normalize_one(p) for p in raw.split(_MULTI_VALUE)) if p]
    if not parts:
        return None
    deduped: list[str] = []
    for part in parts:
        if part not in deduped:
            deduped.append(part)
    return " | ".join(deduped)
