"""The consistency gate. Run this before and after every agent's work.

Written BEFORE any producer or consumer code exists, deliberately: the failure
this prevents is two parallel workers inventing the same vocabulary differently
(rules reading keys the extractor never emitted). It fails on any node type,
edge type, enum value, SSE event or payload key that is not in contract.json.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contracts.contract import (  # noqa: E402
    ContractViolation,
    contract,
    edge_types,
    enum,
    node_types,
    sse_events,
    validate_edge,
    validate_node,
)

SOURCE_DIRS = ["engine", "eval", "web/app", "web/lib", "web/components"]


# --------------------------------------------------------------------------
# 1. The contract must be internally consistent.
# --------------------------------------------------------------------------

def test_every_edge_endpoint_is_a_real_node_type():
    known = set(node_types())
    for name, spec in edge_types().items():
        for src in spec["from"]:
            assert src in known, f"edge {name} starts at unknown node type {src}"
        assert spec["to"] in known, f"edge {name} ends at unknown node type {spec['to']}"


def test_refusal_semantics_cover_exactly_the_refusal_enum():
    codes = set(enum("refusal_code"))
    documented = set(contract()["refusal_semantics"])
    assert codes == documented, (
        f"refusal_code enum and refusal_semantics disagree; "
        f"only in enum: {codes - documented}, only in semantics: {documented - codes}"
    )


def test_every_node_type_key_is_one_of_its_fields():
    for name, spec in node_types().items():
        assert spec["key"] in spec["fields"], f"{name} key {spec['key']} is not in its field list"


def test_sse_stage_names_are_unique():
    stages = [spec["stage"] for spec in sse_events().values()]
    assert len(stages) == len(set(stages)), f"duplicate SSE stage names: {stages}"


def test_latency_targets_name_real_stages():
    stages = {spec["stage"] for spec in sse_events().values()}
    for key in contract()["latency_targets_ms"]:
        if key == "total_p95":
            continue
        assert key in stages, f"latency target {key!r} does not match any SSE stage {sorted(stages)}"


def test_superseded_is_the_only_non_blocking_refusal():
    sem = contract()["refusal_semantics"]
    non_blocking = [c for c, s in sem.items() if s.get("blocks_answer") is False]
    assert non_blocking == ["SUPERSEDED"], (
        "SUPERSEDED must still return an answer with a banner; every other code blocks it. "
        f"Got non-blocking: {non_blocking}"
    )


# --------------------------------------------------------------------------
# 2. Built artifacts must validate against it.
# --------------------------------------------------------------------------

def _build_file(name: str) -> Path | None:
    p = ROOT / "data" / "build" / name
    return p if p.exists() else None


def test_built_nodes_match_the_contract():
    path = _build_file("nodes.jsonl")
    if path is None:
        pytest.skip("no data/build/nodes.jsonl yet - run the ingest")
    seen: dict[str, int] = {}
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        rec = json.loads(line)
        ntype = rec.pop("_type", None)
        assert ntype, f"{path}:{line_no} node has no _type"
        try:
            validate_node(ntype, rec)
        except ContractViolation as exc:
            pytest.fail(f"{path}:{line_no} {exc}")
        seen[ntype] = seen.get(ntype, 0) + 1
    assert seen, "nodes.jsonl is empty"


def test_built_edges_match_the_contract():
    path = _build_file("edges.jsonl")
    if path is None:
        pytest.skip("no data/build/edges.jsonl yet - run the ingest")
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        rec = json.loads(line)
        try:
            validate_edge(rec["_type"], rec["_src_type"], rec["_dst_type"])
        except (ContractViolation, KeyError) as exc:
            pytest.fail(f"{path}:{line_no} {exc}")


def test_every_rule_quote_is_verbatim_in_its_paragraph():
    rules_p, paras_p = _build_file("rules.jsonl"), _build_file("paragraphs.jsonl")
    if rules_p is None or paras_p is None:
        pytest.skip("no built rules/paragraphs yet")
    paras = {}
    for line in paras_p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            paras[r["paragraph_id"]] = r["text"]
    bad = []
    for line in rules_p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rule = json.loads(line)
        text = paras.get(rule["paragraph_id"])
        if text is None:
            bad.append(f"{rule['rule_id']} -> missing paragraph {rule['paragraph_id']}")
            continue
        quote = " ".join((rule.get("source_quote") or "").split()).lower()
        if not quote or quote not in " ".join(text.split()).lower():
            bad.append(f"{rule['rule_id']} quote not verbatim in {rule['paragraph_id']}")
    assert not bad, "rules violate the source-quote invariant:\n  " + "\n  ".join(bad[:20])


# --------------------------------------------------------------------------
# 3. Source code must not invent vocabulary.
# --------------------------------------------------------------------------

def _sources() -> list[Path]:
    """Hand-written source only. Files generated from the contract are in sync by
    construction, and scanning them just re-flags the contract's own vocabulary."""
    out: list[Path] = []
    for d in SOURCE_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.suffix not in {".py", ".ts", ".tsx"}:
                continue
            head = p.read_text(encoding="utf-8", errors="replace")[:200]
            if "GENERATED FROM contracts/contract.json" in head:
                continue
            out.append(p)
    return out


