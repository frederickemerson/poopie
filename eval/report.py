"""Rendering the evaluation results: report.md, and nothing that computes a metric.

Split out of ``eval/run.py`` so each file stays small and single-purpose: ``run``
orchestrates and writes files, this module turns records into markdown, and
``metrics`` does the arithmetic. Like ``metrics`` it is pure over the records --
every number it prints comes from ``eval.metrics``, so the report cannot quietly
disagree with ``metrics.json``.

Two things here are judgement calls worth naming. ``_label_audit`` discloses
labels and numbers that need a caveat rather than dropping them from the tables,
and ``_gallery`` prints every failure in full: docs/positioning.md commits to
publishing the failure modes, so summarising them away would defeat the point.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from engine.llm.ledger import MODEL_ANSWER, MODEL_PLAN
from engine.verify.thresholds import (
    MIN_KEPT_FRACTION,
    NO_EVIDENCE_COSINE_MIN,
    TERM_COVERAGE_MIN,
)
from eval import metrics as M
from eval.questions import Question, summary

ROOT = Path(__file__).resolve().parents[1]

#: Where a refusal came from. Not interchangeable: one is a decision taken
#: before any prose existed, the other is prose that failed verification.
FROM_GATE = "gate"
FROM_VERIFIER = "verifier"


def _git_rev() -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError) as exc:
        return f"unknown ({type(exc).__name__})"


def _table(rows: Sequence[Sequence[str]], header: Sequence[str]) -> str:
    head = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    return "\n".join(head + ["| " + " | ".join(r) + " |" for r in rows])


def _sources(run: dict[str, Any]) -> str:
    """Name the refusals and where each came from."""
    return ", ".join(
        f"{d['code']} ({d.get('source') or FROM_GATE})"
        for d in run.get("refusal_details") or []
    )


def _label_audit(runs: Sequence[dict[str, Any]]) -> list[str]:
    """Labels and numbers that need a caveat. Disclosed, never silently dropped."""
    notes: list[str] = []
    ours = [r for r in runs if r.get("arm") == "ours"]
    decisive = [
        r for r in ours
        if (r["expected"]).get("refusal") == "NEED_CONFIG"
        and r.get("decision") == "DOES_NOT_APPLY"
        and r["expected"].get("ad_number") in (r.get("retrieved_ad_numbers") or [])
    ]
    if decisive:
        notes.append(
            f"{len(decisive)} question(s) labelled `NEED_CONFIG` got a decisive "
            f"`DOES_NOT_APPLY` from the rules engine on the right AD: a model or "
            f"manufacturer rule already excludes the aircraft, so no missing value "
            f"could change the outcome and the label is not supported by the corpus. "
            f"They are still counted against us everywhere above "
            f"({', '.join(r['qid'] for r in decisive)})."
        )
    missing = [
        r for r in ours
        if r["expected"].get("decision") and not r.get("decision_available")
    ]
    if missing:
        notes.append(
            f"{len(missing)} question(s) carry a labelled decision the engine could not "
            f"produce at all; they are excluded from `applicability_accuracy` rather "
            f"than scored, and each record says why."
        )
    errored = [r for r in runs if r.get("error")]
    if errored:
        by_arm = ", ".join(
            f"{a}: {sum(1 for r in errored if r.get('arm') == a)}"
            for a in sorted({r.get("arm") for r in errored})
        )
        notes.append(
            f"{len(errored)} run(s) raised instead of returning a verdict ({by_arm}) "
            f"and are **excluded from every rate above except `target_ad_recall`**, "
            f"which measures retrieval and so still counts a run whose writer failed. "
            f"A denominator can therefore be smaller than the class it came from. "
            f"Each record carries the exception text; the commonest cause is the "
            f"shared cost ledger refusing a call "
            f"({', '.join(sorted(r['qid'] for r in errored))})."
        )
    thin = [
        r for r in ours
        if M.outcome(r) in (M.OUTCOME_FALSE_REFUSAL, M.OUTCOME_REFUSAL_WRONG_CODE)
        and all(d.get("source") == FROM_VERIFIER for d in r["refusal_details"])
    ]
    if thin:
        notes.append(
            f"{len(thin)} of our refusals came from the verifier dropping too much of "
            f"a drafted answer, not from the gate deciding up front. That is a later "
            f"and weaker kind of save: the model had already written the sentence and "
            f"only citation verification stopped it "
            f"({', '.join(r['qid'] for r in thin)})."
        )
    return notes


def _gallery(runs: Sequence[dict[str, Any]], arm: str) -> str:
    """Every failure of this arm, in full. The gallery is a deliverable."""
    rows = M.failures(runs, arm=arm)
    total = sum(1 for r in runs if r.get("arm") == arm)
    if not rows:
        return (
            "No failures recorded for this arm. At this sample size read that as a "
            "small sample, not a solved problem.\n"
        )
    out = [
        f"{len(rows)} of {total} questions went wrong or could not be resolved. "
        f"All of them are here.\n"
    ]
    for run in rows:
        want = run["expected"]
        shown = [s["text"] for s in run["sentences"] if s.get("kept") is not False]
        got = _sources(run) or (f"answered: {shown[0]}" if shown else "nothing")
        out.append(
            f"**{run['qid']}** ({run['kind']}) — {run['question']}\n\n"
            f"- expected: {want['refusal'] or 'an answer'}"
            + (f", decision {want['decision']}" if want["decision"] else "")
            + f"\n- returned: {got[:300]}\n- outcome: `{M.outcome(run)}`\n"
            f"- reason: {M.reason(run)}\n"
        )
    return "\n".join(out)


def _sections(
    runs: Sequence[dict[str, Any]], composition: dict[str, Any], arms: Sequence[str]
) -> list[tuple[str, str]]:
    """Title/body pairs for the report, in order."""
    s = {arm: M.summarise(runs, arm=arm) for arm in arms}

    def grid(keys: Sequence[str], pick, first: str) -> str:
        return _table(
            [[k] + [pick(s[a], k) for a in arms] for k in keys], [first] + list(arms)
        )

    rate = lambda summ, k: summ.rates[k].as_text()  # noqa: E731
    code = lambda summ, k: summ.by_code[k].as_text() if k in summ.by_code else "n/a"  # noqa: E731
    count = lambda summ, k: str(summ.outcomes.get(k, 0))  # noqa: E731
    lat = lambda summ, k: (  # noqa: E731
        f"{summ.p50[k].as_text()} / {summ.p95[k].as_text()}" if k in summ.p50 else "n/a"
    )
    return [
        (
            "Question set",
            f"{composition['total']} questions, generated from the built corpus by "
            f"`eval/questions.py`. {composition['should_refuse']} are traps where the "
            f"honest answer is a refusal.\n\n"
            + _table(
                [[k, str(v)] for k, v in sorted(composition["by_kind"].items())]
                + [["**expects a refusal**", f"**{composition['should_refuse']}**"]],
                ["class", "n"],
            )
            + "\n\n"
            + _table(
                [[k, str(v)] for k, v in sorted(composition["by_expected_code"].items())],
                ["expected refusal code", "n"],
            ),
        ),
        (
            "Results",
            "Numerator/denominator first in every cell: a rate with no sample size is "
            "not a number, and a metric with no data to compute it from reads `n/a` "
            "with the reason.\n\n"
            + _table(
                [[m] + [rate(s[a], m) for a in arms] for m in M.METRIC_ORDER],
                ["metric"] + [f"{a} (n={s[a].n})" for a in arms],
            ),
        ),
        (
            "Refusal recall per code",
            "The wrong code counts as a miss: the code is what tells the user who can "
            "resolve the blocker.\n\n"
            + grid(sorted({c for a in arms for c in s[a].by_code}), code, "expected code"),
        ),
        (
            "Outcomes",
            grid(sorted({k for a in arms for k in s[a].outcomes}), count, "outcome"),
        ),
        (
            "Latency per stage, p50 / p95",
            grid(sorted({x for a in arms for x in s[a].p50}), lat, "stage"),
        ),
        ("Failure gallery", _gallery(runs, arms[0])),
    ]


def report(
    runs: Sequence[dict[str, Any]],
    questions: Sequence[Question],
    harness: Any,
    fleet: Any,
    *,
    arms: Sequence[str],
    warm_up_ms: float,
) -> str:
    """The whole report. ``harness`` and ``fleet`` are read for facts only."""
    composition = summary(list(questions))
    spend = harness.ledger.summary()
    head = [
        "# Evaluation: traceable AD engine vs. plain vector RAG",
        "",
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} at "
        f"commit `{_git_rev()}`. Method and caveats: `docs/evaluation.md`.",
        "",
        f"- Corpus `{harness.corpus.kind}`: {len(harness.corpus.paragraphs)} paragraphs, "
        f"{len(harness.corpus.revisions)} revisions, {len(harness.corpus.ad_numbers)} ADs",
        f"- Fleet: {len(fleet.aircraft)} real aircraft; "
        f"{len(fleet.rules_by_revision)} revisions carry extracted rules",
        f"- Both arms: same corpus, same k=8, same writer prompt, answers written by "
        f"`{MODEL_ANSWER}`; the engine arm also plans with `{MODEL_PLAN}`",
        f"- Spend to date: ${spend['spent_usd']:.4f} of the ${spend['cap_usd']:.2f} cap; "
        f"{spend['cache_hits']} of {spend['calls']} calls served from cache",
        f"- Embedding model warm-up ({warm_up_ms:.0f} ms) excluded from all timings",
        "",
    ]
    short = [
        f"{arm} ({sum(1 for r in runs if r.get('arm') == arm)} of "
        f"{composition['total']})"
        for arm in arms
        if sum(1 for r in runs if r.get("arm") == arm) < composition["total"]
    ]
    partial = (
        [
            f"**This run is incomplete**: {', '.join(short)} questions were run. The "
            f"shared cost ledger ran out mid-run, so every rate above is computed on "
            f"the prefix of the set that completed, not on the whole set."
        ]
        if short
        else []
    )
    limits = partial + _label_audit(runs) + [
        f"Small sample: {composition['total']} questions, "
        f"{composition['should_refuse']} of them traps. Read every rate as an order of "
        f"magnitude, not a point estimate.",
        f"No threshold was tuned for this run, and none has been tuned at all: "
        f"`engine/verify/thresholds.py` states that its values are untuned defaults "
        f"(term coverage {TERM_COVERAGE_MIN}, kept fraction {MIN_KEPT_FRACTION}, "
        f"NO_EVIDENCE cosine floor {NO_EVIDENCE_COSINE_MIN}). The false-refusal and "
        f"wrong-answer rates above are the pair selecting them requires, measured at "
        f"those defaults.",
        "`citation_precision` asks only whether a cited paragraph was retrieved for "
        "that query, so it catches fabricated ids, not weak support; the verifier's "
        "drops are the support measure.",
    ]
    body = [f"## {title}\n\n{text}\n" for title, text in _sections(runs, composition, arms)]
    body.append(
        "## What this evaluation cannot tell you\n\n"
        + "\n".join(f"- {line}" for line in limits)
        + "\n\nFull records: `runs.jsonl` and `metrics.json`.\n"
    )
    return "\n".join(head + body)
