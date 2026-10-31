"""The join between retrieval and the rules engine.

This layer had no tests, which is how a sequencing bug lived here: the aircraft
check returned before the delegation check could run, so
EXTERNAL_SOURCE_REQUIRED was unreachable for any question that named no tail
number -- which is most of them. The ordering is asserted directly below, in
both directions, because getting it backwards is silent: every test of
`decide` itself still passed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.api.applicability import (  # noqa: E402
    ApplicabilityStore,
    decide_for_query,
)
from engine.rules.vocab import (  # noqa: E402
    DECISION_EXCLUDED,
    DECISION_UNDETERMINED,
    REFUSAL_EXTERNAL,
)

REVISION = "2026-21861"
PARAGRAPH = f"{REVISION}#(c)"


def hit(revision_id: str = REVISION) -> SimpleNamespace:
    return SimpleNamespace(revision_id=revision_id, paragraph_id=PARAGRAPH)


def result(*hits) -> SimpleNamespace:
    return SimpleNamespace(hits=list(hits) or [hit()])


def entities(**overrides) -> SimpleNamespace:
    base = {"tail_numbers": [], "serial_numbers": [], "models": [], "typecodes": []}
    return SimpleNamespace(**{**base, **overrides})


def delegation(**overrides) -> dict:
    record = {
        "revision_id": REVISION,
        "paragraph_id": PARAGRAPH,
        "doc_type": "ForeignAD",
        "doc_id": "EASA:2025-0208",
        "label": "EASA AD 2025-0208",
        "dated": "September 24, 2025",
        "held": False,
    }
    record.update(overrides)
    return record


def model_rule(value: str = "A330-941") -> dict:
    return {
        "rule_id": f"{PARAGRAPH}/r01",
        "revision_id": REVISION,
        "paragraph_id": PARAGRAPH,
        "field": "model",
        "operator": "model_matches",
        "value": [value],
        "source_quote": f"Model {value} airplanes",
        "confidence": 0.9,
        "unparsed_reason": None,
    }


def store(*, rules=(), delegations=(), aircraft=()) -> ApplicabilityStore:
    fleet = list(aircraft)
    return ApplicabilityStore(
        rules_by_revision={REVISION: list(rules)} if rules else {"_": []},
        delegations_by_revision={REVISION: list(delegations)} if delegations else {},
        aircraft_by_tail={
            str(a["tail_number"]).upper(): a for a in fleet if a.get("tail_number")
        },
        aircraft=fleet,
    )


def airbus() -> dict:
    return {
        "tail_number": "N101XY",
        "manufacturer": "Airbus",
        "model": "A330-941",
        "typecode": "A339",
        "serial_number": "1983",
    }


# ------------------------------------------------------------------ ordering


def test_delegated_revision_refuses_external_source_with_no_aircraft_named():
    """The regression test. Whether applicability is delegated to a document we
    do not hold is a property of the revision, so it is answerable before any
    aircraft is known -- and it is the honest answer to "which ADs apply to my
    A330-941?", which names no tail number and never will."""
    outcome = decide_for_query(
        store(rules=[model_rule()], delegations=[delegation()]),
        tail_number=None,
        entities=entities(),
        plan=None,
        result=result(),
    )
    assert outcome.available, "a delegation is decidable without an aircraft"
    assert outcome.decision.decision == DECISION_UNDETERMINED
    assert outcome.decision.refusal["code"] == REFUSAL_EXTERNAL
    assert "EASA AD 2025-0208" in outcome.decision.refusal["detail"]
    assert outcome.decision.refusal["evidence_paragraph_ids"] == [PARAGRAPH]


def test_no_aircraft_puts_no_aircraft_in_the_proof_tree():
    """An empty subject, not a placeholder one: the user named no airplane, and
    inventing one would put a tail number in the proof the UI renders."""
    outcome = decide_for_query(
        store(rules=[model_rule()], delegations=[delegation()]),
        tail_number=None,
        entities=entities(),
        plan=None,
        result=result(),
    )
    tree = outcome.decision.proof_tree()
    assert outcome.decision.aircraft == {}
    assert all(v is None for v in tree["aircraft"].values())
    assert tree["conditions"] == []


