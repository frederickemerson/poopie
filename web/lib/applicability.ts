/**
 * The applicability engine, deterministic and rule-driven. No language model is
 * involved in producing an enums.decision value: every outcome here is a fold
 * over Rule nodes against a fleet record, and a field the record does not carry
 * yields CANNOT_DETERMINE rather than a guess.
 *
 * The same function drives the proof tree in the evidence column and every cell
 * of the blast-radius grid, so the two cannot disagree.
 */
import type { Decision, RuleField } from "./contract";
import type { ProofTreeNode } from "./events";
import type { AdEntry, RevisionEntry, RuleNode } from "./corpus";
import type { FleetAircraft } from "./fleet";

/**
 * OpenSky publishes three registry spellings for the Airbus type-certificate
 * holder and one for Boeing (verified against the downloaded dataset: "Airbus",
 * "Airbus Industrie", "Airbus Sas", "Boeing"). Airbus Industrie was renamed
 * Airbus SAS in 2001; the aircraft and the type certificate are the same. The
 * aliasing is declared here rather than hidden in a comparison so the proof tree
 * can show what it resolved.
 */
const MANUFACTURER_ALIASES: Readonly<Record<string, string>> = {
  AIRBUS: "Airbus SAS",
  "AIRBUS INDUSTRIE": "Airbus SAS",
  "AIRBUS SAS": "Airbus SAS",
  BOEING: "The Boeing Company",
  "BOEING COMPANY": "The Boeing Company",
  "THE BOEING COMPANY": "The Boeing Company",
};

export function canonicalManufacturer(raw: string): string | null {
  return MANUFACTURER_ALIASES[raw.trim().toUpperCase()] ?? null;
}

/** Registry model strings are free text. Reduce to the Airbus/Boeing form. */
export function normaliseModel(raw: string): string {
  let s = raw.trim().toUpperCase();
  s = s.replace(/\(([^)]*)\)/g, " $1 ");
  s = s.replace(/^(AIRBUS|BOEING|THE BOEING COMPANY)\s+/, "");
  s = s.replace(/[^A-Z0-9]+/g, "-").replace(/^-|-$/g, "");
  s = s.replace(/-SL$/, "").replace(/SL$/, "");
  return s;
}

function modelMatches(aircraftModel: string, listed: string): boolean {
  const have = normaliseModel(aircraftModel);
  return listed.split(",").some((raw) => {
    const entry = raw.replace(/\band\b/gi, "").trim();
    if (!entry) return false;
    const series = /^(.*?)\s+series$/i.exec(entry);
    if (series && series[1]) {
      // "757-200 series" covers 757-2xx; "A330-200 series" covers A330-2xx.
      const stem = normaliseModel(series[1]);
      return have.startsWith(stem.slice(0, stem.length - 2));
    }
    return have === normaliseModel(entry);
  });
}

function msn(serial: string): number | null {
  const digits = serial.trim().replace(/^0+/, "");
  if (!/^\d+$/.test(digits)) return null;
  return Number.parseInt(digits, 10);
}

function inRange(serial: string, range: string): boolean | null {
  const n = msn(serial);
  const [lo, hi] = range.split("-").map((v) => Number.parseInt(v.trim(), 10));
  if (n === null || lo === undefined || hi === undefined || Number.isNaN(lo) || Number.isNaN(hi)) {
    return null;
  }
  return n >= lo && n <= hi;
}

/** What the fleet record holds for a rule_field. null means the record has none. */
export function fieldValue(aircraft: FleetAircraft, field: RuleField): string | null {
  switch (field) {
    case "manufacturer":
      return aircraft.manufacturer;
    case "model":
      return aircraft.model;
    case "typecode":
      return aircraft.typecode;
    case "serial_number":
      return aircraft.serial_number;
    case "operator":
      return aircraft.operator;
    case "built_year":
      return aircraft.built_year === null ? null : String(aircraft.built_year);
    case "equipment":
      return aircraft.equipment === null ? null : aircraft.equipment.join(", ");
    case "modification":
      return aircraft.modification === null ? null : aircraft.modification.join(", ");
    case "engine":
    case "category":
    case "part_number":
      return null;
    default:
      return null;
  }
}

/** Human label for a condition row in the proof tree. */
function conditionLabel(r: RuleNode): string {
  const field = r.field.replace(/_/g, " ");
  switch (r.operator) {
    case "serial_in_range":
      return `MSN in ${r.value}`;
    case "serial_not_in_range":
      return `MSN outside ${r.value}`;
    case "model_matches":
      return "model is a listed variant";
    case "exists":
      return `${field} present in record`;
    case "not_exists":
      return `${field} absent from record`;
    case "in":
      return `${field} is ${r.value}`;
    case "not_in":
      return `${field} is not ${r.value}`;
    case "neq":
      return `${field} is not ${r.value}`;
    case "unparsed":
      return `${field} clause not parsed`;
    case "eq":
    default:
      return `${field} is ${r.value}`;
  }
}

