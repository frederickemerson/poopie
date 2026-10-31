"""The answer writer, and the envelope that carries its result.

The writer is the second and last model call in the whole path. It runs only
after retrieval and the rules engine have finished, so by the time any prose
exists the evidence it must agree with is already fixed and already on screen.

One decision shapes this module. The writer is NOT asked for character offsets.
A citation id is ``{paragraph_id}@{char_start}-{char_end}``, and a model asked
to produce those numbers will produce plausible ones -- that is exactly the
failure the citation format exists to prevent. Instead the writer names the
evidence the way a person would, by quoting it, and code locates that quote in
the paragraph and computes the offsets itself. A quote that is not present
character for character yields no citation at all; nothing is rounded to the
nearest match. So the offsets in every citation this engine emits were computed
by ``str.find``, never written by a model.

A sentence left with no resolved citation is not repaired here. It travels to
``engine.verify.verifier`` with an empty citation list and is dropped there as
``sentence_carries_no_citation``, so every drop reason the UI shows comes from
one vocabulary.
"""

from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contracts.contract import enum  # noqa: E402
from engine.llm.client import LLMClient, LLMUnavailable  # noqa: E402
from engine.llm.ledger import MODEL_ANSWER, BudgetExceeded  # noqa: E402
from engine.verify.verifier import Sentence, Verification  # noqa: E402

SYSTEM = """You answer questions about FAA airworthiness directives for an \
airline airworthiness engineer.

You are given the question and a numbered list of paragraphs retrieved from \
adopted FAA ADs. Those paragraphs are the ONLY things you may state.

For every sentence you write, quote the exact words in the paragraph that \
establish it. Rules on quotes:
- Copy the quote character for character from the paragraph text, including \
  punctuation, capitalisation and any internal spacing. Do not tidy it, do not \
  ellipse the middle, do not fix an apparent typo.
- Quote the span that carries the claim, not the whole paragraph.
- Every number in your sentence -- a deadline, a count of flight hours, a \
  serial number, a part number -- must appear inside one of that sentence's \
  own quotes.
- Never write a sentence you cannot quote. If the paragraphs do not answer the \
  question, say so in a sentence and quote the closest paragraph you were \
  given, or return no sentences at all.

Do not state whether the AD applies to any particular aircraft: an \
applicability decision has already been made by a rules engine and will be \
shown next to your answer. Do not state a compliance deadline as being in \
force unless the paragraph you quote says so.

Write at most six sentences. Plain declarative prose, no headings, no bullets, \
no preamble, no closing summary."""

#: Each sentence is one object; ``quotes`` names its evidence by paragraph.
ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sentences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "quotes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "paragraph_number": {"type": "integer"},
                                "quote": {"type": "string"},
                            },
                            "required": ["paragraph_number", "quote"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["text", "quotes"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["sentences"],
    "additionalProperties": False,
}

#: Why a quote produced no citation. These are reported, never silently eaten.
QUOTE_UNKNOWN_PARAGRAPH = "quote_names_a_paragraph_not_retrieved"
QUOTE_NOT_VERBATIM = "quote_not_verbatim_in_paragraph"
QUOTE_EMPTY = "quote_is_empty"

_WS = re.compile(r"\s+")


@dataclass
class UnresolvedQuote:
    """A quote the writer offered that code could not turn into a citation."""

    sentence_index: int
    paragraph_id: str | None
    quote: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "sentence_index": self.sentence_index,
            "paragraph_id": self.paragraph_id,
            "quote": self.quote[:160],
            "reason": self.reason,
        }


@dataclass
class AnswerOutcome:
    """What the writer produced, or precisely why it produced nothing."""

    sentences: list[Sentence] = field(default_factory=list)
    unresolved: list[UnresolvedQuote] = field(default_factory=list)
    stage_ms: float = 0.0
    model: str = MODEL_ANSWER
    reason: str | None = None

    @property
    def available(self) -> bool:
        return bool(self.sentences)


def _paragraph_text(hit: Any) -> str:
    return str(getattr(hit, "text", "") or "")


def _render_paragraphs(hits: list[Any]) -> str:
    """The evidence block, numbered so the writer refers to it by number.

    Paragraph ids are shown but never used as the handle: an id like
    ``2026-21902#(o)`` invites a model to assemble a new one. A small integer
    cannot be mistaken for anything the engine will accept as a citation.
    """
    blocks = []
    for number, hit in enumerate(hits, start=1):
        heading = getattr(hit, "heading", None) or getattr(hit, "role", None) or ""
        blocks.append(
            f"[{number}] {getattr(hit, 'ad_number', '?')} paragraph "
            f"{getattr(hit, 'label', '?')} {heading}\n{_paragraph_text(hit)}"
        )
    return "\n\n".join(blocks)