def test_a_named_aircraft_can_still_be_excluded_despite_the_delegation():
    """Ordering holds in the other direction too: a held rule that fails decides
    DOES_NOT_APPLY and needs no external document, because a foreign AD can
    narrow the FAA-stated set and never widen it. Checking the delegation first
    for the no-aircraft case must not promote it above this."""
    boeing = {
        "tail_number": "N701UW",
        "manufacturer": "Boeing",
        "model": "757-232",
        "typecode": "B752",
        "serial_number": "24729",
    }
    outcome = decide_for_query(
        store(rules=[model_rule()], delegations=[delegation()], aircraft=[boeing]),
        tail_number="N701UW",
        entities=entities(),
        plan=None,
        result=result(),
    )
    assert outcome.decision.decision == DECISION_EXCLUDED


def test_a_held_document_does_not_refuse_without_an_aircraft():
    """A document we DO hold is not a blocker, so this falls through to the
    ordinary "no aircraft named" report rather than refusing."""
    outcome = decide_for_query(
        store(rules=[model_rule()], delegations=[delegation(held=True)]),
        tail_number=None,
        entities=entities(),
        plan=None,
        result=result(),
    )
    assert not outcome.available
    assert "tail number" in (outcome.reason or "")


def test_an_aircraft_named_only_by_serial_number_still_decides():
    outcome = decide_for_query(
        store(rules=[model_rule()], aircraft=[airbus()]),
        tail_number=None,
        entities=entities(serial_numbers=["1983"]),
        plan=None,
        result=result(),
    )
    assert outcome.available
    assert outcome.decision.aircraft["tail_number"] == "N101XY"


# ------------------------------------------------------- the reported reasons


def test_no_rules_and_no_delegation_names_the_revision_it_lacked_them_for():
    outcome = decide_for_query(
        store(rules=[model_rule()]),
        tail_number=None,
        entities=entities(),
        plan=None,
        result=result(hit("some-other-revision")),
    )
    assert not outcome.available
    assert "some-other-revision" in (outcome.reason or "")


def test_no_retrieval_is_reported_as_no_revision_not_as_no_aircraft():
    outcome = decide_for_query(
        store(rules=[model_rule()]),
        tail_number=None,
        entities=entities(),
        plan=None,
        result=SimpleNamespace(hits=[]),
    )
    assert not outcome.available
    assert "revision" in (outcome.reason or "")


def test_every_command_a_reason_tells_the_user_to_run_exists():
    """This message pointed at `python3 -m engine.rules.extract_cli` for as long
    as that module had been deleted. A reason the user cannot act on is worse
    than no reason, so the commands named here are checked against the
    Makefile rather than trusted."""
    outcome = decide_for_query(
        ApplicabilityStore({}, {}, {}, []),
        tail_number=None,
        entities=entities(),
        plan=None,
        result=result(),
    )
    assert not outcome.available
    targets = set(re.findall(r"^([a-z][a-z-]*):", (ROOT / "Makefile").read_text(), re.M))
    named = re.findall(r"make ([a-z][a-z-]*)", outcome.reason or "")
    assert named, "the reason should tell the user what to run"
    assert not set(named) - targets, f"no such make target: {set(named) - targets}"


# ------------------------------------------- one source of delegation truth


def test_the_eval_decides_from_the_same_delegations_as_the_engine():
    """Two modules spelled this path as two literals and they drifted.

    The engine read externals.jsonl (1,922 rows) while the eval read a stale
    delegations.jsonl (36 rows), so the labelled set was built from 1.9% of
    the delegations and four of its facts were no longer true. The eval now
    imports the engine's constant, and this pins that they resolve to the same
    records -- a count check is enough, because the failure was two files, not
    two readings of one file.
    """
    store = ApplicabilityStore.load()
    held_by_engine = sum(len(v) for v in store.delegations_by_revision.values())
    if not held_by_engine:
        pytest.skip("no delegations built")

    from eval.questions import CorpusFacts

    assert len(CorpusFacts.load().delegations) == held_by_engine


def test_no_module_resolves_a_path_to_the_abandoned_delegations_file():
    """delegations.jsonl was written by a CLI that no longer exists. Anything
    still reading it is reading a snapshot that stopped updating.

    Only a quoted literal counts: both files that caused this carry a comment
    naming the file in prose, and recording why it was abandoned is the
    opposite of the mistake.
    """
    offenders = []
    for path in sorted(ROOT.glob("**/*.py")):
        if ".venv" in path.parts or "site-packages" in path.parts:
            continue
        if path.name == "test_applicability.py":
            continue
        text = path.read_text(encoding="utf-8")
        if '"delegations.jsonl"' in text or "'delegations.jsonl'" in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"still resolving a path to the abandoned file: {offenders}"
