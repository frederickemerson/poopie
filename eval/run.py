"""Run both arms over the labelled set and publish the numbers.

    python3 -m eval.run [--arm ours|baseline|both] [--limit N] [--out eval/results]

``runs.jsonl`` holds one line per question per arm. Every number in the report
is recomputable from it by ``eval.metrics``, which is what makes the report
checkable rather than assertable; ``metrics.json`` is that computation and
``report.md`` is the table plus the failure gallery. Method and caveats:
docs/evaluation.md.

The engine arm is not reimplemented or re-staged here. It is driven through
``engine.api.server._stream`` -- the same generator the UI consumes -- and every
field recorded comes off that stream's contract-pinned SSE events: the
paragraphs from ``retrieval``, the decision from ``decision``, the prose from
``answer_delta``, the drops from ``verification``, the refusals from ``refusal``
and the verdict from ``done.envelope.answer_status``. The harness decides
nothing about the engine's behaviour; it records it.

The baseline calls the same ``engine.api.answer.write_answer`` the engine does,
so what differs between the arms is the machinery and never the prompt. Each
recorded refusal says whether it arrived before the ``verification`` event (the
gate decided up front) or after it (a drafted answer failed verification),
because those are not the same claim about the system.

Cost: one ``CostLedger(cap_usd=2.0)`` for every call. The client caches on a
hash of its inputs, so re-running over an unchanged corpus is free.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from contracts.contract import ContractViolation
from engine.api import server
from engine.api.applicability import ApplicabilityStore
from engine.llm.client import LLMClient, LLMUnavailable, have_api_key
from engine.llm.ledger import BudgetExceeded, CostLedger
from engine.retrieval.corpus import load_corpus
from engine.retrieval.index import load_index
from eval import metrics as M
from eval.baseline import DenseArmMissing, Passage, run_baseline
from eval.questions import Question, build_set
from eval.report import FROM_GATE, FROM_VERIFIER, report

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "eval" / "results"

#: The harness runs under its own cap, well inside the project budget.
EVAL_CAP_USD = 2.0
ARMS = ("ours", "baseline")

#: Errors that end one question but not the run. A budget breach is not here:
#: it aborts, because continuing would record questions nobody paid for.
_RUN_ERRORS = (LLMUnavailable, DenseArmMissing, ContractViolation, ValueError, KeyError)


@dataclass
class Harness:
    corpus: Any
    index: Any
    client: LLMClient
    ledger: CostLedger


def boot() -> Harness:
    """Load corpus and index once and wire them into the server's state.

    The server's ``_startup`` would do this with the project-wide default cap;
    the harness substitutes its own ledger so the eval cannot spend the ingest's
    budget. Nothing else about the wiring differs.
    """
    corpus = load_corpus()
    index = load_index(corpus)
    ledger = CostLedger(cap_usd=EVAL_CAP_USD)
    client = LLMClient(ledger, offline=not have_api_key())
    server.STATE.corpus = corpus
    server.STATE.index = index
    server.STATE.ledger = ledger
    server.STATE.client = client
    server.STATE.applicability = ApplicabilityStore.load()
    server.STATE.error = None
    return Harness(corpus=corpus, index=index, client=client, ledger=ledger)


def warm_up(_harness: Harness) -> float:
    """Load the embedding model before any timing is taken.

    The first embed call pays a one-off model load of seconds. Left inside the
    first question it would land in the retrieval percentiles, making them a
    measurement of the model loader.
    """
    from engine.retrieval.index import embed

    started = time.perf_counter()
    embed(["warm up the sentence-transformers model"])
    return (time.perf_counter() - started) * 1000.0


def events(stream: Iterable[str]) -> Iterator[tuple[str, dict[str, Any]]]:
    """Parse the SSE frames ``_stream`` yields into (event name, payload)."""
    for frame in stream:
        name: str | None = None
        data: str | None = None
        for line in frame.strip().splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :].strip()
            elif line.startswith("data: "):
                data = line[len("data: ") :]
        if name is None or data is None:
            raise ValueError(f"malformed SSE frame from the engine: {frame!r}")
        yield name, json.loads(data)


def _blank_record(question: Question, arm: str) -> dict[str, Any]:
    """Every key the metrics read, present whether or not the arm got that far."""
    return {
        "qid": question.qid, "arm": arm, "kind": question.kind,
        "question": question.text, "tail_number": question.tail_number,
        "notes": question.notes,
        "expected": {
            "refusal": question.expect_refusal,
            "decision": question.expect_decision,
            "ad_number": question.expect_ad_number,
            "paragraph_roles": list(question.expect_paragraph_roles),
            "must_mention": list(question.must_mention),
        },
        "refusal_codes": [], "refusal_details": [],
        "decision": None, "decision_available": False,
        "decision_unavailable_reason": None,
        "retrieved_paragraph_ids": [], "retrieved_ad_numbers": [],
        "answered": False, "answer_status": None,
        "sentences": [], "citation_ids": [],
        "stage_ms": {}, "total_ms": None, "error": None,
        "cost_usd": 0.0, "model_calls": 0, "cached_calls": 0,
    }


def _sentence_rows(
    drafted: Sequence[Any], verification: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Every drafted sentence, with the verifier's verdict where there is one.

    Dropped sentences stay in the record: the share the verifier removed is a
    result, so it must not be deleted on the way to the report. ``kept`` is
    None for an arm that ran no verifier, which is not the same as False.
    """
    kept = set((verification or {}).get("kept") or [])
    reasons = {
        d.get("index"): d for d in ((verification or {}).get("drop_reasons") or [])
    }
    rows = []
    for s in drafted:
        index = s["index"] if isinstance(s, dict) else s.index
        drop = reasons.get(index) or {}
        rows.append(
            {
                "index": index,
                "text": s["text"] if isinstance(s, dict) else s.text,
                "citation_ids": list(
                    s["citation_ids"] if isinstance(s, dict) else s.citation_ids
                ),
                "kept": None if verification is None else index in kept,
                "drop_reason": drop.get("reason"),
                "drop_detail": drop.get("detail"),
            }
        )
    return rows


