"""Measure the two code-only stages against their contract targets.

    python3 -m engine.retrieval.latency_bench

The entity pass and retrieval are the stages this project claims are fast
because they contain no model call. That claim is checkable, so it is checked
here rather than quoted from memory, and the README names this command next to
its numbers.

Only the model-free stages are measured. Query planning and answer writing are
network calls whose latency is not this engine's to claim.

Queries are generated from the built corpus, not hand-picked, so the mix cannot
be quietly chosen to flatter the result: a third name a real AD (the graph
filter narrows hard), a third are topical phrases taken from real paragraph
headings (no filter, both arms do the work), and a third name an aircraft model
drawn from the fleet.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contracts.contract import contract  # noqa: E402
from engine.paths import BUILD  # noqa: E402
from engine.retrieval.corpus import load_corpus  # noqa: E402
from engine.retrieval.entities import extract_entities  # noqa: E402
from engine.retrieval.index import load_index  # noqa: E402
from engine.retrieval.search import search  # noqa: E402


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(fraction * len(ordered))) - 1))
    return ordered[index]


def build_queries(corpus: Any, count: int) -> list[str]:
    """Generate the query mix from the corpus itself."""
    ad_numbers = sorted(corpus.ad_numbers)
    per_arm = max(1, count // 3)

    named = [
        f"What does AD {ad} require and by when?"
        for ad in ad_numbers[:: max(1, len(ad_numbers) // per_arm)][:per_arm]
    ]

    headings: list[str] = []
    seen: set[str] = set()
    for paragraph in corpus.paragraphs:
        heading = (getattr(paragraph, "heading", None) or "").strip()
        if len(heading) < 12 or heading.lower() in seen:
            continue
        seen.add(heading.lower())
        headings.append(f"{heading} compliance time")
        if len(headings) >= per_arm:
            break

    models: list[str] = []
    fleet_path = BUILD / "nodes.aircraft.jsonl"
    if fleet_path.exists():
        seen_models: set[str] = set()
        for line in fleet_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                node = json.loads(line)
            except json.JSONDecodeError:
                continue
            model = (node.get("model") or "").strip()
            if not model or model.lower() in seen_models:
                continue
            seen_models.add(model.lower())
            models.append(f"Which ADs apply to a {model}?")
            if len(models) >= per_arm:
                break

    return (named + headings + models)[:count]


def measure(count: int = 40, repeats: int = 15) -> dict[str, Any]:
    load_started = time.perf_counter()
    corpus = load_corpus()
    index = load_index(corpus)
    load_seconds = time.perf_counter() - load_started

    queries = build_queries(corpus, count)
    entity_ms: list[float] = []
    retrieval_ms: list[float] = []

    # Warm once per query: a cold first call measures import and page-cache
    # behaviour, not the stage, and the server loads the index at startup.
    for query in queries:
        entities = extract_entities(query, known_ad_numbers=corpus.ad_numbers)
        search(index, query, entities, k=8, revision_scope="current")

    for query in queries:
        for _ in range(repeats):
            started = time.perf_counter()
            entities = extract_entities(query, known_ad_numbers=corpus.ad_numbers)
            entity_ms.append((time.perf_counter() - started) * 1000)

            started = time.perf_counter()
            search(index, query, entities, k=8, revision_scope="current")
            retrieval_ms.append((time.perf_counter() - started) * 1000)

    targets = contract()["latency_targets_ms"]
    stages = {
        "entity_pass": (entity_ms, targets.get("entity_pass")),
        "retrieval": (retrieval_ms, targets.get("retrieval")),
    }
    return {
        "paragraphs": len(corpus.paragraphs),
        "ad_numbers": len(corpus.ad_numbers),
        "queries": len(queries),
        "samples_per_stage": len(entity_ms),
        "index_load_seconds": round(load_seconds, 2),
        "stages": {
            name: {
                "p50": round(statistics.median(values), 2),
                "p95": round(_percentile(values, 0.95), 2),
                "target": target,
                "within_target": _percentile(values, 0.95) <= target if target else None,
            }
            for name, (values, target) in stages.items()
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", type=int, default=40)
    parser.add_argument("--repeats", type=int, default=15)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = measure(count=args.queries, repeats=args.repeats)
    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(
        f"corpus: {report['paragraphs']} paragraphs across {report['ad_numbers']} ADs"
        f" | index load {report['index_load_seconds']}s"
    )
    print(
        f"{report['queries']} generated queries, "
        f"{report['samples_per_stage']} warm samples per stage"
    )
    print()
    print(f"{'stage':14} {'p50':>9} {'p95':>9} {'target':>9}  verdict")
    worst_ok = True
    for name, row in report["stages"].items():
        verdict = "within target" if row["within_target"] else "OVER TARGET"
        worst_ok &= bool(row["within_target"])
        print(
            f"{name:14} {row['p50']:>7.2f}ms {row['p95']:>7.2f}ms "
            f"{row['target']:>7}ms  {verdict}"
        )
    print()
    print(
        "Model-free stages only. Query planning and answer writing are network "
        "calls and are not claimed here."
    )
    return 0 if worst_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
