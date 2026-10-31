"""The verifier: pure code, no model, under 20 ms.

This is the module that makes the citation claim structural rather than a
promise. The answer writer is instructed to cite, but instruction is not
enforcement; nothing it produces reaches the screen except through here.

Four gates, in this order, cheapest and most decisive first:

1. **Resolvable citation.** ``contract.validate_citation`` requires the cited
   paragraph to be in *this query's* retrieved set. A citation to a real
   paragraph that this query did not retrieve is still a fabrication, and this
   is the gate that catches it.
2. **Verbatim span.** The cited character range must lie inside the paragraph's
   own span and the text at that range must be a substring of the paragraph's
   text. A citation whose offsets do not resolve is not a citation.
3. **Numeric support.** Every digit-bearing term in the sentence must appear in
   the cited span. Deadlines, serials and model suffixes are not averaged in.
4. **Term coverage.** The share of the sentence's content terms present in the
   cited span must reach ``TERM_COVERAGE_MIN``.

A sentence with several citations passes if *any one* of them supports it, which
is the right rule: citing two paragraphs where one is wrong is a citation
error, not a content error, and the sentence is still supported by the other.

Drop reasons are lowercase and descriptive on purpose: a drop reason is not a
refusal code, and ``tests/test_contract.py`` is right to fail any source file
that invents a refusal-code-shaped string.
"""

from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contracts.contract import ContractViolation, validate_citation  # noqa: E402
from engine.verify.terms import Overlap, overlap  # noqa: E402
from engine.verify.thresholds import (  # noqa: E402
    MIN_KEPT_FRACTION,
    MIN_KEPT_SENTENCES,
    REQUIRE_NUMERIC_SUPPORT,
    TERM_COVERAGE_MIN,
)

#: citation_id == "{revision_id}#{label}@{char_start}-{char_end}".
_CITATION = re.compile(r"^(?P<para>.+)@(?P<start>\d+)-(?P<end>\d+)$")

# Drop reasons. Stable strings: the UI and the eval harness both key off them.
DROP_UNPARSEABLE = "citation_unparseable"
DROP_NOT_RETRIEVED = "citation_not_in_retrieved_set"
DROP_SPAN_OUTSIDE = "span_outside_paragraph"
DROP_SPAN_NOT_VERBATIM = "span_not_verbatim_in_paragraph"
DROP_NUMERIC = "numeric_term_absent_from_cited_span"
DROP_COVERAGE = "term_coverage_below_threshold"
DROP_NO_CITATION = "sentence_carries_no_citation"


@dataclass(frozen=True)
class CitedSpan:
    """A resolved citation: the paragraph, and the exact text it points at."""

    citation_id: str
    paragraph_id: str
    char_start: int
    char_end: int
    text: str


@dataclass
class Sentence:
    """One sentence as the answer writer produced it."""

    index: int
    text: str
    citation_ids: list[str] = field(default_factory=list)


@dataclass
class SentenceVerdict:
    index: int
    text: str
    kept: bool
    citation_ids: list[str]
    supporting_citation_id: str | None = None
    reason: str | None = None
    detail: str | None = None
    coverage: float | None = None

    def as_drop_reason(self) -> dict[str, object]:
        return {
            "index": self.index,
            "citation_id": self.citation_ids[0] if self.citation_ids else None,
            "reason": self.reason,
            "detail": self.detail,
        }


@dataclass
class Verification:
    """The verifier's full result, plus the exact SSE payload for it."""

    verdicts: list[SentenceVerdict]
    stage_ms: float

    @property
    def kept(self) -> list[SentenceVerdict]:
        return [v for v in self.verdicts if v.kept]

    @property
    def dropped(self) -> list[SentenceVerdict]:
        return [v for v in self.verdicts if not v.kept]

    @property
    def kept_fraction(self) -> float:
        if not self.verdicts:
            return 0.0
        return len(self.kept) / len(self.verdicts)

    @property
    def too_thin(self) -> bool:
        """True when the surviving answer must be converted to a refusal."""
        if not self.verdicts:
            return True
        if len(self.kept) < MIN_KEPT_SENTENCES:
            return True
        return self.kept_fraction < MIN_KEPT_FRACTION

    def as_payload(self) -> dict[str, object]:
        """The ``verification`` SSE payload, exactly the contract's four keys."""
        return {
            "kept": [v.index for v in self.kept],
            "dropped": [v.index for v in self.dropped],
            "drop_reasons": [v.as_drop_reason() for v in self.dropped],
            "stage_ms": round(self.stage_ms, 3),
        }


