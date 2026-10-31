import { CLEAN_SCENARIO } from "./clean";
import { EXTERNAL_SOURCE_SCENARIO } from "./externalSource";
import { NEED_CONFIG_SCENARIO } from "./needConfig";
import { SUPERSEDED_SCENARIO } from "./superseded";
import type { Scenario, ScenarioId } from "./shared";

export const SCENARIOS: readonly Scenario[] = [
  CLEAN_SCENARIO,
  NEED_CONFIG_SCENARIO,
  EXTERNAL_SOURCE_SCENARIO,
  SUPERSEDED_SCENARIO,
];

export const DEFAULT_SCENARIO_ID: ScenarioId = "clean";

export function scenario(id: string): Scenario {
  const found = SCENARIOS.find((s) => s.id === id);
  return found ?? CLEAN_SCENARIO;
}

export type { Scenario, ScenarioId, Frame } from "./shared";
