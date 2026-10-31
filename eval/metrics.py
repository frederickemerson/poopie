"""Metrics: pure functions over recorded runs.

Every function takes run records exactly as ``eval/results/runs.jsonl`` holds
them and returns a ``Rate`` carrying the numerator and denominator beside the
ratio. That shape is the module:

* **A rate without its sample size is not a number.** 100% over three questions
  and over three hundred are different claims, so ``as_text`` prints ``3/3`` first.
* **A metric that cannot be computed says so.** A zero denominator, or every
  case excluded for want of the data to judge it, gives ``rate is None`` and a
  ``reason`` -- never 0% or 100%, which would read as a measurement.

* **Pure.** No I/O, state or model, so anyone can recompute the report.

Two facts come from authoritative sources rather than re-derived here: whether a
refusal code blocks an answer (``engine.verify.refusals.blocks_answer``, off the
contract) and whether a citation resolves (``contracts.contract.validate_citation``).
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
OUTCOME_ANSWERED, OUTCOME_NO_ANSWER = "answered", "no_answer"

#: The gallery holds everything but a correct refusal and a clean answer.
FAILURE_OUTCOMES = (
    OUTCOME_ERROR, OUTCOME_REFUSAL_WRONG_CODE, OUTCOME_WRONG_ANSWER,
    OUTCOME_MISSED_REFUSAL_SILENT, OUTCOME_FALSE_REFUSAL, OUTCOME_NO_ANSWER,
)


@dataclass(frozen=True)
class Rate:
    """A ratio that cannot be printed without its sample size."""
    name: str
    numerator: int
    denominator: int
    excluded: int = 0
    reason: str | None = None

    @property
    def rate(self) -> float | None:
        """None when there is nothing to measure -- not 0.0."""
        return None if self.denominator <= 0 else self.numerator / self.denominator

    def as_text(self) -> str:
        if self.rate is None:
            return f"n/a ({self.reason or 'no cases in the question set'})"
        text = f"{self.numerator}/{self.denominator} ({self.rate * 100:.1f}%)"
        if self.excluded:
            text += f" [{self.excluded} excluded]"
        return text

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "numerator": self.numerator, "rate": self.rate,
                "denominator": self.denominator, "excluded": self.excluded,
                "reason": self.reason, "text": self.as_text()}


@dataclass(frozen=True)
class Latency:
    """One stage's percentile, with the observation count behind it."""

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
        return {"stage": self.stage, "percentile": self.percentile, "ms": self.ms,
                "n": self.n, "reason": self.reason, "text": self.as_text()}

# Record access. Keys are the ones eval/run.py writes into runs.jsonl.

def expected_refusal(run: Run) -> str | None:
    return (run.get("expected") or {}).get("refusal")


def expected_decision(run: Run) -> str | None:
    return (run.get("expected") or {}).get("decision")

def refusal_codes(run: Run) -> list[str]:
    return [str(c) for c in (run.get("refusal_codes") or [])]


def blocking_refusal_codes(run: Run) -> list[str]:
    """Codes that actually withheld an answer. SUPERSEDED is the one code the
    contract marks ``blocks_answer: false``, so it is not a withheld answer."""
    return [c for c in refusal_codes(run) if blocks_answer(c)]


def answered(run: Run) -> bool:
    return bool(run.get("answered"))


def sentences(run: Run) -> list[Mapping[str, Any]]:
    return list(run.get("sentences") or [])


def _expected_blocks(run: Run) -> bool:
    return (code := expected_refusal(run)) is not None and blocks_answer(code)


def outcome(run: Run) -> str:
    """One label per run: the only place these rules live."""
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
    why = (
        f"the rules engine returned {run.get('decision')}"
        if run.get("decision_available")
        else f"no decision was available ({run.get('decision_unavailable_reason')})"
    )
    return {
        OUTCOME_ERROR: f"the run raised: {run.get('error')}",
        OUTCOME_REFUSAL_WRONG_CODE: (
            f"refused {', '.join(refusal_codes(run)) or '(none)'} where {want} was "
            f"expected; the code is what tells the user who can resolve the blocker, "
            f"so the wrong code is a miss"
        ),
        OUTCOME_WRONG_ANSWER: (
            f"answered confidently where {want} was expected; {why}"
        ),
        OUTCOME_MISSED_REFUSAL_SILENT: f"neither refused {want} nor answered",
        OUTCOME_FALSE_REFUSAL: (
            f"refused {', '.join(blocking_refusal_codes(run))} on an answerable question"
        ),
        OUTCOME_NO_ANSWER: "no refusal and no answer: nothing to show",
    }.get(label, "")