function evaluateRule(r: RuleNode, aircraft: FleetAircraft): { decision: Decision; shown: string | null } {
  const raw = fieldValue(aircraft, r.field);
  if (r.operator === "unparsed") return { decision: "CANNOT_DETERMINE", shown: raw };
  if (raw === null || raw === "") {
    return { decision: r.operator === "not_exists" ? "APPLIES" : "CANNOT_DETERMINE", shown: null };
  }
  switch (r.operator) {
    case "exists":
      return { decision: "APPLIES", shown: raw };
    case "not_exists":
      return { decision: "DOES_NOT_APPLY", shown: raw };
    case "model_matches":
      return { decision: modelMatches(raw, r.value) ? "APPLIES" : "DOES_NOT_APPLY", shown: raw };
    case "serial_in_range":
    case "serial_not_in_range": {
      const hit = inRange(raw, r.value);
      if (hit === null) return { decision: "CANNOT_DETERMINE", shown: raw };
      const yes = r.operator === "serial_in_range" ? hit : !hit;
      return { decision: yes ? "APPLIES" : "DOES_NOT_APPLY", shown: `MSN ${msn(raw) ?? raw}` };
    }
    case "in":
    case "eq": {
      const wanted = r.value.split(",").map((v) => v.trim().toLowerCase());
      const canon = r.field === "manufacturer" ? canonicalManufacturer(raw) : null;
      const have = (canon ?? raw).trim().toLowerCase();
      const shown = canon && canon !== raw ? `${raw} → ${canon}` : raw;
      return { decision: wanted.includes(have) ? "APPLIES" : "DOES_NOT_APPLY", shown };
    }
    case "not_in":
    case "neq": {
      const wanted = r.value.split(",").map((v) => v.trim().toLowerCase());
      const canon = r.field === "manufacturer" ? canonicalManufacturer(raw) : null;
      const have = (canon ?? raw).trim().toLowerCase();
      return { decision: wanted.includes(have) ? "DOES_NOT_APPLY" : "APPLIES", shown: raw };
    }
    default:
      return { decision: "CANNOT_DETERMINE", shown: raw };
  }
}

/** AND over conditions: one failure settles it; otherwise unknowns dominate. */
export function foldAll(decisions: readonly Decision[]): Decision {
  if (decisions.some((d) => d === "DOES_NOT_APPLY")) return "DOES_NOT_APPLY";
  if (decisions.some((d) => d === "CANNOT_DETERMINE")) return "CANNOT_DETERMINE";
  return decisions.length === 0 ? "CANNOT_DETERMINE" : "APPLIES";
}

export interface Verdict {
  readonly decision: Decision;
  readonly fired_rule_ids: readonly string[];
  readonly unknown_fields: readonly RuleField[];
  readonly proof_tree: ProofTreeNode;
  /** Set when a held=false document blocks the determination. */
  readonly blocked_by_external: string | null;
}

export function evaluate(
  ad: AdEntry,
  entry: RevisionEntry,
  aircraft: FleetAircraft,
): Verdict {
  const children: ProofTreeNode[] = [];
  const fired: string[] = [];
  const unknown: RuleField[] = [];

  for (const r of entry.rules) {
    const { decision, shown } = evaluateRule(r, aircraft);
    if (decision === "APPLIES") fired.push(r.rule_id);
    if (decision === "CANNOT_DETERMINE" && !unknown.includes(r.field)) unknown.push(r.field);
    children.push({
      id: r.rule_id,
      kind: "condition",
      label: conditionLabel(r),
      decision,
      field: r.field,
      operator: r.operator,
      rule_value: r.value,
      aircraft_value: shown,
      source_quote: r.source_quote,
      citation_id: r.citation_id,
      unparsed_reason: r.unparsed_reason,
    });
  }

  const mcai = entry.adopts_mcai;
  let blocked: string | null = null;
  if (mcai && !mcai.held) {
    blocked = `${mcai.authority} AD ${mcai.ad_number}`;
    children.push({
      id: `${entry.built.revision.revision_id}:mcai`,
      kind: "condition",
      label: `identified in ${mcai.authority} AD ${mcai.ad_number}`,
      decision: "CANNOT_DETERMINE",
      rule_value: `${mcai.authority} AD ${mcai.ad_number}, dated ${mcai.dated}`,
      aircraft_value: null,
      unparsed_reason: `the applicability list lives in ${mcai.authority} AD ${mcai.ad_number}, which this corpus does not hold`,
      external_ref: mcai.foreign_ad_id,
    });
  }

  const decision = foldAll(children.map((c) => c.decision));
  const revision = entry.built.revision;
  return {
    decision,
    fired_rule_ids: fired,
    unknown_fields: unknown,
    blocked_by_external: blocked,
    proof_tree: {
      id: `${revision.revision_id}#c`,
      kind: "all",
      label: `${ad.ad_number} ¶(c) Applicability`,
      decision,
      children,
    },
  };
}

/** One row of the blast-radius grid. */
export interface FleetVerdict {
  readonly tail_number: string;
  readonly operator: string;
  readonly decision: Decision;
  readonly unknown_fields: readonly RuleField[];
}

export function evaluateFleet(
  ad: AdEntry,
  entry: RevisionEntry,
  fleet: readonly FleetAircraft[],
): readonly FleetVerdict[] {
  return fleet.map((aircraft) => {
    const v = evaluate(ad, entry, aircraft);
    return {
      tail_number: aircraft.tail_number,
      operator: aircraft.operator,
      decision: v.decision,
      unknown_fields: v.unknown_fields,
    };
  });
}
