"""Query planning with Haiku, under a JSON schema generated from the contract.

Every enum in the schema is read from ``contracts/contract.json`` at runtime,
not copied here. That is not tidiness: an unconstrained schema lets the model
invent vocabulary (a live call returned an ``intent`` that is not in the enum),
and a copied enum drifts the moment the contract changes. The schema is built by
interpreting the contract's own ``query_plan_schema`` notation, so a new key
there appears in the schema without an edit to this file.

Planning is advisory. It runs concurrently with the entity pass and the entity
pass alone can serve a query, so every failure here -- no API key, budget cap,
timeout, malformed output, an off-enum value -- returns a plan of ``None`` with
a reason the caller can report. This module never raises into the pipeline and
never substitutes a guess for a plan it did not get.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contracts.contract import ContractViolation, contract, enum  # noqa: E402
from engine.llm.client import LLMClient, LLMUnavailable  # noqa: E402
from engine.llm.ledger import MODEL_PLAN, BudgetExceeded  # noqa: E402

SYSTEM = """You plan retrieval over a corpus of FAA airworthiness directives.

Read the user's question and fill the schema. Rules:
- Copy identifiers exactly as written. Never normalise, correct or complete them.
- Leave a field null when the question does not state it. Do not infer a model
  from a tail number, or a manufacturer from a model.
- revision_scope is "current" unless the question names a revision or asks about
  history, in which case "specific" or "all".
