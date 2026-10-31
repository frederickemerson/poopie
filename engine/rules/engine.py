"""The applicability decision. Pure code: no network, no LLM, no randomness.

Separate Rules on a Revision are ANDed, which is how an AD applicability
paragraph reads ("Model 757-200 ... equipped with PSU-mounted video monitors").
Alternatives inside one Rule are ORed by evaluate.py.

Order of resolution, and why:

1. Any rule fails  -> DOES_NOT_APPLY. A conjunction with a false term is false,
   whatever else is unknown, so this is safe even when applicability is
   delegated: a foreign document can narrow the FAA-stated set, never widen it.
2. Applicability delegated to a document we do not hold -> CANNOT_DETERMINE,
   refusing EXTERNAL_SOURCE_REQUIRED. The rule set we hold is partial.
3. A rule we could not parse -> CANNOT_DETERMINE, refusing CANNOT_DETERMINE.
   Only a human reading the clause can resolve it.
4. A rule on a field the record cannot answer -> CANNOT_DETERMINE, refusing
   NEED_CONFIG. The engineer can resolve it by supplying the value.
5. Otherwise every rule passed -> APPLIES.

2 outranks 3 outranks 4 because the refusal code tells the user *who* can fix
it, and the blocker nobody-but-a-document can fix has to be named first.

Step 2 is the only step that needs no aircraft, so it is also exposed on its
own as delegated_without_aircraft, for queries that name no airplane.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Iterable, Sequence

from .evaluate import FAIL, PASS, UNKNOWN, Condition, evaluate
from .vocab import (
    DECISION_APPLIES,
    DECISION_EXCLUDED,
    DECISION_UNDETERMINED,
    OP_UNPARSED,
    REFUSAL_EXTERNAL,
    REFUSAL_NEED_CONFIG,
    REFUSAL_UNPARSED,
)

RESOLVE_EXTERNAL = "load the referenced document"
RESOLVE_HUMAN = "a human reads the highlighted clause"
RESOLVE_USER = "the engineer supplies the value"


@dataclass(frozen=True)
class Decision:
    """A decision plus everything needed to defend it."""

    decision: str
    aircraft: dict[str, Any]
    revision_id: str | None
    conditions: tuple[Condition, ...] = ()
    external_documents: tuple[dict[str, Any], ...] = ()
    refusal: dict[str, Any] | None = None
    fired_rule_ids: tuple[str, ...] = ()
    unknown_fields: tuple[str, ...] = ()
    notes: tuple[str, ...] = dc_field(default_factory=tuple)

    # ------------------------------------------------------------------ views

    def proof_tree(self) -> dict[str, Any]:
        """Self-contained, JSON-serializable evidence for the UI."""
        return {
            "decision": self.decision,
            "revision_id": self.revision_id,
            "aircraft": {
                "tail_number": self.aircraft.get("tail_number"),
                "manufacturer": self.aircraft.get("manufacturer"),
                "model": self.aircraft.get("model"),
                "typecode": self.aircraft.get("typecode"),
                "serial_number": self.aircraft.get("serial_number"),
                "operator": self.aircraft.get("operator"),
            },
            "conditions": [c.as_dict() for c in self.conditions],
            "external_documents": [dict(d) for d in self.external_documents],
            "fired_rule_ids": list(self.fired_rule_ids),
            "unknown_fields": list(self.unknown_fields),
            "refusal": dict(self.refusal) if self.refusal else None,
            "notes": list(self.notes),
        }

    def sse_payload(self, stage_ms: float) -> dict[str, Any]:
        """Exactly the keys contract.sse_events['decision'] declares."""
        return {
            "decision": self.decision,
            "fired_rule_ids": list(self.fired_rule_ids),
            "unknown_fields": list(self.unknown_fields),
            "proof_tree": self.proof_tree(),
            "stage_ms": stage_ms,
        }

    def refusal_payload(self) -> dict[str, Any] | None:
        """Exactly the keys contract.sse_events['refusal'] declares."""
        return dict(self.refusal) if self.refusal else None

    def edge_attrs(self) -> dict[str, Any]:
        """Attributes of the contract's AFFECTED_BY edge."""
        return {
            "decision": self.decision,
            "fired_rule_ids": list(self.fired_rule_ids),
            "unknown_fields": list(self.unknown_fields),
        }


def _refusal(code: str, detail: str, resolvable_by: str, paragraph_ids: Iterable[str]) -> dict[str, Any]:
    return {
        "code": code,
        "detail": detail,
        "resolvable_by": resolvable_by,
        "evidence_paragraph_ids": sorted({p for p in paragraph_ids if p}),
    }


