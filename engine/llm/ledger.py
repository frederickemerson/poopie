"""Token and cost accounting with a hard spend cap.

The project runs on a fixed, small API budget, so every Claude call in this
codebase goes through here. The ledger refuses a call that would breach the cap
rather than discovering the overspend afterwards, and persists every call so the
real spend is auditable after the fact.

Prices are $ per 1M tokens, from the Anthropic pricing table cached 2026-10-06.
Cache-read and cache-write rates follow the standard multipliers (write 1.25x
base input, read 0.1x base input). If billing disagrees, fix PRICING here --
never let a caller carry its own numbers.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LEDGER_PATH = ROOT / "data" / "build" / "cost_ledger.jsonl"

# Model ids are exact strings; never append a date suffix.
MODEL_EXTRACT = "claude-haiku-5-5"
MODEL_PLAN = "claude-haiku-5-5"
MODEL_ANSWER = "claude-sonnet-5-5"


@dataclass(frozen=True)
class Price:
    """$ per 1M tokens."""

    input: float
    output: float

    @property
    def cache_write(self) -> float:
        return self.input * 1.25

    @property
    def cache_read(self) -> float:
        return self.input * 0.10


PRICING: dict[str, Price] = {
    "claude-haiku-5-5": Price(input=0.10, output=0.50),
    "claude-sonnet-5-5": Price(input=2.00, output=10.00),
    "claude-opus-5-5": Price(input=4.00, output=20.00),
}

# The Batch API runs asynchronously at half price. Ingest-time extraction is not
# latency-sensitive, so it should always take this discount.
BATCH_DISCOUNT = 0.50


class BudgetExceeded(RuntimeError):
    """Raised before a call that would push spend past the cap."""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @classmethod
    def from_response(cls, usage: Any) -> "Usage":
        """Read an SDK usage object defensively; absent fields mean zero."""
        return cls(
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
        )


def cost_usd(model: str, usage: Usage, *, batch: bool = False) -> float:
    price = PRICING.get(model)
    if price is None:
        raise KeyError(
            f"no price for {model!r}; add it to PRICING rather than guessing at the call site"
        )
    total = (
        usage.input_tokens * price.input
        + usage.output_tokens * price.output
        + usage.cache_read_tokens * price.cache_read
        + usage.cache_write_tokens * price.cache_write
    ) / 1_000_000
    return total * (BATCH_DISCOUNT if batch else 1.0)


@dataclass
class CostLedger:
    """Append-only spend record with a hard cap.

    cap_usd is deliberately required -- a default would let a caller spend real
    money without naming a limit.
    """

    cap_usd: float
    path: Path = LEDGER_PATH
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def spent_usd(self) -> float:
        if not self.path.exists():
            return 0.0
        total = 0.0
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    total += json.loads(line).get("cost_usd", 0.0)
                except json.JSONDecodeError:
                    # A torn final line must not hide real spend; count nothing
                    # for it but keep going so the cap still reflects the rest.
                    continue
        return total

    def remaining_usd(self) -> float:
        return self.cap_usd - self.spent_usd()

    def check_affordable(self, estimated_usd: float, *, label: str) -> None:
        remaining = self.remaining_usd()
        if estimated_usd > remaining:
            raise BudgetExceeded(
                f"{label}: estimated ${estimated_usd:.4f} exceeds remaining "
                f"${remaining:.4f} of the ${self.cap_usd:.2f} cap. "
                f"Raise the cap explicitly or reduce the workload."
            )

    def record(
        self,
        *,
        model: str,
        usage: Usage,
        label: str,
        batch: bool = False,
        cached_hit: bool = False,
    ) -> float:
        cost = 0.0 if cached_hit else cost_usd(model, usage, batch=batch)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "label": label,
            "batch": batch,
            "cached_hit": cached_hit,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read_tokens": usage.cache_read_tokens,
            "cache_write_tokens": usage.cache_write_tokens,
            "cost_usd": cost,
        }
        with self._lock, self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
        return cost

    def summary(self) -> dict[str, Any]:
        by_label: dict[str, dict[str, float]] = {}
        totals = {"cost_usd": 0.0, "calls": 0, "cache_hits": 0, "input": 0, "output": 0}
        if self.path.exists():
            with self.path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    b = by_label.setdefault(e["label"], {"cost_usd": 0.0, "calls": 0})
                    b["cost_usd"] += e.get("cost_usd", 0.0)
                    b["calls"] += 1
                    totals["cost_usd"] += e.get("cost_usd", 0.0)
                    totals["calls"] += 1
                    totals["cache_hits"] += 1 if e.get("cached_hit") else 0
                    totals["input"] += e.get("input_tokens", 0)
                    totals["output"] += e.get("output_tokens", 0)
        return {
            "cap_usd": self.cap_usd,
            "spent_usd": round(totals["cost_usd"], 4),
            "remaining_usd": round(self.cap_usd - totals["cost_usd"], 4),
            "calls": totals["calls"],
            "cache_hits": totals["cache_hits"],
            "input_tokens": totals["input"],
            "output_tokens": totals["output"],
            "by_label": {k: {"cost_usd": round(v["cost_usd"], 4), "calls": v["calls"]} for k, v in by_label.items()},
        }


def default_cap_usd() -> float:
    """Cap from AD_ENGINE_BUDGET_USD, else a deliberately small default."""
    raw = os.environ.get("AD_ENGINE_BUDGET_USD")
    if raw:
        try:
            return float(raw)
        except ValueError as exc:
            raise ValueError(f"AD_ENGINE_BUDGET_USD={raw!r} is not a number") from exc
    return 15.0