def refusal_recall(runs: Sequence[Run]) -> Rate:
    """Of should-refuse questions, the share refused with the *correct* code.
    The wrong code is a miss, per docs/refusals.md: the code tells the user who
    can resolve the blocker, so NO_EVIDENCE where EXTERNAL_SOURCE_REQUIRED was
    due sends them hunting for nothing."""
    cases = [r for r in runs if expected_refusal(r) is not None and not r.get("error")]
    hits = sum(1 for r in cases if expected_refusal(r) in refusal_codes(r))
    empty = "no question in the set expects a refusal" if not cases else None
    return Rate("refusal_recall", hits, len(cases), reason=empty)


def refusal_recall_by_code(runs: Sequence[Run]) -> dict[str, Rate]:
    """Per-code recall: the codes are not interchangeable."""
    out: dict[str, Rate] = {}
    scored = [r for r in runs if not r.get("error")]
    for code in sorted({c for r in scored if (c := expected_refusal(r))}):
        cases = [r for r in scored if expected_refusal(r) == code]
        hits = sum(1 for r in cases if code in refusal_codes(r))
        out[code] = Rate(f"refusal_recall[{code}]", hits, len(cases))
    return out


def false_refusal_rate(runs: Sequence[Run]) -> Rate:
    """Of questions with no expected refusal, the share refused anyway."""
    cases = [r for r in runs if expected_refusal(r) is None and not r.get("error")]
    bad = sum(1 for r in cases if blocking_refusal_codes(r))
    none = "every question in the set expects a refusal" if not cases else None
    return Rate("false_refusal_rate", bad, len(cases), reason=none)


def wrong_answer_rate(runs: Sequence[Run]) -> Rate:
    """The headline: should have refused, answered confidently instead. The
    denominator is the should-refuse questions whose code *blocks* an answer;
    SUPERSEDED is excluded, since the contract has it annotate an answer rather
    than withhold one, so answering there is correct."""
    cases = [r for r in runs if _expected_blocks(r) and not r.get("error")]
    skipped = [r for r in runs if expected_refusal(r) and not _expected_blocks(r)]
    bad = sum(1 for r in cases if answered(r) and not blocking_refusal_codes(r))
    none = "no question expects a blocking refusal" if not cases else None
    return Rate("wrong_answer_rate", bad, len(cases),
                excluded=len(skipped), reason=none)


def citation_precision(runs: Sequence[Run]) -> Rate:
    """Share of cited paragraph ids in that query's retrieved set, judged by
    ``contracts.contract.validate_citation`` -- the verifier's own check."""
    total = good = 0
    for run in runs:
        retrieved = set(run.get("retrieved_paragraph_ids") or [])
        for citation_id in run.get("citation_ids") or []:
            total += 1
            try:
                validate_citation(str(citation_id), retrieved)
            except ContractViolation:
                continue  # counted in the denominator, not in the numerator
            good += 1
    none_cited = "this arm produced no citations to judge" if not total else None
    return Rate("citation_precision", good, total, reason=none_cited)


def citation_coverage(runs: Sequence[Run]) -> Rate:
    """Share of answer sentences carrying a citation, over every sentence the
    writer drafted in both arms: counting only the ones our verifier kept would
    be 100% by construction."""
    drafted = [s for run in runs for s in sentences(run)]
    cited = sum(1 for s in drafted if s.get("citation_ids"))
    no_prose = "this arm produced no answer prose" if not drafted else None
    return Rate("citation_coverage", cited, len(drafted), reason=no_prose)


def target_ad_recall(runs: Sequence[Run]) -> Rate:
    """Where the question names an AD, the share of runs that retrieved that AD.

    The objective part of answer correctness, and the only part scorable without
    a model judging prose: an arm that never retrieved the directive it was
    asked about cannot have answered from it, whatever its sentences say.

    This is the one metric that still counts a run whose *writer* failed, if
    that run recorded a retrieval: retrieval runs before the model, so a
    question the budget could not fund an answer for has still measured its
    retrieval, and dropping it would discard a real observation and leave the
    arms with different denominators. No retrieval at all is excluded, not zero.
    """
    named = [r for r in runs if (r.get("expected") or {}).get("ad_number")]
    cases = [r for r in named if r.get("retrieved_paragraph_ids")]
    hits = sum(
        1 for r in cases
        if r["expected"]["ad_number"] in (r.get("retrieved_ad_numbers") or [])
    )
    no_cases = (
        "no question in the set names an AD"
        if not named
        else "no run retrieved anything" if not cases else None
    )
    return Rate(
        "target_ad_recall", hits, len(cases),
        excluded=len(named) - len(cases), reason=no_cases,
    )