def _locate(quote: str, text: str) -> int:
    """Offset of ``quote`` in ``text``, or -1. Exact match first, then a
    whitespace-tolerant retry.

    The retry exists because XML paragraph text carries newlines and runs of
    spaces from the source document, and a writer copying a quote across a line
    break legitimately renders it with one space. That is the same characters in
    the same order, so accepting it is not a loosening of the verbatim rule --
    the offsets still bound the real span in the real document. Nothing else is
    forgiven: no case folding, no punctuation substitution, no near match.
    """
    found = text.find(quote)
    if found >= 0:
        return found
    needle = _WS.sub(" ", quote).strip()
    if not needle:
        return -1
    # Walk the collapsed form while keeping a map back to original offsets.
    collapsed: list[str] = []
    offsets: list[int] = []
    previous_space = False
    for index, char in enumerate(text):
        if char.isspace():
            if not previous_space:
                collapsed.append(" ")
                offsets.append(index)
            previous_space = True
            continue
        previous_space = False
        collapsed.append(char)
        offsets.append(index)
    hit = "".join(collapsed).find(needle)
    if hit < 0:
        return -1
    return offsets[hit]


def _span_end(quote: str, text: str, start: int) -> int:
    """End offset in the original text for a quote starting at ``start``."""
    if text.startswith(quote, start):
        return start + len(quote)
    # Whitespace-tolerant match: consume the quote's non-space characters.
    wanted = [c for c in quote if not c.isspace()]
    index, position = 0, start
    while position < len(text) and index < len(wanted):
        if text[position].isspace():
            position += 1
            continue
        if text[position] != wanted[index]:
            return -1
        index += 1
        position += 1
    return position if index == len(wanted) else -1


def resolve_quotes(
    raw_sentences: list[dict[str, Any]], hits: list[Any]
) -> tuple[list[Sentence], list[UnresolvedQuote]]:
    """Turn the writer's quotes into citation ids, in code, or report failure."""
    by_number = {number: hit for number, hit in enumerate(hits, start=1)}
    sentences: list[Sentence] = []
    unresolved: list[UnresolvedQuote] = []

    for index, raw in enumerate(raw_sentences):
        text = str(raw.get("text") or "").strip()
        if not text:
            continue
        citation_ids: list[str] = []
        for quote_raw in raw.get("quotes") or []:
            quote = str(quote_raw.get("quote") or "")
            number = quote_raw.get("paragraph_number")
            hit = by_number.get(number) if isinstance(number, int) else None
            if hit is None:
                unresolved.append(
                    UnresolvedQuote(index, None, quote, QUOTE_UNKNOWN_PARAGRAPH)
                )
                continue
            paragraph_id = str(getattr(hit, "paragraph_id", ""))
            if not quote.strip():
                unresolved.append(
                    UnresolvedQuote(index, paragraph_id, quote, QUOTE_EMPTY)
                )
                continue
            body = _paragraph_text(hit)
            offset = _locate(quote, body)
            end = _span_end(quote, body, offset) if offset >= 0 else -1
            if offset < 0 or end < 0:
                unresolved.append(
                    UnresolvedQuote(index, paragraph_id, quote, QUOTE_NOT_VERBATIM)
                )
                continue
            base = int(getattr(hit, "char_start", 0))
            citation_ids.append(f"{paragraph_id}@{base + offset}-{base + end}")
        sentences.append(Sentence(index=index, text=text, citation_ids=citation_ids))

    return sentences, unresolved


