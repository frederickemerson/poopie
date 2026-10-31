"""CLI: extract Rules and Actions from built paragraphs.

    python3 -m engine.rules.extract_cli                 # live, Haiku + disk cache
    python3 -m engine.rules.extract_cli --offline       # no API: everything unparsed
    python3 -m engine.rules.extract_cli --limit 40      # smoke run

Writes data/build/{rules,actions,delegations,external_nodes}.jsonl and prints a
report. Extraction is cached by content hash in engine.llm.client, so re-running
over unchanged paragraphs costs nothing.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

from engine.llm.client import LLMClient, have_api_key
from engine.llm.ledger import CostLedger
from engine.paths import BUILD, PARAGRAPHS_JSONL
from engine.rules.extract import extract, partition


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise SystemExit(
            f"{path} does not exist. Build it first with: python3 -m engine.ingest.build"
        )
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--offline", action="store_true", help="no API calls; mark everything unparsed")
    ap.add_argument("--limit", type=int, default=None, help="cap paragraphs, for smoke runs")
    ap.add_argument("--budget", type=float, default=5.0, help="hard USD cap for this run")
    args = ap.parse_args()

    paragraphs = _read_jsonl(PARAGRAPHS_JSONL)
    applicability, actions = partition(paragraphs)
    selected = applicability + actions
    if args.limit:
        selected = selected[: args.limit]

    offline = args.offline or not have_api_key()
    ledger = CostLedger(cap_usd=args.budget)
    client = None if offline else LLMClient(ledger)

    print(
        f"paragraphs={len(paragraphs)} applicability={len(applicability)} "
        f"actions={len(actions)} selected={len(selected)} "
        f"mode={'offline' if offline else 'live'} cap=${args.budget:.2f}"
    )

    result = extract(selected, client=client, offline=offline)

    counts = {
        "rules": _write_jsonl(BUILD / "rules.jsonl", result.rules),
        "actions": _write_jsonl(BUILD / "actions.jsonl", result.actions),
        "delegations": _write_jsonl(BUILD / "delegations.jsonl", result.delegations),
        "external_nodes": _write_jsonl(BUILD / "external_nodes.jsonl", result.external_nodes),
    }
    print("wrote:", json.dumps(counts))
    print("report:", json.dumps(result.report, indent=2, default=str)[:1500])
    print("spend:", json.dumps(ledger.summary()))


if __name__ == "__main__":
    main()
