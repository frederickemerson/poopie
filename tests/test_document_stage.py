"""A proposal must never be citable as law, and an adopted AD is not yet an obligation.

These two guarantees are structural, not editorial. The supplied NPRM catalogue
is 431 proposed rules; the final-rule corpus is separate. Mixing them would let
the engine answer "what must I do" from a document that imposes nothing.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contracts.contract import enum  # noqa: E402
from engine.graph.stage import (  # noqa: E402
    ADOPTED_NOT_YET_EFFECTIVE,
    EFFECTIVE,
    PROPOSED,
    SUPERSEDED,
    UNKNOWN,
    annotate,
    corpus_breakdown,
    revision_stage,
)

BUILD = ROOT / "data" / "build"
TODAY = dt.date(2026, 10, 31)


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


# --------------------------------------------------------------------- unit

def test_every_stage_is_a_contract_value():
    for stage in (PROPOSED, ADOPTED_NOT_YET_EFFECTIVE, EFFECTIVE, SUPERSEDED, UNKNOWN):
        assert stage in enum("document_stage")


def test_future_effective_date_is_not_yet_an_obligation():
    rev = {"revision_id": "x", "effective_on": "2026-12-01"}
    assert revision_stage(rev, today=TODAY) == ADOPTED_NOT_YET_EFFECTIVE
    assert annotate(rev, today=TODAY)["imposes_obligation_now"] is False


def test_past_effective_date_is_in_force():
    rev = {"revision_id": "x", "effective_on": "2026-01-05"}
    assert revision_stage(rev, today=TODAY) == EFFECTIVE
    assert annotate(rev, today=TODAY)["imposes_obligation_now"] is True


def test_effective_on_today_is_in_force():
    """Boundary: an AD effective today is in force today."""
    rev = {"revision_id": "x", "effective_on": TODAY.isoformat()}
    assert revision_stage(rev, today=TODAY) == EFFECTIVE


def test_superseded_wins_over_effectiveness():
    rev = {"revision_id": "x", "effective_on": "2026-01-05", "superseded_by": "2026-21-13"}
    assert revision_stage(rev, today=TODAY) == SUPERSEDED


def test_missing_effective_date_is_unknown_not_assumed_effective():
    assert revision_stage({"revision_id": "x"}, today=TODAY) == UNKNOWN
    assert annotate({"revision_id": "x"}, today=TODAY)["imposes_obligation_now"] is False


def test_malformed_effective_date_is_unknown():
    assert revision_stage({"effective_on": "not-a-date"}, today=TODAY) == UNKNOWN


def test_explanation_names_the_effective_date():
    note = annotate({"effective_on": "2026-12-01"}, today=TODAY)
    assert "2026-12-01" in note["explanation"]


# ---------------------------------------------------------------- the corpus

def test_only_revision_paragraphs_are_in_the_obligation_file():
    """The load-bearing guarantee, as contract 1.2.0 states it.

    A proposal MAY be indexed, retrieved and cited -- the challenge's dataset is
    431 of them -- but it may never supply an obligation or a deadline. So the
    guarantee is no longer "no NPRM text exists" but "no NPRM text is in the
    file the obligation path reads". ``data/build/paragraphs.jsonl`` is that
    file: ``engine.rules`` turns its records into Actions carrying
    ``compliance_time``. Proposals live in ``nprm_paragraphs.jsonl``.

    The fence itself is tested in tests/test_nprm_retrieval.py.
    """
    paragraphs = _jsonl(BUILD / "paragraphs.jsonl")
    if not paragraphs:
        pytest.skip("no built paragraphs yet")
    nodes = _jsonl(BUILD / "nodes.jsonl")
    revision_ids = {n["revision_id"] for n in nodes if n.get("_type") == "Revision"}
    nprm_ids = {n["nprm_id"] for n in nodes if n.get("_type") == "NPRM"}

    orphans = [p["paragraph_id"] for p in paragraphs if p.get("revision_id") not in revision_ids]
    assert not orphans, (
        f"{len(orphans)} citable paragraphs do not trace to a Revision: {orphans[:5]}"
    )
    leaked = [
        p["paragraph_id"]
        for p in paragraphs
        if p.get("revision_id") in nprm_ids
        or p.get("nprm_id")
        or p.get("source_kind") == "NPRM"
        or p.get("document_stage") == PROPOSED
    ]
    assert not leaked, f"NPRM text reached the obligation file: {leaked[:5]}"


def test_proposal_text_is_indexed_and_every_line_of_it_is_proposed():
    """The other half: a build that indexed nothing would satisfy the fence and
    fail the task. If proposals were harvested they must all be staged."""
    proposals = _jsonl(BUILD / "nprm_paragraphs.jsonl")
    if not proposals:
        pytest.skip("no harvested proposal text yet")
    nodes = _jsonl(BUILD / "nodes.jsonl")
    nprm_ids = {n["nprm_id"] for n in nodes if n.get("_type") == "NPRM"}
    wrong = [p["paragraph_id"] for p in proposals if p.get("document_stage") != PROPOSED]
    assert not wrong, f"proposal paragraphs not staged {PROPOSED}: {wrong[:5]}"
    orphans = [p["paragraph_id"] for p in proposals if p.get("nprm_id") not in nprm_ids]
    assert not orphans, f"proposal paragraphs with no NPRM node: {orphans[:5]}"


def test_corpus_breakdown_accounts_for_every_revision():
    nodes = _jsonl(BUILD / "nodes.jsonl")
    revisions = [n for n in nodes if n.get("_type") == "Revision"]
    if not revisions:
        pytest.skip("no built revisions yet")
    counts = corpus_breakdown(revisions, today=TODAY)
    assert sum(counts.values()) == len(revisions)
    assert set(counts) <= set(enum("document_stage"))
