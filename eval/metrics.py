"""Metrics: pure functions over recorded runs.

Every function here takes the same thing -- a sequence of run records, exactly
as ``eval/results/runs.jsonl`` holds them -- and returns a ``Rate`` carrying the
numerator and denominator alongside the ratio. That shape is the point of the
module:

* **A rate without its sample size is not a number.** "100%" over three
  questions and "100%" over three hundred are different claims, so ``Rate``
  cannot be rendered without ``n``; ``as_text`` prints ``3/3`` first.
* **A metric that cannot be computed says so.** When the denominator is zero, or
  every case had to be excluded because the data to judge it is missing, the
  rate is ``None`` and ``reason`` names the cause. It is never reported as 0% or
  100%, which would read as a measurement.
* **Pure.** No I/O, no engine state, no model. The tests build records by hand;
  the report builds them from disk. Both go through the same code.

Two facts are read from authoritative sources rather than re-derived here:
whether a refusal code blocks an answer comes from the contract via
``engine.verify.refusals.blocks_answer``, and whether a citation resolves comes
from ``contracts.contract.validate_citation``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from contracts.contract import ContractViolation, validate_citation
from engine.verify.refusals import blocks_answer

Run = Mapping[str, Any]

# Outcome labels. Stable strings: the report's failure gallery keys off them.
OUTCOME_ERROR = "error"
OUTCOME_REFUSAL_CORRECT = "refusal_correct"
OUTCOME_REFUSAL_WRONG_CODE = "refusal_wrong_code"
OUTCOME_WRONG_ANSWER = "wrong_answer"
OUTCOME_MISSED_REFUSAL_SILENT = "missed_refusal_no_answer"
OUTCOME_FALSE_REFUSAL = "false_refusal"
OUTCOME_ANSWERED = "answered"
OUTCOME_NO_ANSWER = "no_answer"

#: Outcomes that belong in the failure gallery.
FAILURE_OUTCOMES = (
    OUTCOME_ERROR,
    OUTCOME_REFUSAL_WRONG_CODE,
    OUTCOME_WRONG_ANSWER,
    OUTCOME_MISSED_REFUSAL_SILENT,
    OUTCOME_FALSE_REFUSAL,
    OUTCOME_NO_ANSWER,
)


@dataclass(frozen=True)
class Rate:
    """A ratio that can never be printed without its sample size."""

    name: str
    numerator: int
    denominator: int
    excluded: int = 0
    reason: str | None = None

    @property
    def rate(self) -> float | None:
        """None when there is nothing to measure -- not 0.0."""
        if self.denominator <= 0:
            return None
        return self.numerator / self.denominator

    def as_text(self) -> str:
        if self.rate is None:
            return f"n/a ({self.reason or 'no cases in the question set'})"
        text = f"{self.numerator}/{self.denominator} ({self.rate * 100:.1f}%)"
        if self.excluded:
            text += f" [{self.excluded} excluded]"
        return text

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "excluded": self.excluded,
            "rate": self.rate,
            "reason": self.reason,
            "text": self.as_text(),
        }


@dataclass(frozen=True)
class Latency:
    """One stage's percentile, with the number of observations behind it."""

    stage: str
    percentile: int
    ms: float | None
    n: int
    reason: str | None = None

    def as_text(self) -> str:
        if self.ms is None:
            return f"n/a ({self.reason or 'no timings recorded'})"
        return f"{self.ms:.0f} ms (n={self.n})"

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "percentile": self.percentile,
            "ms": self.ms,
            "n": self.n,
            "reason": self.reason,
            "text": self.as_text(),
        }


# --------------------------------------------------------------- record access


def expected_refusal(run: Run) -> str | None:
    return (run.get("expected") or {}).get("refusal")


def expected_decision(run: Run) -> str | None:
    return (run.get("expected") or {}).get("decision")


def refusal_codes(run: Run) -> list[str]:
    return [str(c) for c in (run.get("refusal_codes") or [])]


def blocking_refusal_codes(run: Run) -> list[str]:
    """Codes that actually withheld an answer.

    SUPERSEDED is the one code the contract marks ``blocks_answer: false``, so
    it must not count as a refusal when measuring whether we withheld.
    """
    return [c for c in refusal_codes(run) if blocks_answer(c)]


def answered(run: Run) -> bool:
    return bool(run.get("answered"))


def sentences(run: Run) -> list[Mapping[str, Any]]:
    return list(run.get("sentences") or [])


def _expected_blocks(run: Run) -> bool:
    code = expected_refusal(run)
    return code is not None and blocks_answer(code)


# -------------------------------------------------------------------- outcomes


