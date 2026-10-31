"""Refusals. Code decides; the model never does.

Codes, detail text, ``resolvable_by`` and ``blocks_answer`` all come from
``contracts/contract.json``'s ``refusal_semantics``, so this module cannot drift
from the contract or invent a seventh code.

Division of labour, following docs/refusals.md's "who can resolve it" rule:

* ``engine.rules`` owns the three applicability codes -- ``NEED_CONFIG``,
  ``CANNOT_DETERMINE`` and ``EXTERNAL_SOURCE_REQUIRED`` -- because the thing
  that distinguishes them (a rule's ``operator``, whether the delegated document
  is held, whether the fleet record can answer the field) is a rules fact. This
  module passes those through and only guarantees they carry evidence.
* This module owns the three retrieval-side codes -- ``NO_EVIDENCE``,
  ``OUT_OF_SCOPE`` and ``SUPERSEDED`` -- plus the conversion of an
  over-thinned answer into a refusal.

The authoritative signal is preferred over the score in every case. An AD number
that the graph does not hold is ``NO_EVIDENCE`` on the strength of the graph
lookup, with no threshold involved; the cosine threshold only decides queries
that named nothing we can look up.

If the answer writer emits a refusal itself, ``model_refusal_signal`` records it
as a retrieval/rules miss. It is never used as the refusal.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contracts.contract import contract, validate_enum, validate_event  # noqa: E402
from engine.verify.thresholds import NO_EVIDENCE_COSINE_MIN  # noqa: E402

CODE_NO_EVIDENCE = "NO_EVIDENCE"
CODE_OUT_OF_SCOPE = "OUT_OF_SCOPE"
CODE_SUPERSEDED = "SUPERSEDED"
CODE_NEED_CONFIG = "NEED_CONFIG"


def semantics(code: str) -> dict[str, Any]:
    validate_enum("refusal_code", code)
    return contract()["refusal_semantics"][code]


def blocks_answer(code: str) -> bool:
    """Only SUPERSEDED answers anyway; the contract is the single source."""
    return semantics(code).get("blocks_answer", True) is not False


def resolvable_by(code: str) -> str:
    return str(semantics(code)["resolvable_by"])


@dataclass(frozen=True)
class Refusal:
    code: str
    detail: str
    evidence_paragraph_ids: tuple[str, ...]
    resolvable_by: str | None = None

    @property
    def blocks(self) -> bool:
        return blocks_answer(self.code)

    def as_payload(self) -> dict[str, Any]:
        """The ``refusal`` SSE payload, validated against the contract."""
        payload = {
            "code": self.code,
            "detail": self.detail,
            "resolvable_by": self.resolvable_by or resolvable_by(self.code),
            "evidence_paragraph_ids": list(self.evidence_paragraph_ids),
        }
        validate_event("refusal", payload)
        return payload


class EvidenceFreeRefusal(ValueError):
    """A refusal with nothing to show. docs/refusals.md calls this a defect."""


def build(
    code: str,
    detail: str,
    evidence_paragraph_ids: list[str],
    *,
    resolver: str | None = None,
    allow_empty_evidence: bool = False,
) -> Refusal:
    """Make a refusal, refusing to make an evidence-free one."""
    evidence = tuple(dict.fromkeys(p for p in evidence_paragraph_ids if p))
    if not evidence and not allow_empty_evidence:
        raise EvidenceFreeRefusal(
            f"{code} refusal has no evidence paragraph. Every refusal must be able "
            f"to show why; pass allow_empty_evidence=True only when the corpus "
            f"genuinely retrieved nothing at all."
        )
    return Refusal(
        code=code,
        detail=detail,
        evidence_paragraph_ids=evidence,
        resolvable_by=resolver,
    )


# --------------------------------------------------------------- retrieval side


def identifier_not_in_corpus(
    missing: list[str], evidence_paragraph_ids: list[str], *, corpus_size: int
) -> Refusal:
    """An AD number, docket or amendment the graph does not hold.

    Authoritative: a graph lookup, not a score. The message states the corpus
    bound rather than implying the directive does not exist.
    """
    names = ", ".join(sorted(missing))
    return build(
        CODE_NO_EVIDENCE,
        f"{names} is not in the {corpus_size} airworthiness directives loaded here. "
        f"This corpus is the Federal Register AD series for the ingest window only, "
        f"so the directive may exist outside it.",
        evidence_paragraph_ids,
        allow_empty_evidence=not evidence_paragraph_ids,
    )


def nothing_above_threshold(
    top_cosine: float, evidence_paragraph_ids: list[str], *, corpus_size: int
) -> Refusal:
    return build(
        CODE_NO_EVIDENCE,
        f"Nothing in the {corpus_size} directives loaded here matches this question "
        f"closely enough to answer from (best passage similarity "
        f"{top_cosine:.2f}, threshold {NO_EVIDENCE_COSINE_MIN:.2f}). The closest "
        f"passages found are shown so the gap is visible.",
        evidence_paragraph_ids,
        allow_empty_evidence=not evidence_paragraph_ids,
    )


def model_not_in_corpus(
    models: list[str], evidence_paragraph_ids: list[str]
) -> Refusal:
    """A model or manufacturer named in the query that no loaded AD covers."""
    names = ", ".join(sorted(models))
    return build(
        CODE_OUT_OF_SCOPE,
        f"No airworthiness directive loaded here concerns {names}. This engine "
        f"answers only from the FAA AD text it holds; it does not cover aircraft "
        f"types absent from that set.",
        evidence_paragraph_ids,
        allow_empty_evidence=not evidence_paragraph_ids,
    )


def not_an_ad_question(
    topic: str | None, evidence_paragraph_ids: list[str]
) -> Refusal:
    """The plan found nothing in the question that this corpus indexes.

    Decided from the query plan's own structured output -- no identifier, no
    aircraft, and the catch-all intent -- not from a keyword list.
    """
    subject = f" about {topic}" if topic else ""
    return build(
        CODE_OUT_OF_SCOPE,
        f"This question{subject} does not name a directive, a docket or an aircraft, "
        f"and is not answerable from airworthiness directive text. This engine covers "
        f"FAA AD applicability, requirements and revision history only.",
        evidence_paragraph_ids,
        allow_empty_evidence=not evidence_paragraph_ids,
    )


def under_specified_ad_question(
    intent: str | None, evidence_paragraph_ids: list[str]
) -> Refusal:
    """An airworthiness directive question that names no directive and no aircraft.

    The exact complement of not_an_ad_question, decided from the same
    structured plan output rather than from the words in the question: the
    plan named nothing and the entity pass found nothing, but the intent is
    one of the AD-specific ones rather than the catch-all, so the question IS
    in scope and simply has not said what it is about.

    That distinction is the whole point of emitting NEED_CONFIG here instead
    of NO_EVIDENCE. NO_EVIDENCE says the corpus does not hold the answer, which
    is a statement about us and sends the engineer away. The truth is that the
    person asking can clear this in seconds by naming the AD or the tail
    number, and the refusal should say so.
    """
    asked = f" {intent}" if intent else ""
    return build(
        CODE_NEED_CONFIG,
        f"This is an airworthiness directive{asked} question, but it names neither a "
        f"directive nor an aircraft, so there is nothing to look up yet. Name the AD "
        f"number, the docket, or a tail number and ask again.",
        evidence_paragraph_ids,
        resolver="the engineer names the directive or the aircraft",
        allow_empty_evidence=not evidence_paragraph_ids,
    )


def superseded(
    revision_id: str,
    superseded_by: str,
    evidence_paragraph_ids: list[str],
    *,
    effective_on: str | None = None,
    ad_number: str | None = None,
) -> Refusal:
    """The only non-blocking code: the answer is still given, with a banner."""
    subject = f"AD {ad_number} revision {revision_id}" if ad_number else revision_id
    when = f" (effective {effective_on})" if effective_on else ""
    return build(
        CODE_SUPERSEDED,
        f"{subject} was superseded by {superseded_by}{when}. Answering from the "
        f"revision you asked about; check the current revision before acting.",
        evidence_paragraph_ids,
    )


def answer_too_thin(
    kept: int, total: int, drop_reasons: list[str], evidence_paragraph_ids: list[str]
) -> Refusal:
    """Verification removed too much of the answer to show the rest.

    ``NO_EVIDENCE`` is the right code: what remains is not supported by the
    retrieved passages, which is the same situation as retrieving nothing, and
    the user action is the same.
    """
    reasons = ", ".join(sorted(set(drop_reasons))) or "unsupported"
    return build(
        CODE_NO_EVIDENCE,
        f"Only {kept} of {total} drafted sentences were supported by the cited "
        f"passages ({reasons}), which is too little to show as an answer. The "
        f"retrieved passages are shown instead so they can be read directly.",
        evidence_paragraph_ids,
    )


# ------------------------------------------------------------------- model miss


@dataclass(frozen=True)
class ModelRefusalSignal:
    """The writer tried to refuse. Logged as a defect upstream, never acted on."""

    emitted_code: str | None
    raw_text: str
    retrieved_paragraph_ids: tuple[str, ...]

    def as_log(self) -> dict[str, Any]:
        return {
            "event": "writer_attempted_refusal",
            "emitted_code": self.emitted_code,
            "note": "retrieval or the rules engine should have refused first",
            "retrieved": list(self.retrieved_paragraph_ids),
            "raw": self.raw_text[:400],
        }


def model_refusal_signal(
    emitted_code: str | None, raw_text: str, retrieved_paragraph_ids: list[str]
) -> ModelRefusalSignal:
    return ModelRefusalSignal(
        emitted_code=emitted_code,
        raw_text=raw_text,
        retrieved_paragraph_ids=tuple(retrieved_paragraph_ids),
    )