def _ledger_rows_since(harness: "Harness", offset: int) -> tuple[int, list[dict[str, Any]]]:
    """The ledger rows appended since ``offset``, and the new end offset.

    The ledger is append-only, so reading from a byte offset gives this turn's
    calls exactly -- cost *and* whether each one was served from the content-hash
    cache. The cache flag matters as much as the cost: a cached call returns in
    about a millisecond, so a run containing one has not measured what the model
    stages really take, and ``eval.metrics`` drops its model timings rather than
    publish a cache hit as a latency.
    """
    path = harness.ledger.path
    if not path.exists():
        return offset, []
    size = path.stat().st_size
    if size <= offset:
        return size, []
    with path.open(encoding="utf-8") as fh:
        fh.seek(offset)
        blob = fh.read()
    rows: list[dict[str, Any]] = []
    for line in blob.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            # A torn final line is a ledger-writing artefact, not a call we can
            # attribute. Skip it rather than guess at its cost or cache flag.
            continue
    return size, rows


def _bill(record: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    """Attribute this turn's model calls to the record."""
    record["cost_usd"] = round(sum(float(r.get("cost_usd") or 0.0) for r in rows), 6)
    record["model_calls"] = len(rows)
    record["cached_calls"] = sum(1 for r in rows if r.get("cached_hit"))


def run_ours(question: Question, harness: Harness) -> dict[str, Any]:
    """Record one turn of the engine's own pipeline. Decides nothing itself."""
    record = _blank_record(question, "ours")
    offset = harness.ledger.path.stat().st_size if harness.ledger.path.exists() else 0
    frames = list(events(server._stream(question.text, question.tail_number)))
    _bill(record, _ledger_rows_since(harness, offset)[1])
    payloads = {name: payload for name, payload in frames}
    if "error" in payloads:
        record["error"] = str(payloads["error"].get("message"))
        return record

    passages = [
        Passage.from_hit(h)
        for h in (payloads.get("retrieval") or {}).get("paragraphs") or []
    ]
    record["retrieved_paragraph_ids"] = [p.paragraph_id for p in passages]
    record["retrieved_ad_numbers"] = sorted({p.ad_number for p in passages if p.ad_number})

    decision = payloads.get("decision") or {}
    tree = decision.get("proof_tree") or {}
    record["decision"] = decision.get("decision")
    record["decision_available"] = decision.get("decision") is not None
    if isinstance(tree, dict) and tree.get("unavailable"):
        record["decision_unavailable_reason"] = str(tree["unavailable"])

    # A refusal that arrives before `verification` was decided by the gate,
    # before any prose existed. One arriving after it is a drafted answer that
    # failed verification. The stream's own order is the authority on which.
    seen_verification = False
    for name, payload in frames:
        if name == "verification":
            seen_verification = True
        elif name == "refusal":
            record["refusal_details"].append(
                {
                    "code": payload["code"], "detail": payload["detail"],
                    "resolvable_by": payload.get("resolvable_by"),
                    "source": FROM_VERIFIER if seen_verification else FROM_GATE,
                }
            )
    record["refusal_codes"] = [d["code"] for d in record["refusal_details"]]

    # `answer_delta` names the prose "sentence"; the record calls it "text" so
    # both arms' sentences have one shape.
    drafted = [
        {"index": p["index"], "text": p["sentence"],
         "citation_ids": list(p.get("citation_ids") or [])}
        for name, p in frames
        if name == "answer_delta"
    ]
    record["sentences"] = _sentence_rows(drafted, payloads.get("verification"))
    record["citation_ids"] = [c for s in record["sentences"] for c in s["citation_ids"]]

    done = payloads.get("done") or {}
    envelope = done.get("envelope") or {}
    status = envelope.get("answer_status")
    record["answer_status"] = status
    # The engine's own verdict on whether it answered. Not re-derived here: it
    # is the field the UI renders, so the eval must be scoring the same thing.
    record["answered"] = status in ("ANSWERED", "PARTIAL")
    record["stage_ms"] = dict(done.get("stage_timings") or {})
    record["total_ms"] = done.get("total_ms")
    return record


def run_baseline_arm(question: Question, harness: Harness) -> dict[str, Any]:
    """Top-8 cosine, one answer from the engine's writer, no refusal path."""
    record = _blank_record(question, "baseline")
    offset = harness.ledger.path.stat().st_size if harness.ledger.path.exists() else 0
    out = run_baseline(harness.index, harness.client, question.text)
    _bill(record, _ledger_rows_since(harness, offset)[1])
    record["retrieved_paragraph_ids"] = [p.paragraph_id for p in out.passages]
    record["retrieved_ad_numbers"] = sorted({p.ad_number for p in out.passages if p.ad_number})
    # verification=None, not an empty verdict: this arm ran no verifier at all.
    record["sentences"] = _sentence_rows(out.sentences, None)
    record["citation_ids"] = out.citation_ids
    record["answered"] = bool(out.sentences)
    record["answer_status"] = "ANSWERED" if out.sentences else "REFUSED"
    record["stage_ms"] = {k: round(v, 2) for k, v in out.stage_ms.items()}
    record["total_ms"] = round(out.total_ms, 2)
    record["decision_unavailable_reason"] = (
        "the baseline has no rules engine, so it produces no decision value"
    )
    if not out.answer.available and out.answer.reason:
        record["error"] = f"writer produced nothing: {out.answer.reason}"
    return record


def execute(
    questions: Sequence[Question], harness: Harness, arms: Sequence[str]
) -> tuple[list[dict[str, Any]], str | None]:
    """Run every question through every arm. Returns the runs and any abort reason.

    A budget breach stops the run but does not discard it: the cost ledger is
    shared with the ingest, so the eval can legitimately run out of money
    part-way through. The records collected so far are still written, with the
    breach recorded against the question that hit it, and the report's per-arm
    sample sizes show how far it got. Silently returning fewer questions than
    the set contains would be the dishonest option.
    """
    runners = {"ours": run_ours, "baseline": run_baseline_arm}
    out: list[dict[str, Any]] = []
    for question in questions:
        for arm in arms:
            try:
                out.append(runners[arm](question, harness))
            except BudgetExceeded as exc:
                record = _blank_record(question, arm)
                record["error"] = f"BudgetExceeded: {exc}"
                out.append(record)
                print(f"  {question.qid:9s} {arm:9s} budget exhausted", flush=True)
                return out, str(exc)
            except _RUN_ERRORS as exc:
                record = _blank_record(question, arm)
                record["error"] = f"{type(exc).__name__}: {exc}"
                out.append(record)
            print(f"  {question.qid:9s} {arm:9s} {M.outcome(out[-1])}", flush=True)
    return out, None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the AD engine evaluation harness.")
    ap.add_argument("--arm", choices=["ours", "baseline", "both"], default="both")
    ap.add_argument("--limit", type=int, default=None, help="first N questions only")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    arms = ARMS if args.arm == "both" else (args.arm,)
    harness = boot()
    questions = build_set()[: args.limit] if args.limit else build_set()
    print(f"{len(questions)} questions x {len(arms)} arm(s); cap ${EVAL_CAP_USD:.2f}")
    warm_up_ms = warm_up(harness)
    runs, aborted = execute(questions, harness, arms)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "runs.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in runs), encoding="utf-8"
    )
    (args.out / "metrics.json").write_text(
        json.dumps({a: M.summarise(runs, arm=a).as_dict() for a in arms}, indent=2),
        encoding="utf-8",
    )
    (args.out / "report.md").write_text(
        report(
            runs, questions, harness, server.STATE.applicability,
            arms=arms, warm_up_ms=warm_up_ms,
        ),
        encoding="utf-8",
    )
    for arm in arms:
        rates = M.summarise(runs, arm=arm).rates
        print(f"{arm}: wrong_answer={rates['wrong_answer_rate'].as_text()} "
              f"refusal_recall={rates['refusal_recall'].as_text()}")
    print(f"wrote {args.out}/runs.jsonl, metrics.json, report.md")
    print(f"spend: ${harness.ledger.summary()['spent_usd']:.4f}")
    if aborted:
        print(f"INCOMPLETE: {aborted}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
