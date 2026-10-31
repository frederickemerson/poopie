"""JSON schemas and prompts for rule/action extraction.

The enums are read from contracts/contract.json at runtime and pinned into the
schema with "enum": [...]. This is not decoration. A live call during design
returned operator "equipped with" -- a word the rules engine cannot evaluate --
and a schema without enums lets that through silently, producing vocabulary
nobody downstream can act on. With the enum pinned, the decoder cannot emit it.

The system prompts are byte-stable across every paragraph so the prompt cache
breakpoint in engine/llm/client.py actually hits. Nothing per-paragraph, and
nothing time-varying, may enter them.
"""

from __future__ import annotations

from typing import Any

from .vocab import (
    BASES,
    FIELDS,
    NODE_FOREIGN_AD,
    NODE_SERVICE_BULLETIN,
    OPERATORS,
    AUTHORITIES,
)

_NULLABLE_STRING = {"anyOf": [{"type": "string"}, {"type": "null"}]}

_RANGE = {
    "type": "object",
    "description": "One inclusive serial range. A single serial has low == high.",
    "properties": {"low": {"type": "string"}, "high": {"type": "string"}},
    "required": ["low", "high"],
    "additionalProperties": False,
}

_EXTERNAL_DOC = {
    "type": "object",
    "properties": {
        "document_type": {"type": "string", "enum": [NODE_FOREIGN_AD, NODE_SERVICE_BULLETIN]},
        "authority": {
            "type": "string",
            "enum": list(AUTHORITIES),
            "description": "Issuing authority for a foreign AD; the unlisted value otherwise.",
        },
        "manufacturer": _NULLABLE_STRING,
        "number": {"type": "string", "description": "Document number, e.g. 2025-0208 or 757-25-0320 RB."},
        "revision": _NULLABLE_STRING,
        "dated": _NULLABLE_STRING,
        "label": {"type": "string", "description": "How the AD names the document, verbatim."},
        "source_quote": {"type": "string"},
    },
    "required": [
        "document_type", "authority", "manufacturer", "number",
        "revision", "dated", "label", "source_quote",
    ],
    "additionalProperties": False,
}


def rule_schema() -> dict[str, Any]:
    """Schema for APPLICABILITY extraction, with contract enums pinned."""
    return {
        "type": "object",
        "properties": {
            "rules": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string", "enum": list(FIELDS)},
                        "operator": {"type": "string", "enum": list(OPERATORS)},
                        "value": {
                            "anyOf": [
                                {"type": "string"},
                                {"type": "array", "items": {"anyOf": [{"type": "string"}, _RANGE]}},
                            ]
                        },
                        "source_quote": {
                            "type": "string",
                            "description": "Verbatim span copied from the paragraph text.",
                        },
                        "confidence": {"type": "number"},
                        "unparsed_reason": _NULLABLE_STRING,
                    },
                    "required": [
                        "field", "operator", "value", "source_quote",
                        "confidence", "unparsed_reason",
                    ],
                    "additionalProperties": False,
                },
            },
            "external_applicability": {"type": "array", "items": _EXTERNAL_DOC},
        },
        "required": ["rules", "external_applicability"],
        "additionalProperties": False,
    }


