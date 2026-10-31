/**
 * Demo questions for the live engine, one per recorded scenario slot.
 *
 * The recorded scenarios in lib/scenarios ask about the four ADs in lib/corpus.
 * Those AD numbers are not in the built Federal Register corpus the engine
 * serves, so replaying a recorded question against the live engine retrieves
 * nothing useful. These are the live equivalents.
 *
 * Every question below was run against the engine and the outcome recorded from
 * what came back, not predicted:
 *
 *   AD 2026-20-13 / N655AA  DOES_NOT_APPLY   mfr pass, model fail, equipment unknown
 *   AD 2026-20-13 / N845AM  NEED_CONFIG      mfr + model pass, equipment unanswerable
 *   AD 2026-20-10 / N967AM  EXTERNAL_SOURCE_REQUIRED  applicability in a Boeing RB
 *   AD 2026-20-12 / N220CY  EXTERNAL_SOURCE_REQUIRED  serial list in an EA ASB appendix
 *
 * Each carries a tail number. Applicability needs one aircraft: a model alone
 * matches hundreds of records, and the engine refuses to pick one, so a question
 * without a tail number lands on "no specific aircraft identified" by design.
 */
import type { RefusalCode } from "./contract";
import type { ScenarioId } from "./mockStream";

export interface LiveDemo {
  /** The recorded scenario this stands in for, so one toolbar drives both. */
  readonly id: ScenarioId;
  readonly label: string;
  readonly query: string;
  readonly tail_number: string;
  /** What the engine actually returned when this was run. */
  readonly observed_refusal: RefusalCode | null;
  readonly watch_for: string;
}

export const LIVE_DEMOS: readonly LiveDemo[] = [
  {
    id: "clean",
    label: "decided — 757 vs a 737 AD",
    query: "Does AD 2026-20-13 apply to N655AA?",
    tail_number: "N655AA",
    observed_refusal: null,
    watch_for:
      "Manufacturer resolves green via the normalization table, the model condition goes red with the reason, and the decision is DOES_NOT_APPLY without ever reaching the equipment question.",
  },
  {
    id: "need_config",
    label: "NEED_CONFIG — equipment fit",
    query: "Does AD 2026-20-13 apply to N845AM?",
    tail_number: "N845AM",
    observed_refusal: "NEED_CONFIG",
    watch_for:
      "Same AD, a real 737-800: every condition the record can answer passes, and the PSU-monitor condition stays amber because OpenSky has no equipment column. A technician can clear it in seconds, which is why it is NEED_CONFIG and not CANNOT_DETERMINE.",
  },
  {
    id: "external_source",
    label: "EXTERNAL_SOURCE_REQUIRED — 787 bulletin",
    query: "Does AD 2026-20-10 apply to N967AM?",
    tail_number: "N967AM",
    observed_refusal: "EXTERNAL_SOURCE_REQUIRED",
    watch_for:
      "Manufacturer and model both pass, and the engine still refuses: paragraph (c) hands the affected set to a Boeing Alert Requirements Bulletin this corpus does not hold. Plain vector search answers yes here.",
  },
  {
    id: "superseded",
    label: "EXTERNAL_SOURCE_REQUIRED — serial appendix",
    query: "Does AD 2026-20-12 apply to N220CY?",
    tail_number: "N220CY",
    observed_refusal: "EXTERNAL_SOURCE_REQUIRED",
    watch_for:
      "The applicability is a list of HPT seal serial numbers in an appendix to an Engine Alliance bulletin. The extractor marked the serial clause unparsed rather than guessing a range, so all 478 fleet records come back amber.",
  },
];

export const DEFAULT_LIVE_DEMO: LiveDemo = LIVE_DEMOS[0]!;

export function liveDemo(id: string): LiveDemo {
  return LIVE_DEMOS.find((d) => d.id === id) ?? DEFAULT_LIVE_DEMO;
}

/**
 * The tail number in a free-typed question, if one of the demo aircraft is named.
 * Nothing is inferred beyond an exact match: the engine runs its own entity pass
 * over the text, and this only fills the explicit `tail_number` slot so the
 * applicability stage has an aircraft when the user typed one.
 */
export function tailNumberIn(query: string): string | null {
  const upper = query.toUpperCase();
  const match = /\b(N[0-9][0-9A-Z]{1,4})\b/.exec(upper);
  return match?.[1] ?? null;
}
