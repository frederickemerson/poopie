"""Legal stage of a document: proposed, adopted, effective, superseded.

This distinction is the difference between "you must do this" and "you may have
to do this later", and it is not cosmetic. In the corpus as built, 25 of 29
final rules were adopted but not yet effective. Answering "what must I do by
when" from one of those, without saying so, asserts an obligation that does not
yet exist.

The stage is derived from authoritative structured fields only -- the node type,
`effective_on`, and `superseded_by` -- never from prose.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from contracts.contract import enum

PROPOSED = "PROPOSED"
ADOPTED_NOT_YET_EFFECTIVE = "ADOPTED_NOT_YET_EFFECTIVE"
EFFECTIVE = "EFFECTIVE"
SUPERSEDED = "SUPERSEDED"
UNKNOWN = "UNKNOWN"


def _as_date(value: Any) -> dt.date | None:
    if not value:
        return None
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def revision_stage(revision: dict[str, Any], *, today: dt.date | None = None) -> str:
    """Stage of one Revision node. Superseded wins over effectiveness."""
    today = today or dt.date.today()
    if revision.get("superseded_by"):
        return SUPERSEDED
    effective = _as_date(revision.get("effective_on"))
    if effective is None:
        return UNKNOWN
    return EFFECTIVE if effective <= today else ADOPTED_NOT_YET_EFFECTIVE


def nprm_stage(_nprm: dict[str, Any]) -> str:
    """An NPRM is always a proposal, whatever its dates say."""
    return PROPOSED


# ------------------------------------------------------- the obligation fence

#: ``Paragraph.source_kind`` values. The parent document type is the
#: authoritative discriminator: an adopted rule and a proposal are different
#: node types carrying different fields, not two shades of the same thing.
SOURCE_KIND_REVISION = "REVISION"
SOURCE_KIND_NPRM = "NPRM"

for _value in (SOURCE_KIND_REVISION, SOURCE_KIND_NPRM):
    if _value not in enum("source_kind"):
        raise ValueError(f"{_value!r} is not a contract source_kind")

#: Why a paragraph was refused as the basis of an obligation. One vocabulary,
#: so the reason travels with the refusal instead of being re-worded per caller.
NOT_AN_ADOPTED_DOCUMENT = "source_kind is not an adopted revision"
STAGED_AS_A_PROPOSAL = "document_stage is a proposal"


def may_establish_obligation(source_kind: str | None, document_stage: str | None) -> bool:
    """Can a statement that an obligation exists rest on this paragraph?

    Only a paragraph of an adopted ``Revision`` can. This is the executable
    form of the contract invariant, and it turns on ``source_kind`` -- the
    parent node type -- rather than on anything read out of the text. A
    proposal's own section headings are word for word those of the rule it
    proposes, so the text cannot tell them apart and must never be asked to.

    An adopted revision whose effective date has not arrived still *may*
    establish an obligation: it imposes one, on a stated future date, and
    ``annotate`` carries that date. Saying "no obligation at all" there would
    be a different wrong answer. ``imposes_obligation_now`` is the separate
    question of whether it bites today.
    """
    if source_kind != SOURCE_KIND_REVISION:
        return False
    return document_stage != PROPOSED


def obligation_refusal(source_kind: str | None, document_stage: str | None) -> str | None:
    """Why this paragraph cannot establish an obligation, or None if it can."""
    if may_establish_obligation(source_kind, document_stage):
        return None
    if source_kind != SOURCE_KIND_REVISION:
        return NOT_AN_ADOPTED_DOCUMENT
    return STAGED_AS_A_PROPOSAL


def split_obligation_evidence(paragraphs: list[Any]) -> tuple[list[Any], list[dict[str, Any]]]:
    """Partition retrieved paragraphs into (can bear an obligation, cannot).

    The second list carries the reason per paragraph, so a caller reports what
    it set aside instead of silently shrinking the evidence. Anything with no
    ``source_kind`` at all is excluded: an unlabelled paragraph is not proof
    that it is adopted.
    """
    eligible: list[Any] = []
    excluded: list[dict[str, Any]] = []
    for paragraph in paragraphs:
        kind = getattr(paragraph, "source_kind", None)
        stage = getattr(paragraph, "document_stage", None)
        if kind is None and isinstance(paragraph, dict):
            kind, stage = paragraph.get("source_kind"), paragraph.get("document_stage")
        reason = obligation_refusal(kind, stage)
        if reason is None:
            eligible.append(paragraph)
            continue
        identifier = (
            paragraph.get("paragraph_id")
            if isinstance(paragraph, dict)
            else getattr(paragraph, "paragraph_id", None)
        )
        excluded.append(
            {
                "paragraph_id": identifier,
                "source_kind": kind,
                "document_stage": stage,
                "reason": reason,
            }
        )
    return eligible, excluded


def describe(stage: str, revision: dict[str, Any] | None = None) -> str:
    """One sentence an engineer can act on."""
    if stage == PROPOSED:
        return (
            "This is a notice of proposed rulemaking. It is a proposal open for "
            "comment and imposes no obligation."
        )
    if stage == ADOPTED_NOT_YET_EFFECTIVE:
        when = (revision or {}).get("effective_on") or "a future date"
        return (
            f"This AD is adopted but does not take effect until {when}. "
            f"Compliance times run from the effective date, not from today."
        )
    if stage == EFFECTIVE:
        when = (revision or {}).get("effective_on")
        return f"This AD is in effect{f' (effective {when})' if when else ''}."
    if stage == SUPERSEDED:
        by = (revision or {}).get("superseded_by")
        return f"This revision has been superseded{f' by {by}' if by else ''}; read the current one."
    return "The effective date of this document could not be determined from its metadata."


def annotate(revision: dict[str, Any], *, today: dt.date | None = None) -> dict[str, Any]:
    """Stage plus its explanation, for attaching to a proof tree or answer."""
    stage = revision_stage(revision, today=today)
    if stage not in enum("document_stage"):
        raise ValueError(f"{stage!r} is not a contract document_stage")
    return {
        "document_stage": stage,
        "effective_on": revision.get("effective_on"),
        "superseded_by": revision.get("superseded_by"),
        "imposes_obligation_now": stage == EFFECTIVE,
        "explanation": describe(stage, revision),
    }


def corpus_breakdown(revisions: list[dict[str, Any]], *, today: dt.date | None = None) -> dict[str, int]:
    counts = {s: 0 for s in enum("document_stage")}
    for r in revisions:
        counts[revision_stage(r, today=today)] += 1
    return counts
