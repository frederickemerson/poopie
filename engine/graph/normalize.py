"""Manufacturer / model normalization between OpenSky strings and AD text forms.

Driven entirely by data/reference/aircraft_normalization.json. No fuzzy or
heuristic matching: a string is either listed in the table or it is unmapped
(None). Unmapped is an honest answer and is counted in coverage reports.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

TABLE_PATH = Path(__file__).resolve().parents[2] / "data" / "reference" / "aircraft_normalization.json"


def _key(text: str) -> str:
    return " ".join(text.split()).casefold()


@lru_cache(maxsize=1)
def table() -> dict[str, Any]:
    try:
        with TABLE_PATH.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot load normalization table {TABLE_PATH}: {exc}") from exc


@lru_cache(maxsize=1)
def _alias_index() -> dict[str, str]:
    """casefolded alias or AD form -> canonical manufacturer."""
    index: dict[str, str] = {}
    for canonical, spec in table()["manufacturers"].items():
        for alias in [canonical, *spec["ad_forms"], *spec["opensky_aliases"]]:
            k = _key(alias)
            if index.setdefault(k, canonical) != canonical:
                raise ValueError(f"alias {alias!r} maps to two manufacturers")
    return index


def normalize_manufacturer(raw: str | None) -> str | None:
    """Canonical manufacturer for an OpenSky name or an AD 'make'; None if unlisted."""
    if not raw or not raw.strip():
        return None
    return _alias_index().get(_key(raw))


def ad_manufacturer_forms(canonical: str) -> list[str]:
    """Forms of this manufacturer that AD applicability text uses."""
    return list(table()["manufacturers"][canonical]["ad_forms"])


def type_info(typecode: str | None) -> dict[str, Any] | None:
    """Table row for an ICAO type designator (manufacturer, family, ad_models)."""
    if not typecode:
        return None
    return table()["types"].get(typecode.strip().upper())


def known_typecodes() -> frozenset[str]:
    return frozenset(table()["types"])


def _model_key(text: str) -> str:
    k = _key(text)
    return k[: -len(" series")] if k.endswith(" series") else k


def typecodes_for_ad_model(ad_model: str) -> list[str]:
    """ICAO typecodes whose series name equals an AD model string ('737-800' -> ['B738'])."""
    want = _model_key(ad_model)
    return sorted(c for c, info in table()["types"].items() if want in {_model_key(m) for m in info["ad_models"]})


def manufacturer_matches_ad(aircraft_manufacturer: str | None, ad_make: str | None) -> bool | None:
    """True/False when both sides are mapped; None (unknown) when either is not."""
    a, b = normalize_manufacturer(aircraft_manufacturer), normalize_manufacturer(ad_make)
    if a is None or b is None:
        return None
    return a == b


def manufacturer_conflicts_with_type(manufacturer: str | None, typecode: str | None) -> bool:
    """True when a mapped manufacturer contradicts the typecode's manufacturer."""
    canonical, info = normalize_manufacturer(manufacturer), type_info(typecode)
    return bool(canonical and info and canonical != info["manufacturer"])
