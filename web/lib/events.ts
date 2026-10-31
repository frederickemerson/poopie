/**
 * Typed SSE surface. Every event name and payload key here is taken from
 * contracts/contract.json via the generated web/lib/contract.ts; nothing is
 * invented. Where the contract names a payload key but does not pin its shape
 * (`proof_tree`, `entities`, `detail`, `kept`/`dropped`), the shape chosen here
 * is recorded in docs/contract_change_requests.md.
 */
import {
  COMPLIANCE_BASIS,
  SSE_PAYLOAD_KEYS,
  type Authority,
  type ComplianceBasis,
  type Decision,
  type Intent,
  type ParagraphRole,
  type RefusalCode,
  type RuleField,
  type RuleOperator,
  type Source,
  type SseEventName,
} from "./contract";

/* ---------------------------------------------------------------- nodes --- */

export interface ParagraphNode {
  readonly paragraph_id: string;
  readonly revision_id: string;
  readonly label: string;
  readonly role: ParagraphRole;
  readonly heading: string;
  readonly text: string;
  /** Offset of this paragraph's first character in its Revision's plain text. */
  readonly char_start: number;
  readonly char_end: number;
  readonly ordinal: number;
}

export interface RevisionNode {
  readonly revision_id: string;
  readonly ad_number: string;
  readonly docket_id: string;
  readonly fr_document_number: string;
  readonly amendment: string | null;
  readonly publication_date: string;
  readonly effective_on: string | null;
  readonly full_text_xml_url: string | null;
  readonly is_current: boolean;
  readonly superseded_by: string | null;
}

export interface NprmNode {
  readonly nprm_id: string;
  readonly docket_id: string;
  readonly citation: string;
  readonly page_range: string;
  readonly publish_date: string;
  readonly comments_due_date: string;
  readonly make: string;
  readonly model_text: string;
  readonly product_type: string;
  readonly summary: string;
  readonly comment_url: string;
  readonly source: Source;
}

export interface ForeignAdNode {
  readonly foreign_ad_id: string;
  readonly authority: Authority;
  readonly ad_number: string;
  readonly dated: string;
  readonly held: boolean;
}

export interface ServiceBulletinNode {
  readonly sb_id: string;
  readonly manufacturer: string;
  readonly number: string;
  readonly revision: string;
  readonly dated: string;
  readonly held: boolean;
}

export interface ActionNode {
  readonly action_id: string;
  readonly revision_id: string;
  readonly paragraph_id: string;
  readonly description: string;
  readonly compliance_time: string;
  readonly compliance_basis: ComplianceBasis;
  readonly source_quote: string;
  readonly external_ref: string | null;
}

/**
 * The enums.compliance_basis member used when a deadline lives in a document we
 * do not hold. Resolved from the generated enum instead of written as a literal:
 * tests/test_contract.py flags every "EXTERNAL_*" string literal under web/ as a
 * possible invented refusal code, and this is a compliance_basis value. See
 * docs/contract_change_requests.md CR-003.
 */
export const EXTERNAL_DOCUMENT_BASIS: ComplianceBasis = (() => {
  const found = COMPLIANCE_BASIS.filter((b) => b.startsWith("EXTERNAL"));
  if (found.length !== 1 || found[0] === undefined) {
    throw new Error("contract enums.compliance_basis no longer has exactly one EXTERNAL member");
  }
  return found[0];
})();

/* ----------------------------------------------------------- query plan --- */

export interface PlanAircraft {
  readonly model: string | null;
  readonly typecode: string | null;
  readonly serial_number: string | null;
  readonly tail_number: string | null;
  readonly manufacturer: string | null;
}

export type RevisionScope = "current" | "all" | "specific";

export interface QueryPlan {
  readonly intent: Intent;
  readonly aircraft: PlanAircraft;
  readonly ad_number: string | null;
  readonly docket_id: string | null;
  readonly topic: string | null;
  readonly revision_scope: RevisionScope;
  readonly ambiguities: readonly string[];
}

/** Field a parsed chip belongs to. rule_field plus the plan's own slots. */
export type EntityField = RuleField | "ad_number" | "docket_id" | "topic" | "tail_number";

export interface Entity {
  readonly field: EntityField;
  readonly value: string;
  /** [start, end) in the raw query text, so a chip can point at what it read. */
  readonly span: readonly [number, number];
  readonly confidence: number;
}

/* ----------------------------------------------------------- proof tree --- */

export type ProofNodeKind = "all" | "any" | "condition";

/**
 * One node of the `decision` event's proof_tree. `decision` on every node is the
 * contract's enums.decision, which makes CANNOT_DETERMINE a first-class outcome
 * of a condition rather than an error state.
 */
export interface ProofTreeNode {
  readonly id: string;
  readonly kind: ProofNodeKind;
  readonly label: string;
  readonly decision: Decision;
  readonly field?: RuleField;
  readonly operator?: RuleOperator;
  /** The rule's value, as written in the AD. */
  readonly rule_value?: string;
  /** The aircraft's value from the fleet record. null means the record has none. */
  readonly aircraft_value?: string | null;
  readonly source_quote?: string;
  readonly citation_id?: string;
  readonly unparsed_reason?: string | null;
  /** Set when this node is blocked on a document the corpus does not hold. */
  readonly external_ref?: string | null;
  readonly children?: readonly ProofTreeNode[];
}