def outcome(run: Run) -> str:
    """One label per run. Pure, and the only place the rules live."""
    if run.get("error"):
        return OUTCOME_ERROR
    want = expected_refusal(run)
    if want is not None:
        if want in refusal_codes(run):
            return OUTCOME_REFUSAL_CORRECT
        if blocking_refusal_codes(run):
            return OUTCOME_REFUSAL_WRONG_CODE
        return OUTCOME_WRONG_ANSWER if answered(run) else OUTCOME_MISSED_REFUSAL_SILENT
    if blocking_refusal_codes(run):
        return OUTCOME_FALSE_REFUSAL
    return OUTCOME_ANSWERED if answered(run) else OUTCOME_NO_ANSWER


def reason(run: Run) -> str:
    """One line saying what went wrong, for the failure gallery."""
    label = outcome(run)
    want = expected_refusal(run)
    got = refusal_codes(run) or ["(none)"]
    if label == OUTCOME_ERROR:
        return f"the run raised: {run.get('error')}"
    if label == OUTCOME_REFUSAL_WRONG_CODE:
        return (
            f"refused {', '.join(got)} where {want} was expected; the code is what "
            f"tells the user who can resolve it, so the wrong code is a miss"
        )
    if label == OUTCOME_WRONG_ANSWER:
        return (
            f"answered confidently where {want} was expected"
            + (
                f"; no decision was available ({run.get('decision_unavailable_reason')})"
                if not run.get("decision_available")
                else f"; the rules engine returned {run.get('decision')}"
            )
        )
    if label == OUTCOME_MISSED_REFUSAL_SILENT:
        return f"neither refused {want} nor produced an answer"
    if label == OUTCOME_FALSE_REFUSAL:
        return f"refused {', '.join(blocking_refusal_codes(run))} on an answerable question"
    if label == OUTCOME_NO_ANSWER:
        return "no refusal and no answer: the turn produced nothing to show"
    return ""


# --------------------------------------------------------------------- metrics


def refusal_recall(runs: Sequence[Run]) -> Rate:
    """Of should-refuse questions, the share refused with the *correct* code.

    A refusal carrying the wrong code counts as a miss. docs/refusals.md is
    explicit about why: the code is the part that tells the user who can resolve
    the blocker, so NO_EVIDENCE where EXTERNAL_SOURCE_REQUIRED was due sends the
    user to look for a document that was never missing.
    """
    cases = [r for r in runs if expected_refusal(r) is not None]
    hits = sum(1 for r in cases if expected_refusal(r) in refusal_codes(r))
    return Rate(
        "refusal_recall",
        hits,
        len(cases),
        reason="no question in the set expects a refusal" if not cases else None,
    )


def refusal_recall_by_code(runs: Sequence[Run]) -> dict[str, Rate]:
    """Per-code recall, because the codes are not interchangeable."""
    out: dict[str, Rate] = {}
    for code in sorted({c for r in runs if (c := expected_refusal(r))}):
        cases = [r for r in runs if expected_refusal(r) == code]
        hits = sum(1 for r in cases if code in refusal_codes(r))
        out[code] = Rate(f"refusal_recall[{code}]", hits, len(cases))
    return out


def false_refusal_rate(runs: Sequence[Run]) -> Rate:
    """Of questions with no expected refusal, the share refused anyway."""
    cases = [r for r in runs if expected_refusal(r) is None and not r.get("error")]
    bad = sum(1 for r in cases if blocking_refusal_codes(r))
    return Rate(
        "false_refusal_rate",
        bad,
        len(cases),
        reason="every question in the set expects a refusal" if not cases else None,
    )


def wrong_answer_rate(runs: Sequence[Run]) -> Rate:
    """The headline: should have refused, answered confidently instead.

    Denominator is the should-refuse questions whose expected code *blocks* an
    answer. SUPERSEDED is excluded by construction -- the contract says it
    annotates an answer rather than withholding one, so answering is correct
    there and counting it would overstate the rate.
    """
    cases = [r for r in runs if _expected_blocks(r) and not r.get("error")]
    excluded = sum(
        1 for r in runs if expected_refusal(r) is not None and not _expected_blocks(r)
    )
    bad = sum(
        1 for r in cases if answered(r) and not blocking_refusal_codes(r)
    )
    return Rate(
        "wrong_answer_rate",
        bad,
        len(cases),
        excluded=excluded,
        reason="no question expects a blocking refusal" if not cases else None,
    )


def citation_precision(runs: Sequence[Run]) -> Rate:
    """Share of cited paragraph ids that were in that query's retrieved set.

    Judged by ``contracts.contract.validate_citation``, which is the same check
    the verifier applies, so this number cannot disagree with the gate that
    produced the answer.
    """
    total = 0
    good = 0
    for run in runs:
        retrieved = set(run.get("retrieved_paragraph_ids") or [])
        for citation_id in run.get("citation_ids") or []:
            total += 1
            try:
                validate_citation(str(citation_id), retrieved)
            except ContractViolation:
                continue
            good += 1
    return Rate(
        "citation_precision",
        good,
        total,
        reason="this arm produced no citations to judge" if not total else None,
    )