def _unheld(external: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Delegations to documents this corpus does not contain."""
    return [d for d in external if not d.get("held")]


def _describe(doc: dict[str, Any]) -> str:
    label = doc.get("label") or doc.get("doc_id") or "an external document"
    dated = doc.get("dated")
    return f"{label} ({dated})" if dated else str(label)


def _external_refusal(unheld: Sequence[dict[str, Any]], *, because: str) -> dict[str, Any]:
    names = "; ".join(_describe(d) for d in unheld)
    return _refusal(
        REFUSAL_EXTERNAL,
        f"Applicability is defined in {names}, which is not in this corpus. {because}",
        RESOLVE_EXTERNAL,
        [d.get("paragraph_id", "") for d in unheld],
    )


def decide(
    aircraft: dict[str, Any],
    rules: Sequence[dict[str, Any]],
    *,
    revision_id: str | None = None,
    external_applicability: Sequence[dict[str, Any]] = (),
) -> Decision:
    """Decide whether a Revision applies to one Aircraft. Side-effect free."""
    conditions = tuple(evaluate(rule, aircraft) for rule in rules)
    unheld = tuple(_unheld(external_applicability))
    base = {
        "aircraft": dict(aircraft),
        "revision_id": revision_id,
        "conditions": conditions,
        "external_documents": unheld,
    }

    failed = [c for c in conditions if c.outcome == FAIL]
    if failed:
        return Decision(
            decision=DECISION_EXCLUDED,
            fired_rule_ids=tuple(c.rule_id for c in failed),
            unknown_fields=(),
            **base,
        )

    unknown = [c for c in conditions if c.outcome == UNKNOWN]
    unknown_fields = tuple(sorted({c.field for c in unknown}))
    passed = tuple(c.rule_id for c in conditions if c.outcome == PASS)

    if unheld:
        return Decision(
            decision=DECISION_UNDETERMINED,
            fired_rule_ids=passed,
            unknown_fields=unknown_fields,
            refusal=_external_refusal(
                unheld,
                because="The rules held here are partial, so applicability cannot be decided.",
            ),
            **base,
        )

    unparsed = [c for c in unknown if c.operator == OP_UNPARSED]
    if unparsed:
        return Decision(
            decision=DECISION_UNDETERMINED,
            fired_rule_ids=passed,
            unknown_fields=unknown_fields,
            refusal=_refusal(
                REFUSAL_UNPARSED,
                "This applicability clause could not be reduced to a checkable rule: "
                + "; ".join(c.reason for c in unparsed[:3]),
                RESOLVE_HUMAN,
                [c.paragraph_id for c in unparsed],
            ),
            **base,
        )

    if unknown:
        wanted = ", ".join(
            f"{c.field} ({c.value})" if isinstance(c.value, str) and c.value else c.field
            for c in unknown[:3]
        )
        return Decision(
            decision=DECISION_UNDETERMINED,
            fired_rule_ids=passed,
            unknown_fields=unknown_fields,
            refusal=_refusal(
                REFUSAL_NEED_CONFIG,
                f"Every other condition is satisfied. Undetermined because the fleet record "
                f"cannot answer: {wanted}.",
                RESOLVE_USER,
                [c.paragraph_id for c in unknown],
            ),
            **base,
        )

    if not conditions:
        return Decision(
            decision=DECISION_UNDETERMINED,
            fired_rule_ids=(),
            unknown_fields=(),
            refusal=_refusal(
                REFUSAL_UNPARSED,
                "No applicability rule was extracted for this revision, so there is nothing "
                "to check this airplane against.",
                RESOLVE_HUMAN,
                [],
            ),
            notes=("no applicability rules on this revision",),
            **base,
        )

    return Decision(
        decision=DECISION_APPLIES,
        fired_rule_ids=passed,
        unknown_fields=(),
        **base,
    )


def delegated_without_aircraft(
    external_applicability: Sequence[dict[str, Any]],
    *,
    revision_id: str | None = None,
) -> Decision | None:
    """The part of applicability that is decidable with no aircraft at all.

    Whether a Revision defines its applicability by reference to a document
    this corpus does not hold is a property of the Revision, not of any one
    airplane. It is knowable before a tail number is, and no amount of
    aircraft detail overcomes it -- so it is answerable for a query that names
    no aircraft, where every other branch of `decide` is not.

    Returns None when nothing is delegated, which is not a decision: with no
    aircraft and no delegation there is genuinely nothing to decide, and
    saying CANNOT_DETERMINE there would refuse a question we simply never
    asked.

    `aircraft` is empty on the returned Decision rather than a placeholder,
    because there is no subject: inventing one would put an airplane in the
    proof tree that the user never named. A caller that *has* an aircraft must
    use `decide` instead, which can still reach DOES_NOT_APPLY on a held rule
    and never need the external document at all -- step 1 above.
    """
    unheld = tuple(_unheld(external_applicability))
    if not unheld:
        return None
    return Decision(
        decision=DECISION_UNDETERMINED,
        aircraft={},
        revision_id=revision_id,
        conditions=(),
        external_documents=unheld,
        refusal=_external_refusal(
            unheld,
            because="Applicability cannot be decided for any airplane without it.",
        ),
        notes=("decided from the revision alone: no aircraft was named",),
    )
