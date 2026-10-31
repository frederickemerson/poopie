"""Resolve a query to one aircraft and one revision, then let the rules engine decide.

This is the join between the retrieval stage and the rules engine. It contains
no applicability logic of its own -- every decision value comes from
engine.rules.engine.decide, which is pure code. What lives here is only the
question "which aircraft and which revision is this query about?", which is a
lookup, not a judgement.

When the query names no aircraft there is nothing to decide against, and that
is reported as such rather than guessed at.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engine.paths import BUILD
from engine.rules.engine import Decision, decide

RULES_PATH = BUILD / "rules.jsonl"
DELEGATIONS_PATH = BUILD / "delegations.jsonl"
AIRCRAFT_PATH = BUILD / "nodes.aircraft.jsonl"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


@dataclass
class ApplicabilityStore:
    """Rules, delegations and the fleet, indexed once at startup."""

    rules_by_revision: dict[str, list[dict[str, Any]]]
    delegations_by_revision: dict[str, list[dict[str, Any]]]
    aircraft_by_tail: dict[str, dict[str, Any]]
    aircraft: list[dict[str, Any]]

    @property
    def has_rules(self) -> bool:
        return bool(self.rules_by_revision)

    @classmethod
    def load(cls) -> "ApplicabilityStore":
        rules: dict[str, list[dict[str, Any]]] = {}
        for rule in _read_jsonl(RULES_PATH):
            rules.setdefault(rule.get("revision_id") or "", []).append(rule)

        delegations: dict[str, list[dict[str, Any]]] = {}
        for row in _read_jsonl(DELEGATIONS_PATH):
            delegations.setdefault(row.get("revision_id") or "", []).append(row)

        fleet = [
            {k: v for k, v in node.items() if k != "_type"}
            for node in _read_jsonl(AIRCRAFT_PATH)
            if node.get("_type") == "Aircraft"
        ]
        by_tail = {
            str(a["tail_number"]).upper(): a for a in fleet if a.get("tail_number")
        }
        return cls(rules, delegations, by_tail, fleet)

    # ------------------------------------------------------------ resolution

    def aircraft_from(
        self,
        *,
        tail_number: str | None,
        entities: Any,
        plan: Any | None,
    ) -> dict[str, Any] | None:
        """Find the aircraft this query is about, or None.

        Resolution order is most specific first: an explicit tail number, a tail
        number in the query text, then a serial number. A bare model name is NOT
        enough to pick an aircraft -- several hundred aircraft share a model, and
        silently choosing one would invent the answer.
        """
        for tail in self._candidate_tails(tail_number, entities, plan):
            hit = self.aircraft_by_tail.get(tail.upper())
            if hit:
                return hit

        for serial in (getattr(entities, "serial_numbers", None) or []):
            for a in self.aircraft:
                if a.get("serial_number") and str(a["serial_number"]) == str(serial):
                    return a
        return None

    @staticmethod
    def _candidate_tails(tail_number, entities, plan) -> list[str]:
        out: list[str] = []
        if tail_number:
            out.append(tail_number)
        out += list(getattr(entities, "tail_numbers", None) or [])
        planned = getattr(getattr(plan, "aircraft", None), "tail_number", None)
        if planned:
            out.append(planned)
        return out

    def revision_from(self, *, entities: Any, result: Any) -> str | None:
        """The revision the query is about: the top retrieved hit's revision."""
        for hit in (getattr(result, "hits", None) or []):
            rev = getattr(hit, "revision_id", None)
            if rev:
                return rev
        return None


@dataclass
class ApplicabilityOutcome:
    """What the API layer needs to emit, including why no decision was made."""

    decision: Decision | None
    reason: str | None = None

    @property
    def available(self) -> bool:
        return self.decision is not None


def decide_for_query(
    store: ApplicabilityStore,
    *,
    tail_number: str | None,
    entities: Any,
    plan: Any | None,
    result: Any,
) -> ApplicabilityOutcome:
    """Run the rules engine for this query, or say precisely why we cannot."""
    if not store.has_rules:
        return ApplicabilityOutcome(
            None,
            "No extracted rules are loaded. Run: python3 -m engine.rules.extract_cli",
        )

    revision_id = store.revision_from(entities=entities, result=result)
    if revision_id is None:
        return ApplicabilityOutcome(None, "No revision retrieved for this query.")

    rules = store.rules_by_revision.get(revision_id) or []
    delegations = store.delegations_by_revision.get(revision_id) or []
    if not rules and not delegations:
        return ApplicabilityOutcome(
            None, f"No applicability rules extracted for revision {revision_id}."
        )

    aircraft = store.aircraft_from(tail_number=tail_number, entities=entities, plan=plan)
    if aircraft is None:
        return ApplicabilityOutcome(
            None,
            "No specific aircraft identified. Applicability needs a tail number or "
            "serial number; a model alone matches many aircraft.",
        )

    return ApplicabilityOutcome(
        decide(
            aircraft,
            rules,
            revision_id=revision_id,
            external_applicability=delegations,
        )
    )


def fleet_matrix(store: ApplicabilityStore, revision_id: str) -> dict[str, Any]:
    """Every aircraft's decision for one revision, for the BlastRadius grid."""
    rules = store.rules_by_revision.get(revision_id) or []
    delegations = store.delegations_by_revision.get(revision_id) or []
    cells = []
    counts = {"APPLIES": 0, "DOES_NOT_APPLY": 0, "CANNOT_DETERMINE": 0}
    for aircraft in store.aircraft:
        d = decide(aircraft, rules, revision_id=revision_id, external_applicability=delegations)
        counts[d.decision] = counts.get(d.decision, 0) + 1
        cells.append(
            {
                "tail_number": aircraft.get("tail_number"),
                "operator": aircraft.get("operator"),
                "model": aircraft.get("model"),
                "decision": d.decision,
                "unknown_fields": list(d.unknown_fields),
            }
        )
    return {"revision_id": revision_id, "counts": counts, "cells": cells}
