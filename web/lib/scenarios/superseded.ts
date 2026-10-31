/**
 * Scenario 4 - SUPERSEDED. The only refusal code with blocks_answer=false: the
 * answer about the revision the technician asked for is still given, with a
 * banner and a link to the revision that replaced it.
 */
import { evaluate } from "../applicability";
import { AD_A330_RMP, CITE_A330_RMP, REV_2025_07990, REV_2026_22390 } from "../corpus";
import { REFUSAL_SEMANTICS } from "../contract";
import { aircraftByTail } from "../fleet";
import type { EngineEvent, RefusalPayload } from "../events";
import { adAndRevision, entity, emptyPlan, retrievalOf, stageTimings, type Frame, type Scenario } from "./shared";

const QUERY = "What does AD 2025-09-07 require for N401DZ?";
const asked = adAndRevision(AD_A330_RMP, 0);
const current = adAndRevision(AD_A330_RMP, 1);

const subject = aircraftByTail("N401DZ");
if (!subject) throw new Error("N401DZ is not in the fleet extract");

const verdict = evaluate(AD_A330_RMP, asked, subject);

const refusal: RefusalPayload<"SUPERSEDED"> = {
  code: "SUPERSEDED",
  detail: {
    superseded_warning: {
      asked_revision_id: asked.built.revision.revision_id,
      current_revision_id: current.built.revision.revision_id,
      current_ad_number: current.built.revision.ad_number,
      note:
        "AD 2025-09-07 was replaced by AD 2026-23-01 (Amendment 39-23507), effective " +
        "December 28, 2026. The answer below is for the revision you asked about.",
    },
  },
  resolvable_by: REFUSAL_SEMANTICS.SUPERSEDED.resolvable_by,
  evidence_paragraph_ids: ["2026-22390#b", "2026-22390#c"],
};

const SENTENCES: readonly { sentence: string; citation_ids: readonly string[] }[] = [
  {
    sentence:
      "AD 2025-09-07 applies to N401DZ: Model A330-941 is listed and the AD covers all manufacturer serial numbers.",
    citation_ids: [CITE_A330_RMP.old_all_serials],
  },
  {
    sentence:
      "It requires revising the airplane flight manual to address dual loss of RMP data synchronization, within 30 days after June 6, 2025.",
    citation_ids: [CITE_A330_RMP.old_action, CITE_A330_RMP.old_compliance],
  },
  {
    sentence:
      "That revision has been replaced: AD 2026-23-01 retains those revisions and additionally requires installing the RMP data synchronization modification.",
    citation_ids: [CITE_A330_RMP.new_replaces, CITE_A330_RMP.new_action],
  },
  {
    sentence:
      "The current revision narrows applicability to manufacturer serial numbers (MSN) 1900 through 1960 inclusive, so MSN 1915 is still affected.",
    citation_ids: [CITE_A330_RMP.new_serials],
  },
];

const frames: Frame[] = [
  {
    delay_ms: 110,
    event: {
      event: "entities",
      data: {
        stage_ms: 3,
        entities: [
          entity(QUERY, "ad_number", "2025-09-07"),
          entity(QUERY, "tail_number", "N401DZ"),
        ],
      },
    },
  },
  {
    delay_ms: 700,
    event: {
      event: "query_plan",
      data: {
        stage_ms: 688,
        model: "claude-sonnet-4-6",
        plan: emptyPlan({
          intent: "requirement",
          ad_number: "2025-09-07",
          docket_id: "FAA-2024-2149",
          topic: "radio management panel data synchronization",
          revision_scope: "specific",
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
    delay_ms: 190,
    event: {
      event: "retrieval",
      data: retrievalOf(asked, ["c", "g", "f", "a"], 0.953, 83, [
        current.built.paragraph("b"),
        current.built.paragraph("c"),
        current.built.paragraph("g"),
      ]),
    },
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
        stage_ms: 4,
      },
    },
  },
  { delay_ms: 120, event: { event: "refusal", data: refusal } },
  ...SENTENCES.map(
    (s, index): Frame => ({
      delay_ms: 210,
      event: { event: "answer_delta", data: { ...s, index } },
    }),
  ),
  {
    delay_ms: 140,
    event: {
      event: "verification",
      data: { kept: [0, 1, 2, 3], dropped: [], drop_reasons: {}, stage_ms: 17 },
    },
  },
];

frames.push({
  delay_ms: 60,
  event: { event: "done", data: { total_ms: 1241, stage_timings: stageTimings(frames) } } satisfies EngineEvent,
});

export const SUPERSEDED_SCENARIO: Scenario = {
  id: "superseded",
  label: "SUPERSEDED - answer still given, with a banner",
  query: QUERY,
  watch_for:
    "The only refusal that does not block the answer: banner, link to AD 2026-23-01, and a timeline where the asked revision has faded.",
  refusal_code: "SUPERSEDED",
  subject_tail: subject.tail_number,
  ad_number: "2025-09-07",
  frames,
};

export const SUPERSEDED_REVISIONS = { asked: REV_2025_07990, current: REV_2026_22390 };
