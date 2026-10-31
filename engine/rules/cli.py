"""CLI for the applicability layer.

  python3 -m engine.rules extract [--offline] [--cap 5.0] [--paragraphs P] [--out-dir D]
  python3 -m engine.rules matrix  [--out-dir D]

The extract cap is deliberately small and explicit: the ledger refuses the pass
rather than discovering an overspend afterwards.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine import paths  # noqa: E402
from engine.llm.client import LLMClient, LLMUnavailable, have_api_key  # noqa: E402
from engine.llm.ledger import CostLedger  # noqa: E402

from . import extract as extract_mod, matrix as matrix_mod, records  # noqa: E402

DEFAULT_CAP_USD = 5.0
AIRCRAFT_NODES = paths.BUILD / "nodes.aircraft.jsonl"


def _load_paragraphs(path: Path, *, revisions: Sequence[str], limit: int | None) -> list[dict[str, Any]]:
    paragraphs = matrix_mod.load_jsonl(path)
    if revisions:
        wanted = set(revisions)
        paragraphs = [p for p in paragraphs if p.get("revision_id") in wanted]
    if limit:
        keep = list(dict.fromkeys(p["revision_id"] for p in paragraphs))[:limit]
        paragraphs = [p for p in paragraphs if p["revision_id"] in set(keep)]
    missing = [p.get("paragraph_id") for p in paragraphs if not p.get("text")]
    if missing:
        raise ValueError(f"paragraphs without text: {missing[:5]}")
    return paragraphs


def cmd_extract(args: argparse.Namespace) -> int:
    paragraphs = _load_paragraphs(
        Path(args.paragraphs), revisions=args.revision or [], limit=args.limit
    )
    if not paragraphs:
        print("no paragraphs matched; nothing to extract", file=sys.stderr)
        return 1

    ledger = CostLedger(cap_usd=args.cap)
    offline = args.offline or not have_api_key()
    if args.offline is False and not have_api_key():
        print(
            "ANTHROPIC_API_KEY is not set. Re-run with --offline to emit every "
            "applicability clause as unparsed instead of guessing.",
            file=sys.stderr,
        )
        return 2

    spent_before = ledger.spent_usd()
    client = None if offline else LLMClient(ledger=ledger, offline=False)
    try:
        result = extract_mod.extract(paragraphs, client=client, offline=offline)
    except LLMUnavailable as exc:
        print(f"{exc}\nRe-run with --offline.", file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir)
    written = {
        "rules.jsonl": records.write_jsonl(out_dir / "rules.jsonl", result.rules, node_type="Rule"),
        "actions.jsonl": records.write_jsonl(out_dir / "actions.jsonl", result.actions, node_type="Action"),
        "nodes.rules.jsonl": records.write_nodes(out_dir / "nodes.rules.jsonl", result.external_nodes),
        "edges.rules.jsonl": records.write_jsonl(out_dir / "edges.rules.jsonl", result.edges()),
        "externals.jsonl": records.write_jsonl(out_dir / "externals.jsonl", result.delegations),
    }
    report = {
        **result.report,
        "written": written,
        "run_cost_usd": round(ledger.spent_usd() - spent_before, 6),
        "cost": ledger.summary(),
    }
    (out_dir / "extraction_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


def cmd_matrix(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    aircraft = matrix_mod.load_jsonl(Path(args.aircraft))
    rules = matrix_mod.load_jsonl(Path(args.rules))
    externals_path = Path(args.externals)
    delegations = matrix_mod.load_jsonl(externals_path) if externals_path.exists() else []
    if args.limit:
        aircraft = aircraft[: args.limit]
    built = matrix_mod.build(aircraft, rules, delegations)
    written = matrix_mod.write(out_dir, built)
    summary = {k: v for k, v in built.items() if k not in {"cells", "edges"}}
    summary["written"] = {k: str(v) for k, v in written.items()}
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="engine.rules", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    ex = sub.add_parser("extract", help="extract Rules and Actions from paragraphs")
    ex.add_argument("--paragraphs", default=str(paths.PARAGRAPHS_JSONL))
    ex.add_argument("--out-dir", default=str(paths.BUILD))
    ex.add_argument("--cap", type=float, default=DEFAULT_CAP_USD, help="hard spend cap in USD")
    ex.add_argument("--offline", action="store_true", help="emit unparsed rules, call nothing")
    ex.add_argument("--revision", action="append", help="limit to these revision_ids")
    ex.add_argument("--limit", type=int, help="limit to the first N revisions")
    ex.set_defaults(func=cmd_extract)

    mx = sub.add_parser("matrix", help="precompute the fleet x AD decision matrix")
    mx.add_argument("--aircraft", default=str(AIRCRAFT_NODES))
    mx.add_argument("--rules", default=str(paths.BUILD / "rules.jsonl"))
    mx.add_argument("--externals", default=str(paths.BUILD / "externals.jsonl"))
    mx.add_argument("--out-dir", default=str(paths.BUILD))
    mx.add_argument("--limit", type=int, help="limit to the first N aircraft")
    mx.set_defaults(func=cmd_matrix)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
