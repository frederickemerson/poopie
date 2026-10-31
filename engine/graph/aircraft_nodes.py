"""Write contract-validated Aircraft nodes and merge them into nodes.jsonl.

Decision: Aircraft lines go to their own file, data/build/nodes.aircraft.jsonl,
so this writer never touches lines another agent owns. `merge_nodes` is the
documented, deterministic step that folds that file into data/build/nodes.jsonl:
every non-Aircraft line is preserved byte-for-byte and in order, all existing
Aircraft lines are replaced, and the new Aircraft lines are appended. Re-running
it is idempotent. The rewrite is atomic (temp file + os.replace).

    python3 -m engine.graph.aircraft_nodes --merge
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from contracts.contract import validate_node  # noqa: E402

NODE_TYPE = "Aircraft"
AIRCRAFT_PATH = ROOT / "data" / "build" / "nodes.aircraft.jsonl"
NODES_PATH = ROOT / "data" / "build" / "nodes.jsonl"


def node_line(record: dict[str, object]) -> str:
    """Validate against the contract and serialize deterministically (sorted by fleet order)."""
    validate_node(NODE_TYPE, record)
    return json.dumps({"_type": NODE_TYPE, **record}, ensure_ascii=False, sort_keys=False)


def write_aircraft_nodes(records: Iterable[dict[str, object]], path: Path = AIRCRAFT_PATH) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [node_line(r) for r in records]
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    os.replace(tmp, path)
    return len(lines)


def _is_aircraft_line(line: str) -> bool:
    try:
        return json.loads(line).get("_type") == NODE_TYPE
    except json.JSONDecodeError as exc:
        raise ValueError(f"nodes.jsonl contains a non-JSON line: {line[:80]!r}") from exc


def merge_nodes(aircraft_path: Path = AIRCRAFT_PATH, nodes_path: Path = NODES_PATH) -> int:
    """Replace the Aircraft lines in nodes_path with those from aircraft_path."""
    new_lines = [ln for ln in aircraft_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    kept: list[str] = []
    if nodes_path.exists():
        kept = [ln for ln in nodes_path.read_text(encoding="utf-8").splitlines() if ln.strip() and not _is_aircraft_line(ln)]
    tmp = nodes_path.with_suffix(nodes_path.suffix + ".tmp")
    tmp.write_text("".join(ln + "\n" for ln in [*kept, *new_lines]), encoding="utf-8")
    os.replace(tmp, nodes_path)
    return len(new_lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--merge", action="store_true")
    if not ap.parse_args().merge:
        ap.error("pass --merge")
    print(f"merged {merge_nodes()} Aircraft nodes into {NODES_PATH}")