def resolve_citation(
    citation_id: str,
    retrieved: dict[str, "object"],
    retrieved_ids: set[str],
) -> tuple[CitedSpan | None, str | None, str | None]:
    """Resolve one citation id. Returns (span, reason, detail).

    ``retrieved`` maps paragraph_id to anything with ``text``, ``char_start`` and
    ``char_end`` -- a ``Paragraph`` or a search ``Hit`` both satisfy it.
    """
    match = _CITATION.match(citation_id.strip())
    if not match:
        return None, DROP_UNPARSEABLE, f"{citation_id!r} is not {{paragraph_id}}@{{start}}-{{end}}"
    paragraph_id = match.group("para")
    start, end = int(match.group("start")), int(match.group("end"))
    try:
        validate_citation(citation_id, retrieved_ids)
    except ContractViolation as exc:
        return None, DROP_NOT_RETRIEVED, str(exc)
    source = retrieved.get(paragraph_id)
    if source is None:
        return None, DROP_NOT_RETRIEVED, f"{paragraph_id!r} has no retrieved record"

    p_start = int(getattr(source, "char_start"))
    p_end = int(getattr(source, "char_end"))
    text = str(getattr(source, "text"))
    if start >= end or start < p_start or end > p_end:
        return (
            None,
            DROP_SPAN_OUTSIDE,
            f"span {start}-{end} is not inside paragraph span {p_start}-{p_end}",
        )
    # Paragraph offsets index Revision.plain_text; the paragraph's own text
    # starts at p_start, so a span inside it slices directly.
    cited = text[start - p_start : end - p_start]
    if not cited.strip() or cited not in text:
        return (
            None,
            DROP_SPAN_NOT_VERBATIM,
            f"text at {start}-{end} is not a verbatim substring of {paragraph_id}",
        )
    return CitedSpan(citation_id, paragraph_id, start, end, cited), None, None


def _best_support(
    sentence: Sentence,
    retrieved: dict[str, object],
    retrieved_ids: set[str],
    *,
    coverage_min: float,
    require_numeric: bool,
) -> SentenceVerdict:
    if not sentence.citation_ids:
        return SentenceVerdict(
            index=sentence.index,
            text=sentence.text,
            kept=False,
            citation_ids=[],
            reason=DROP_NO_CITATION,
            detail="every answer sentence must carry at least one citation_id",
        )

    best: tuple[Overlap, CitedSpan] | None = None
    first_failure: tuple[str, str] | None = None
    for citation_id in sentence.citation_ids:
        span, reason, detail = resolve_citation(citation_id, retrieved, retrieved_ids)
        if span is None:
            if first_failure is None:
                first_failure = (reason or DROP_UNPARSEABLE, detail or "")
            continue
        scored = overlap(sentence.text, span.text)
        if best is None or scored.coverage > best[0].coverage:
            best = (scored, span)

    if best is None:
        reason, detail = first_failure or (DROP_UNPARSEABLE, "")
        return SentenceVerdict(
            index=sentence.index,
            text=sentence.text,
            kept=False,
            citation_ids=list(sentence.citation_ids),
            reason=reason,
            detail=detail,
        )

    scored, span = best
    if require_numeric and not scored.numeric_support:
        return SentenceVerdict(
            index=sentence.index,
            text=sentence.text,
            kept=False,
            citation_ids=list(sentence.citation_ids),
            supporting_citation_id=span.citation_id,
            reason=DROP_NUMERIC,
            detail=f"absent from the cited span: {', '.join(scored.missing_numeric)}",
            coverage=scored.coverage,
        )
    if scored.coverage < coverage_min:
        return SentenceVerdict(
            index=sentence.index,
            text=sentence.text,
            kept=False,
            citation_ids=list(sentence.citation_ids),
            supporting_citation_id=span.citation_id,
            reason=DROP_COVERAGE,
            detail=(
                f"coverage {scored.coverage:.2f} < {coverage_min:.2f}; "
                f"absent: {', '.join(scored.missing_terms[:8])}"
            ),
            coverage=scored.coverage,
        )
    return SentenceVerdict(
        index=sentence.index,
        text=sentence.text,
        kept=True,
        citation_ids=list(sentence.citation_ids),
        supporting_citation_id=span.citation_id,
        coverage=scored.coverage,
    )


def verify(
    sentences: list[Sentence],
    retrieved: dict[str, object],
    *,
    coverage_min: float = TERM_COVERAGE_MIN,
    require_numeric: bool = REQUIRE_NUMERIC_SUPPORT,
) -> Verification:
    """Verify every sentence against the paragraphs retrieved for this query."""
    started = time.perf_counter()
    retrieved_ids = set(retrieved)
    verdicts = [
        _best_support(
            sentence,
            retrieved,
            retrieved_ids,
            coverage_min=coverage_min,
            require_numeric=require_numeric,
        )
        for sentence in sentences
    ]
    return Verification(
        verdicts=verdicts, stage_ms=(time.perf_counter() - started) * 1000.0
    )