def applicability_accuracy(runs: Sequence[Run]) -> Rate:
    """Where a decision was labelled, the share matching the rules engine.

    A labelled question the engine produced no decision for is *excluded*, not
    scored: counting it wrong would blame the rules engine for a gap in rule
    extraction, and counting it right would be a lie. Exclusions are reported.
    """
    labelled = [r for r in runs if expected_decision(r) and not r.get("error")]
    judged = [r for r in labelled if r.get("decision_available")]
    hits = sum(1 for r in judged if r.get("decision") == expected_decision(r))
    blocked = (
        f"no decision was available for any of the {len(labelled)} labelled "
        f"questions" if labelled else "no question carries a labelled decision"
    )
    return Rate(
        "applicability_accuracy",
        hits,
        len(judged),
        excluded=len(labelled) - len(judged),
        reason=None if judged else blocked,
    )


def _percentile(values: Sequence[float], percentile: int) -> float:
    """Nearest-rank: no interpolation, so a printed p95 really happened."""
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile / 100 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


#: Stages whose clock is a model call, plus the total containing them. Only a
#: run that really made one may report them: a cache hit returns in ~1 ms and a
#: budget rejection faster, and neither is a latency anyone will experience.
MODEL_BACKED_STAGES = ("query_plan", "answer", "total")


def _stage_values(runs: Sequence[Run]) -> dict[str, list[float]]:
    """stage -> its admissible observations, with "total" as one more stage."""
    out: dict[str, list[float]] = {}
    for run in runs:
        # A record without call accounting predates it; trust its timings.
        counted = "model_calls" in run
        fresh = int(run.get("model_calls") or 0) - int(run.get("cached_calls") or 0)
        timings = dict(run.get("stage_ms") or {}, total=run.get("total_ms"))
        for stage, ms in timings.items():
            if counted and fresh <= 0 and str(stage) in MODEL_BACKED_STAGES:
                continue
            if isinstance(ms, (int, float)):
                out.setdefault(str(stage), []).append(float(ms))
    return out


def latency_percentiles(runs: Sequence[Run], percentile: int) -> dict[str, Latency]:
    values = _stage_values(runs)
    if not values:
        return {"total": Latency("total", percentile, None, 0, "nothing was timed")}
    out = {
        stage: Latency(stage, percentile, _percentile(obs, percentile), len(obs))
        for stage, obs in sorted(values.items())
    }
    cached = "cache-served: no fresh model call to time"
    for stage in MODEL_BACKED_STAGES:
        out.setdefault(stage, Latency(stage, percentile, None, 0, cached))
    return out


def latency_p50(runs: Sequence[Run]) -> dict[str, Latency]:
    return latency_percentiles(runs, 50)


def latency_p95(runs: Sequence[Run]) -> dict[str, Latency]:
    return latency_percentiles(runs, 95)


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
            "arm": self.arm, "n": self.n,
            "rates": {k: v.as_dict() for k, v in self.rates.items()},
            "refusal_recall_by_code": {k: v.as_dict() for k, v in self.by_code.items()},
            "latency_p50": {k: v.as_dict() for k, v in self.p50.items()},
            "latency_p95": {k: v.as_dict() for k, v in self.p95.items()},
            "outcomes": self.outcomes,
        }


#: The metrics, in report order. Wrong-answer rate first: in a safety domain it
#: is the number that matters. One registry, so the report's table and
#: ``summarise`` cannot disagree about what was measured.
METRICS = {
    "wrong_answer_rate": wrong_answer_rate,
    "refusal_recall": refusal_recall,
    "false_refusal_rate": false_refusal_rate,
    "target_ad_recall": target_ad_recall,
    "citation_precision": citation_precision,
    "citation_coverage": citation_coverage,
    "applicability_accuracy": applicability_accuracy,
}
METRIC_ORDER = tuple(METRICS)


def summarise(runs: Sequence[Run], *, arm: str) -> ArmSummary:
    """All metrics for one arm's runs."""
    mine = [r for r in runs if r.get("arm") == arm]
    histogram: dict[str, int] = {}
    for run in mine:
        histogram[outcome(run)] = histogram.get(outcome(run), 0) + 1
    return ArmSummary(
        arm=arm,
        n=len(mine),
        rates={name: fn(mine) for name, fn in METRICS.items()},
        by_code=refusal_recall_by_code(mine),
        p50=latency_p50(mine),
        p95=latency_p95(mine),
        outcomes=histogram,
    )


def failures(runs: Sequence[Run], *, arm: str) -> list[Run]:
    """Every run of this arm that went wrong, in question order."""
    return [r for r in runs if r.get("arm") == arm and outcome(r) in FAILURE_OUTCOMES]
