"""Generate web/lib/fleet.ts from the real OpenSky aircraft database.

Real records only. Fields absent in the source stay null (never invented) - that
absence is what drives the amber CANNOT_DETERMINE cells in the blast-radius grid.
"""
import csv, json, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/frederick/Documents/Projects/autsg")
SRC = ROOT / "data/raw/fleet/aircraftDatabase.csv"
OUT = ROOT / "web/lib/fleet.ts"

ALIAS = {
    "Delta Air Lines Inc": "Delta Air Lines", "Delta Air Lines": "Delta Air Lines",
    "American Airlines Inc": "American Airlines", "American Airlines": "American Airlines",
    "United Airlines Inc": "United Airlines", "United Airlines": "United Airlines",
    "Lufthansa": "Lufthansa", "Qatar Airways": "Qatar Airways",
    "Federal Express": "FedEx Express", "Allegiant Air": "Allegiant Air",
}
QUOTA = {
    "American Airlines": {"A319": 5, "A320": 9, "A321": 3, "B752": 2},
    "Delta Air Lines":   {"A339": 8, "A321": 4, "B752": 4, "A320": 1, "A319": 1},
    "United Airlines":   {"A319": 4, "A320": 4, "B752": 3, "B753": 2},
    "Qatar Airways":     {"A320": 5, "A333": 4, "A332": 2},
    "Lufthansa":         {"A320": 6, "A333": 2, "A321": 2, "A319": 1},
    "Allegiant Air":     {"A320": 6},
    "FedEx Express":     {"B752": 8},
}

def msn(a):
    s = a["serial_number"].lstrip("0")
    return (0, int(s)) if s.isdigit() else (1, 0)

def spread(items, n):
    """Pick n records spread evenly across the serial-number range, so the grid
    shows a genuine mix of in-range and out-of-range aircraft rather than a
    cluster that happens to sort first."""
    items = sorted(items, key=msn)
    if len(items) <= n:
        return items
    step = (len(items) - 1) / (n - 1) if n > 1 else 0
    return [items[round(i * step)] for i in range(n)]

pool = defaultdict(lambda: defaultdict(list))
with SRC.open(encoding="utf-8", errors="replace") as fh:
    for rec in csv.DictReader(fh):
        op = ALIAS.get((rec.get("operator") or "").strip())
        tc = (rec.get("typecode") or "").strip()
        if not op or op not in QUOTA or tc not in QUOTA[op]:
            continue
        tail = (rec.get("registration") or "").strip()
        serial = (rec.get("serialnumber") or "").strip()
        model = (rec.get("model") or "").strip()
        maker = (rec.get("manufacturername") or "").strip()
        if not (tail and serial and model and maker):
            continue
        built = (rec.get("built") or "").strip()[:4]
        pool[op][tc].append({
            "tail_number": tail,
            "icao24": rec["icao24"].strip(),
            "manufacturer": maker,
            "model": model,
            "typecode": tc,
            "serial_number": serial,
            "operator": op,
            "built_year": int(built) if built.isdigit() else None,
        })

fleet = []
for op, quota in QUOTA.items():
    for tc, n in quota.items():
        got = spread(pool[op][tc], n)
        if len(got) < n:
            print(f"warn: {op}/{tc} only {len(got)} of {n}", file=sys.stderr)
        fleet.extend(got)

seen, uniq = set(), []
for a in fleet:
    if a["tail_number"] in seen:
        continue
    seen.add(a["tail_number"])
    uniq.append(a)

ops = sorted({a["operator"] for a in uniq})
body = json.dumps(uniq, indent=2, ensure_ascii=False)
OUT.write_text(f'''// GENERATED from the OpenSky Network public aircraft database
// (https://opensky-network.org/datasets/metadata/aircraftDatabase.csv) by
// scripts/gen_fleet.py. Real registrations, real manufacturer serial numbers,
// real operators. Regenerate rather than hand-editing.
//
// PROVENANCE NOTE, surfaced in the UI: OpenSky carries no equipment, modification
// or supplemental-type-certificate data. Those fields are therefore absent, not
// unset-and-guessable, which is exactly why equipment-conditioned ADs resolve to
// {len(uniq)} cells of which some can only be CANNOT_DETERMINE.

import type {{ Source }} from "./contract";

export interface FleetAircraft {{
  readonly tail_number: string;
  readonly icao24: string;
  readonly manufacturer: string;
  readonly model: string;
  readonly typecode: string;
  readonly serial_number: string;
  readonly operator: string;
  readonly built_year: number | null;
  /** OpenSky holds no equipment list. Always null; never inferred. */
  readonly equipment: readonly string[] | null;
  /** OpenSky holds no modification or STC record. Always null; never inferred. */
  readonly modification: readonly string[] | null;
}}

export const FLEET_SOURCE: Source = "opensky";

export const FLEET_PROVENANCE = {{
  dataset: "OpenSky Network public aircraft database",
  url: "https://opensky-network.org/datasets/metadata/aircraftDatabase.csv",
  retrieved: "2026-10-31",
  aircraft: {len(uniq)},
  operators: {len(ops)},
  absent_fields: ["equipment", "modification", "part_number"] as const,
  caveat:
    "Registration, manufacturer serial number, model and operator are as published by OpenSky. " +
    "The dataset carries no equipment, modification or STC record, so every equipment-conditioned " +
    "applicability rule resolves to CANNOT_DETERMINE rather than a guess.",
}} as const;

const RAW: readonly Omit<FleetAircraft, "equipment" | "modification">[] = {body} as const;

export const FLEET: readonly FleetAircraft[] = RAW.map((a) => ({{
  ...a,
  equipment: null,
  modification: null,
}}));

export const FLEET_OPERATORS: readonly string[] = {json.dumps(ops)};

export function aircraftByTail(tail: string): FleetAircraft | undefined {{
  return FLEET.find((a) => a.tail_number === tail);
}}
''', encoding="utf-8")
print(f"wrote {OUT} - {len(uniq)} aircraft, {len(ops)} operators")
