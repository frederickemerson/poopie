"""Table-driven joins between AD text and a fleet record.

An AD writes ``Model 757-200 and -300 series airplanes``; the fleet record says
``model: "757-232", typecode: "B752"``. Byte equality between those two strings
is meaningless, so model and manufacturer comparisons go through
``data/reference/aircraft_normalization.json`` via engine/graph/normalize.py.
That table is the authoritative join; this module adds no fuzzy matching.

Three outcomes, never two: True (the table proves a match), False (the table
proves a mismatch), None (the table does not cover this string, so the honest
answer is that we do not know).
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.graph import normalize  # noqa: E402


def key(text: str) -> str:
    """Casefold + whitespace collapse -- the only normalization the table uses."""
    return " ".join(text.split()).casefold()


def _series_key(text: str) -> str:
    k = key(text)
    return k[: -len(" series")] if k.endswith(" series") else k


@lru_cache(maxsize=1)
def _families() -> tuple[str, ...]:
    """Family names in the normalization table, longest first for prefix matching."""
    names = {info["family"] for info in normalize.table()["types"].values()}
    return tuple(sorted(names, key=len, reverse=True))


def family_of_ad_model(ad_model: str) -> str | None:
    """Family an AD model string belongs to, read off the table's family names.

    '737-800' -> '737', 'A330-941' -> 'A330'. Returns None when no family name in
    the table is a prefix of the string, which is the case for schemes the table
    does not describe ('ERJ 170-200 LR', 'BD-100-1A10').
    """
    text = _series_key(ad_model)
    for family in _families():
        fam = key(family)
        if text == fam or text.startswith(fam + "-") or text.startswith(fam + " "):
            return family
    return None


def family_of_typecode(typecode: str | None) -> str | None:
    info = normalize.type_info(typecode)
    return info["family"] if info else None


def model_matches(aircraft: dict, ad_model: str) -> tuple[bool | None, str]:
    """Does this aircraft's type match one AD model string? With a reason."""
    typecode = aircraft.get("typecode")
    raw_model = aircraft.get("model")

    typecodes = normalize.typecodes_for_ad_model(ad_model)
    if typecodes:
        if not typecode:
            return None, f"{ad_model!r} is typecode {typecodes}, and the record has no typecode"
        if typecode.strip().upper() in typecodes:
            return True, f"typecode {typecode} is {ad_model!r} in the normalization table"
        return False, f"typecode {typecode} is not {ad_model!r} (table: {typecodes})"

    ad_family = family_of_ad_model(ad_model)
    own_family = family_of_typecode(typecode)
    if ad_family and own_family and ad_family != own_family:
        return False, f"{typecode} is family {own_family}, {ad_model!r} is family {ad_family}"
    if raw_model and _series_key(raw_model) == _series_key(ad_model):
        return True, f"fleet model string {raw_model!r} is {ad_model!r}"
    if ad_family and own_family:
        return None, (
            f"{ad_model!r} is a variant of family {ad_family} that the normalization table "
            f"does not list; {typecode} ({raw_model!r}) is the same family, so it can be "
            f"neither confirmed nor excluded"
        )
    return None, f"the normalization table does not cover the AD model string {ad_model!r}"


def manufacturer_matches(aircraft: dict, ad_make: str) -> tuple[bool | None, str]:
    """Does this aircraft's manufacturer match an AD 'make' string?"""
    own = aircraft.get("manufacturer")
    verdict = normalize.manufacturer_matches_ad(own, ad_make)
    if verdict is True:
        return True, f"{own!r} and {ad_make!r} are the same manufacturer in the table"
    if verdict is False:
        return False, f"{own!r} and {ad_make!r} are different manufacturers in the table"
    if own and key(own) == key(ad_make):
        return True, f"manufacturer string {own!r} equals the AD make verbatim"
    if not own:
        return None, "the fleet record has no manufacturer"
    return None, (
        f"the normalization table does not map {own!r} or {ad_make!r}, so they can be "
        f"neither confirmed nor excluded"
    )
