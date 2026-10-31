"""Evaluate one Rule against one Aircraft record. Pure, deterministic, no I/O.

Every operator returns one of three outcomes and a reason string that goes
straight into the proof tree the UI renders:

  pass     the rule is satisfied
  fail     the rule is violated -- the AD cannot apply to this airplane
  unknown  the fleet record cannot answer, or the clause was never parsed

A rule is NEVER guessed into pass or fail. Alternatives listed inside one rule
value are ORed (one applicability clause = one rule); separate rules are ANDed
by engine.py.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from . import match, serials
from .vocab import (
    NEGATED,
    OP_EQ,
    OP_EXISTS,
    OP_IN,
    OP_MODEL,
    OP_SERIAL_IN,
    OP_UNPARSED,
    aircraft_field,
)

PASS = "pass"
FAIL = "fail"
UNKNOWN = "unknown"
OUTCOMES = (PASS, FAIL, UNKNOWN)


class RuleValueError(ValueError):
    """A persisted rule value does not match the shape its operator requires."""


@dataclass(frozen=True)
class Condition:
    """One row of the proof tree. JSON-serializable by construction."""

    rule_id: str
    field: str
    operator: str
    value: Any
    aircraft_field: str | None
    aircraft_value: Any
    outcome: str
    reason: str
    paragraph_id: str
    source_quote: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def as_items(value: Any) -> list[str]:
    """Scalar or list value -> list of comparison strings."""
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        items = [str(value)]
    elif isinstance(value, list) and all(isinstance(v, (str, int, float)) for v in value):
        items = [str(v) for v in value]
    else:
        raise RuleValueError(f"expected a string or list of strings, got {value!r}")
    cleaned = [i.strip() for i in items if str(i).strip()]
    if not cleaned:
        raise RuleValueError("value is empty")
    return cleaned


def as_ranges(value: Any) -> list[tuple[str, str]]:
    """Serial-range value -> list of (low, high). A discrete serial is low == high."""
    raw = value if isinstance(value, list) else [value]
    out: list[tuple[str, str]] = []
    for entry in raw:
        if isinstance(entry, dict) and "low" in entry and "high" in entry:
            out.append((str(entry["low"]).strip(), str(entry["high"]).strip()))
        elif isinstance(entry, str) and entry.strip():
            out.append((entry.strip(), entry.strip()))
        else:
            raise RuleValueError(f"expected {{'low':..,'high':..}} entries, got {entry!r}")
    if not out:
        raise RuleValueError("serial range value is empty")
    return out


def _combine(verdicts: list[tuple[bool | None, str]]) -> tuple[bool | None, str]:
    """OR over the alternatives inside one rule, keeping the deciding reason."""
    for verdict, reason in verdicts:
        if verdict is True:
            return True, reason
    unknowns = [r for v, r in verdicts if v is None]
    if unknowns:
        return None, "; ".join(unknowns[:3])
    return False, "; ".join(r for _, r in verdicts[:3])


def _match_one(field: str, aircraft: dict[str, Any], item: str) -> tuple[bool | None, str]:
    """One alternative of an eq/in/model_matches rule."""
    if field == "model":
        return match.model_matches(aircraft, item)
    if field == "manufacturer":
        return match.manufacturer_matches(aircraft, item)
    target = aircraft_field(field)
    own = aircraft.get(target) if target else None
    if field == "typecode":
        same = str(own).strip().upper() == item.strip().upper()
        return same, f"typecode {own!r} {'is' if same else 'is not'} {item!r}"
    if field == "serial_number":
        verdict = serials.equal(str(own), item)
        if verdict is None:
            return None, f"{serials.describe(str(own))} cannot be ordered against {item!r}"
        return verdict, f"serial {own!r} {'is' if verdict else 'is not'} {item!r}"
    if field == "built_year":
        try:
            same = int(str(own).strip()) == int(item.strip())
        except (TypeError, ValueError):
            return None, f"built_year {own!r} or {item!r} is not a year"
        return same, f"built_year {own} {'is' if same else 'is not'} {item}"
    # Free-text fleet columns (operator, engines). Equality proves a match;
    # inequality proves nothing, because these strings are verbatim and
    # unmerged in the source (docs/fleet.md).
    if match.key(str(own)) == match.key(item):
        return True, f"{field} {own!r} equals {item!r}"
    return None, (
        f"{field} {own!r} is not verbatim {item!r}; this fleet column is free text, "
        f"so a difference does not prove a mismatch"
    )


def _serial_verdict(aircraft: dict[str, Any], value: Any) -> tuple[bool | None, str]:
    own = aircraft.get(aircraft_field("serial_number"))
    verdicts = []
    for low, high in as_ranges(value):
        verdict = serials.in_range(str(own) if own is not None else None, low, high)
        if verdict is None:
            verdicts.append((None, f"{serials.describe(own)} is not orderable against {low}-{high}"))
        else:
            inside = "within" if verdict else "outside"
            verdicts.append((verdict, f"serial {own!r} is {inside} {low}-{high} inclusive"))
    return _combine(verdicts)


def _exists_verdict(field: str, aircraft: dict[str, Any], value: Any) -> tuple[bool | None, str]:
    target = aircraft_field(field)
    if target is None:
        return None, (
            f"the fleet data has no {field} column at all (docs/fleet.md), so whether "
            f"this airplane has it is not knowable from the record"
        )
    own = aircraft.get(target)
    if own in (None, ""):
        return None, f"the fleet record has no {field} value"
    wanted = value if isinstance(value, str) else ""
    if wanted.strip():
        return None, (
            f"{field} is recorded as {own!r}, which does not confirm or exclude "
            f"{wanted.strip()!r}; the fleet column is free text, not an installed-"
            f"configuration list"
        )
    return True, f"the fleet record has a {field} value ({own!r})"


def evaluate(rule: dict[str, Any], aircraft: dict[str, Any]) -> Condition:
    """Evaluate one Rule against one Aircraft. Never raises on rule content."""
    operator = rule["operator"]
    field = rule["field"]
    target = aircraft_field(field)
    row = {
        "rule_id": rule["rule_id"],
        "field": field,
        "operator": operator,
        "value": rule.get("value"),
        "aircraft_field": target,
        "aircraft_value": aircraft.get(target) if target else None,
        "paragraph_id": rule["paragraph_id"],
        "source_quote": rule.get("source_quote") or "",
    }

    if operator == OP_UNPARSED:
        reason = rule.get("unparsed_reason") or "the extractor could not reduce this clause to a rule"
        return Condition(outcome=UNKNOWN, reason=reason, **row)

    base = NEGATED.get(operator, operator)
    negated = operator in NEGATED
    try:
        if base == OP_EXISTS:
            verdict, reason = _exists_verdict(field, aircraft, rule.get("value"))
        elif base == OP_SERIAL_IN:
            verdict, reason = _serial_verdict(aircraft, rule.get("value"))
        elif base in (OP_EQ, OP_IN, OP_MODEL):
            if target is None:
                verdict, reason = None, (
                    f"the fleet data has no {field} column at all (docs/fleet.md)"
                )
            elif aircraft.get(target) in (None, ""):
                verdict, reason = None, f"the fleet record has no {field} value"
            else:
                items = as_items(rule.get("value"))
                if base == OP_EQ and len(items) > 1:
                    raise RuleValueError(
                        f"{OP_EQ} takes one value; {len(items)} given (use {OP_IN})"
                    )
                verdict, reason = _combine(
                    [_match_one(field, aircraft, item) for item in items]
                )
        else:  # pragma: no cover - vocab._self_check pins the operator set
            raise RuleValueError(f"no evaluator for operator {operator!r}")
    except RuleValueError as exc:
        return Condition(outcome=UNKNOWN, reason=f"rule value is unusable: {exc}", **row)

    if verdict is None:
        return Condition(outcome=UNKNOWN, reason=reason, **row)
    if negated:
        verdict = not verdict
        reason = f"negated ({operator}): {reason}"
    return Condition(outcome=PASS if verdict else FAIL, reason=reason, **row)
