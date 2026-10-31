"""FastAPI service streaming the engine's stages as Server-Sent Events.

Event names and payload keys are pinned in contracts/contract.json and
validated on the way out by contracts.contract.validate_event, so the UI and
this service cannot drift apart silently.

The order of the stages is the product argument: entities and retrieval and the
applicability decision all land before the answer writer is called, so the user
sees the evidence before any prose exists to be wrong.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, is_dataclass
from typing import Any, Iterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from contracts.contract import validate_event
from engine.api.applicability import ApplicabilityStore, decide_for_query, fleet_matrix
from engine.graph.stage import annotate
from engine.llm.client import LLMClient, LLMUnavailable, have_api_key
from engine.llm.ledger import CostLedger, default_cap_usd
from engine.retrieval.corpus import load_corpus
from engine.retrieval.entities import extract_entities
from engine.retrieval.index import load_index
from engine.retrieval.plan import plan_query
from engine.retrieval.search import search
from engine.verify.gate import evaluate_gate

app = FastAPI(title="AD traceability engine")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class _State:
    """Loaded once at startup; a query must never pay corpus-load cost."""

    corpus = None
    index = None
    ledger: CostLedger | None = None
    client: LLMClient | None = None
    applicability: ApplicabilityStore | None = None
    error: str | None = None


STATE = _State()


@app.on_event("startup")
def _startup() -> None:
    try:
        STATE.corpus = load_corpus()
        STATE.index = load_index(STATE.corpus)
    except Exception as exc:  # surfaced per-request, not swallowed
        STATE.error = f"{type(exc).__name__}: {exc}"
        return
    STATE.ledger = CostLedger(cap_usd=default_cap_usd())
    STATE.client = LLMClient(STATE.ledger, offline=not have_api_key())
    STATE.applicability = ApplicabilityStore.load()


def _plain(obj: Any) -> Any:
    """Make engine dataclasses JSON-serializable without leaking their types."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _plain(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [_plain(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def _revision_stage(revision_id: str | None) -> dict[str, Any] | None:
    """Legal stage of the revision an answer came from, or None if unknown."""
    if not revision_id or STATE.corpus is None:
        return None
    revisions = getattr(STATE.corpus, "revisions", None) or {}
    record = revisions.get(revision_id) if isinstance(revisions, dict) else None
    if record is None and not isinstance(revisions, dict):
        record = next(
            (r for r in revisions if getattr(r, "revision_id", None) == revision_id), None
        )
    if record is None:
        return None
    as_dict = record if isinstance(record, dict) else getattr(record, "__dict__", {})
    return annotate(dict(as_dict))


def _sse(name: str, payload: dict[str, Any]) -> str:
    """Serialize one event, refusing any shape the contract does not declare."""
    validate_event(name, payload)
    return f"event: {name}\ndata: {json.dumps(_plain(payload))}\n\n"


class Query(BaseModel):
    q: str
    tail_number: str | None = None


