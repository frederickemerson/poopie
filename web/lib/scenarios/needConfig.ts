/**
 * Scenario 2 - NEED_CONFIG. Paragraph (c) is conditioned on a manufacturer
 * serial number; the query named a model but no MSN and matched no single fleet
 * record. The amber node in the proof tree and the amber pulse on the plan chip
 * are the same fact at two zoom levels.
 */
import { evaluate } from "../applicability";
import { AD_A320_NLG, CITE_A320, REV_2026_23114 } from "../corpus";
import { REFUSAL_SEMANTICS } from "../contract";
import type { EngineEvent, RefusalPayload } from "../events";
import { adAndRevision, entity, emptyPlan, querySubject, retrievalOf, envelopeFor, stageTimings, type Frame, type Scenario } from "./shared";

const QUERY = "Does AD 2026-23-05 apply to our Airbus A320-214s?";
const entry = adAndRevision(AD_A320_NLG, 0);

const subject = querySubject({ manufacturer: "Airbus", model: "A320-214", typecode: "A320" });
const verdict = evaluate(AD_A320_NLG, entry, subject);

const serialRule = entry.rules.find((r) => r.field === "serial_number");
if (!serialRule) throw new Error("AD 2026-23-05 revision 1 has no serial_number rule");

const refusal: RefusalPayload<"NEED_CONFIG"> = {
  code: "NEED_CONFIG",
  detail: {
    which_value: {
      field: "serial_number",
      question: "Which manufacturer serial number (MSN)? Paragraph (c) is conditioned on it.",
      rule_value: serialRule.value,
      source_quote: serialRule.source_quote,
    },
  },
  resolvable_by: REFUSAL_SEMANTICS.NEED_CONFIG.resolvable_by,
  evidence_paragraph_ids: [serialRule.paragraph_id],
};

const frames: Frame[] = [
  {
    delay_ms: 110,
    event: {
      event: "entities",
      data: {
        stage_ms: 3,
        entities: [
          entity(QUERY, "ad_number", "2026-23-05"),
          entity(QUERY, "manufacturer", "Airbus"),
          entity(QUERY, "model", "A320-214"),
        ],
      },
    },
  },
  {
    delay_ms: 690,
    event: {
      event: "query_plan",
      data: {
        stage_ms: 681,
        model: "claude-sonnet-4-6",
        plan: emptyPlan({
          intent: "applicability",
          ad_number: "2026-23-05",
          docket_id: "FAA-2026-8779",
          topic: "nose landing gear sliding tube inspection",
          aircraft: {
            model: "A320-214",
            typecode: "A320",
            serial_number: null,
            tail_number: null,
            manufacturer: "Airbus",
          },
          ambiguities: [
            "serial_number: not supplied, and no single fleet record was matched",
            "fleet scope: “our A320-214s” names an operator fleet, not one airplane",
          ],
        }),
      },
    },
  },
  {
    delay_ms: 150,
    event: { event: "retrieval", data: retrievalOf(entry, ["c", "f", "g"], 0.918, 61) },
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
        stage_ms: 2,
      },
    },
  },
  { delay_ms: 140, event: { event: "refusal", data: refusal } },
];

frames.push({
  delay_ms: 50,
  event: { event: "done", data: { total_ms: 751, stage_timings: stageTimings(frames), envelope: envelopeFor(frames, {
      revisionId: REV_2026_23114.revision.revision_id,
      supersededBy: null,
      documentStage: "EFFECTIVE",
    }) } } satisfies EngineEvent,
});

export const NEED_CONFIG_SCENARIO: Scenario = {
  id: "need_config",
  label: "NEED_CONFIG - serial number missing",
  query: QUERY,
  watch_for:
    "Model and manufacturer resolve green, the serial-number condition stays amber, and the amber plan chip becomes the refusal.",
  refusal_code: "NEED_CONFIG",
  subject_tail: null,
  ad_number: AD_A320_NLG.ad_number,
  frames,
};

export const NEED_CONFIG_REVISION = REV_2026_23114;
export const NEED_CONFIG_CITES = CITE_A320;
