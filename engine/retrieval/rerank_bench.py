"""Measure reranking against the real index: quality delta and latency cost.

    python3 -m engine.retrieval.rerank_bench [--runs 15] [--json out.json]

Two kinds of query, labelled by hand (the labels are in ``QUERIES`` and are the
weakest part of this measurement; they are a judgement, not ground truth):

* ``named``  - the query names an AD number. The graph filter already narrows
  the candidates to that AD, so "the AD is in the top 3" is true before and
  after by construction. The gold label is the paragraph *role* that answers
  the question (e.g. REQUIRED_ACTIONS), and the metric is role precision.
* ``topic``  - no AD number. Gold is the set of ADs whose text is genuinely
  about the topic (found by reading the corpus), and the metric is whether a
  gold AD's paragraph reaches rank 1 / the top 3.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.retrieval.corpus import load_corpus  # noqa: E402
from engine.retrieval.entities import extract_entities  # noqa: E402
from engine.retrieval.index import load_index  # noqa: E402
from engine.retrieval.rerank import RERANK_MODEL, RERANK_WINDOW, warm_up  # noqa: E402
from engine.retrieval.search import search  # noqa: E402

LATENCY_TARGET_MS = json.loads(
    (ROOT / "contracts" / "contract.json").read_text()
)["latency_targets_ms"]["retrieval"]


@dataclass(frozen=True)
class Q:
    text: str
    kind: str  # "named" or "topic"
    gold_roles: tuple[str, ...] = ()
    gold_ads: tuple[str, ...] = ()
    named_ad: str | None = None


QUERIES: tuple[Q, ...] = (
    Q("What does AD 2026-21-13 require?", "named", ("REQUIRED_ACTIONS",), named_ad="2026-21-13"),
    Q("compliance time for AD 2026-20-10", "named", ("COMPLIANCE",), named_ad="2026-20-10"),
    Q("Which airplanes does AD 2026-22-02 apply to?", "named", ("APPLICABILITY",), named_ad="2026-22-02"),
    Q("unsafe condition addressed by AD 2026-21-05", "named", ("UNSAFE_CONDITION",), named_ad="2026-21-05"),
    Q("when is AD 2026-20-15 effective", "named", ("EFFECTIVE_DATE",), named_ad="2026-20-15"),
    Q("alternative method of compliance AD 2026-21-03", "named", ("AMOC",), named_ad="2026-21-03"),
    Q("what must be done for AD 2026-21-10 tail rotor gearbox", "named", ("REQUIRED_ACTIONS",), named_ad="2026-21-10"),
    Q("AD 2026-20-08 inspection interval", "named", ("COMPLIANCE", "REQUIRED_ACTIONS"), named_ad="2026-20-08"),
    Q("exceptions to AD 2026-20-10", "named", ("EXCEPTIONS",), named_ad="2026-20-10"),
    Q("fuel pump wiring inspection", "topic", gold_ads=("2026-21-03",)),
    Q("FCPC software", "topic", gold_ads=("2026-22-02",)),
    Q("main rotor servo-control", "topic", gold_ads=("2026-21-05",)),
    Q("tail rotor gearbox torque", "topic", gold_ads=("2026-21-10",)),
    Q("elevator tab control system cracks", "topic", gold_ads=("2026-21-13",)),
    Q("horizontal stabilizer corrosion", "topic", gold_ads=("2026-20-05", "2026-20-14")),
    Q("engine compressor inspection", "topic", gold_ads=("2026-20-11", "2026-21-04", "2026-21-11")),
    Q("Airbus A330 fuel system", "topic", gold_ads=("2026-21-03",)),
    Q("bleed air leak pneumatic", "topic", gold_ads=("2026-20-15",)),
    Q("exhaust system cracking Leonardo helicopters", "topic", gold_ads=("2026-20-07",)),
    Q("life limit engine part", "topic", gold_ads=("2026-21-04",)),
    Q("lightning protection wing Bombardier", "topic", gold_ads=("2026-20-09",)),
    Q("Pratt & Whitney engine fuel control", "topic", gold_ads=("2026-21-06",)),
    Q("General Electric engine software update", "topic", gold_ads=("2026-21-11",)),
    Q("placards and markings", "topic", gold_ads=("2026-20-03",)),
    Q("Boeing flight controls wing inspection", "topic", gold_ads=("2026-20-10",)),
)


@dataclass
class Row:
    q: Q
    before: list[str]
    after: list[str]
    before_ads: list[str | None]
    after_ads: list[str | None]
    before_roles: list[str]
    after_roles: list[str]
    status: str = "applied"


def _first_gold(ads: list[str | None], gold: tuple[str, ...]) -> int | None:
    return next((i + 1 for i, a in enumerate(ads) if a in gold), None)


def _first_role(roles: list[str], gold: tuple[str, ...]) -> int | None:
    return next((i + 1 for i, r in enumerate(roles) if r in gold), None)


def run_queries(index, corpus) -> list[Row]:
    rows: list[Row] = []
    for q in QUERIES:
        ents = extract_entities(q.text, known_ad_numbers=corpus.ad_numbers)
        base = search(index, q.text, ents, rerank=False)
        rr = search(index, q.text, ents, rerank=True)
        rows.append(
            Row(
                q,
                [h.paragraph_id for h in base.hits],
                [h.paragraph_id for h in rr.hits],
                [h.ad_number for h in base.hits],
                [h.ad_number for h in rr.hits],
                [h.role for h in base.hits],
                [h.role for h in rr.hits],
                rr.rerank_status,
            )
        )
    return rows


def summarise(rows: list[Row]) -> dict[str, object]:
    out: dict[str, object] = {"queries": len(rows)}
    out["top1_changed"] = sum(r.before[:1] != r.after[:1] for r in rows)
    out["top8_set_changed"] = sum(set(r.before) != set(r.after) for r in rows)
    out["statuses"] = sorted({r.status for r in rows})
    named = [r for r in rows if r.q.kind == "named"]
    topic = [r for r in rows if r.q.kind == "topic"]
    out["named_n"], out["topic_n"] = len(named), len(topic)
    out["named_top1_changed"] = sum(r.before[:1] != r.after[:1] for r in named)
    out["topic_top1_changed"] = sum(r.before[:1] != r.after[:1] for r in topic)
    # Named-AD paragraph in top 3: before / after / moved-in.
    def named_in3(ads, q):
        return q.named_ad in ads[:3]
    out["named_ad_in_top3_before"] = sum(named_in3(r.before_ads, r.q) for r in named)
    out["named_ad_in_top3_after"] = sum(named_in3(r.after_ads, r.q) for r in named)
    out["named_ad_moved_into_top3"] = sum(
        named_in3(r.after_ads, r.q) and not named_in3(r.before_ads, r.q) for r in named
    )
    # Role precision (named queries).
    for tag, attr in (("before", "before_roles"), ("after", "after_roles")):
        out[f"role_top1_{tag}"] = sum(
            getattr(r, attr)[:1] and getattr(r, attr)[0] in r.q.gold_roles for r in named
        )
        out[f"role_top3_{tag}"] = sum(
            _first_role(getattr(r, attr), r.q.gold_roles) in (1, 2, 3) for r in named
        )
    # Gold-AD placement (topic queries).
    for tag, attr in (("before", "before_ads"), ("after", "after_ads")):
        ranks = [_first_gold(getattr(r, attr), r.q.gold_ads) for r in topic]
        out[f"gold_top1_{tag}"] = sum(x == 1 for x in ranks)
        out[f"gold_top3_{tag}"] = sum(x is not None and x <= 3 for x in ranks)
        out[f"gold_mrr_{tag}"] = round(
            statistics.fmean(1 / x if x else 0.0 for x in ranks), 4
        )
    return out


def measure_latency(index, corpus, runs: int) -> dict[str, dict[str, float]]:
    """Warm per-query wall time of `search`, off vs on. Model is loaded first."""
    entity_sets = [
        (q.text, extract_entities(q.text, known_ad_numbers=corpus.ad_numbers))
        for q in QUERIES
    ]
    for text, ents in entity_sets:  # warm embedder, caches, cross-encoder
        search(index, text, ents, rerank=True)
        search(index, text, ents, rerank=False)
    result: dict[str, dict[str, float]] = {}
    for label, flag in (("off", False), ("on", True)):
        samples: list[float] = []
        for _ in range(runs):
            for text, ents in entity_sets:
                t0 = time.perf_counter()
                search(index, text, ents, rerank=flag)
                samples.append((time.perf_counter() - t0) * 1000)
        samples.sort()
        result[label] = {
            "n": len(samples),
            "p50_ms": round(statistics.median(samples), 1),
            "p95_ms": round(samples[int(0.95 * (len(samples) - 1))], 1),
            "max_ms": round(samples[-1], 1),
        }
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", type=int, default=15)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(argv)

    reason = warm_up()
    if reason:
        print(f"cross-encoder unavailable, nothing to measure: {reason}", file=sys.stderr)
        return 2
    corpus = load_corpus()
    index = load_index(corpus)
    rows = run_queries(index, corpus)
    report = {
        "model": RERANK_MODEL,
        "window": RERANK_WINDOW,
        "corpus_paragraphs": len(corpus.paragraphs),
        "latency_target_ms": LATENCY_TARGET_MS,
        "quality": summarise(rows),
        "latency": measure_latency(index, corpus, args.runs),
        "per_query": [
            {
                "query": r.q.text,
                "kind": r.q.kind,
                "top1_before": r.before[:1],
                "top1_after": r.after[:1],
                "top3_before": r.before[:3],
                "top3_after": r.after[:3],
                "top8_before": r.before,
                "top8_after": r.after,
            }
            for r in rows
        ],
    }
    text = json.dumps(report, indent=2)
    if args.json:
        args.json.write_text(text)
    print(json.dumps({k: v for k, v in report.items() if k != "per_query"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
