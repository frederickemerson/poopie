/**
 * The mock engine stream. Four scenarios, every event typed against the
 * generated contract mirror, every citation span proved verbatim at module load.
 * The real FastAPI service and this file produce the same wire format, so the
 * only thing that changes when the backend is ready is ENGINE_STREAM_URL in
 * lib/sseClient.ts.
 */
import { SSE_PAYLOAD_KEYS, type SseEventName } from "./contract";
import type { EngineEvent } from "./events";
import { DEFAULT_SCENARIO_ID, SCENARIOS, scenario } from "./scenarios";
import type { Frame, Scenario, ScenarioId } from "./scenarios";

export { DEFAULT_SCENARIO_ID, SCENARIOS, scenario };
export type { Frame, Scenario, ScenarioId };

/**
 * Guard: an event may carry exactly the payload keys the contract declares for
 * it, no more and no fewer. This is the UI-side half of tests/test_contract.py.
 */
export function assertPayloadKeys(event: EngineEvent): void {
  const declared = SSE_PAYLOAD_KEYS[event.event as SseEventName];
  const present = Object.keys(event.data);
  const missing = declared.filter((k) => !present.includes(k));
  const extra = present.filter((k) => !declared.includes(k));
  if (missing.length || extra.length) {
    throw new Error(
      `${event.event}: payload keys disagree with the contract` +
        (missing.length ? ` (missing ${missing.join(", ")})` : "") +
        (extra.length ? ` (undeclared ${extra.join(", ")})` : ""),
    );
  }
}

export function mockFrames(id: string): readonly Frame[] {
  const s = scenario(id);
  for (const frame of s.frames) assertPayloadKeys(frame.event);
  return s.frames;
}

export function mockEvents(id: string): readonly EngineEvent[] {
  return mockFrames(id).map((f) => f.event);
}

export interface StreamOptions {
  /** 1 = the timings the scenario declares. 0 = fire everything immediately. */
  readonly speed?: number;
  readonly signal?: AbortSignal;
}

const wait = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve) => {
    if (ms <= 0 || signal?.aborted) return resolve();
    const t = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(t);
      resolve();
    }, { once: true });
  });

/** Replay a scenario with its declared inter-event delays. */
export async function* streamMockScenario(
  id: string,
  options: StreamOptions = {},
): AsyncGenerator<EngineEvent> {
  const speed = options.speed ?? 1;
  for (const frame of mockFrames(id)) {
    await wait(frame.delay_ms * speed, options.signal);
    if (options.signal?.aborted) return;
    yield frame.event;
  }
}

/** The exact Server-Sent Events wire frame for one engine event. */
export function toSsePayload(event: EngineEvent): string {
  return `event: ${event.event}\ndata: ${JSON.stringify(event.data)}\n\n`;
}

export function scenarioIds(): readonly ScenarioId[] {
  return SCENARIOS.map((s) => s.id);
}

/**
 * Resolve a free-typed query to a scenario, so the query bar is not a prop. An
 * AD number in the text wins; a tail number is the tie-breaker; otherwise the
 * scenario the dev toggle selected is used.
 */
export function pickScenario(query: string | null, fallbackId: string): Scenario {
  if (query) {
    const exact = SCENARIOS.find((s) => s.query.toLowerCase() === query.trim().toLowerCase());
    if (exact) return exact;
    const byTail = SCENARIOS.find((s) => s.subject_tail !== null && query.includes(s.subject_tail));
    if (byTail) return byTail;
    // No tail in the question: prefer a scenario that is also about a fleet
    // rather than one airplane, which is what distinguishes NEED_CONFIG from a
    // clean hit on the same AD.
    const byAd = SCENARIOS.filter((s) => query.includes(s.ad_number));
    const fleetWide = byAd.find((s) => s.subject_tail === null);
    if (fleetWide) return fleetWide;
    if (byAd[0]) return byAd[0];
  }
  return scenario(fallbackId);
}
