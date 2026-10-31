"""The fast entity pass: pure regex and table lookup, no model, no I/O.

This runs first and alone is often the whole answer -- "what does AD 2026-22-02
require?" needs no semantic search, it needs the paragraphs of one revision.
Because it never calls out, it is the fallback when query planning is slow or
fails, which is why it must stay independent of everything downstream.

Two design rules, both from the project's engineering principles:

* Where a structured authority exists, it decides. Tail numbers follow the
  14 CFR 47.15 N-number grammar, not ``N\\w+``. Typecodes and model strings come
  from ``data/reference/aircraft_normalization.json``, not from guessing at
  digit patterns. AD numbers are confirmed against the set of AD numbers the
  corpus actually holds.
* An ambiguous token is classified by evidence, never by preference. A bare
  ``2026-21-13`` is shaped like both an AD number and an ISO date; it is called
  an AD number only when an ``AD`` token precedes it or the corpus holds it.
  Otherwise it is reported as ambiguous, and the caller can see why.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.graph.normalize import _model_key, table, variant_model_index  # noqa: E402

#: Modern FAA docket, the format contracts/contract.json pins for Docket.key.
_DOCKET = re.compile(r"\bFAA[- ]?(\d{4}-\d{3,5})\b", re.IGNORECASE)
#: Part-39 amendment, e.g. 39-23504.
_AMENDMENT = re.compile(r"\b(39-\d{4,6})\b")
#: AD number with an explicit token. Both separators occur in real prose.
_AD_TOKEN = re.compile(r"\bAD[\s-]*(\d{2,4}-\d{2}-\d{2})(R\d+)?\b", re.IGNORECASE)
#: AD-number-shaped token with no qualifier: resolved by corpus lookup.
_AD_SHAPED = re.compile(r"\b(\d{4}-\d{2}-\d{2})(R\d+)?\b")
#: Foreign AD number, e.g. EASA AD 2025-0208, ANAC AD 2024-04-02R01.
_FOREIGN_AD = re.compile(
    r"\b(EASA|TCCA|ANAC|CAAC|CAAI|Transport Canada)\s+AD\s+([A-Z0-9][A-Z0-9./-]*)",
    re.IGNORECASE,
)
#: N-number per 14 CFR 47.15: 1-5 digits, or 1-4 digits + 1 letter, or 1-3
#: digits + 2 letters; no leading zero; I and O are not used.
_TAIL = re.compile(
    r"\bN([1-9]\d{0,4}|[1-9]\d{0,3}[A-HJ-NP-Z]|[1-9]\d{0,2}[A-HJ-NP-Z]{2})\b"
)
#: A serial needs a cue token. A bare number is not a serial, ever.
_SERIAL = re.compile(
    r"\b(?:MSN|S/?N|serial(?:\s+number)?|line\s+number|variable\s+number)"
    r"[\s.:#]*([A-Z]?\d{1,6}[A-Z]?)\b",
    re.IGNORECASE,
)
#: ATA chapter, in both forms the corpus uses ("ATA 27", "ATA ... Code 27").
_ATA = re.compile(
    r"\bATA\b(?:[^.\d]{0,40}?)(?:chapter|code)?\s*(\d{2})\b", re.IGNORECASE
)
#: Model strings as ADs write them: a family number with a dash suffix.
_MODEL_SHAPED = re.compile(r"\b([A-Z]{0,3}\d{2,4}(?:-\d{1,4}[A-Z]{0,2})+)\b")


@dataclass
class Entities:
    """Everything the fast pass could name, plus what it could not resolve.

    ``ambiguous`` is first-class: a token that is shaped like an identifier but
    matches nothing authoritative is surfaced, not silently dropped, because it
    is usually the reason a query will end in a refusal.
    """

    ad_numbers: list[str] = field(default_factory=list)
    docket_ids: list[str] = field(default_factory=list)
    amendments: list[str] = field(default_factory=list)
    tail_numbers: list[str] = field(default_factory=list)
    serial_numbers: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    typecodes: list[str] = field(default_factory=list)
    manufacturers: list[str] = field(default_factory=list)
    ata_chapters: list[str] = field(default_factory=list)
    foreign_ads: list[str] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)

    def as_payload(self) -> dict[str, list[str]]:
        """The ``entities`` SSE payload: only the kinds that actually matched."""
        return {k: v for k, v in self.__dict__.items() if v}

    @property
    def is_empty(self) -> bool:
        return not any(self.__dict__.values())

    @property
    def has_identifier(self) -> bool:
        """True when the pass found something that pins a specific document."""
        return bool(self.ad_numbers or self.docket_ids or self.amendments)


@lru_cache(maxsize=1)
def _model_index() -> dict[str, tuple[tuple[str, ...], str]]:
    """Casefolded model/manufacturer string -> (typecodes, manufacturer).

    Built once from two recorded sources, never from a guess: the normalization
    table supplies the series names an AD uses ("737-800"), and the built fleet
    supplies the variant designations an operator uses ("A320-214"), which the
    table deliberately omits and points at Aircraft.model for. A string absent
    from both is not a model as far as this engine is concerned.

    The typecodes are a tuple because a designation can legitimately name more
    than one ICAO type: "ERJ 170-200" is both E75L and E75S, the long- and
    short-wing Embraer 175. The graph filter unions what it is handed, so
    carrying both widens the candidate set, which is the honest reading -- an
    AD on either wing is a candidate. Keeping whichever was iterated first
    answered for half the type and said nothing about the other half.

    The series table is consulted first, so it owns the manufacturer for any
    string both sources name: it is the vocabulary the documents are in.
    """
    index: dict[str, tuple[tuple[str, ...], str]] = {}

    def add(key: str, typecode: str | None, manufacturer: str) -> None:
        held = index.get(key)
        if held is None:
            index[key] = ((typecode,) if typecode else (), manufacturer)
            return
        codes, first_manufacturer = held
        if typecode and typecode not in codes:
            index[key] = ((*codes, typecode), first_manufacturer)

    data = table()
    for typecode, spec in data["types"].items():
        add(_model_key(typecode), typecode, spec["manufacturer"])
    for typecode, spec in data["types"].items():
        for model in spec["ad_models"]:
            add(_model_key(model), typecode, spec["manufacturer"])
    for variant, (typecode, manufacturer) in variant_model_index().items():
        if manufacturer:
            add(variant, typecode, manufacturer)
    for canonical, spec in data["manufacturers"].items():
        for alias in [canonical, *spec["ad_forms"], *spec["opensky_aliases"]]:
            add(_model_key(alias), None, canonical)
    return index


def _dedup(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def extract_entities(
    query: str, *, known_ad_numbers: frozenset[str] | None = None
) -> Entities:
    """Name every identifier in a query. Pure function, no I/O, no model.

    ``known_ad_numbers`` is the corpus's AD-number set; it is what resolves a
    bare ``2026-21-13`` from an ISO date. Without it, only AD numbers carrying
    an explicit ``AD`` token are claimed, and the rest go to ``ambiguous``.
    """
    ents = Entities()
    known = known_ad_numbers or frozenset()
    # Spans an unambiguous pattern has already claimed. A later, looser pattern
    # never re-reads them, so a docket number cannot also be reported as a
    # model and a foreign AD number cannot be reported as ambiguous.
    consumed: list[tuple[int, int]] = []

    def overlaps(span: tuple[int, int]) -> bool:
        return any(span[0] < b and a < span[1] for a, b in consumed)

    for match in _FOREIGN_AD.finditer(query):
        ents.foreign_ads.append(
            f"{match.group(1).upper()} AD {match.group(2).rstrip('.,;')}"
        )
        consumed.append(match.span())
    for match in _DOCKET.finditer(query):
        ents.docket_ids.append(f"FAA-{match.group(1)}")
        consumed.append(match.span())
    for match in _AMENDMENT.finditer(query):
        ents.amendments.append(match.group(1))
        consumed.append(match.span())
    for match in _TAIL.finditer(query):
        ents.tail_numbers.append(f"N{match.group(1).upper()}")
        consumed.append(match.span())
    for match in _SERIAL.finditer(query):
        ents.serial_numbers.append(match.group(1).upper())
        consumed.append(match.span())
    for match in _ATA.finditer(query):
        ents.ata_chapters.append(match.group(1))

    claimed: set[str] = set()
    for match in _AD_TOKEN.finditer(query):
        if overlaps(match.span()):
            continue
        number = match.group(1) + (match.group(2) or "")
        ents.ad_numbers.append(number)
        claimed.add(number)
        consumed.append(match.span())
    for match in _AD_SHAPED.finditer(query):
        if overlaps(match.span()):
            continue
        number = match.group(1) + (match.group(2) or "")
        if number in known:
            ents.ad_numbers.append(number)
        else:
            ents.ambiguous.append(number)
        consumed.append(match.span())

    index = _model_index()
    lowered = query.casefold()
    for alias, (typecodes, manufacturer) in index.items():
        # Word-boundary containment, so "737" does not match inside "1737".
        if alias in lowered and re.search(
            rf"(?<![\w-]){re.escape(alias)}(?![\w-])", lowered
        ):
            if not typecodes:
                ents.manufacturers.append(manufacturer)
                continue
            ents.models.append(alias)
            ents.typecodes.extend(typecodes)
            ents.manufacturers.append(manufacturer)

    known_models = {m.casefold() for m in ents.models}
    for match in _MODEL_SHAPED.finditer(query):
        shaped = match.group(1)
        if overlaps(match.span()) or shaped.casefold() in known_models:
            continue
        ents.ambiguous.append(shaped)

    for name in (
        "ad_numbers",
        "docket_ids",
        "amendments",
        "tail_numbers",
        "serial_numbers",
        "models",
        "typecodes",
        "manufacturers",
        "ata_chapters",
        "foreign_ads",
        "ambiguous",
    ):
        setattr(ents, name, _dedup(getattr(ents, name)))
    return ents