def write_answer(
    client: LLMClient | None,
    question: str,
    hits: list[Any],
    *,
    stage_note: str | None = None,
    label: str = "answer",
) -> AnswerOutcome:
    """Draft an answer over the retrieved paragraphs. Never raises.

    ``label`` is the ledger label for this call. It exists so a caller that
    runs the writer more than once per question -- the eval harness runs it
    for both arms -- can have each arm billed separately and still be using
    this one function, which is the only way the two arms are comparable: a
    baseline with its own prompt would be measuring the prompt, not the engine.
    """
    started = time.perf_counter()

    def elapsed() -> float:
        return (time.perf_counter() - started) * 1000.0

    if client is None:
        return AnswerOutcome(stage_ms=elapsed(), reason="no client supplied")
    if not hits:
        return AnswerOutcome(stage_ms=elapsed(), reason="no paragraphs retrieved")

    user = f"Question: {question}\n\nParagraphs:\n\n{_render_paragraphs(hits)}"
    if stage_note:
        user += f"\n\nLegal stage of these documents: {stage_note}"

    try:
        completion = client.complete(
            model=MODEL_ANSWER,
            system=SYSTEM,
            user=user,
            label=label,
            max_tokens=2048,
            schema=ANSWER_SCHEMA,
            estimated_usd=0.02,
        )
    except (LLMUnavailable, BudgetExceeded) as exc:
        return AnswerOutcome(stage_ms=elapsed(), reason=str(exc))

    try:
        raw = json.loads(completion.text)
    except json.JSONDecodeError as exc:
        return AnswerOutcome(stage_ms=elapsed(), reason=f"answer was not JSON: {exc}")
    raw_sentences = raw.get("sentences")
    if not isinstance(raw_sentences, list):
        return AnswerOutcome(stage_ms=elapsed(), reason="answer carried no sentences")

    sentences, unresolved = resolve_quotes(raw_sentences, hits)
    return AnswerOutcome(
        sentences=sentences,
        unresolved=unresolved,
        stage_ms=elapsed(),
        model=getattr(completion, "model", MODEL_ANSWER),
    )


# ------------------------------------------------------------------- envelope


def build_envelope(
    *,
    answer_status: str,
    document_stage: str | None,
    decision: Any | None,
    decision_unavailable: str | None,
    verification: Verification | None,
    answer: AnswerOutcome | None,
    revision_id: str | None,
    superseded_by: str | None,
    refusals: list[dict[str, Any]],
    traversal: dict[str, Any] | None,
    unreviewed_rules: int,
) -> dict[str, Any]:
    """Assemble contract.answer_envelope. Every field present, no silence.

    A field that cannot be filled carries the reason it cannot, which is why
    this takes ``decision_unavailable`` and not just ``decision``.
    """
    if answer_status not in enum("answer_status"):
        raise ValueError(f"{answer_status!r} is not a contract answer_status")

    kept = list(verification.kept) if verification else []
    citations = [
        {
            "sentence_index": v.index,
            "text": v.text,
            "citation_ids": list(v.citation_ids),
            "supporting_citation_id": v.supporting_citation_id,
        }
        for v in kept
    ]

    limitations: list[str] = []
    if document_stage == "ADOPTED_NOT_YET_EFFECTIVE":
        limitations.append(
            "This AD is adopted but not yet effective, so it imposes no "
            "obligation today. Any compliance time quoted runs from its "
            "effective date."
        )
    if document_stage == "PROPOSED":
        limitations.append(
            "This document is a proposal, not a rule. It establishes no "
            "obligation and cannot be complied with."
        )
    for refusal in refusals:
        if refusal.get("code") == "EXTERNAL_SOURCE_REQUIRED":
            limitations.append(
                "Applicability is delegated to a document this engine does not "
                f"hold: {refusal.get('detail') or 'an external source'}."
            )
    if unreviewed_rules:
        limitations.append(
            f"{unreviewed_rules} applicability rule(s) used here are "
            "machine-extracted and not human-reviewed."
        )
    if answer and answer.unresolved:
        limitations.append(
            f"{len(answer.unresolved)} quote(s) offered by the answer writer did "
            "not resolve to a verbatim span and were discarded."
        )
    if verification and verification.dropped:
        limitations.append(
            f"{len(verification.dropped)} drafted sentence(s) failed citation "
            "verification and are not shown."
        )

    missing_inputs: list[str] = []
    for refusal in refusals:
        if refusal.get("code") == "NEED_CONFIG":
            missing_inputs.extend(refusal.get("resolvable_by") or [])
    if decision is not None:
        missing_inputs.extend(list(getattr(decision, "unknown_fields", ()) or ()))

    return {
        "answer_status": answer_status,
        "document_stage": document_stage or "UNKNOWN",
        "applicability_result": getattr(decision, "decision", None),
        "evaluated_conditions": (
            decision.proof_tree()
            if decision is not None
            else {"unavailable": decision_unavailable}
        ),
        "revision_status": {
            "revision_id": revision_id,
            "superseded_by": superseded_by,
            "current": superseded_by is None,
        },
        "citations": citations,
        "missing_inputs": sorted(set(missing_inputs)),
        "limitations": limitations,
        # No traversal_outcome means "not attempted". There is no enum member
        # for that and inventing one would be the exact failure the contract
        # gate exists to catch, so the field carries null plus the reason.
        "traversal": traversal
        or {
            "outcome": None,
            "reason": "reference traversal did not run for this query",
            "followed": [],
            "missing": [],
        },
    }
