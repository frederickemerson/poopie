"use client";

/**
 * The engine's own GET /health, polled.
 *
 * Four things decide whether a demo can work at all: is the service up, is the
 * corpus loaded, is the retrieval index loaded, and is the LLM live or offline.
 * All four come from the engine; none is inferred from a failed query.
 */
import { useCallback, useEffect, useState } from "react";

export interface SpendSummary {
  readonly cap_usd?: number;
  readonly spent_usd?: number;
  readonly remaining_usd?: number;
  readonly calls?: number;
  readonly cache_hits?: number;
}

export interface BackendHealth {
  readonly reachable: boolean;
  readonly origin?: string;
  readonly corpus_loaded?: boolean;
  readonly index_loaded?: boolean;
  /** "live" when an API key is configured, "offline" otherwise. */
  readonly llm?: string | null;
  readonly error?: string | null;
  readonly spend?: SpendSummary | null;
}

export type HealthStatus = "probing" | "ready" | "degraded" | "unreachable";

export interface HealthView {
  readonly health: BackendHealth | null;
  readonly status: HealthStatus;
  readonly checkedAt: number | null;
  readonly refresh: () => void;
}

const POLL_MS = 15_000;

export function healthStatus(health: BackendHealth | null): HealthStatus {
  if (health === null) return "probing";
  if (!health.reachable) return "unreachable";
  if (health.error) return "degraded";
  if (health.corpus_loaded !== true || health.index_loaded !== true) return "degraded";
  return "ready";
}

export function useBackendHealth(): HealthView {
  const [health, setHealth] = useState<BackendHealth | null>(null);
  const [checkedAt, setCheckedAt] = useState<number | null>(null);
  const [nonce, setNonce] = useState(0);

  const refresh = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    let live = true;
    const controller = new AbortController();

    const probe = async () => {
      try {
        const response = await fetch("/api/health", {
          cache: "no-store",
          signal: controller.signal,
        });
        const payload = (await response.json()) as BackendHealth;
        if (!live) return;
        setHealth(payload);
        setCheckedAt(Date.now());
      } catch (error: unknown) {
        if (!live || controller.signal.aborted) return;
        setHealth({
          reachable: false,
          error: error instanceof Error ? error.message : "health probe failed",
        });
        setCheckedAt(Date.now());
      }
    };

    void probe();
    const timer = window.setInterval(() => void probe(), POLL_MS);
    return () => {
      live = false;
      controller.abort();
      window.clearInterval(timer);
    };
  }, [nonce]);

  return { health, status: healthStatus(health), checkedAt, refresh };
}
