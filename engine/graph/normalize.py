"""Manufacturer / model normalization between OpenSky strings and AD text forms.

Series-level normalization is driven entirely by
data/reference/aircraft_normalization.json. No fuzzy or heuristic matching: a
string is either listed in the table or it is unmapped (None). Unmapped is an
honest answer and is counted in coverage reports.

Variant-level strings are deliberately NOT in that table -- its own note says
so: "ad_models are type-level series names (e.g. 737-800) as ICAO type
designators cover several variants (737-823, 737-824...); variant-level
matching uses Aircraft.model." variant_model_index() is that second half: it
reads the variant designations off the built fleet, which is recorded data from
the aircraft register, not a list anyone maintains by hand.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from engine.paths import BUILD

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


@lru_cache(maxsize=1)
def variant_model_index() -> dict[str, tuple[str, str | None]]:
    """Variant designation -> (typecode, canonical manufacturer), from the fleet.

    The register records both the variant a tail number actually is ("A320-214")
    and its ICAO typecode ("A320"), so this mapping is read, never inferred. An
    engineer asks about the aircraft they operate, which means the variant; the
    AD names the series. Without this half, "my A330-941" resolved to no type at
    all -- 423 of the 478 aircraft in the built fleet carry a variant string the
    series table does not list, so the graph filter silently stopped narrowing
    for 88% of the fleet.

    Returns {} when the fleet has not been built. A variant whose typecode is
    absent from the series table is skipped rather than invented, and a variant
    that two typecodes disagree about is dropped from both: the register is
    authoritative, but it is not guaranteed self-consistent, and a model string
    that could mean two types must narrow to neither.
    """
    path = BUILD / "nodes.aircraft.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}

    known = set(table()["types"])
    seen: dict[str, set[str]] = {}
    manufacturers: dict[str, str | None] = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            node = json.loads(line)
        except json.JSONDecodeError:
            continue
        if node.get("_type") != "Aircraft":
            continue
        model = str(node.get("model") or "").strip()
        typecode = str(node.get("typecode") or "").strip()
        if not model or typecode not in known:
            continue
        key = _model_key(model)
        seen.setdefault(key, set()).add(typecode)
        manufacturers.setdefault(key, table()["types"][typecode].get("manufacturer"))

    return {
        key: (next(iter(codes)), manufacturers.get(key))
        for key, codes in seen.items()
        if len(codes) == 1
    }


def manufacturer_conflicts_with_type(manufacturer: str | None, typecode: str | None) -> bool:
    """True when a mapped manufacturer contradicts the typecode's manufacturer."""
    canonical, info = normalize_manufacturer(manufacturer), type_info(typecode)
    return bool(canonical and info and canonical != info["manufacturer"])
