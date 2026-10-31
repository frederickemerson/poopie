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
