"""The only place this project calls Claude.

Three things every call gets, because each one was a real cost or correctness
risk and none of them should be re-invented per caller:

1. A CostLedger (required argument, no default) -- a call that cannot name its
   budget does not get to spend money.
2. A content-addressed disk cache -- re-running the ingest over unchanged ADs
   costs nothing, which is what makes iteration affordable.
3. Prompt caching on the system block -- the extraction system prompt is
   identical across thousands of calls, so it should be read from cache.

Model choice is pinned in ledger.py: Haiku 5.5 for bulk extraction and query
planning, Sonnet 5.5 for the answer writer. Extraction and planning are
structured-output tasks over short inputs, which is what Haiku is for; the
answer writer is the only stage whose prose quality the user sees.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import anthropic

from .ledger import CostLedger, Usage

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "data" / "build" / "llm_cache"


class LLMUnavailable(RuntimeError):
    """No API key configured. Callers must degrade honestly, never fabricate."""


def load_env() -> None:
    """Load .env without a dependency. Values already in the environment win."""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def have_api_key() -> bool:
    load_env()
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


@dataclass
class Completion:
    text: str
    parsed: Any | None
    usage: Usage
    cost_usd: float
    cached_hit: bool
    model: str


class LLMClient:
    """Cached, budgeted wrapper over the Messages API."""

    def __init__(self, ledger: CostLedger, *, cache_dir: Path = CACHE_DIR, offline: bool = False):
        self.ledger = ledger
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.offline = offline
        self._client: anthropic.Anthropic | None = None

    @property
    def client(self) -> anthropic.Anthropic:
        if self.offline:
            raise LLMUnavailable("client is in offline mode")
        if self._client is None:
            load_env()
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise LLMUnavailable(
                    "ANTHROPIC_API_KEY is not set. Put it in .env (gitignored) "
                    "or run the pipeline with --offline, which marks every rule "
                    "it cannot extract as unparsed instead of guessing."
                )
            self._client = anthropic.Anthropic()
        return self._client

    # ---------------------------------------------------------------- cache

    @staticmethod
    def _key(payload: dict[str, Any]) -> str:
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def _read_cache(self, key: str) -> dict[str, Any] | None:
        p = self._cache_path(key)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            p.unlink(missing_ok=True)
            return None

    def _write_cache(self, key: str, record: dict[str, Any]) -> None:
        tmp = self._cache_path(key).with_suffix(".tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._cache_path(key))

    # ------------------------------------------------------------- requests

    def _build_params(
        self,
        *,
        model: str,
        system: str,
        user: str,
        max_tokens: int,
        schema: dict[str, Any] | None,
        effort: str | None,
    ) -> dict[str, Any]:
        # The system prompt is identical across thousands of extraction calls,
        # so it carries the cache breakpoint. Volatile content stays in messages,
        # after the breakpoint, or nothing would ever hit cache.
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": [{"role": "user", "content": user}],
        }
        output_config: dict[str, Any] = {}
        if effort:
            output_config["effort"] = effort
        if schema:
            output_config["format"] = {
                "type": "json_schema",
                "schema": schema,
            }
        if output_config:
            params["output_config"] = output_config
        return params

    def complete(
        self,
        *,
        model: str,
        system: str,
        user: str,
        label: str,
        max_tokens: int = 4096,
        schema: dict[str, Any] | None = None,
        effort: str | None = "low",
        estimated_usd: float = 0.01,
    ) -> Completion:
        """One completion, served from disk cache when the inputs are unchanged."""
        key = self._key(
            {
                "model": model,
                "system": system,
                "user": user,
                "schema": schema,
                "effort": effort,
                "max_tokens": max_tokens,
            }
        )
        hit = self._read_cache(key)
        if hit is not None:
            usage = Usage(**hit["usage"])
            self.ledger.record(model=model, usage=usage, label=label, cached_hit=True)
            return Completion(
                text=hit["text"],
                parsed=hit.get("parsed"),
                usage=usage,
                cost_usd=0.0,
                cached_hit=True,
                model=model,
            )

        self.ledger.check_affordable(estimated_usd, label=label)
        params = self._build_params(
            model=model, system=system, user=user,
            max_tokens=max_tokens, schema=schema, effort=effort,
        )
        response = self.client.messages.create(**params)

        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        parsed = None
        if schema and text.strip():
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                # Truncation is by far the commonest cause and looks identical to
                # malformed output, so name it rather than making the caller guess.
                if getattr(response, "stop_reason", None) == "max_tokens":
                    raise ValueError(
                        f"{label}: output hit max_tokens={max_tokens} and the JSON was cut "
                        f"off mid-structure. Raise max_tokens; do not parse the fragment."
                    )
                raise ValueError(
                    f"{label}: model returned non-JSON under a json_schema output_config "
                    f"(stop_reason={getattr(response, 'stop_reason', None)!r}): {text[:300]!r}"
                )

        usage = Usage.from_response(response.usage)
        cost = self.ledger.record(model=model, usage=usage, label=label)
        self._write_cache(
            key,
            {"text": text, "parsed": parsed, "usage": usage.__dict__, "model": model},
        )
        return Completion(
            text=text, parsed=parsed, usage=usage,
            cost_usd=cost, cached_hit=False, model=model,
        )

    # ---------------------------------------------------------------- batch

    def batch_complete(
        self,
        requests: Iterable[tuple[str, dict[str, Any]]],
        *,
        model: str,
        label: str,
        poll_seconds: int = 20,
    ) -> dict[str, Completion]:
        """Run many completions through the Batch API at half price.

        `requests` yields (custom_id, kwargs) where kwargs match complete().
        Cached ids are served from disk and never submitted. Results come back
        in arbitrary order, so they are keyed by custom_id, never by position.
        """
        import time

        pending: list[dict[str, Any]] = []
        out: dict[str, Completion] = {}
        keys: dict[str, str] = {}
        # The Batch API constrains custom_id to ^[a-zA-Z0-9_-]{1,64}$, but our
        # natural ids are paragraph ids like "2026-21902#(o)". Submit a safe
        # surrogate and map results back, rather than mangling the caller's ids.
        safe_to_real: dict[str, str] = {}

        for custom_id, kw in requests:
            key = self._key(
                {
                    "model": model,
                    "system": kw["system"],
                    "user": kw["user"],
                    "schema": kw.get("schema"),
                    "effort": kw.get("effort", "low"),
                    "max_tokens": kw.get("max_tokens", 4096),
                }
            )
            keys[custom_id] = key
            hit = self._read_cache(key)
            if hit is not None:
                usage = Usage(**hit["usage"])
                self.ledger.record(model=model, usage=usage, label=label, cached_hit=True)
                out[custom_id] = Completion(
                    text=hit["text"], parsed=hit.get("parsed"), usage=usage,
                    cost_usd=0.0, cached_hit=True, model=model,
                )
                continue
            safe_id = f"r{len(pending):05d}_{key[:16]}"
            safe_to_real[safe_id] = custom_id
            pending.append(
                {
                    "custom_id": safe_id,
                    "params": self._build_params(
                        model=model,
                        system=kw["system"],
                        user=kw["user"],
                        max_tokens=kw.get("max_tokens", 4096),
                        schema=kw.get("schema"),
                        effort=kw.get("effort", "low"),
                    ),
                }
            )

        if not pending:
            return out

        batch = self.client.messages.batches.create(requests=pending)
        while True:
            status = self.client.messages.batches.retrieve(batch.id)
            if status.processing_status == "ended":
                break
            time.sleep(poll_seconds)

        for result in self.client.messages.batches.results(batch.id):
            cid = safe_to_real.get(result.custom_id, result.custom_id)
            if result.result.type != "succeeded":
                # Do not silently drop: the caller must see which ids failed.
                out[cid] = Completion(
                    text="", parsed=None, usage=Usage(),
                    cost_usd=0.0, cached_hit=False, model=model,
                )
                continue
            msg = result.result.message
            text = "".join(
                b.text for b in msg.content if getattr(b, "type", None) == "text"
            )
            parsed = None
            if text.strip():
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    parsed = None
            usage = Usage.from_response(msg.usage)
            cost = self.ledger.record(model=model, usage=usage, label=label, batch=True)
            self._write_cache(
                keys[cid],
                {"text": text, "parsed": parsed, "usage": usage.__dict__, "model": model},
            )
            out[cid] = Completion(
                text=text, parsed=parsed, usage=usage,
                cost_usd=cost, cached_hit=False, model=model,
            )
        return out
