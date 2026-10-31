/**
 * Scenario 1 - a clean applicability hit. Three cited sentences, a fully green
 * proof tree, and one sentence the verifier drops because its citation does not
 * resolve to a paragraph in the retrieved set. The dropped sentence exists so the
 * gate is visible: the UI never renders it.
 */
import { evaluate } from "../applicability";
import { AD_A320_NLG, CITE_A320, REV_2026_23114 } from "../corpus";
import { aircraftByTail } from "../fleet";
import type { EngineEvent } from "../events";
import { adAndRevision, entity, emptyPlan, retrievalOf, envelopeFor, stageTimings, type Frame, type Scenario } from "./shared";

const QUERY = "Does AD 2026-23-05 apply to N117UW, an A320-214 with MSN 1224, and what must I do by when?";
const entry = adAndRevision(AD_A320_NLG, 0);

const subject = aircraftByTail("N117UW");
if (!subject) throw new Error("N117UW is not in the fleet extract");

const verdict = evaluate(AD_A320_NLG, entry, subject);

/** A span in paragraph (h), which this query never retrieved. */
const UNRETRIEVED_CITATION = CITE_A320.prohibition;

const SENTENCES: readonly { sentence: string; citation_ids: readonly string[] }[] = [
  {
    sentence:
      "AD 2026-23-05 applies to N117UW: MSN 1224 falls inside manufacturer serial numbers (MSN) 1000 through 2500 inclusive.",
    citation_ids: [CITE_A320.serials],
  },
  {
    sentence:
      "Paragraph (g) requires a special detailed inspection of the affected NLG sliding tube for cracking and overheat damage.",
    citation_ids: [CITE_A320.action],
  },
  {
    sentence:
      "Compliance is due within 6,000 flight cycles or 36 months after the effective date of this AD, whichever occurs first.",
    citation_ids: [CITE_A320.compliance],
  },
  {
    sentence:
      "An alternative method of compliance is available for airplanes already inspected under the parts installation prohibition.",
    citation_ids: [UNRETRIEVED_CITATION],
  },
];

const frames: Frame[] = [
  {
    delay_ms: 120,
    event: {
      event: "entities",
      data: {
        stage_ms: 4,
        entities: [
          entity(QUERY, "ad_number", "2026-23-05"),
          entity(QUERY, "tail_number", "N117UW"),
          entity(QUERY, "model", "A320-214"),
          entity(QUERY, "serial_number", "1224", 0.94),
        ],
      },
    },
  },
  {
    delay_ms: 760,
    event: {
      event: "query_plan",
      data: {
        stage_ms: 742,
        model: "claude-sonnet-4-6",
        plan: emptyPlan({
          intent: "applicability",
          ad_number: "2026-23-05",
          docket_id: "FAA-2026-8779",
          topic: "nose landing gear sliding tube inspection",
          aircraft: {
            model: "A320-214",
            typecode: "A320",
            serial_number: "1224",
            tail_number: "N117UW",
            manufacturer: "Airbus SAS",
          },
        }),
      },
    },
  },
  {
    delay_ms: 180,
    event: { event: "retrieval", data: retrievalOf(entry, ["c", "g", "f", "a", "e"], 0.941, 68) },
  },
  {
    delay_ms: 90,
    event: {
      event: "decision",
      data: {
        decision: verdict.decision,
        fired_rule_ids: verdict.fired_rule_ids,
        unknown_fields: verdict.unknown_fields,
        proof_tree: verdict.proof_tree,
        stage_ms: 3,
      },
    },
  },
  ...SENTENCES.map(
    (s, index): Frame => ({
      delay_ms: 230,
      event: { event: "answer_delta", data: { ...s, index } },
    }),
  ),
  {
    delay_ms: 150,
    event: {
      event: "verification",
      data: {
        kept: [0, 1, 2],
        dropped: [3],
        // The verifier's own code, so the recorded stream and the live one speak
        // one vocabulary (engine/verify/verifier.py).
        drop_reasons: [
          {
            index: 3,
            citation_id: UNRETRIEVED_CITATION,
            reason: "citation_not_in_retrieved_set",
            detail: `${UNRETRIEVED_CITATION} was not in the set retrieved for this query`,
          },
        ],
        stage_ms: 12,
      },
    },
  },
];

frames.push({
  delay_ms: 60,
  event: {
    event: "done",
    data: { total_ms: 1098, stage_timings: stageTimings(frames), envelope: envelopeFor(frames, {
      revisionId: REV_2026_23114.revision.revision_id,
      supersededBy: null,
      documentStage: "EFFECTIVE",
    }) },
  } satisfies EngineEvent,
});

export const CLEAN_SCENARIO: Scenario = {
  id: "clean",
  label: "Clean applicability hit",
  query: QUERY,
  watch_for:
    "Three conditions resolve green in sequence; a fourth answer sentence is dropped by the verifier and never rendered.",
  refusal_code: null,
  subject_tail: subject.tail_number,
  ad_number: AD_A320_NLG.ad_number,
  frames,
};

export const CLEAN_REVISION = REV_2026_23114;
