"""OpenSky aircraft database loader: CSV rows -> contract `Aircraft` records.

Real values only. An empty source cell becomes None; nothing is inferred,
defaulted or generated. Run `python3 -m engine.ingest.fleet --demo-fleet`.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import shutil
import sys
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_URL = "https://opensky-network.org/datasets/metadata/aircraftDatabase.csv"
RAW_PATH = ROOT / "data" / "raw" / "fleet" / "aircraftDatabase.csv"
SOURCE_NAME = "opensky"

# contract Aircraft field <- OpenSky column
COLUMN_MAP: dict[str, str] = {
    "tail_number": "registration",
    "icao24": "icao24",
    "manufacturer": "manufacturername",
    "model": "model",
    "typecode": "typecode",
    "serial_number": "serialnumber",
    "operator": "operator",
    "owner": "owner",
    "built_year": "built",
    "engines": "engines",
}

_HTML_BREAK = "<br>"
# OpenSky writes this date where the build date is unknown; no aircraft was built in year 1.
BUILT_UNKNOWN_SENTINEL = "0001-01-01"


class MalformedBuilt(ValueError):
    """`built` cell is non-empty but not a parseable ISO date."""


def clean(value: str | None) -> str | None:
    """Empty / whitespace-only cell -> None, otherwise the stripped text."""
    if value is None:
        return None
    text = value.strip()
    return text or None


def clean_engines(value: str | None) -> str | None:
    """Strip the stray HTML line-break markup some source cells carry; nothing else."""
    text = clean(value)
    if text is None:
        return None
    return clean(text.replace(_HTML_BREAK, " ").replace("<br/>", " "))


def parse_built_year(value: str | None) -> int | None:
    """Year from an ISO 'YYYY-MM-DD' (or 'YYYY') cell. Blank -> None; malformed raises."""
    text = clean(value)
    if text is None or text == BUILT_UNKNOWN_SENTINEL:
        return None
    try:
        year = dt.date.fromisoformat(text).year if len(text) > 4 else int(text)
    except ValueError as exc:
        raise MalformedBuilt(f"unparseable built value {value!r}") from exc
    if not 1900 <= year <= dt.date.today().year:
        raise MalformedBuilt(f"implausible built year in {value!r}")
    return year


def map_row(row: dict[str, str], stats: Counter[str] | None = None) -> dict[str, object] | None:
    """Map one CSV row to an Aircraft record, or None when it has no registration (the key)."""
    tail = clean(row.get(COLUMN_MAP["tail_number"]))
    if tail is None:
        if stats is not None:
            stats["skipped_no_registration"] += 1
        return None
    record: dict[str, object] = {"tail_number": tail}
    for field, column in COLUMN_MAP.items():
        if field in ("tail_number", "built_year", "engines"):
            continue
        record[field] = clean(row.get(column))
    record["engines"] = clean_engines(row.get(COLUMN_MAP["engines"]))
    try:
        record["built_year"] = parse_built_year(row.get(COLUMN_MAP["built_year"]))
    except MalformedBuilt as exc:
        print(f"warning: {tail}: {exc}; built_year left null", file=sys.stderr)
        record["built_year"] = None
        if stats is not None:
            stats["malformed_built"] += 1
    record["source"] = SOURCE_NAME
    return record


def iter_aircraft(path: Path, stats: Counter[str] | None = None) -> Iterator[dict[str, object]]:
    """Stream mapped Aircraft records from the CSV; duplicate tail numbers keep the first."""
    seen: set[str] = set()
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            record = map_row(row, stats)
            if record is None:
                continue
            tail = str(record["tail_number"])
            if tail in seen:
                if stats is not None:
                    stats["skipped_duplicate_tail"] += 1
                continue
            seen.add(tail)
            yield record


def ensure_downloaded(path: Path = RAW_PATH, url: str = SOURCE_URL) -> Path:
    """Stream the database to `path` unless it already exists. Never re-downloads."""
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=60) as resp, part.open("wb") as out:
            shutil.copyfileobj(resp, out, length=1 << 20)
    except (urllib.error.URLError, OSError) as exc:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"download of {url} failed: {exc}") from exc
    part.replace(path)
    return path


def main(argv: list[str] | None = None) -> int:
    from engine.graph.aircraft_nodes import write_aircraft_nodes
    from engine.ingest.fleet_report import write_fleet_doc
    from engine.ingest.fleet_select import select_demo_fleet

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--demo-fleet", action="store_true", help="select the documented demo fleet")
    ap.add_argument("--csv", type=Path, default=RAW_PATH)
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "build" / "nodes.aircraft.jsonl")
    ap.add_argument("--doc", type=Path, default=ROOT / "docs" / "fleet.md")
    args = ap.parse_args(argv)
    if not args.demo_fleet:
        ap.error("only --demo-fleet is implemented")
    csv_path = ensure_downloaded(args.csv) if args.csv == RAW_PATH else args.csv
    result = select_demo_fleet(csv_path)
    write_aircraft_nodes(result.fleet, args.out)
    write_fleet_doc(result, args.doc)
    print(f"demo fleet: {len(result.fleet)} aircraft, {len(result.operators)} operators -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