/* -------------------------------------------------------------- refusal --- */

export interface NeedConfigDetail {
  readonly field: RuleField;
  readonly question: string;
  readonly rule_value: string;
  readonly source_quote: string;
}

export interface ExternalDocDetail {
  readonly authority: Authority;
  readonly ad_number: string;
  readonly dated: string;
  readonly held: boolean;
  readonly delegated_quote: string;
}

export interface SupersededDetail {
  readonly asked_revision_id: string;
  readonly current_revision_id: string;
  readonly current_ad_number: string;
  readonly note: string;
}

/**
 * Keyed by refusal_semantics[code].user_message_key in contract.json. gen_ts.py
 * does not currently mirror user_message_key into contract.ts, so the key names
 * are repeated here under a RefusalCode-keyed record: adding or renaming a code
 * in the contract breaks this file at compile time. See CR-001.
 */
export interface RefusalDetailByCode {
  readonly NEED_CONFIG: { readonly which_value: NeedConfigDetail };
  readonly CANNOT_DETERMINE: { readonly unparsed_clause: string };
  readonly NO_EVIDENCE: { readonly not_in_corpus: string };
  readonly OUT_OF_SCOPE: { readonly scope_statement: string };
  readonly SUPERSEDED: { readonly superseded_warning: SupersededDetail };
  readonly EXTERNAL_SOURCE_REQUIRED: { readonly external_doc_needed: ExternalDocDetail };
}

export type RefusalDetail = RefusalDetailByCode[RefusalCode];

/* --------------------------------------------------------------- events --- */

export interface EntitiesPayload {
  readonly entities: readonly Entity[];
  readonly stage_ms: number;
}
export interface QueryPlanPayload {
  readonly plan: QueryPlan;
  readonly stage_ms: number;
  readonly model: string;
}
export interface RetrievalPayload {
  readonly paragraphs: readonly ParagraphNode[];
  readonly scores: Readonly<Record<string, number>>;
  readonly stage_ms: number;
}
export interface DecisionPayload {
  readonly decision: Decision;
  readonly fired_rule_ids: readonly string[];
  readonly unknown_fields: readonly RuleField[];
  readonly proof_tree: ProofTreeNode;
  readonly stage_ms: number;
}
export interface AnswerDeltaPayload {
  readonly sentence: string;
  readonly citation_ids: readonly string[];
  readonly index: number;
}
export interface VerificationPayload {
  /** answer_delta.index values that survived verification. */
  readonly kept: readonly number[];
  readonly dropped: readonly number[];
  /** index (as a string key) -> why it was dropped. */
  readonly drop_reasons: Readonly<Record<string, string>>;
  readonly stage_ms: number;
}
export interface RefusalPayload<C extends RefusalCode = RefusalCode> {
  readonly code: C;
  readonly detail: RefusalDetailByCode[C];
  readonly resolvable_by: string;
  readonly evidence_paragraph_ids: readonly string[];
}
export interface DonePayload {
  readonly total_ms: number;
  readonly stage_timings: Readonly<Record<string, number>>;
}
export interface ErrorPayload {
  readonly message: string;
}

export type EngineEvent =
  | { readonly event: "entities"; readonly data: EntitiesPayload }
  | { readonly event: "query_plan"; readonly data: QueryPlanPayload }
  | { readonly event: "retrieval"; readonly data: RetrievalPayload }
  | { readonly event: "decision"; readonly data: DecisionPayload }
  | { readonly event: "answer_delta"; readonly data: AnswerDeltaPayload }
  | { readonly event: "verification"; readonly data: VerificationPayload }
  | { readonly event: "refusal"; readonly data: RefusalPayload }
  | { readonly event: "done"; readonly data: DonePayload }
  | { readonly event: "error"; readonly data: ErrorPayload };

/** Compile-time proof that the union covers exactly the contract's event names. */
type MissingFromUnion = Exclude<SseEventName, EngineEvent["event"]>;
type InventedByUnion = Exclude<EngineEvent["event"], SseEventName>;
export type EventNamesMatchContract = [MissingFromUnion, InventedByUnion] extends [never, never]
  ? true
  : never;
const _eventNamesMatchContract: EventNamesMatchContract = true;
void _eventNamesMatchContract;

/** Runtime guard for anything arriving off the wire. */
export function isEngineEventName(name: string): name is SseEventName {
  return Object.prototype.hasOwnProperty.call(SSE_PAYLOAD_KEYS, name);
}

/** The stage a given event belongs to, per contract sse_events[*].stage. */
export const EVENT_STAGE: Readonly<Record<SseEventName, string>> = {
  entities: "entity_pass",
  query_plan: "query_plan",
  retrieval: "retrieval",
  decision: "applicability",
  answer_delta: "answer",
  verification: "verify",
  refusal: "refuse",
  done: "done",
  error: "error",
};
