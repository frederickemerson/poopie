"""Read the cost ledger and print what was actually spent.

Every cost figure quoted in the README or in any report must come from here,
and the command that produced it must be printable next to it. A cost claimed
without a command that reproduces it is the same defect as a threshold claimed
without a sweep.

    python3 -m engine.llm.report

The ledger is append-only and written by engine.llm.ledger on every call,
including cache hits (which record zero). Nothing here estimates anything: a
label absent from the ledger has no cost to report, and is reported as absent.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.paths import BUILD  # noqa: E402

LEDGER = BUILD / "cost_ledger.jsonl"

#: Labels that make up bulk corpus extraction, as opposed to query-time calls.
EXTRACTION_LABELS = {
    "extract_rules",
    "extract_rules_retry",
    "extract_actions",
}


def read_ledger(path: Path = LEDGER) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def summarise(rows: list[dict[str, Any]], *, paragraphs: int | None = None) -> dict[str, Any]:
    calls: Counter[str] = Counter()
    usd: Counter[str] = Counter()
    cached: Counter[str] = Counter()
    for row in rows:
        label = str(row.get("label") or row.get("model") or "unlabelled")
        calls[label] += 1
        usd[label] += float(row.get("cost_usd") or 0.0)
        if row.get("cached_hit"):
            cached[label] += 1

    extraction_usd = sum(usd[label] for label in EXTRACTION_LABELS)
    extraction_calls = sum(calls[label] for label in EXTRACTION_LABELS)
    out: dict[str, Any] = {
        "ledger": str(LEDGER),
        "entries": len(rows),
        "total_usd": round(sum(usd.values()), 6),
        "by_label": {
            label: {
                "calls": calls[label],
                "cached_hits": cached[label],
                "usd": round(usd[label], 6),
            }
            for label in sorted(calls, key=lambda k: -usd[k])
        },
        "extraction": {
            "labels": sorted(EXTRACTION_LABELS),
            "calls": extraction_calls,
            "usd": round(extraction_usd, 6),
        },
    }
    if paragraphs:
        out["extraction"]["paragraphs_in_corpus"] = paragraphs
        out["extraction"]["usd_per_paragraph"] = round(extraction_usd / paragraphs, 8)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    rows = read_ledger()
    if not rows:
        print(f"no ledger at {LEDGER}; nothing has been spent, or nothing was recorded")
        return 0

    paragraphs_file = BUILD / "paragraphs.jsonl"
    paragraphs = (
        sum(1 for line in paragraphs_file.read_text(encoding="utf-8").splitlines() if line.strip())
        if paragraphs_file.exists()
        else None
    )
    report = summarise(rows, paragraphs=paragraphs)

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"ledger: {report['ledger']}")
    print(f"entries: {report['entries']}")
    print(f"total: ${report['total_usd']:.6f}")
    print()
    print(f"{'label':28} {'calls':>6} {'cached':>7} {'usd':>11}")
    for label, row in report["by_label"].items():
        print(f"{label:28} {row['calls']:>6} {row['cached_hits']:>7} {row['usd']:>11.6f}")
    extraction = report["extraction"]
    print()
    print(
        f"bulk extraction: {extraction['calls']} calls, ${extraction['usd']:.6f}"
    )
    if "usd_per_paragraph" in extraction:
        print(
            f"  over {extraction['paragraphs_in_corpus']} paragraphs in the built corpus: "
            f"${extraction['usd_per_paragraph']:.8f} per paragraph"
        )
        print(
            "  (an average over the corpus, not a per-call price: not every "
            "paragraph needs a rules pass)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