def citation_coverage(runs: Sequence[Run]) -> Rate:
    """Share of answer sentences carrying at least one citation."""
    total = 0
    cited = 0
    for run in runs:
        for sentence in sentences(run):
            total += 1
            if sentence.get("citation_ids"):
                cited += 1
    return Rate(
        "citation_coverage",
        cited,
        total,
        reason="this arm produced no answer prose" if not total else None,
    )


def applicability_accuracy(runs: Sequence[Run]) -> Rate:
    """Where a decision was labelled, the share matching the rules engine.

    A labelled question for which the engine produced no decision at all is
    *excluded*, not scored. Counting it as wrong would blame the rules engine
    for a gap in rule extraction, and counting it as right would be a lie; the
    exclusion count and its reasons are reported next to the rate.
    """
    labelled = [r for r in runs if expected_decision(r) is not None and not r.get("error")]
    judged = [r for r in labelled if r.get("decision_available")]
    hits = sum(1 for r in judged if r.get("decision") == expected_decision(r))
    excluded = len(labelled) - len(judged)
    if not judged:
        return Rate(
            "applicability_accuracy",
            0,
            0,
            excluded=excluded,
            reason=(
                f"no decision was available for any of the {len(labelled)} labelled "
                f"questions"
                if labelled
                else "no question in the set carries a labelled decision"
            ),
        )
    return Rate("applicability_accuracy", hits, len(judged), excluded=excluded)


# -------------------------------------------------------------------- latency


def _percentile(values: Sequence[float], percentile: int) -> float:
    """Nearest-rank percentile: the smallest observation at or above the rank.

    No interpolation, deliberately: with tens of observations an interpolated
    p95 reports a number that was never measured.
    """
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile / 100 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def _stage_values(runs: Sequence[Run]) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for run in runs:
        for stage, ms in (run.get("stage_ms") or {}).items():
            if isinstance(ms, (int, float)):
                out.setdefault(str(stage), []).append(float(ms))
        total = run.get("total_ms")
        if isinstance(total, (int, float)):
            out.setdefault("total", []).append(float(total))
    return out


def latency_percentiles(runs: Sequence[Run], percentile: int) -> dict[str, Latency]:
    values = _stage_values(runs)
    if not values:
        return {
            "total": Latency("total", percentile, None, 0, "no timings were recorded")
        }
    return {
        stage: Latency(stage, percentile, _percentile(obs, percentile), len(obs))
        for stage, obs in sorted(values.items())
    }


def latency_p50(runs: Sequence[Run]) -> dict[str, Latency]:
    return latency_percentiles(runs, 50)


def latency_p95(runs: Sequence[Run]) -> dict[str, Latency]:
    return latency_percentiles(runs, 95)


# --------------------------------------------------------------------- rollup


@dataclass
class ArmSummary:
    """Every metric for one arm, plus the outcome histogram behind them."""

    arm: str
    n: int
    rates: dict[str, Rate] = field(default_factory=dict)
    by_code: dict[str, Rate] = field(default_factory=dict)
    p50: dict[str, Latency] = field(default_factory=dict)
    p95: dict[str, Latency] = field(default_factory=dict)
    outcomes: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "n": self.n,
            "rates": {k: v.as_dict() for k, v in self.rates.items()},
            "refusal_recall_by_code": {k: v.as_dict() for k, v in self.by_code.items()},
            "latency_p50": {k: v.as_dict() for k, v in self.p50.items()},
            "latency_p95": {k: v.as_dict() for k, v in self.p95.items()},
            "outcomes": self.outcomes,
        }


#: Metric order for the report table. Wrong-answer rate first: in a safety
#: domain it is the number that matters, so it does not go below the fold.
METRIC_ORDER = (
    "wrong_answer_rate",
    "refusal_recall",
    "false_refusal_rate",
    "citation_precision",
    "citation_coverage",
    "applicability_accuracy",
)


def summarise(runs: Sequence[Run], *, arm: str) -> ArmSummary:
    """All metrics for one arm's runs. Pure over the records."""
    mine = [r for r in runs if r.get("arm") == arm]
    histogram: dict[str, int] = {}
    for run in mine:
        label = outcome(run)
        histogram[label] = histogram.get(label, 0) + 1
    return ArmSummary(
        arm=arm,
        n=len(mine),
        rates={
            "wrong_answer_rate": wrong_answer_rate(mine),
            "refusal_recall": refusal_recall(mine),
            "false_refusal_rate": false_refusal_rate(mine),
            "citation_precision": citation_precision(mine),
            "citation_coverage": citation_coverage(mine),
            "applicability_accuracy": applicability_accuracy(mine),
        },
        by_code=refusal_recall_by_code(mine),
        p50=latency_p50(mine),
        p95=latency_p95(mine),
        outcomes=histogram,
    )


def failures(runs: Sequence[Run], *, arm: str) -> list[Run]:
    """Every run of this arm that went wrong, in question order. Nothing hidden."""
    return [
        r
        for r in runs
        if r.get("arm") == arm and outcome(r) in FAILURE_OUTCOMES
    ]
