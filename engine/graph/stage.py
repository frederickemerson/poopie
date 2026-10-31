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
#: authoritative discriminator: an adopted rule, a proposal and a document the
#: user loaded are different node types carrying different fields, not three
#: shades of the same thing.
SOURCE_KIND_REVISION = "REVISION"
SOURCE_KIND_NPRM = "NPRM"
SOURCE_KIND_USER_DOCUMENT = "USER_DOCUMENT"

for _value in (SOURCE_KIND_REVISION, SOURCE_KIND_NPRM, SOURCE_KIND_USER_DOCUMENT):
    if _value not in enum("source_kind"):
        raise ValueError(f"{_value!r} is not a contract source_kind")

#: **The allow-list.** The one kind of document whose paragraphs may carry an
#: obligation. An allow-list rather than "anything that is not a proposal",
#: because the set of things that are not an adopted FAA rule is open-ended --
#: it already holds proposals and user uploads, and the next kind added to the
#: contract must be refused by default rather than admitted by omission. The
#: self-check below makes forgetting to decide a startup error.
OBLIGATION_BEARING_SOURCE_KINDS = frozenset({SOURCE_KIND_REVISION})

#: Every contract source_kind this module has deliberately classified. Keeping
#: it exhaustive is the point: a new kind in contracts/contract.json that nobody
#: has ruled on fails here instead of defaulting into, or out of, the fence.
_CLASSIFIED_SOURCE_KINDS = frozenset(
    {SOURCE_KIND_REVISION, SOURCE_KIND_NPRM, SOURCE_KIND_USER_DOCUMENT}
)

if _CLASSIFIED_SOURCE_KINDS != set(enum("source_kind")):
    raise ValueError(
        "engine.graph.stage has not classified every contract source_kind: "
        f"unclassified {sorted(set(enum('source_kind')) - _CLASSIFIED_SOURCE_KINDS)}, "
        f"unknown to the contract {sorted(_CLASSIFIED_SOURCE_KINDS - set(enum('source_kind')))}. "
        "Decide whether the new kind may establish an obligation and say so in "
        "OBLIGATION_BEARING_SOURCE_KINDS."
    )

#: Why a paragraph was refused as the basis of an obligation. One vocabulary,
#: so the reason travels with the refusal instead of being re-worded per caller.
NOT_AN_ADOPTED_DOCUMENT = "source_kind is not an adopted revision"
STAGED_AS_A_PROPOSAL = "document_stage is a proposal"
NOT_AN_FAA_DOCUMENT = (
    "source_kind is a document the user loaded, not an FAA airworthiness directive"
)


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

    A ``USER_DOCUMENT`` can never pass, at any stage. The uploader supplies a
    ``document_stage`` and may well declare EFFECTIVE -- their service bulletin
    or their EASA AD may genuinely be in force in its own world -- but this
    engine has not verified that against anything, and an answer that said "you
    must, by this date" on the strength of a form field would be the whole
    failure this module exists to prevent. The stage is therefore powerless
    here: the gate is the allow-list, and the stage only narrows it further.
    """
    if source_kind not in OBLIGATION_BEARING_SOURCE_KINDS:
        return False
    return document_stage != PROPOSED


def obligation_refusal(source_kind: str | None, document_stage: str | None) -> str | None:
    """Why this paragraph cannot establish an obligation, or None if it can."""
    if may_establish_obligation(source_kind, document_stage):
        return None
    if source_kind == SOURCE_KIND_USER_DOCUMENT:
        return NOT_AN_FAA_DOCUMENT
    if source_kind not in OBLIGATION_BEARING_SOURCE_KINDS:
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


def describe_source_kind(source_kind: str | None) -> str:
    """What kind of document this is, in one sentence a reader can act on.

    ``describe`` answers "what stage is it at", which is only half the question
    once the corpus holds documents the FAA did not publish. A reader looking at
    a citation needs to know *whose* document it is before the stage means
    anything.
    """
    if source_kind == SOURCE_KIND_REVISION:
        return "An adopted FAA airworthiness directive, published in the Federal Register."
    if source_kind == SOURCE_KIND_NPRM:
        return (
            "A notice of proposed rulemaking published by the FAA. A proposal, "
            "open for comment, imposing nothing."
        )
    if source_kind == SOURCE_KIND_USER_DOCUMENT:
        return (
            "A document loaded into this engine by its user. It is not an FAA "
            "airworthiness directive, this engine has not verified it, and nothing "
            "in it can establish an obligation or a compliance deadline here."
        )
    return "The kind of document this came from could not be determined."


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
