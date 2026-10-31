/**
 * Which engine drives a run. "engine" is the FastAPI service; "mock" replays a
 * recorded scenario from lib/scenarios.
 *
 * The mock is not dead weight. It is the fallback that keeps a live demo alive
 * if the backend dies mid-presentation, so it stays reachable from the toolbar
 * and the toolbar always says which one produced what is on screen.
 */
export type EngineSource = "engine" | "mock";

export const ENGINE_SOURCES: readonly EngineSource[] = ["engine", "mock"];

export const DEFAULT_ENGINE_SOURCE: EngineSource = "engine";

const STORE_KEY = "poopie.engine-source";

export function isEngineSource(value: unknown): value is EngineSource {
  return value === "engine" || value === "mock";
}

export function readStoredEngineSource(): EngineSource {
  try {
    const stored = window.localStorage.getItem(STORE_KEY);
    return isEngineSource(stored) ? stored : DEFAULT_ENGINE_SOURCE;
  } catch {
    return DEFAULT_ENGINE_SOURCE;
  }
}

export function storeEngineSource(source: EngineSource): void {
  try {
    window.localStorage.setItem(STORE_KEY, source);
  } catch {
    // A blocked storage API must not stop a run; the choice just will not stick.
  }
}

export const SOURCE_LABEL: Readonly<Record<EngineSource, string>> = {
  engine: "live engine",
  mock: "recorded",
};
