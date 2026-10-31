"""The labelled evaluation set.

Questions are generated FROM the built corpus rather than written against a
snapshot of it, so the set stays valid as the corpus grows and cannot silently
drift into asking about ADs that are no longer loaded. Each carries the answer
we expect and, where applicable, the refusal code we expect -- both written
down before anything is run.

Five classes, mirroring the evaluation plan:
  answerable          - a correct, citable answer exists
  applicability_trap  - looks answerable, but the honest answer is a refusal
  revision            - about supersession / which revision is current
  out_of_scope        - not an AD question at all
  ambiguous           - under-specified; the engine should ask, not guess
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from engine.paths import BUILD
from engine.api.applicability import DELEGATIONS_PATH
from engine.rules.engine import decide

QuestionClass = Literal[
    "answerable", "applicability_trap", "revision", "out_of_scope", "ambiguous"
]


@dataclass(frozen=True)
class Question:
    qid: str
    text: str
    kind: QuestionClass
    expect_refusal: str | None = None
    expect_decision: str | None = None
    expect_paragraph_roles: tuple[str, ...] = ()
    expect_ad_number: str | None = None
    tail_number: str | None = None
    notes: str = ""
    must_mention: tuple[str, ...] = field(default_factory=tuple)

    @property
    def should_refuse(self) -> bool:
        return self.expect_refusal is not None


def _read(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


@dataclass
class CorpusFacts:
    """Everything the generator needs, read once from the build."""

    ads: list[dict[str, Any]]
    revisions: list[dict[str, Any]]
    foreign: list[dict[str, Any]]
    bulletins: list[dict[str, Any]]
    aircraft: list[dict[str, Any]]
    delegations: list[dict[str, Any]]
    rules: list[dict[str, Any]]

    @classmethod
    def load(cls) -> "CorpusFacts":
        nodes = _read(BUILD / "nodes.jsonl")
        by = lambda t: [n for n in nodes if n.get("_type") == t]  # noqa: E731
        return cls(
            ads=by("AD"),
            revisions=by("Revision"),
            foreign=by("ForeignAD"),
            bulletins=by("ServiceBulletin"),
            aircraft=[
                {k: v for k, v in n.items() if k != "_type"}
                for n in _read(BUILD / "nodes.aircraft.jsonl")
                if n.get("_type") == "Aircraft"
            ],
            # The same file the engine decides from, imported rather than
            # spelled again: these were two literals and they drifted. The
            # eval read a stale delegations.jsonl holding 36 rows while the
            # engine read externals.jsonl holding 1,922, so the trap bucket
            # was built from 1.9% of the delegations, and 4 of its facts were
            # no longer true at all.
            delegations=_read(DELEGATIONS_PATH),
            rules=_read(BUILD / "rules.jsonl"),
        )

    def revision_for(self, revision_id: str) -> dict[str, Any] | None:
        return next((r for r in self.revisions if r.get("revision_id") == revision_id), None)


# --------------------------------------------------------------------------
# Fixed questions: these do not depend on which ADs happen to be loaded.
# --------------------------------------------------------------------------

OUT_OF_SCOPE: list[Question] = [
    Question("oos-01", "What is the MEL dispatch limit for an inoperative APU?",
             "out_of_scope", expect_refusal="OUT_OF_SCOPE",
             notes="Minimum Equipment List is a different document class entirely."),
    Question("oos-02", "Who is the CEO of Boeing?", "out_of_scope",
             expect_refusal="OUT_OF_SCOPE", notes="Not about AD content."),
    Question("oos-03", "Write me a pre-flight checklist for a Cessna 172.",
             "out_of_scope", expect_refusal="OUT_OF_SCOPE"),
    Question("oos-04", "What is the current price of jet fuel?", "out_of_scope",
             expect_refusal="OUT_OF_SCOPE"),
    Question("oos-05", "Which ADs apply to my Sukhoi Superjet 100?", "out_of_scope",
             expect_refusal="OUT_OF_SCOPE",
             notes="Model genuinely absent from the corpus."),
    Question("oos-06", "Summarise EASA's rulemaking process.", "out_of_scope",
             expect_refusal="OUT_OF_SCOPE"),
    Question("oos-07", "How do I file a service difficulty report?", "out_of_scope",
             expect_refusal="OUT_OF_SCOPE"),
]

NO_EVIDENCE: list[Question] = [
    Question("noev-01", "What does AD 1998-04-11 require?", "applicability_trap",
             expect_refusal="NO_EVIDENCE",
             notes="Well outside the ingest window; must state the corpus bound."),
    Question("noev-02", "Tell me about AD 2011-07-22 on Honeywell APUs.",
             "applicability_trap", expect_refusal="NO_EVIDENCE"),
    Question("noev-03", "What is required by docket FAA-1999-5678?",
             "applicability_trap", expect_refusal="NO_EVIDENCE"),
]

AMBIGUOUS: list[Question] = [
    Question("amb-01", "Does this AD apply to my aircraft?", "ambiguous",
             expect_refusal="NEED_CONFIG",
             notes="Names neither an AD nor an aircraft."),
    Question("amb-02", "What do I need to do?", "ambiguous",
             expect_refusal="NEED_CONFIG"),
    Question("amb-03", "Is my 767 affected?", "ambiguous",
             expect_refusal="NEED_CONFIG",
             notes="Model only; several hundred 767s in the fleet."),
    Question("amb-04", "When is it due?", "ambiguous", expect_refusal="NEED_CONFIG"),
    Question("amb-05", "Which revision should I be reading?", "ambiguous",
             expect_refusal="NEED_CONFIG"),
]


# --------------------------------------------------------------------------
# Generated questions: grounded in whatever the corpus actually holds.
# --------------------------------------------------------------------------

def _answerable(facts: CorpusFacts, limit: int = 12) -> list[Question]:
    out: list[Question] = []
    delegating = {d.get("revision_id") for d in facts.delegations}
    for rev in facts.revisions:
        if len(out) >= limit:
            break
        rid, ad = rev.get("revision_id"), rev.get("ad_number")
        if not ad or rid in delegating:
            continue  # delegating revisions are traps, not answerable
        out.append(
            Question(
                f"ans-{len(out) + 1:02d}",
                f"What is the unsafe condition addressed by AD {ad}?",
                "answerable",
                expect_ad_number=ad,
                expect_paragraph_roles=("UNSAFE_CONDITION",),
                notes=f"revision {rid}",
            )
        )
    return out


def _applicability_traps(facts: CorpusFacts, limit: int = 10) -> list[Question]:
    """Revisions whose applicability is delegated to a document we do not hold."""
    out: list[Question] = []
    for d in facts.delegations:
        if len(out) >= limit:
            break
        rid = d.get("revision_id")
        rev = facts.revision_for(rid) if rid else None
        ad = (rev or {}).get("ad_number")
        if not ad:
            continue
        ref = d.get("external_ref") or d.get("reference") or "an external document"
        out.append(
            Question(
                f"trap-{len(out) + 1:02d}",
                f"Does AD {ad} apply to my aircraft?",
                "applicability_trap",
                expect_refusal="EXTERNAL_SOURCE_REQUIRED",
                expect_decision="CANNOT_DETERMINE",
                expect_ad_number=ad,
                notes=f"applicability delegated to {ref}; a plausible-sounding answer here is unsafe",
                must_mention=(str(ref)[:40],),
            )
        )
    return out


def _needs_config(facts: CorpusFacts, limit: int = 6) -> list[Question]:
    """Questions whose only blocker is a value the fleet record cannot carry.

    The (revision, aircraft) pair is *selected* with the pure rules engine: it
    enters this bucket only if decide() reaches a NEED_CONFIG refusal on it.
    That is selection, not grading. It establishes that the question is the
    kind of question this bucket exists to ask, and the run then asserts the
    end-to-end behaviour selection never touched -- the code the gate emits,
    that the answer is actually withheld, and that the envelope names the
    missing field and says the engineer can supply it.

    Selecting on nothing but "this revision has a rule on an unavailable
    field" produced questions that were not NEED_CONFIG cases at all, and the
    eval asserted the wrong code for them:

      * the revision also held a clause the extractor could not parse, where
        the engine correctly says CANNOT_DETERMINE -- no value the engineer
        supplies would settle an unparsable clause;
      * the revision was superseded, so a non-blocking SUPERSEDED refusal rode
        along and the question measured supersession as much as the value;
      * the chosen aircraft was already excluded by a serial-number rule, so
        the missing equipment value never came up and DOES_NOT_APPLY was the
        honest answer.

    All three are the engine being right and the label being wrong.
    """
    unavailable = {"equipment", "modification", "part_number", "category"}

    by_revision: dict[str, list[dict[str, Any]]] = {}
    for rule in facts.rules:
        rid = rule.get("revision_id")
        if rid:
            by_revision.setdefault(rid, []).append(rule)

    externals_by_revision: dict[str, list[dict[str, Any]]] = {}
    for row in facts.delegations:
        rid = row.get("revision_id")
        if rid:
            externals_by_revision.setdefault(rid, []).append(row)

    out: list[Question] = []
    seen: set[str] = set()
    for rule in facts.rules:
        if len(out) >= limit:
            break
        if rule.get("field") not in unavailable:
            continue
        rid = rule.get("revision_id")
        if not rid or rid in seen:
            continue
        seen.add(rid)
        rev = facts.revision_for(rid)
        ad = (rev or {}).get("ad_number")
        if not ad:
            continue

        chosen = None
        for aircraft in facts.aircraft:
            if not aircraft.get("tail_number"):
                continue
            decision = decide(
                aircraft,
                by_revision.get(rid, []),
                revision_id=rid,
                external_applicability=externals_by_revision.get(rid, []),
            )
            refusal = decision.refusal or {}
            if refusal.get("code") == "NEED_CONFIG":
                chosen = aircraft
                break
        if chosen is None:
            continue

        out.append(
            Question(
                f"cfg-{len(out) + 1:02d}",
                f"Does AD {ad} apply to {chosen['tail_number']}?",
                "applicability_trap",
                expect_refusal="NEED_CONFIG",
                expect_decision="CANNOT_DETERMINE",
                expect_ad_number=ad,
                tail_number=chosen["tail_number"],
                notes=f"conditioned on {rule.get('field')}, which no fleet record carries",
            )
        )
    return out


def _revision(facts: CorpusFacts, limit: int = 8) -> list[Question]:
    out: list[Question] = []
    for rev in facts.revisions:
        if len(out) >= limit:
            break
        ad = rev.get("ad_number")
        if not ad:
            continue
        out.append(
            Question(
                f"rev-{len(out) + 1:02d}",
                f"Is AD {ad} the current revision, or has it been superseded?",
                "revision",
                expect_ad_number=ad,
                expect_paragraph_roles=("AFFECTED_ADS",),
                notes="SUPERSEDED is non-blocking: an answer must still be produced",
            )
        )
    return out


def build_set(facts: CorpusFacts | None = None) -> list[Question]:
    facts = facts or CorpusFacts.load()
    questions = (
        _answerable(facts)
        + _applicability_traps(facts)
        + _needs_config(facts)
        + _revision(facts)
        + NO_EVIDENCE
        + OUT_OF_SCOPE
        + AMBIGUOUS
    )
    seen: set[str] = set()
    for q in questions:
        if q.qid in seen:
            raise ValueError(f"duplicate question id {q.qid}")
        seen.add(q.qid)
    return questions


def summary(questions: list[Question]) -> dict[str, Any]:
    from collections import Counter

    return {
        "total": len(questions),
        "by_kind": dict(Counter(q.kind for q in questions)),
        "should_refuse": sum(1 for q in questions if q.should_refuse),
        "by_expected_code": dict(
            Counter(q.expect_refusal for q in questions if q.expect_refusal)
        ),
    }


if __name__ == "__main__":
    qs = build_set()
    print(json.dumps(summary(qs), indent=2))
    for q in qs[:5]:
        print(f"  {q.qid:9s} [{q.kind:18s}] {q.text[:70]}")
