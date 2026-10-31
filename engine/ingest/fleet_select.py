"""Deterministic demo-fleet selection from the OpenSky database.

Every filter below is a stated, countable rule; the doc generator prints each
one with its count. There is no randomness and no hand-picking: within an
operator, aircraft are ordered by SHA-1 of the tail number (stable, unrelated
to any attribute) and the first MAX_PER_OPERATOR are taken.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from engine.graph.normalize import known_typecodes, manufacturer_conflicts_with_type
from engine.ingest.fleet import iter_aircraft

# ICAO 24-bit address block allocated to the United States (structured signal, not a tail-number guess).
US_ICAO24_FIRST, US_ICAO24_LAST = "a00000", "adf7c7"
MIN_PER_OPERATOR = 6
MAX_PER_OPERATOR = 20
MAX_FLEET = 600

# Aircraft fields that map onto contract rule_fields present in this source.
RULE_FIELD_SOURCE = {
    "manufacturer": "manufacturer", "model": "model", "typecode": "typecode",
    "serial_number": "serial_number", "engine": "engines", "operator": "operator",
    "built_year": "built_year",
}


@dataclass
class SelectionResult:
    fleet: list[dict[str, object]]
    operators: Counter[str]
    funnel: list[tuple[str, int]]
    row_stats: Counter[str]
    population: list[dict[str, object]]  # all rows with a table typecode, any country
    pool: list[dict[str, object]]        # eligible before per-operator caps
    params: dict[str, object] = field(default_factory=dict)


def _in_us_block(icao24: object) -> bool:
    return isinstance(icao24, str) and US_ICAO24_FIRST <= icao24.lower() <= US_ICAO24_LAST


def _tail_hash(record: dict[str, object]) -> str:
    return hashlib.sha1(str(record["tail_number"]).encode("utf-8")).hexdigest()


def select_demo_fleet(
    csv_path: Path,
    min_per_operator: int = MIN_PER_OPERATOR,
    max_per_operator: int = MAX_PER_OPERATOR,
    max_fleet: int = MAX_FLEET,
) -> SelectionResult:
    row_stats: Counter[str] = Counter()
    types = known_typecodes()
    funnel: Counter[str] = Counter()
    population: list[dict[str, object]] = []
    pool: list[dict[str, object]] = []
    for rec in iter_aircraft(csv_path, row_stats):
        funnel["1 rows with a registration"] += 1
        if rec["typecode"] not in types:
            continue
        funnel["2 typecode in normalization table (transport types)"] += 1
        population.append(rec)
        if not _in_us_block(rec["icao24"]):
            continue
        funnel["3 icao24 in US allocation block"] += 1
        if rec["serial_number"] is None:
            continue
        funnel["4 has serial_number"] += 1
        if rec["operator"] is None:
            continue
        funnel["5 has operator"] += 1
        if manufacturer_conflicts_with_type(rec["manufacturer"], rec["typecode"]):  # type: ignore[arg-type]
            funnel["excluded: manufacturer contradicts typecode"] += 1
            continue
        funnel["6 no manufacturer/typecode contradiction (= eligible pool)"] += 1
        pool.append(rec)

    by_operator: dict[str, list[dict[str, object]]] = defaultdict(list)
    for rec in pool:
        by_operator[str(rec["operator"])].append(rec)
    ranked = sorted(by_operator.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    fleet: list[dict[str, object]] = []
    for operator, recs in ranked:
        if len(recs) < min_per_operator:
            break
        chosen = sorted(recs, key=_tail_hash)[:max_per_operator]
        if len(fleet) + len(chosen) > max_fleet:
            continue
        fleet.extend(chosen)
    fleet.sort(key=lambda r: (str(r["operator"]), _tail_hash(r)))
    operators = Counter(str(r["operator"]) for r in fleet)
    return SelectionResult(
        fleet=fleet, operators=operators, funnel=list(funnel.items()), row_stats=row_stats,
        population=population, pool=pool,
        params={"MIN_PER_OPERATOR": min_per_operator, "MAX_PER_OPERATOR": max_per_operator,
                "MAX_FLEET": max_fleet, "US_ICAO24": f"{US_ICAO24_FIRST}-{US_ICAO24_LAST}"},
    )