def test_no_source_file_invents_a_refusal_code():
    """Catch a worker writing e.g. 'NEEDS_CONFIG' or 'NO_DATA' instead of a contract code."""
    allowed = _all_enum_values()
    shape = re.compile(r"[\"'](NEED[A-Z_]*|NO_[A-Z_]+|CANNOT_[A-Z_]+|OUT_OF_[A-Z_]+|SUPERSED[A-Z_]*|EXTERNAL_[A-Z_]+)[\"']")
    offenders = []
    for path in _sources():
        if path.resolve() == Path(__file__).resolve():
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for m in shape.finditer(line):
                if m.group(1) not in allowed:
                    offenders.append(f"{path.relative_to(ROOT)}:{n} invented refusal code {m.group(1)!r}")
    assert not offenders, "use contract refusal codes only:\n  " + "\n  ".join(offenders)


def _all_enum_values() -> set[str]:
    """Every value the contract defines, across all enums.

    The point of these scanners is to catch *invented* vocabulary. A value that
    legitimately belongs to another enum (UNKNOWN is both a document_stage and
    an authority) is not an invention, so the union is the right allow-list.
    """
    return {v for values in contract()["enums"].values() for v in values}


def test_no_source_file_invents_a_decision_value():
    allowed = _all_enum_values()
    shape = re.compile(r"[\"'](APPLIES[A-Z_]*|DOES_NOT[A-Z_]*|NOT_APPLICABLE|AFFECTED|UNAFFECTED|UNKNOWN)[\"']")
    offenders = []
    for path in _sources():
        if path.resolve() == Path(__file__).resolve():
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for m in shape.finditer(line):
                if m.group(1) not in allowed:
                    offenders.append(f"{path.relative_to(ROOT)}:{n} invented decision {m.group(1)!r}")
    assert not offenders, "use contract decision values only:\n  " + "\n  ".join(offenders)


def test_no_source_file_emits_an_undeclared_sse_event():
    allowed = set(sse_events())
    emit = re.compile(r"""(?:emit|send_event|yield_event|sse)\(\s*["']([a-z_]+)["']""")
    offenders = []
    for path in _sources():
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for m in emit.finditer(line):
                if m.group(1) not in allowed:
                    offenders.append(f"{path.relative_to(ROOT)}:{n} emits undeclared event {m.group(1)!r}")
    assert not offenders, "declare SSE events in the contract first:\n  " + "\n  ".join(offenders)


def test_typescript_mirror_is_in_sync():
    ts = ROOT / "web" / "lib" / "contract.ts"
    if not ts.exists():
        pytest.skip("web/lib/contract.ts not generated yet")
    body = ts.read_text(encoding="utf-8")
    m = re.search(r'CONTRACT_VERSION\s*=\s*["\']([\d.]+)["\']', body)
    assert m, "web/lib/contract.ts must export CONTRACT_VERSION"
    assert m.group(1) == contract()["contract_version"], (
        f"TS mirror is version {m.group(1)}, contract.json is {contract()['contract_version']}. "
        f"Regenerate with: python contracts/gen_ts.py"
    )
    for code in enum("refusal_code"):
        assert code in body, f"TS mirror is missing refusal code {code}"


def test_every_refusal_resolvable_by_is_prose_not_a_list():
    """``resolvable_by`` names WHO can resolve a refusal, as a sentence.

    It was briefly emitted as a list by one producer and consumed as a list by
    another. Since every other producer emits a string, the consumer extended
    a list with a string and got one character per element -- a list of
    letters presented to an engineer as the fields to supply. The type is
    pinned here so neither half of that can come back.
    """
    from engine.verify import refusals as R

    for code in enum("refusal_code"):
        value = R.resolvable_by(code)
        assert isinstance(value, str), f"{code} resolvable_by is {type(value).__name__}"
        assert value.strip(), f"{code} resolvable_by is empty"


