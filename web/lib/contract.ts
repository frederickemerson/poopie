// GENERATED FROM contracts/contract.json - DO NOT EDIT BY HAND.
// Regenerate with: python contracts/gen_ts.py

export const CONTRACT_VERSION = "1.0.0";

export type ParagraphRole = "EFFECTIVE_DATE" | "AFFECTED_ADS" | "APPLICABILITY" | "SUBJECT" | "UNSAFE_CONDITION" | "COMPLIANCE" | "REQUIRED_ACTIONS" | "EXCEPTIONS" | "CREDIT" | "AMOC" | "ADDITIONAL_INFO" | "IBR" | "OTHER";
export const PARAGRAPH_ROLE: readonly ParagraphRole[] = ["EFFECTIVE_DATE", "AFFECTED_ADS", "APPLICABILITY", "SUBJECT", "UNSAFE_CONDITION", "COMPLIANCE", "REQUIRED_ACTIONS", "EXCEPTIONS", "CREDIT", "AMOC", "ADDITIONAL_INFO", "IBR", "OTHER"] as const;

export type RuleField = "manufacturer" | "model" | "typecode" | "serial_number" | "engine" | "operator" | "built_year" | "category" | "equipment" | "modification" | "part_number";
export const RULE_FIELD: readonly RuleField[] = ["manufacturer", "model", "typecode", "serial_number", "engine", "operator", "built_year", "category", "equipment", "modification", "part_number"] as const;

export type RuleOperator = "eq" | "neq" | "in" | "not_in" | "model_matches" | "serial_in_range" | "serial_not_in_range" | "exists" | "not_exists" | "unparsed";
export const RULE_OPERATOR: readonly RuleOperator[] = ["eq", "neq", "in", "not_in", "model_matches", "serial_in_range", "serial_not_in_range", "exists", "not_exists", "unparsed"] as const;

export type Decision = "APPLIES" | "DOES_NOT_APPLY" | "CANNOT_DETERMINE";
export const DECISION: readonly Decision[] = ["APPLIES", "DOES_NOT_APPLY", "CANNOT_DETERMINE"] as const;

export type ComplianceBasis = "CALENDAR_DATE" | "FLIGHT_HOURS" | "FLIGHT_CYCLES" | "DAYS_AFTER_EFFECTIVE" | "EXTERNAL_DOCUMENT" | "UNPARSED";
export const COMPLIANCE_BASIS: readonly ComplianceBasis[] = ["CALENDAR_DATE", "FLIGHT_HOURS", "FLIGHT_CYCLES", "DAYS_AFTER_EFFECTIVE", "EXTERNAL_DOCUMENT", "UNPARSED"] as const;

export type Intent = "applicability" | "requirement" | "revision" | "search" | "fleet_impact";
export const INTENT: readonly Intent[] = ["applicability", "requirement", "revision", "search", "fleet_impact"] as const;

export type RefusalCode = "NEED_CONFIG" | "CANNOT_DETERMINE" | "NO_EVIDENCE" | "OUT_OF_SCOPE" | "SUPERSEDED" | "EXTERNAL_SOURCE_REQUIRED";
export const REFUSAL_CODE: readonly RefusalCode[] = ["NEED_CONFIG", "CANNOT_DETERMINE", "NO_EVIDENCE", "OUT_OF_SCOPE", "SUPERSEDED", "EXTERNAL_SOURCE_REQUIRED"] as const;

export type DocumentStage = "PROPOSED" | "ADOPTED_NOT_YET_EFFECTIVE" | "EFFECTIVE" | "SUPERSEDED" | "UNKNOWN";
export const DOCUMENT_STAGE: readonly DocumentStage[] = ["PROPOSED", "ADOPTED_NOT_YET_EFFECTIVE", "EFFECTIVE", "SUPERSEDED", "UNKNOWN"] as const;

export type Authority = "FAA" | "EASA" | "TCCA" | "ANAC" | "CAAC" | "UNKNOWN";
export const AUTHORITY: readonly Authority[] = ["FAA", "EASA", "TCCA", "ANAC", "CAAC", "UNKNOWN"] as const;

export type Source = "nprm_spreadsheet" | "federal_register" | "opensky" | "derived";
export const SOURCE: readonly Source[] = ["nprm_spreadsheet", "federal_register", "opensky", "derived"] as const;

export type SseEventName =
  "entities" | "query_plan" | "retrieval" | "decision" | "answer_delta" | "verification" | "refusal" | "done" | "error";

export const SSE_PAYLOAD_KEYS: Record<SseEventName, readonly string[]> = {
  entities: ["entities", "stage_ms"],
  query_plan: ["plan", "stage_ms", "model"],
  retrieval: ["paragraphs", "scores", "stage_ms"],
  decision: ["decision", "fired_rule_ids", "unknown_fields", "proof_tree", "stage_ms"],
  answer_delta: ["sentence", "citation_ids", "index"],
  verification: ["kept", "dropped", "drop_reasons", "stage_ms"],
  refusal: ["code", "detail", "resolvable_by", "evidence_paragraph_ids"],
  done: ["total_ms", "stage_timings"],
  error: ["message"],
};

export const REFUSAL_SEMANTICS: Record<RefusalCode, {
  trigger: string; resolvable_by: string; blocks_answer: boolean;
}> = {
  NEED_CONFIG: { trigger: "Rule exists on a field the query did not supply and the fleet record does not hold.", resolvable_by: "user supplies the value", blocks_answer: true },
  CANNOT_DETERMINE: { trigger: "Applicability text the extractor could not parse (Rule.operator == 'unparsed').", resolvable_by: "human reads the highlighted clause", blocks_answer: true },
  NO_EVIDENCE: { trigger: "Top fused retrieval score below threshold.", resolvable_by: "none; out of corpus", blocks_answer: true },
  OUT_OF_SCOPE: { trigger: "Query plan intent outside AD content, or a model absent from the corpus.", resolvable_by: "none", blocks_answer: true },
  SUPERSEDED: { trigger: "Asked about a revision that has a newer one. Answer IS still given, with a banner.", resolvable_by: "read the current revision", blocks_answer: false },
  EXTERNAL_SOURCE_REQUIRED: { trigger: "Applicability or compliance time is delegated to a ForeignAD or ServiceBulletin with held=false.", resolvable_by: "load the referenced document", blocks_answer: true },
};

export const LATENCY_TARGETS_MS = {"entity_pass": 5, "retrieval": 100, "applicability": 10, "query_plan": 1000, "verify": 20, "total_p95": 3000} as const;

export const CITATION_ID_FORMAT = "{revision_id}#{label}@{char_start}-{char_end}";
