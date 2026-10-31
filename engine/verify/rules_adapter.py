"""Adapter onto ``engine.rules``. Applicability is not reimplemented here.

``engine.rules.engine.decide`` is the only producer of a contract decision value
and it already builds the ``NEED_CONFIG`` / ``CANNOT_DETERMINE`` /
``EXTERNAL_SOURCE_REQUIRED`` payloads, including the who-can-resolve-it
distinction. This module's whole job is to feed it the right inputs and to pass
its verdict through unchanged.

It does repair exactly one thing: a refusal the rules engine emits with an empty
``evidence_paragraph_ids`` (its "no applicability rule was extracted" branch has
no paragraph to point at). docs/refusals.md calls an evidence-free refusal a
defect, so the retrieved paragraphs for the query are used as the evidence of
last resort, and the repair is recorded in the detail text rather than hidden.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RULES_JSONL = ROOT / "data" / "build" / "rules.jsonl"
EXTERNALS_JSONL = ROOT / "data" / "build" / "externals.jsonl"


class RulesUnavailable(RuntimeError):
    """The rules build has not produced its output yet."""


@dataclass
class RuleSet:
    """Rules and applicability delegations, grouped by revision."""

    by_revision: dict[str, list[dict[str, Any]]]
    external_by_revision: dict[str, list[dict[str, Any]]]

    def revisions(self) -> set[str]:
        return set(self.by_revision) | set(self.external_by_revision)


def load_rules(
    rules_path: Path = RULES_JSONL, externals_path: Path = EXTERNALS_JSONL
) -> RuleSet:
    """Load the rules build. Raises ``RulesUnavailable`` if it is not there."""
    from engine.rules import matrix as matrix_mod
    from engine.rules.records import SCOPE_APPLICABILITY

    if not rules_path.exists():
        raise RulesUnavailable(
            f"{rules_path} does not exist. Produced by: "
            f"python3 -m engine.rules extract (see engine/rules/cli.py)"
        )
    rules = matrix_mod.load_jsonl(rules_path)
    delegations = (
        matrix_mod.load_jsonl(externals_path) if externals_path.exists() else []
    )
    return RuleSet(
        by_revision=matrix_mod.group_by(rules, "revision_id"),
        external_by_revision=matrix_mod.group_by(
            [d for d in delegations if d.get("scope") == SCOPE_APPLICABILITY],
            "revision_id",
        ),
    )


def compliance_delegations(
    revision_id: str, externals_path: Path = EXTERNALS_JSONL
) -> list[dict[str, Any]]:
    """Unheld documents that own this revision's *deadlines*, not its scope.

    This is the ``EXTERNAL_SOURCE_REQUIRED`` compliance-time variant in
    docs/refusals.md 1b: the AD applies and we say so, only the deadline is
    refused.
    """
    from engine.rules import matrix as matrix_mod
    from engine.rules.records import SCOPE_COMPLIANCE

    if not externals_path.exists():
        return []
    return [
        d
        for d in matrix_mod.load_jsonl(externals_path)
        if d.get("scope") == SCOPE_COMPLIANCE
        and d.get("revision_id") == revision_id
        and not d.get("held")
    ]


def decide_for(
    aircraft: dict[str, Any], revision_id: str, ruleset: RuleSet
) -> Any | None:
    """One applicability decision, or None when this revision has no rules.

    None means "the rules build does not cover this revision", which is a
    different fact from CANNOT_DETERMINE and must not be reported as one.
    """
    from engine.rules import decide

    rules = ruleset.by_revision.get(revision_id)
    external = ruleset.external_by_revision.get(revision_id, [])
    if rules is None and not external:
        return None
    return decide(
        aircraft,
        rules or [],
        revision_id=revision_id,
        external_applicability=external,
    )


def repair_evidence(
    refusal: dict[str, Any], fallback_paragraph_ids: list[str]
) -> dict[str, Any]:
    """Guarantee the invariant that every refusal can show why.

    Returns the refusal unchanged when it already carries evidence.
    """
    if refusal.get("evidence_paragraph_ids"):
        return refusal
    if not fallback_paragraph_ids:
        return refusal
    repaired = dict(refusal)
    repaired["evidence_paragraph_ids"] = sorted(fallback_paragraph_ids)
    repaired["detail"] = (
        f"{refusal.get('detail', '').rstrip()} "
        f"(the rules engine named no paragraph for this refusal; the paragraphs "
        f"retrieved for this query are shown instead)"
    ).strip()
    return repaired
