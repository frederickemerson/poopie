/** Helpers shared by the four scenarios. */
import type { RefusalCode } from "../contract";
import type { EngineEvent, Entity, ParagraphNode, QueryPlan, RetrievalPayload } from "../events";
import type { AdEntry, RevisionEntry } from "../corpus";
import type { FleetAircraft } from "../fleet";

export type ScenarioId = "clean" | "need_config" | "external_source" | "superseded";

export interface Frame {
  /** Wall-clock gap before this event, mirroring the stage it reports. */
  readonly delay_ms: number;
  readonly event: EngineEvent;
}

export interface Scenario {
  readonly id: ScenarioId;
  readonly label: string;
  readonly query: string;
  /** One line on the dev toggle: what a judge should watch for. */
  readonly watch_for: string;
  readonly refusal_code: RefusalCode | null;
  readonly subject_tail: string | null;
  readonly ad_number: string;
  readonly frames: readonly Frame[];
}

/**
 * A subject assembled from the query rather than from the fleet database. Empty
 * strings mean "the query did not supply this and no fleet record was matched",
 * which the engine treats the same way it treats a field the OpenSky record does
 * not carry: CANNOT_DETERMINE, never a guess.
 */
export function querySubject(partial: Partial<FleetAircraft>): FleetAircraft {
  return {
    tail_number: partial.tail_number ?? "",
    icao24: partial.icao24 ?? "",
    manufacturer: partial.manufacturer ?? "",
    model: partial.model ?? "",
    typecode: partial.typecode ?? "",
    serial_number: partial.serial_number ?? "",
    operator: partial.operator ?? "",
    built_year: partial.built_year ?? null,
    equipment: partial.equipment ?? null,
    modification: partial.modification ?? null,
  };
}

/** Locate entity spans in the query text so a chip can point at what it read. */
export function entity(
  query: string,
  field: Entity["field"],
  value: string,
  confidence = 0.98,
): Entity {
  const at = query.indexOf(value);
  const span: readonly [number, number] = at < 0 ? [0, 0] : [at, at + value.length];
  return { field, value, span, confidence };
}

export function emptyPlan(overrides: Partial<QueryPlan> = {}): QueryPlan {
  return {
    intent: "applicability",
    aircraft: {
      model: null,
      typecode: null,
      serial_number: null,
      tail_number: null,
      manufacturer: null,
      ...(overrides.aircraft ?? {}),
    },
    ad_number: null,
    docket_id: null,
    topic: null,
    revision_scope: "current",
    ambiguities: [],
    ...overrides,
  };
}

/** Retrieval payload for a set of paragraph labels, with plausible fused scores. */
export function retrievalOf(
  entry: RevisionEntry,
  labels: readonly string[],
  topScore: number,
  stage_ms: number,
  extra: readonly ParagraphNode[] = [],
): RetrievalPayload {
  const paragraphs = labels.map((l) => entry.built.paragraph(l));
  const all = [...paragraphs, ...extra];
  const scores: Record<string, number> = {};
  all.forEach((p, i) => {
    scores[p.paragraph_id] = Number((topScore - i * 0.047).toFixed(3));
  });
  return { paragraphs: all, scores, stage_ms };
}

export function stageTimings(frames: readonly Frame[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const { event } of frames) {
    if ("stage_ms" in event.data && typeof event.data.stage_ms === "number") {
      const key =
        event.event === "entities"
          ? "entity_pass"
          : event.event === "decision"
            ? "applicability"
            : event.event === "verification"
              ? "verify"
              : event.event;
      out[key] = event.data.stage_ms;
    }
  }
  return out;
}

export function adAndRevision(ad: AdEntry, index: number): RevisionEntry {
  const entry = ad.revisions[index];
  if (!entry) throw new Error(`${ad.ad_number} has no revision at index ${index}`);
  return entry;
}
