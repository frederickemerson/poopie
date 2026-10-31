"""Precompute the whole fleet x AD decision matrix for BlastRadius.

One decision is a few microseconds of pure Python, so the matrix is built in a
single pass and persisted; the UI never recomputes it. Nothing here touches the
network or an LLM, so the matrix is reproducible from the same three inputs:
the Aircraft nodes, the Rules, and the applicability delegations.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Sequence

from .engine import decide
from .records import SCOPE_APPLICABILITY


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist")
    out = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no} is not JSON: {exc}") from exc
    return out


def group_by(records: Iterable[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        out.setdefault(record[key], []).append(record)
    return out


def applicability_delegations(delegations: Iterable[dict[str, Any]]) -> dict[str, list[dict]]:
    return group_by(
        (d for d in delegations if d.get("scope") == SCOPE_APPLICABILITY), "revision_id"
    )


def build(
    aircraft: Sequence[dict[str, Any]],
    rules: Sequence[dict[str, Any]],
    delegations: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Decide every (aircraft, revision) pair. Deterministic and side-effect free."""
    by_revision = group_by(rules, "revision_id")
    external = applicability_delegations(delegations)
    revisions = sorted(set(by_revision) | set(external))

    started = time.perf_counter()
    cells: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    totals: Counter[str] = Counter()
    per_revision: dict[str, Counter[str]] = {}
    refusals: Counter[str] = Counter()
    decisions_made = 0

    for revision_id in revisions:
        revision_rules = by_revision.get(revision_id, [])
        revision_external = external.get(revision_id, [])
        row: dict[str, Any] = {}
        counts: Counter[str] = Counter()
        for record in aircraft:
            result = decide(
                record,
                revision_rules,
                revision_id=revision_id,
                external_applicability=revision_external,
            )
            decisions_made += 1
            code = result.refusal["code"] if result.refusal else None
            cell = {"decision": result.decision}
            if code:
                cell["refusal_code"] = code
            if result.unknown_fields:
                cell["unknown_fields"] = list(result.unknown_fields)
            row[record["tail_number"]] = cell
            counts[result.decision] += 1
            totals[result.decision] += 1
            if code:
                refusals[code] += 1
            edges.append(
                {
                    "_type": "AFFECTED_BY",
                    "_src_type": "Aircraft",
                    "_src": record["tail_number"],
                    "_dst_type": "Revision",
                    "_dst": revision_id,
                    **result.edge_attrs(),
                }
            )
        cells[revision_id] = row
        per_revision[revision_id] = counts

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return {
        "aircraft_count": len(aircraft),
        "revision_count": len(revisions),
        "revisions": revisions,
        "decisions": decisions_made,
        "build_ms": round(elapsed_ms, 2),
        "us_per_decision": round((elapsed_ms * 1000.0) / decisions_made, 2) if decisions_made else None,
        "distribution": dict(sorted(totals.items())),
        "refusal_codes": dict(sorted(refusals.items())),
        "by_revision": {r: dict(sorted(c.items())) for r, c in per_revision.items()},
        "cells": cells,
        "edges": edges,
    }


def write(out_dir: Path, matrix: dict[str, Any]) -> dict[str, Path]:
    """Persist the matrix and its AFFECTED_BY edges."""
    out_dir.mkdir(parents=True, exist_ok=True)
    edges = matrix["edges"]
    body = {k: v for k, v in matrix.items() if k != "edges"}
    matrix_path = out_dir / "decision_matrix.json"
    edges_path = out_dir / "edges.decisions.jsonl"
    matrix_path.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
    with edges_path.open("w", encoding="utf-8") as fh:
        for e in edges:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    return {"matrix": matrix_path, "edges": edges_path}
