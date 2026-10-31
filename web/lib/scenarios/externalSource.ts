/**
 * Scenario 3 - EXTERNAL_SOURCE_REQUIRED, the one that matters most.
 *
 * AD 2026-22-02 paragraph (c) reads, verbatim: "This AD applies to Airbus SAS
 * Model A330-941 airplanes, certificated in any category, as identified in
 * European Union Aviation Safety Agency (EASA) AD 2025-0208, dated September 24,
 * 2025 (EASA AD 2025-0208)."
 *
 * The model condition is satisfiable from the fleet record. Membership of the
 * affected set is not: it lives in EASA AD 2025-0208, which this corpus does not
 * hold. Guessing would be the single worst thing this engine could do, so it
 * refuses and shows exactly which document would settle it.
 */
import { evaluate } from "../applicability";
import { AD_A330_FCPC, CITE_A330, EASA_AD_2025_0208, REV_2026_21861 } from "../corpus";
import { DELEGATION_QUOTE } from "../corpus/ad_a330_fcpc";
import { REFUSAL_SEMANTICS } from "../contract";
import { aircraftByTail } from "../fleet";
import type { EngineEvent, RefusalPayload } from "../events";
import { adAndRevision, entity, emptyPlan, retrievalOf, envelopeFor, stageTimings, type Frame, type Scenario } from "./shared";

const QUERY = "Does AD 2026-22-02 apply to N401DZ, our A330-941, MSN 1915?";
const entry = adAndRevision(AD_A330_FCPC, 0);

const subject = aircraftByTail("N401DZ");
if (!subject) throw new Error("N401DZ is not in the fleet extract");

const verdict = evaluate(AD_A330_FCPC, entry, subject);

const refusal: RefusalPayload<"EXTERNAL_SOURCE_REQUIRED"> = {
  code: "EXTERNAL_SOURCE_REQUIRED",
  detail: {
    external_doc_needed: {
      authority: EASA_AD_2025_0208.authority,
      ad_number: EASA_AD_2025_0208.ad_number,
      dated: EASA_AD_2025_0208.dated,
      held: EASA_AD_2025_0208.held,
      delegated_quote: DELEGATION_QUOTE,
    },
  },
  resolvable_by: REFUSAL_SEMANTICS.EXTERNAL_SOURCE_REQUIRED.resolvable_by,
  evidence_paragraph_ids: ["2026-21861#c", "2026-21861#g", "2026-21861#k"],
};

const frames: Frame[] = [
  {
    delay_ms: 110,
    event: {
      event: "entities",
      data: {
        stage_ms: 4,
        entities: [
          entity(QUERY, "ad_number", "2026-22-02"),
          entity(QUERY, "tail_number", "N401DZ"),
          entity(QUERY, "model", "A330-941"),
          entity(QUERY, "serial_number", "1915", 0.96),
        ],
      },
    },
  },
  {
    delay_ms: 820,
    event: {
      event: "query_plan",
      data: {
        stage_ms: 806,
        model: "claude-sonnet-4-6",
        plan: emptyPlan({
          intent: "applicability",
          ad_number: "2026-22-02",
          docket_id: "FAA-2026-8782",
          topic: "Flight Control Primary Computer standard",
          aircraft: {
            model: "A330-941",
            typecode: "A339",
            serial_number: "1915",
            tail_number: "N401DZ",
            manufacturer: "Airbus SAS",
          },
        }),
      },
    },
  },
  {
    // Over the 100 ms retrieval target: the latency badge is meant to say so.
    delay_ms: 230,
    event: { event: "retrieval", data: retrievalOf(entry, ["c", "g", "k", "a", "h"], 0.967, 118) },
  },
  {
    delay_ms: 80,
    event: {
      event: "decision",
      data: {
        decision: verdict.decision,
        fired_rule_ids: verdict.fired_rule_ids,
        unknown_fields: verdict.unknown_fields,
        proof_tree: verdict.proof_tree,
        stage_ms: 6,
      },
    },
  },
  { delay_ms: 150, event: { event: "refusal", data: refusal } },
];

frames.push({
  delay_ms: 50,
  event: { event: "done", data: { total_ms: 934, stage_timings: stageTimings(frames), envelope: envelopeFor(frames, {
      revisionId: REV_2026_21861.revision.revision_id,
      supersededBy: null,
      documentStage: "EFFECTIVE",
    }) } } satisfies EngineEvent,
});

export const EXTERNAL_SOURCE_SCENARIO: Scenario = {
  id: "external_source",
  label: "EXTERNAL_SOURCE_REQUIRED - applicability delegated to EASA",
  query: QUERY,
  watch_for:
    "Model resolves green, then the delegation node goes amber and the engine names the exact document it would need.",
  refusal_code: "EXTERNAL_SOURCE_REQUIRED",
  subject_tail: subject.tail_number,
  ad_number: AD_A330_FCPC.ad_number,
  frames,
};

export const EXTERNAL_SOURCE_REVISION = REV_2026_21861;
export const EXTERNAL_SOURCE_CITES = CITE_A330;