def action_schema() -> dict[str, Any]:
    """Schema for COMPLIANCE / REQUIRED_ACTIONS extraction."""
    return {
        "type": "object",
        "properties": {
            "actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "compliance_time": _NULLABLE_STRING,
                        "compliance_basis": {"type": "string", "enum": list(BASES)},
                        "source_quote": {
                            "type": "string",
                            "description": "Verbatim span copied from the paragraph text.",
                        },
                        "external_ref": _NULLABLE_STRING,
                        "external_document": {"anyOf": [_EXTERNAL_DOC, {"type": "null"}]},
                    },
                    "required": [
                        "description", "compliance_time", "compliance_basis",
                        "source_quote", "external_ref", "external_document",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["actions"],
        "additionalProperties": False,
    }


def _enum_lines() -> str:
    return (
        f"rule_field: {', '.join(FIELDS)}\n"
        f"rule_operator: {', '.join(OPERATORS)}\n"
    )


RULE_SYSTEM = f"""You read one paragraph of a United States FAA airworthiness directive (14 CFR
part 39) and reduce its applicability conditions to machine-checkable rules.

Vocabulary (the response schema enforces it; nothing outside it exists):
{_enum_lines()}
RULES OF EXTRACTION

1. One clause becomes one rule. Alternatives listed inside a clause are ONE
   rule whose value is a list; the reader ORs them. Separate rules are ANDed.
2. source_quote must be copied character for character from the paragraph text
   you are given: the shortest span that carries the condition. Do not
   paraphrase, re-punctuate, straighten curly quotes, fix spacing or join two
   separate spans. It is checked as a substring and a mismatch is a failure.
3. Emit nothing for a clause that constrains no airplane. "certificated in any
   category" and "all serial numbers" are universal statements, not conditions.
4. Models: use model_matches, with the AD's own model designations expanded out
   of shorthand. "Model 757-200 and -300 series airplanes" becomes one rule with
   value ["757-200", "757-300"]. Keep the manufacturer's designation; never
   convert it to an ICAO type code.
5. The manufacturer named in the applicability sentence is its own rule:
   field manufacturer, operator eq, value as the AD writes it.
6. Serial numbers: ONE rule, operator serial_in_range (or serial_not_in_range
   for an exclusion), value a list of {{"low","high"}} objects. A single serial
   is an entry with low == high. "20003 through 20407 inclusive" is one entry.
7. Installed equipment, embodied modifications, STCs and part numbers use
   field equipment / modification / part_number with operator exists or
   not_exists, and value naming the item as the AD names it.
8. If a clause cannot be expressed with the operators above - a numeric
   threshold other than a serial range, a nested exception, a condition on a
   table you cannot see - emit operator "unparsed", value "", and an
   unparsed_reason saying exactly what you could not express. The source_quote
   must still be verbatim. This is the correct, expected answer for hard prose;
   a wrong rule is much worse than an honest unparsed one.
9. If the applicability is identified in, defined by, or limited to the airplanes
   listed in another document - a foreign authority's AD, a service bulletin,
   an attachment - add it to external_applicability as well as emitting the
   rules you can read directly. number is the document's own number; label is
   how this AD names it, verbatim.
10. confidence is your own 0-1 confidence in the rule, not in the paragraph.

Return only the JSON object the schema describes."""


ACTION_SYSTEM = f"""You read one paragraph of a United States FAA airworthiness directive (14 CFR
part 39) and extract the actions it requires and when they are due.

compliance_basis is one of: {', '.join(BASES)}

RULES OF EXTRACTION

1. One required action per entry. description is one plain sentence saying what
   must be done.
2. compliance_time is the deadline as the AD states it, or null when the
   paragraph states none.
3. compliance_basis:
   - a fixed date -> the calendar-date value
   - flight hours or flight cycles -> the matching value
   - any interval measured from this AD's effective date, in days, months or
     years -> the days-after-effective value
   - the deadline is stated in a document this AD only points at (a service
     bulletin, a foreign AD) -> the external-document value, and set
     external_ref to that document's name verbatim plus external_document
   - a time you cannot classify -> the unparsed value
4. source_quote must be copied character for character from the paragraph text:
   the shortest span carrying the action and its time. Do not paraphrase or
   normalize punctuation.
5. A paragraph that only points elsewhere without stating an action of its own
   ("Comply with this AD within the compliance times specified, unless already
   done.") has no actions. Return an empty list. Do not invent one.

Return only the JSON object the schema describes."""


def user_message(paragraph: dict[str, Any]) -> str:
    """Per-paragraph payload. Stays out of the cached system block."""
    return (
        f"AD revision: {paragraph['revision_id']}\n"
        f"Paragraph label: {paragraph['label']}\n"
        f"Heading: {paragraph.get('heading') or ''}\n"
        f"Role: {paragraph['role']}\n"
        f"--- paragraph text begins ---\n"
        f"{paragraph['text']}\n"
        f"--- paragraph text ends ---"
    )


def retry_message(paragraph: dict[str, Any], failures: list[str]) -> str:
    """Second and final attempt, with the exact verification failures fed back."""
    listed = "\n".join(f"- {f}" for f in failures)
    return (
        f"{user_message(paragraph)}\n\n"
        f"Your previous answer was rejected:\n{listed}\n\n"
        f"Copy each source_quote character for character out of the paragraph text above. "
        f"If you cannot find a verbatim span for a condition, emit that condition with "
        f'operator "unparsed" and say so in unparsed_reason instead of adjusting the quote.'
    )
