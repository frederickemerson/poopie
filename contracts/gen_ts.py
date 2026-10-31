"""Generate web/lib/contract.ts from contract.json so the UI cannot drift.

Run after any contract change:  python contracts/gen_ts.py
tests/test_contract.py fails if the mirror is stale.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((ROOT / "contracts" / "contract.json").read_text(encoding="utf-8"))
OUT = ROOT / "web" / "lib" / "contract.ts"


def union(values: list[str]) -> str:
    return " | ".join(f'"{v}"' for v in values)


def main() -> None:
    e = CONTRACT["enums"]
    lines = [
        "// GENERATED FROM contracts/contract.json - DO NOT EDIT BY HAND.",
        "// Regenerate with: python contracts/gen_ts.py",
        "",
        f'export const CONTRACT_VERSION = "{CONTRACT["contract_version"]}";',
        "",
    ]

    for name, values in e.items():
        ts_name = "".join(p.capitalize() for p in name.split("_"))
        lines.append(f"export type {ts_name} = {union(values)};")
        lines.append(
            f"export const {name.upper()}: readonly {ts_name}[] = ["
            + ", ".join(f'"{v}"' for v in values)
            + "] as const;"
        )
        lines.append("")

    lines.append("export type SseEventName =")
    lines.append("  " + union(list(CONTRACT["sse_events"])) + ";")
    lines.append("")
    lines.append("export const SSE_PAYLOAD_KEYS: Record<SseEventName, readonly string[]> = {")
    for name, spec in CONTRACT["sse_events"].items():
        lines.append(f'  {name}: [{", ".join(chr(34) + k + chr(34) for k in spec["payload"])}],')
    lines.append("};")
    lines.append("")

    lines.append("export const REFUSAL_SEMANTICS: Record<RefusalCode, {")
    lines.append("  trigger: string; resolvable_by: string; blocks_answer: boolean;")
    lines.append("}> = {")
    for code, spec in CONTRACT["refusal_semantics"].items():
        blocks = "false" if spec.get("blocks_answer") is False else "true"
        trigger = spec["trigger"].replace('"', '\\"')
        resolv = spec["resolvable_by"].replace('"', '\\"')
        lines.append(f'  {code}: {{ trigger: "{trigger}", resolvable_by: "{resolv}", blocks_answer: {blocks} }},')
    lines.append("};")
    lines.append("")
    lines.append(
        "export const LATENCY_TARGETS_MS = "
        + json.dumps(CONTRACT["latency_targets_ms"])
        + " as const;"
    )
    lines.append("")
    lines.append(f'export const CITATION_ID_FORMAT = "{CONTRACT["citation"]["id_format"]}";')
    lines.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(lines)} lines)")


if __name__ == "__main__":
    main()