- published_year is the four-digit year a question scopes itself to when it asks
  which directives were published, issued or released in that year ("which ADs
  were published in 2025" -> "2025"). Leave it null otherwise. A year that is
  part of an AD number, a docket or an amendment is not a published_year.
- intent must be one of the allowed values. Use "search" when none of the more
  specific intents fits.
- use "recent" for a question about the corpus as a whole rather than about one
  document: which directives are newest, what is new, or which were published in
  a given year. It names no directive, docket or aircraft. "What are the latest
  ADs", "what's new" and "which ADs were published in 2025" are all "recent".
- intent is "recent" only when the question asks which directives are the
  newest, most recent or latest ones held, and names no directive, no docket and
  no aircraft: "what are the latest ADs", "which ADs came out most recently",
  "show me the newest directives". A question that names any subject is not
  "recent": "the latest revision of AD 2026-21-07" names a directive,
  "recent Boeing 737 ADs" names an aircraft, and "recent fuel pump ADs" asks
  about a topic -- all of those are an ordinary search or a revision question.
- ambiguities lists anything genuinely unclear, in the user's own words. An empty
  list is the normal case.
- You decide nothing else. You do not judge applicability, you do not decide
  whether the corpus holds the answer, and you never refuse."""


@dataclass
class QueryPlan:
    """The contract's ``query_plan_schema``, validated against its enums."""

    intent: str
    aircraft: dict[str, str | None] = field(default_factory=dict)
    ad_number: str | None = None
    docket_id: str | None = None
    topic: str | None = None
    #: The year a corpus-listing question scopes itself to, as written. A
    #: string rather than an int because the contract's schema notation has one
    #: nullable scalar form and a second one would be a shape to keep in sync.
    published_year: str | None = None
    revision_scope: str = "current"
    ambiguities: list[str] = field(default_factory=list)

    def as_payload(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "aircraft": self.aircraft,
            "ad_number": self.ad_number,
            "docket_id": self.docket_id,
            "topic": self.topic,
            "published_year": self.published_year,
            "revision_scope": self.revision_scope,
            "ambiguities": self.ambiguities,
        }


@dataclass
class PlanOutcome:
    """A plan, or the reason there isn't one. Never both empty."""

    plan: QueryPlan | None
    stage_ms: float
    model: str
    reason: str | None = None
    cached_hit: bool = False
    cost_usd: float = 0.0


def revision_scopes() -> list[str]:
    """The revision_scope values, read from the contract's own notation."""
    raw = contract()["query_plan_schema"]["revision_scope"]
    scopes = [part.strip() for part in str(raw).split("|") if part.strip()]
    if not scopes:
        raise ContractViolation(
            f"query_plan_schema.revision_scope is {raw!r}; expected 'a|b|c'"
        )
    return scopes


def _field_schema(key: str, spec: Any) -> dict[str, Any]:
    """Interpret one entry of the contract's query_plan_schema."""
    if isinstance(spec, dict):
        return {
            "type": "object",
            "properties": {k: _field_schema(k, v) for k, v in spec.items()},
            "required": sorted(spec),
            "additionalProperties": False,
        }
    if isinstance(spec, list):
        return {"type": "array", "items": {"type": "string"}}
    text = str(spec)
    if text.startswith("one of enums."):
        return {"type": "string", "enum": enum(text.split(".", 1)[1])}
    if "|" in text and "null" not in text:
        return {"type": "string", "enum": [p.strip() for p in text.split("|")]}
    if text == "string|null":
        return {"type": ["string", "null"]}
    raise ContractViolation(
        f"query_plan_schema.{key} is {spec!r}, which this planner does not know how "
        f"to turn into a JSON schema. Extend _field_schema or fix the contract."
    )


def plan_schema() -> dict[str, Any]:
    """The json_schema for the planner call, generated from the contract."""
    spec = contract()["query_plan_schema"]
    return {
        "type": "object",
        "properties": {k: _field_schema(k, v) for k, v in spec.items()},
        "required": sorted(spec),
        "additionalProperties": False,
    }


def _year(raw: Any) -> str | None:
    """A four-digit year, or nothing. Anything else is discarded, not repaired.

    The planner is told to copy identifiers verbatim and this is the one field
    it is asked to produce rather than copy, so it is the one field worth
    bounding. A value that is not a plain year would be used to filter the
    whole corpus, and a silent mis-filter reads as "there were no directives
    that year", which is a false claim about the corpus.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    return text if len(text) == 4 and text.isdigit() else None


def _coerce(raw: dict[str, Any]) -> QueryPlan:
    """Validate the model's object against the contract enums before use."""
    intent = raw.get("intent")
    if not isinstance(intent, str):
        raise ContractViolation(f"plan has no intent: {raw!r}")
    if intent not in enum("intent"):
        raise ContractViolation(f"{intent!r} is not a contract intent")
    scope = raw.get("revision_scope") or "current"
    if scope not in revision_scopes():
        raise ContractViolation(f"{scope!r} is not a contract revision_scope")
    aircraft_raw = raw.get("aircraft") or {}
    if not isinstance(aircraft_raw, dict):
        raise ContractViolation(f"plan.aircraft is {type(aircraft_raw).__name__}")
    allowed = set(contract()["query_plan_schema"]["aircraft"])
    extra = set(aircraft_raw) - allowed
    if extra:
        raise ContractViolation(f"plan.aircraft has undeclared keys {sorted(extra)}")
    ambiguities = raw.get("ambiguities") or []
    if not isinstance(ambiguities, list):
        raise ContractViolation("plan.ambiguities is not a list")
    return QueryPlan(
        intent=intent,
        aircraft={k: aircraft_raw.get(k) for k in sorted(allowed)},
        ad_number=raw.get("ad_number"),
        docket_id=raw.get("docket_id"),
        topic=raw.get("topic"),
        published_year=_year(raw.get("published_year")),
        revision_scope=scope,
        ambiguities=[str(a) for a in ambiguities],
    )


def plan_query(
    client: LLMClient | None, query: str, *, max_tokens: int = 512
) -> PlanOutcome:
    """Plan one query. Returns a reason instead of raising, always.

    The prompt contains the query and nothing else that varies, so the client's
    content-hash cache makes a repeated dev run free.
    """
    import time

    started = time.perf_counter()

    def elapsed() -> float:
        return (time.perf_counter() - started) * 1000.0

    if client is None:
        return PlanOutcome(
            plan=None, stage_ms=elapsed(), model=MODEL_PLAN, reason="no client supplied"
        )
    try:
        completion = client.complete(
            model=MODEL_PLAN,
            system=SYSTEM,
            user=query,
            label="query_plan",
            max_tokens=max_tokens,
            schema=plan_schema(),
            effort="low",
            estimated_usd=0.002,
        )
    except (LLMUnavailable, BudgetExceeded) as exc:
        return PlanOutcome(
            plan=None, stage_ms=elapsed(), model=MODEL_PLAN, reason=str(exc)
        )
    except (ValueError, ContractViolation) as exc:
        return PlanOutcome(
            plan=None,
            stage_ms=elapsed(),
            model=MODEL_PLAN,
            reason=f"planner returned unusable output: {exc}",
        )
    except Exception as exc:  # transport, rate limit, timeout: all advisory here
        return PlanOutcome(
            plan=None,
            stage_ms=elapsed(),
            model=MODEL_PLAN,
            reason=f"{type(exc).__name__}: {exc}",
        )

    raw = completion.parsed
    if raw is None and completion.text.strip():
        try:
            raw = json.loads(completion.text)
        except json.JSONDecodeError as exc:
            return PlanOutcome(
                plan=None,
                stage_ms=elapsed(),
                model=completion.model,
                reason=f"planner output is not JSON: {exc}",
                cached_hit=completion.cached_hit,
                cost_usd=completion.cost_usd,
            )
    if not isinstance(raw, dict):
        return PlanOutcome(
            plan=None,
            stage_ms=elapsed(),
            model=completion.model,
            reason="planner returned no object",
            cached_hit=completion.cached_hit,
            cost_usd=completion.cost_usd,
        )
    try:
        plan = _coerce(raw)
    except ContractViolation as exc:
        return PlanOutcome(
            plan=None,
            stage_ms=elapsed(),
            model=completion.model,
            reason=f"planner violated the contract: {exc}",
            cached_hit=completion.cached_hit,
            cost_usd=completion.cost_usd,
        )
    return PlanOutcome(
        plan=plan,
        stage_ms=elapsed(),
        model=completion.model,
        cached_hit=completion.cached_hit,
        cost_usd=completion.cost_usd,
    )