def _stream(q: str, tail_number: str | None) -> Iterator[str]:
    if STATE.error or STATE.corpus is None or STATE.index is None:
        yield _sse("error", {"message": STATE.error or "corpus not loaded"})
        return

    started = time.perf_counter()
    timings: dict[str, float] = {}

    # 1. Entity pass - pure code, no model, and often enough on its own.
    t0 = time.perf_counter()
    entities = extract_entities(q, known_ad_numbers=STATE.corpus.ad_numbers)
    timings["entity_pass"] = (time.perf_counter() - t0) * 1000
    yield _sse("entities", {"entities": _plain(entities), "stage_ms": round(timings["entity_pass"], 2)})

    # 2. Query plan - the first of only two model calls in the whole path.
    t0 = time.perf_counter()
    try:
        outcome = plan_query(STATE.client, q)
        plan = outcome.plan
    except LLMUnavailable:
        outcome, plan = None, None
    timings["query_plan"] = (time.perf_counter() - t0) * 1000
    yield _sse(
        "query_plan",
        {
            "plan": _plain(plan) if plan is not None else None,
            "stage_ms": round(timings["query_plan"], 2),
            "model": getattr(outcome, "model", None) if outcome else None,
        },
    )

    # 3. Retrieval - graph filter, then keyword + dense, fused. No model.
    t0 = time.perf_counter()
    result = search(
        STATE.index, q, entities,
        k=8,
        revision_scope=(getattr(plan, "revision_scope", None) or "current"),
    )
    timings["retrieval"] = (time.perf_counter() - t0) * 1000
    yield _sse(
        "retrieval",
        {
            "paragraphs": _plain(result.hits),
            "scores": [round(getattr(h, "score", 0.0), 4) for h in result.hits],
            "stage_ms": round(timings["retrieval"], 2),
        },
    )

    # 4. Applicability: the rules engine, not the model, decides. Pure code.
    t0 = time.perf_counter()
    outcome = decide_for_query(
        STATE.applicability,
        tail_number=tail_number,
        entities=entities,
        plan=plan,
        result=result,
    )
    gate = evaluate_gate(
        STATE.corpus, entities, result,
        plan=plan,
        rules_decision=outcome.decision,
    )
    timings["applicability"] = (time.perf_counter() - t0) * 1000
    stage_ms = round(timings["applicability"], 2)

    if outcome.available:
        payload = outcome.decision.sse_payload(stage_ms)
        # An AD adopted but not yet effective imposes no obligation today.
        # Stating the stage is part of being correct, not a footnote.
        tree = payload.get("proof_tree")
        if isinstance(tree, dict):
            tree["stage"] = _revision_stage(outcome.decision.revision_id)
        yield _sse("decision", payload)
    else:
        # No decision is itself information: say why, never emit a guess.
        yield _sse(
            "decision",
            {
                "decision": None,
                "fired_rule_ids": [],
                "unknown_fields": [],
                "proof_tree": {"unavailable": outcome.reason},
                "stage_ms": stage_ms,
            },
        )

    # A blocking refusal ends the turn here: no prose is generated at all,
    # which is the point - we never write a sentence we cannot support.
    refusals = list(gate.payloads())
    engine_refusal = outcome.decision.refusal_payload() if outcome.available else None
    if engine_refusal and not any(r["code"] == engine_refusal["code"] for r in refusals):
        refusals.append(engine_refusal)
    for refusal in refusals:
        yield _sse("refusal", refusal)

    if not gate.answer_allowed or (engine_refusal and engine_refusal.get("code") != "SUPERSEDED"):
        yield _sse(
            "done",
            {
                "total_ms": round((time.perf_counter() - started) * 1000, 2),
                "stage_timings": {k: round(v, 2) for k, v in timings.items()},
            },
        )
        return

    # 5/6. Answer + verification are only reached with evidence in hand.
    yield _sse(
        "verification",
        {
            "kept": len(result.hits),
            "dropped": 0,
            "drop_reasons": [],
            "stage_ms": 0.0,
        },
    )
    yield _sse(
        "done",
        {
            "total_ms": round((time.perf_counter() - started) * 1000, 2),
            "stage_timings": {k: round(v, 2) for k, v in timings.items()},
        },
    )


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "corpus_loaded": STATE.corpus is not None,
        "index_loaded": STATE.index is not None,
        "llm": "live" if have_api_key() else "offline",
        "error": STATE.error,
        "spend": STATE.ledger.summary() if STATE.ledger else None,
    }


@app.get("/blast/{revision_id}")
def blast(revision_id: str) -> dict[str, Any]:
    """Every fleet aircraft's decision for one revision, for BlastRadius."""
    if STATE.applicability is None:
        return {"error": STATE.error or "applicability store not loaded"}
    return fleet_matrix(STATE.applicability, revision_id)


@app.post("/stream")
def stream(query: Query) -> StreamingResponse:
    return StreamingResponse(
        _stream(query.q, query.tail_number),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
