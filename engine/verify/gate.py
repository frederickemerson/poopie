"""Which refusal fires, in which order, and why that order.

One function, ``evaluate_gate``, is the single place that decides. Keeping it in
one place is the point: the "who can resolve it" distinction in
docs/refusals.md is only useful if it is applied consistently, and six call
sites each making part of the decision is how that goes wrong.

Order is authoritative-signal-first, and each step is a fact rather than a
score wherever a fact exists:

1. An AD number, docket or amendment the graph does not hold. A lookup miss, no
   threshold. ``NO_EVIDENCE``.
2. A model or manufacturer no loaded directive concerns -- distinguished from
   "we cannot filter by model yet", which is not the same claim.
   ``OUT_OF_SCOPE``.
3. The plan names nothing this corpus is keyed on: ``OUT_OF_SCOPE`` when the
   plan's intent is the catch-all, ``NEED_CONFIG`` when it is AD-specific.
   Checked before anything score-based, because it is a fact about the question
   rather than about the corpus.
4. Nothing retrieved at all. ``NO_EVIDENCE``.
5. Best-passage similarity below the tuned floor. ``NO_EVIDENCE``.
6. The rules engine's own refusal, passed through unchanged.
7. ``SUPERSEDED``, appended whether or not anything above fired, because it does
   not block an answer -- it annotates one.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.retrieval.corpus import Corpus  # noqa: E402
from engine.retrieval.entities import Entities  # noqa: E402
from engine.retrieval.graph_filter import series_covering  # noqa: E402
from engine.retrieval.plan import QueryPlan  # noqa: E402
from engine.retrieval.search import SearchResult  # noqa: E402
from engine.verify import refusals as R  # noqa: E402
from engine.verify.rules_adapter import repair_evidence  # noqa: E402
from engine.verify.thresholds import NO_EVIDENCE_COSINE_MIN  # noqa: E402

#: Prefixes used by graph_filter to report a filter it could not satisfy.
_ABSENT_MODEL_PREFIXES = ("model:no matching Rule", "manufacturer:")
_UNAVAILABLE_MODEL_FILTER = "model:no Rule nodes in graph"


@dataclass
class GateResult:
    """Every refusal that fired, and whether an answer may still be written."""

    refusals: list[R.Refusal] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def blocking(self) -> list[R.Refusal]:
        return [r for r in self.refusals if r.blocks]

    @property
    def warnings(self) -> list[R.Refusal]:
        return [r for r in self.refusals if not r.blocks]

    @property
    def answer_allowed(self) -> bool:
        return not self.blocking

    def payloads(self) -> list[dict[str, Any]]:
        return [r.as_payload() for r in self.refusals]


def _missing_identifiers(result: SearchResult) -> list[str]:
    out: list[str] = []
    for item in result.filter_report.get("unavailable", []) or []:
        text = str(item)
        for prefix in ("ad:", "docket:", "amendment:", "revision:"):
            if text.startswith(prefix):
                out.extend(text[len(prefix) :].split(","))
    return [o for o in out if o]


def _absent_models(result: SearchResult) -> list[str]:
    out: list[str] = []
    for item in result.filter_report.get("unavailable", []) or []:
        text = str(item)
        if text == _UNAVAILABLE_MODEL_FILTER:
            continue
        for prefix in _ABSENT_MODEL_PREFIXES:
            if text.startswith(prefix):
                out.append(text.split(":", 1)[-1].strip() or text)
    return [o for o in out if o]


def _evidence(result: SearchResult, limit: int = 8) -> list[str]:
    return [h.paragraph_id for h in result.hits[:limit]]


def _superseded_refusals(
    corpus: Corpus, result: SearchResult, entities: Entities
) -> list[R.Refusal]:
    """One SUPERSEDED warning per retrieved revision that has a newer one."""
    out: list[R.Refusal] = []
    seen: set[str] = set()
    for hit in result.hits:
        meta = corpus.revisions.get(hit.revision_id)
        if meta is None or not meta.superseded_by or hit.revision_id in seen:
            continue
        seen.add(hit.revision_id)
        evidence = [
            h.paragraph_id for h in result.hits if h.revision_id == hit.revision_id
        ]
        newer = corpus.revisions.get(meta.superseded_by)
        out.append(
            R.superseded(
                hit.revision_id,
                meta.superseded_by,
                evidence,
                effective_on=newer.effective_on if newer else None,
                ad_number=meta.ad_number,
            )
        )
    del entities  # entity-side scope is already reflected in what was retrieved
    return out


def _model_only_subject(entities: Entities, plan: QueryPlan | None) -> str | None:
    """The sole model designation an applicability question gives, if that is all.

    ``applicability`` is the one intent whose output is a verdict about a single
    airframe, so it is the one intent a model designation cannot satisfy.
    ``fleet_impact`` legitimately takes a model and is not considered here, and
    a question about a document rather than an aircraft is not under-specified
    just because it mentions a type.
    """
    if plan is None or plan.intent != "applicability":
        return None
    if plan.ad_number or plan.docket_id or entities.has_identifier:
        return None
    if entities.tail_numbers or entities.serial_numbers:
        return None
    aircraft = plan.aircraft or {}
    if aircraft.get("tail_number") or aircraft.get("serial_number"):
        return None
    designation = (aircraft.get("model") or aircraft.get("typecode") or "").strip()
    return designation or None


def evaluate_gate(
    corpus: Corpus,
    entities: Entities,
    result: SearchResult,
    *,
    plan: QueryPlan | None = None,
    rules_decision: Any | None = None,
    cosine_min: float = NO_EVIDENCE_COSINE_MIN,
) -> GateResult:
    """Decide every refusal for one query. Pure function over the stage outputs."""
    gate = GateResult()
    corpus_size = len(corpus.ad_numbers) or len(corpus.revisions)
    evidence = _evidence(result)

    missing = _missing_identifiers(result)
    resolved_identifier = any(
        str(a).startswith(("ad:", "docket:", "amendment:", "revision"))
        for a in (result.filter_report.get("applied") or [])
    )
    if missing and not resolved_identifier:
        gate.refusals.append(
            R.identifier_not_in_corpus(missing, evidence, corpus_size=corpus_size)
        )
        gate.refusals.extend(_superseded_refusals(corpus, result, entities))
        return gate

    absent_models = _absent_models(result)
    if absent_models and not resolved_identifier:
        gate.refusals.append(R.model_not_in_corpus(absent_models, evidence))
        return gate

    # The question identifies nothing this corpus is keyed on: no directive, no
    # docket, no aircraft, from either the plan or the entity pass.
    names_nothing = (
        plan is not None
        and not plan.ad_number
        and not plan.docket_id
        and not any((plan.aircraft or {}).values())
        and not entities.has_identifier
        and not entities.models
        and not entities.typecodes
    )
    # "search" is the plan's catch-all intent; every other one is AD-specific.
    # That enum is the only thing separating "this is not an AD question" from
    # "this is an AD question that has not said which AD", and the two want
    # opposite refusals: one sends the engineer elsewhere, the other tells them
    # what to type. Both are read off the plan, never off the wording.
    plan_names_nothing = names_nothing and plan.intent == "search"
    under_specified = names_nothing and plan.intent != "search"

    # Asked before "did we retrieve anything", and deliberately not conjoined
    # with the similarity floor. Both of those are statements about the corpus;
    # naming nothing is a statement about the question, and it stays true at
    # every score. Conjoining them is what let six traps through: "what is the
    # compliance time?", naming no directive, retrieves a real compliance
    # paragraph from an arbitrary directive at cosine 0.54, so the floor never
    # fired and a confident, correctly cited answer to a question nobody asked
    # went out. A high score is the dangerous case here, not the safe one.
    if plan_names_nothing:
        gate.refusals.append(R.not_an_ad_question(plan.topic, evidence))
        return gate
    if under_specified:
        gate.refusals.append(R.under_specified_ad_question(plan.intent, evidence))
        return gate

    if not result.hits:
        gate.refusals.append(
            R.nothing_above_threshold(0.0, [], corpus_size=corpus_size)
        )
        return gate

    below_floor = result.top_cosine < cosine_min
    if below_floor:
        # Recorded before the return, not after it. This note sat below the
        # NO_EVIDENCE return and so could never be reached, which hid exactly
        # the case it was written to flag: with no plan there is nothing to
        # tell an out-of-scope question apart from an under-specified one, and
        # NO_EVIDENCE becomes a catch-all for both.
        if plan is None and not entities.has_identifier:
            gate.notes.append("no query plan: OUT_OF_SCOPE could not be distinguished")
        gate.refusals.append(
            R.nothing_above_threshold(
                result.top_cosine, evidence, corpus_size=corpus_size
            )
        )
        return gate

    if rules_decision is not None:
        payload = getattr(rules_decision, "refusal", None)
        if payload:
            repaired = repair_evidence(dict(payload), evidence)
            gate.refusals.append(
                R.build(
                    repaired["code"],
                    repaired["detail"],
                    list(repaired.get("evidence_paragraph_ids") or []),
                    resolver=repaired.get("resolvable_by"),
                    allow_empty_evidence=not evidence,
                )
            )

    # Asked last, and only if nothing has blocked yet, because the rules engine's
    # own refusal is the more specific answer whenever it has one: a revision that
    # delegates applicability to a document we do not hold is EXTERNAL_SOURCE_
    # REQUIRED whether or not an airframe was named, and must not be demoted to a
    # question about the aircraft.
    if gate.answer_allowed:
        designation = _model_only_subject(entities, plan)
        if designation is not None:
            series = series_covering(corpus, designation)
            if series:
                gate.refusals.append(
                    R.model_names_a_fleet(designation, series, evidence)
                )
                return gate
            if series is not None:
                # Not a prefix of any series in 1,836 indexed designations, so
                # the claim "no directive here concerns it" is supported.
                gate.refusals.append(R.model_not_in_corpus([designation], evidence))
                return gate
            # series is None: the graph holds no aircraft rules, so absence
            # cannot be distinguished from an unbuilt filter. Say nothing.

    gate.refusals.extend(_superseded_refusals(corpus, result, entities))
    return gate
