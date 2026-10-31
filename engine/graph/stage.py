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