def test_missing_inputs_are_contract_rule_fields_not_prose():
    """The envelope's missing_inputs must name fields, from a structured source."""
    from engine.api.answer import build_envelope

    class _Decision:
        decision = "CANNOT_DETERMINE"
        unknown_fields = ("equipment", "modification")

        def proof_tree(self):
            return {"decision": self.decision}

    envelope = build_envelope(
        answer_status="REFUSED",
        document_stage="EFFECTIVE",
        decision=_Decision(),
        decision_unavailable=None,
        verification=None,
        answer=None,
        revision_id="r1",
        superseded_by=None,
        # A NEED_CONFIG refusal whose resolvable_by is prose. If the envelope
        # reads that field, this test fails with a list of letters.
        refusals=[
            {
                "code": "NEED_CONFIG",
                "detail": "which value?",
                "resolvable_by": "the engineer supplies the value",
                "evidence_paragraph_ids": [],
            }
        ],
        traversal=None,
        unreviewed_rules=0,
    )
    fields = set(enum("rule_field"))
    offenders = [m for m in envelope["missing_inputs"] if m not in fields]
    assert not offenders, (
        f"missing_inputs carries non-rule_field values {offenders}; it must come "
        f"from the decision's unknown_fields, not from refusal prose"
    )
    assert envelope["missing_inputs"] == ["equipment", "modification"]


# --------------------------------------------------------------- NPRM staging
#
# The challenge's own dataset is NPRMs and the organizers ask for their full
# text, so proposals ARE indexed. These tests are the fence that keeps that
# from turning a proposal into an obligation.


def test_paragraph_can_name_an_nprm_parent_and_must_say_which():
    fields = set(contract()["node_types"]["Paragraph"]["fields"])
    assert {"nprm_id", "source_kind", "document_stage"} <= fields
    assert {"REVISION", "NPRM"} <= set(enum("source_kind"))


def test_a_paragraph_names_exactly_one_parent_and_a_source_kind_for_each():
    """Every source_kind must have a parent-id field on Paragraph, and vice versa.

    This is the join between the two halves of the contract: a third kind
    (USER_DOCUMENT) added to the enum with no ``user_document_id`` field would
    produce paragraphs whose parent document cannot be named, and a parent-id
    field with no kind would produce paragraphs nothing can filter by.
    """
    fields = set(contract()["node_types"]["Paragraph"]["fields"])
    parent_of = {"REVISION": "revision_id", "NPRM": "nprm_id", "USER_DOCUMENT": "user_document_id"}
    assert set(enum("source_kind")) == set(parent_of), (
        "a new source_kind needs its parent-id field on Paragraph and an entry here"
    )
    for kind, parent in parent_of.items():
        assert parent in fields, f"source_kind {kind} has no {parent} field on Paragraph"


def test_nprm_carries_the_challenge_record_id_and_a_full_text_link():
    """record_id is the index's stable key and the rubric asks us to cite it."""
    fields = set(contract()["node_types"]["NPRM"]["fields"])
    for required in ("record_id", "federal_register_link", "plain_text"):
        assert required in fields, f"NPRM must carry {required}"


def test_revision_carries_the_federal_register_citation_and_pages():
    """The rubric asks for 'the Federal Register citation and page range'."""
    fields = set(contract()["node_types"]["Revision"]["fields"])
    for required in ("fr_citation", "start_page", "end_page"):
        assert required in fields, f"Revision must carry {required}"


def test_the_nprm_invariant_permits_indexing_but_forbids_obligation():
    """The amended invariant must allow citation AND forbid obligation.

    Worth pinning explicitly: the easy way to satisfy the rubric is to delete
    the invariant, and the easy way to keep the invariant is to ignore the
    rubric. The contract has to do both at once.
    """
    invariants = " ".join(contract()["invariants"])
    nprm = next(i for i in contract()["invariants"] if i.startswith("An NPRM is a PROPOSAL"))
    lowered = nprm.lower()
    assert "may be indexed" in lowered, "proposals must be indexable"
    assert "proposed" in lowered, "a proposal's citations must carry its stage"
    assert "obligation" in lowered, "the invariant must still forbid obligation"
    assert "deadline" in lowered, "the invariant must still forbid a deadline"
    assert "never" in invariants.lower()


def test_no_source_file_treats_an_nprm_paragraph_as_an_obligation():
    """A compliance basis must never be derived from a PROPOSED paragraph.

    Catches the shape where code reads a compliance_time off whatever
    paragraph it retrieved without checking the document stage first.
    """
    offenders = []
    for path in _sources():
        if path.resolve() == Path(__file__).resolve():
            continue
        body = path.read_text(encoding="utf-8", errors="replace")
        if "nprm" not in body.lower():
            continue
        lines = body.splitlines()
        for n, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("*"):
                continue
            # A compliance deadline pulled from something NPRM-shaped, with no
            # stage check anywhere nearby, is the failure this guards.
            if "compliance" in line.lower() and "nprm" in line.lower():
                window = "\n".join(lines[max(0, n - 12) : n + 12])
                if "PROPOSED" not in window and "document_stage" not in window:
                    offenders.append(
                        f"{path.relative_to(ROOT)}:{n} reads a compliance value "
                        f"from NPRM data with no document_stage check nearby"
                    )
    assert not offenders, (
        "an NPRM is a proposal and cannot supply a deadline:\n  "
        + "\n  ".join(offenders)
    )
