/**
 * The fleet-impact matrix, as the engine computes it.
 *
 *   GET /blast/{revision_id}
 *   -> { revision_id, counts: {APPLIES, DOES_NOT_APPLY, CANNOT_DETERMINE},
 *        cells: [{tail_number, operator, model, decision, unknown_fields}] }
 *
 * The counts come from the engine and are rendered as sent. Nothing here
 * re-decides an aircraft: the grid and the proof tree both have to come out of
 * the same decide() call or they will eventually disagree on stage.
 */
import type { Decision, RuleField } from "./contract";
import { FLEET_PROVENANCE } from "./fleet";

export interface BlastCell {
  readonly tail_number: string;
  readonly operator: string | null;
  readonly model: string | null;
  readonly decision: Decision;
  readonly unknown_fields: readonly RuleField[];
}

export interface BlastCounts {
  readonly APPLIES: number;
  readonly DOES_NOT_APPLY: number;
  readonly CANNOT_DETERMINE: number;
}

export interface BlastMatrix {
  readonly revision_id: string;
  readonly counts: BlastCounts;
  readonly cells: readonly BlastCell[];
}

/**
 * A revision the UI may ask for a matrix of. Only revisions a run actually
 * surfaced are offered, so the grid can never show a revision the engine did
 * not read for a real query.
 */
export interface BlastRevisionRef {
  readonly revision_id: string;
  readonly ad_number: string | null;
  /** True when the rules engine produced a decision against this revision. */
  readonly decided: boolean;
}

export interface OperatorGroup {
  readonly operator: string;
  readonly cells: readonly BlastCell[];
  readonly affected: number;
  readonly undetermined: number;
}

const UNATTRIBUTED = "operator not in the fleet record";

/** Group by operator, largest fleet first; operators are verbatim OpenSky strings. */
export function groupByOperator(cells: readonly BlastCell[]): readonly OperatorGroup[] {
  const buckets = new Map<string, BlastCell[]>();
  for (const cell of cells) {
    const key = cell.operator ?? UNATTRIBUTED;
    const bucket = buckets.get(key);
    if (bucket) bucket.push(cell);
    else buckets.set(key, [cell]);
  }
  return [...buckets.entries()]
    .map(([operator, group]) => ({
      operator,
      cells: group,
      affected: group.filter((c) => c.decision === "APPLIES").length,
      undetermined: group.filter((c) => c.decision === "CANNOT_DETERMINE").length,
    }))
    .sort((a, b) => b.cells.length - a.cells.length || a.operator.localeCompare(b.operator));
}

/**
 * Why a field could not be settled.
 *
 * The fields with no source column at all come from FLEET_PROVENANCE, which
 * scripts/gen_fleet.py writes from the downloaded dataset, and are documented in
 * docs/fleet.md. Every other field is one the record does carry in general, so
 * the blocker is the clause rather than the dataset, and the wording says so
 * instead of blaming the data.
 */
const NO_SOURCE_COLUMN: ReadonlySet<string> = new Set(FLEET_PROVENANCE.absent_fields);

export function explainUnknownField(field: string): string {
  const name = field.replace(/_/g, " ");
  if (NO_SOURCE_COLUMN.has(field)) {
    return `${name}: the OpenSky dataset has no ${name} column, so no fleet record can answer it (docs/fleet.md)`;
  }
  return `${name}: the rules engine could not evaluate the ${name} clause against this record, so it withheld the decision`;
}

export function explainCell(cell: BlastCell): string {
  if (cell.decision !== "CANNOT_DETERMINE") return "";
  if (cell.unknown_fields.length === 0) {
    return "the rules engine could not settle this aircraft from the AD text and the fleet record alone";
  }
  return cell.unknown_fields.map(explainUnknownField).join("\n");
}

/** Every field that blocked at least one aircraft, with how many it blocked. */
export function unknownFieldTally(cells: readonly BlastCell[]): readonly { field: string; count: number }[] {
  const tally = new Map<string, number>();
  for (const cell of cells) {
    if (cell.decision !== "CANNOT_DETERMINE") continue;
    for (const field of cell.unknown_fields) tally.set(field, (tally.get(field) ?? 0) + 1);
  }
  return [...tally.entries()]
    .map(([field, count]) => ({ field, count }))
    .sort((a, b) => b.count - a.count);
}

/* ------------------------------------------------------------------ fetch --- */

function isDecision(value: unknown): value is Decision {
  return value === "APPLIES" || value === "DOES_NOT_APPLY" || value === "CANNOT_DETERMINE";
}

function parseCell(raw: unknown): BlastCell | null {
  if (typeof raw !== "object" || raw === null) return null;
  const row = raw as Record<string, unknown>;
  if (typeof row.tail_number !== "string" || !isDecision(row.decision)) return null;
  return {
    tail_number: row.tail_number,
    operator: typeof row.operator === "string" && row.operator !== "" ? row.operator : null,
    model: typeof row.model === "string" && row.model !== "" ? row.model : null,
    decision: row.decision,
    unknown_fields: Array.isArray(row.unknown_fields)
      ? (row.unknown_fields.filter((f): f is string => typeof f === "string") as readonly RuleField[])
      : [],
  };
}

export async function fetchBlastMatrix(
  revisionId: string,
  signal?: AbortSignal,
): Promise<BlastMatrix> {
  const response = await fetch(`/api/blast/${encodeURIComponent(revisionId)}`, {
    cache: "no-store",
    signal,
  });
  const payload = (await response.json()) as Record<string, unknown>;

  if (!response.ok || typeof payload.error === "string") {
    throw new Error(
      typeof payload.error === "string" ? payload.error : `blast request failed: ${response.status}`,
    );
  }

  const counts = (payload.counts ?? {}) as Record<string, unknown>;
  const cells = Array.isArray(payload.cells)
    ? payload.cells.map(parseCell).filter((c): c is BlastCell => c !== null)
    : [];

  return {
    revision_id: typeof payload.revision_id === "string" ? payload.revision_id : revisionId,
    counts: {
      APPLIES: typeof counts.APPLIES === "number" ? counts.APPLIES : 0,
      DOES_NOT_APPLY: typeof counts.DOES_NOT_APPLY === "number" ? counts.DOES_NOT_APPLY : 0,
      CANNOT_DETERMINE: typeof counts.CANNOT_DETERMINE === "number" ? counts.CANNOT_DETERMINE : 0,
    },
    cells,
  };
}
