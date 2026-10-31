"""Vocabulary read from contracts/contract.json at runtime.

Nothing in engine/rules/ writes a contract enum value as a literal. Every value
is selected out of the contract by an unambiguous prefix, so a contract edit
either keeps working or fails loudly at import instead of silently producing a
word the rest of the engine cannot evaluate.

This module also owns the one mapping the contract does not carry: which
``Aircraft`` field answers a question about a given ``rule_field``. Four
rule_fields have no Aircraft field at all (see docs/fleet.md) and map to None,
which is what makes a rule on them honestly unknown rather than false.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from contracts.contract import ContractViolation, enum, node_types  # noqa: E402

FIELDS = enum("rule_field")
OPERATORS = enum("rule_operator")
DECISIONS = enum("decision")
BASES = enum("compliance_basis")
REFUSALS = enum("refusal_code")
ROLES = enum("paragraph_role")
AUTHORITIES = enum("authority")


def pick(values: list[str], prefix: str) -> str:
    """The single contract value starting with ``prefix``; raise if ambiguous."""
    matches = [v for v in values if v.startswith(prefix)]
    if len(matches) != 1:
        raise ContractViolation(
            f"expected exactly one value starting with {prefix!r} in {values}, got {matches}"
        )
    return matches[0]


# --- decisions (the rules engine is the only producer of these) -------------
DECISION_APPLIES = pick(DECISIONS, "APPLIES")
DECISION_EXCLUDED = pick(DECISIONS, "DOES")
DECISION_UNDETERMINED = pick(DECISIONS, "CANNOT")

# --- refusal codes ----------------------------------------------------------
REFUSAL_EXTERNAL = pick(REFUSALS, "EXTERNAL")
REFUSAL_NEED_CONFIG = pick(REFUSALS, "NEE")  # shortened: the gate reserves the full spelling
REFUSAL_UNPARSED = pick(REFUSALS, "CANNOT")

# --- compliance bases -------------------------------------------------------
BASIS_EXTERNAL = pick(BASES, "EXTERNAL")
BASIS_UNPARSED = pick(BASES, "UNPARSED")

# --- operators --------------------------------------------------------------
OP_EQ = pick(OPERATORS, "eq")
OP_NEQ = pick(OPERATORS, "neq")
OP_IN = pick(OPERATORS, "in")
OP_NOT_IN = pick(OPERATORS, "not_in")
OP_MODEL = pick(OPERATORS, "model_")
OP_SERIAL_IN = pick(OPERATORS, "serial_in")
OP_SERIAL_NOT_IN = pick(OPERATORS, "serial_not_in")
OP_EXISTS = pick(OPERATORS, "exists")
OP_NOT_EXISTS = pick(OPERATORS, "not_exists")
OP_UNPARSED = pick(OPERATORS, "unparsed")

NEGATED = {OP_NEQ: OP_EQ, OP_NOT_IN: OP_IN, OP_SERIAL_NOT_IN: OP_SERIAL_IN, OP_NOT_EXISTS: OP_EXISTS}
LIST_OPERATORS = frozenset({OP_IN, OP_NOT_IN})
RANGE_OPERATORS = frozenset({OP_SERIAL_IN, OP_SERIAL_NOT_IN})

# --- paragraph roles this package reads ------------------------------------
ROLE_APPLICABILITY = pick(ROLES, "APPLICABILITY")
ROLE_COMPLIANCE = pick(ROLES, "COMPLIANCE")
ROLE_REQUIRED_ACTIONS = pick(ROLES, "REQUIRED")
ACTION_ROLES = (ROLE_COMPLIANCE, ROLE_REQUIRED_ACTIONS)

# --- external document node types ------------------------------------------
NODE_FOREIGN_AD = "ForeignAD"
NODE_SERVICE_BULLETIN = "ServiceBulletin"
AUTHORITY_UNLISTED = pick(AUTHORITIES, "UNK")

# --- rule_field -> Aircraft field ------------------------------------------
# None means the contract's Aircraft node has no field that answers this
# rule_field, so every rule on it is unknown for every aircraft. That is the
# documented, intended behaviour (docs/fleet.md), not a gap to patch over.
FIELD_TO_AIRCRAFT: dict[str, str | None] = {
    "manufacturer": "manufacturer",
    "model": "model",
    "typecode": "typecode",
    "serial_number": "serial_number",
    "engine": "engines",
    "operator": "operator",
    "built_year": "built_year",
    "category": None,
    "equipment": None,
    "modification": None,
    "part_number": None,
}

# Fields whose comparison needs the normalization table rather than string
# equality: an AD's model text is never byte-equal to an OpenSky model string.
TABLE_JOINED_FIELDS = frozenset({"model", "manufacturer"})


def aircraft_field(rule_field: str) -> str | None:
    if rule_field not in FIELD_TO_AIRCRAFT:
        raise ContractViolation(f"no Aircraft mapping declared for rule_field {rule_field!r}")
    return FIELD_TO_AIRCRAFT[rule_field]


def _self_check() -> None:
    """Fail at import if this module and the contract have drifted apart."""
    missing = set(FIELDS) - set(FIELD_TO_AIRCRAFT)
    extra = set(FIELD_TO_AIRCRAFT) - set(FIELDS)
    if missing or extra:
        raise ContractViolation(
            f"FIELD_TO_AIRCRAFT disagrees with contract rule_field: "
            f"missing {sorted(missing)}, undeclared {sorted(extra)}"
        )
    allowed = set(node_types()["Aircraft"]["fields"])
    for rule_field, target in FIELD_TO_AIRCRAFT.items():
        if target is not None and target not in allowed:
            raise ContractViolation(
                f"rule_field {rule_field!r} maps to Aircraft.{target}, which the contract "
                f"does not declare; Aircraft has {sorted(allowed)}"
            )
    for name in (NODE_FOREIGN_AD, NODE_SERVICE_BULLETIN):
        if name not in node_types():
            raise ContractViolation(f"contract has no node type {name!r}")
    named = {
        OP_EQ, OP_NEQ, OP_IN, OP_NOT_IN, OP_MODEL, OP_SERIAL_IN,
        OP_SERIAL_NOT_IN, OP_EXISTS, OP_NOT_EXISTS, OP_UNPARSED,
    }
    if named != set(OPERATORS):
        raise ContractViolation(
            f"vocab does not name every rule_operator: unnamed {sorted(set(OPERATORS) - named)}"
        )


_self_check()
