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
  type AnswerStatus,
  type Authority,
  type ComplianceBasis,
  type Decision,
  type DocumentStage,
  type Intent,
  type ParagraphRole,
  type RefusalCode,
  type RuleField,
  type RuleOperator,
  type Source,
  type SourceKind,
  type SseEventName,
  type TraversalOutcome,
} from "./contract";

/* ---------------------------------------------------------------- nodes --- */

/**
 * The findable half of a citation, from engine/api/citations.py.
 *
 * A citation id is an exact character anchor and stays one; this is what a
 * reader takes to paper beside it. Every field the source does not hold is
 * `null` and named in `not_recorded`, so the UI can say "not recorded" instead
 * of printing a page number nobody published.
 *
 * `document_stage` is never absent: the engine cannot construct one of these
 * without a contract stage, which is what lets every pill show it.
 */
export interface HumanReference {
  readonly citation_id: string;
  readonly document_id: string;
  readonly source_kind: SourceKind | null;
  readonly document_stage: DocumentStage;
  /** One sentence from engine/graph/stage.py. For a proposal it says so. */
  readonly stage_note: string;
  readonly is_proposal: boolean;
  /** record_id for a proposal, AD number for an adopted AD. */
  readonly handle: string;
  readonly ad_number: string | null;
  readonly record_id: string | null;
  /** "91 FR 66019". Null when the source gave no citation in that form. */
  readonly fr_citation: string | null;
  /** "66019-66022", from the source's own page integers. */
  readonly page_range: string | null;
  /** The source's citation verbatim when it is not in "91 FR 66019" form. */
  readonly source_citation_text: string | null;
  readonly paragraph_label: string;
  readonly paragraph_role: ParagraphRole | null;
  readonly federal_register_link: string | null;
  readonly not_recorded: readonly string[];
  /** The whole reference on one line, as the engine composed it. */
  readonly display: string;
}

export interface ParagraphNode {
  readonly paragraph_id: string;
  readonly revision_id: string;
  /** Carried by the live retrieval hit; the AD this paragraph's revision belongs to. */
  readonly ad_number?: string | null;
  readonly label: string;
  readonly role: ParagraphRole;
  readonly heading: string;
  readonly text: string;
  /** Offset of this paragraph's first character in its Revision's plain text. */
  readonly char_start: number;
  readonly char_end: number;
  /**
   * Position within the revision. The live `retrieval` event does not carry it
   * (hits are ordered by fused score, not by document order), so it is optional
   * and filled from the hit index when the engine omits it.
   */
  readonly ordinal?: number;
  /** The paragraph's own full-span citation id, as the engine computed it. */
  readonly citation_id?: string;
  /**
   * The human reference for this paragraph's document. Optional because an
   * engine build older than contract 1.2.0 does not send one; when it is
   * missing the UI says the stage was not reported rather than assuming one.
   */
  readonly human_reference?: HumanReference;
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
  /** "91 FR 67442", from the Federal Register index. Null when not held. */
  readonly fr_citation: string | null;
  readonly start_page: number | null;
  readonly end_page: number | null;
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

/**
 * Field a parsed chip belongs to: rule_field, the plan's own slots, and the
 * remaining buckets the live entity pass emits (`amendments`, `ata_chapters`,
 * `foreign_ads`, `ambiguous`). The contract pins `entities` as a payload key but
 * not its shape; see docs/contract_change_requests.md.
 */
export type EntityField =
  | RuleField
  | "ad_number"
  | "docket_id"
  | "topic"
  | "tail_number"
  | "amendment"
  | "ata_chapter"
  | "foreign_ad"
  | "ambiguous";

export interface Entity {
  readonly field: EntityField;
  readonly value: string;
  /** [start, end) in the raw query text, so a chip can point at what it read. */
  readonly span: readonly [number, number];
  /**
   * Absent on the live wire: the entity pass is deterministic code, not a
   * scorer, so it publishes no confidence. The UI states "deterministic match"
   * rather than inventing a number.
   */
  readonly confidence?: number;
}

/* ----------------------------------------------------------- proof tree --- */

export type ProofNodeKind = "all" | "any" | "condition";

/** The fleet record the rules engine decided against, as the engine reports it. */
export interface ProofAircraft {
  readonly tail_number?: string | null;
  readonly manufacturer?: string | null;
  readonly model?: string | null;
  readonly typecode?: string | null;
  readonly serial_number?: string | null;
  readonly operator?: string | null;
}

/**
 * A document the revision delegates to and the corpus does not hold. Mirrors the
 * `external_documents` entries of the live proof tree; every field is the
 * engine's own, none derived in the UI.
 */
export interface ExternalDocumentRef {
  readonly doc_type?: string | null;
  readonly doc_id?: string | null;
  readonly label?: string | null;
  readonly dated?: string | null;
  readonly held?: boolean;
  readonly scope?: string | null;
  readonly role?: ParagraphRole | string | null;
  readonly paragraph_id?: string | null;
  readonly source_quote?: string | null;
}

/**
 * Legal stage of the revision the decision came from, as produced by
 * engine/graph/stage.py. Treated as opaque text by the UI: it is rendered, never
 * compared against a literal, so a new contract document_stage needs no UI edit.
 */
export interface RevisionStageNote {
  readonly document_stage?: string | null;
  readonly effective_on?: string | null;
  readonly superseded_by?: string | null;
  readonly imposes_obligation_now?: boolean;
  readonly explanation?: string | null;
}

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
  /** Why the rules engine reached this node's outcome, in the engine's words. */
  readonly reason?: string | null;
  /** Set when this node is blocked on a document the corpus does not hold. */
  readonly external_ref?: string | null;
  /** Root only: the fleet record and the revision the decision was made against. */
  readonly revision_id?: string | null;
  readonly aircraft?: ProofAircraft | null;
  readonly stage?: RevisionStageNote | null;
  readonly external_documents?: readonly ExternalDocumentRef[];
  readonly children?: readonly ProofTreeNode[];
}

/**
 * What the `decision` event carries when the rules engine could not run at all -
 * no aircraft resolved, no rules extracted for the retrieved revision. The
 * reason is the engine's own sentence and is shown verbatim: "no decision" is
 * information, not a loading state.
 */
export interface ProofTreeUnavailable {
  readonly unavailable: string;
}

export function isProofTreeUnavailable(
  tree: ProofTreeNode | ProofTreeUnavailable,
): tree is ProofTreeUnavailable {
  return "unavailable" in tree;
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
  /** null when the rules engine could not run; proof_tree then says why. */
  readonly decision: Decision | null;
  readonly fired_rule_ids: readonly string[];
  readonly unknown_fields: readonly RuleField[];
  readonly proof_tree: ProofTreeNode | ProofTreeUnavailable;
  readonly stage_ms: number;
}
export interface AnswerDeltaPayload {
  readonly sentence: string;
  readonly citation_ids: readonly string[];
  readonly index: number;
}
/**
 * Why one drafted sentence was dropped. `reason` is a stable code from
 * engine/verify/verifier.py, so the UI can show the machine vocabulary next to
 * the prose rather than paraphrasing it.
 */
export interface DropReason {
  readonly index: number;
  readonly citation_id: string | null;
  readonly reason: string;
  readonly detail: string | null;
}

export interface VerificationPayload {
  /** answer_delta.index values that survived verification. */
  readonly kept: readonly number[];
  readonly dropped: readonly number[];
  readonly drop_reasons: readonly DropReason[];
  readonly stage_ms: number;
  /**
   * Set only if a build of the engine reports kept/dropped as counts instead of
   * naming indices. The counts stay counts: expanding one into a set of
   * sentence indices would guess which sentence survived, which is the single
   * thing the verification gate exists to prevent.
   */
  readonly counted?: { readonly kept: number; readonly dropped: number } | null;
}
/**
 * One row of the `listing` event: a published revision as the corpus holds it,
 * flattened for display. Every field is the engine's own - the rows are ordered
 * in pure code from the graph index, so no field here is a model's reading of a
 * document.
 *
 * `make` and `product_type` are null when the index holds none for that
 * revision, and the UI says so rather than inferring a manufacturer from the AD
 * number.
 */
export interface ListingRow {
  readonly ad_number: string;
  readonly publication_date: string;
  readonly effective_on: string;
  /** "91 FR 67452", as the Federal Register index carries it. */
  readonly fr_citation: string;
  readonly is_current: boolean;
  readonly make: string | null;
  readonly product_type: string | null;
}

/**
 * A corpus listing: the newest directives *this corpus* holds, which is not the
 * same set as the newest directives that exist.
 *
 * The three bounds are not decoration. `rows` is the head of
 * `total_available`, ordered by `ordered_by`, over a corpus that runs from
 * `corpus_earliest` to `corpus_latest` - so a run whose corpus ended months ago
 * must not read as a live Federal Register feed. They travel with the rows
 * because the only honest way to render a top-N is beside the N it came from.
 */
export interface ListingPayload {
  readonly rows: readonly ListingRow[];
  /**
   * How the rows were ordered, in the engine's own words - the running service
   * sends "publication_date descending", not a bare field name. It is printed
   * beside the rows and never compared against a literal.
   */
  readonly ordered_by: string;
  /**
   * What the rows were narrowed to, in the engine's own words ("published in
   * 2025"), or null for the whole corpus. It changes what `total_available`
   * counts - the matches rather than the corpus - so the copy must branch on
   * it rather than print it as a decoration.
   */
  readonly filter: string | null;
  readonly corpus_earliest: string;
  readonly corpus_latest: string;
  /** How many revisions the ordering ran over. `rows` is the head of it. */
  readonly total_available: number;
  readonly stage_ms: number;
}

export interface RefusalPayload<C extends RefusalCode = RefusalCode> {
  /**
   * The keyed detail object when the engine sends one, or the engine's own
   * sentence. The live service sends a sentence; it is rendered verbatim rather
   * than reshaped into fields the payload does not contain.
   */
  readonly code: C;
  readonly detail: RefusalDetailByCode[C] | string;
  readonly resolvable_by: string;
  readonly evidence_paragraph_ids: readonly string[];
}
/* -------------------------------------------------------------- envelope --- */

export interface RevisionStatus {
  readonly revision_id: string | null;
  readonly superseded_by: string | null;
  readonly current: boolean;
}

export interface EnvelopeCitation {
  readonly sentence_index: number;
  readonly text: string;
  readonly citation_ids: readonly string[];
  readonly supporting_citation_id: string | null;
  /**
   * One reference per entry in `citation_ids`, in the same order. Optional for
   * the same reason as `ParagraphNode.human_reference`: an older engine build
   * does not send them.
   */
  readonly references?: readonly HumanReference[];
}

/**
 * Reference traversal. `outcome` is null when traversal did not run, and then
 * `reason` says so: the contract has no enum member for "not attempted", and
 * inventing one is exactly what the contract gate exists to catch.
 */
export interface TraversalReport {
  readonly outcome: TraversalOutcome | null;
  readonly reason?: string | null;
  readonly followed: readonly string[];
  readonly missing: readonly string[];
}

/**
 * contract.answer_envelope: the full shape of a delivered answer. A blocking
 * refusal carries one too, with answer_status REFUSED - a refusal is a delivered
 * answer, so it still has to say what was established and what would resolve it.
 */
export interface AnswerEnvelope {
  readonly answer_status: AnswerStatus;
  readonly document_stage: string;
  readonly applicability_result: Decision | null;
  readonly evaluated_conditions: ProofTreeNode | ProofTreeUnavailable;
  readonly revision_status: RevisionStatus;
  readonly citations: readonly EnvelopeCitation[];
  /** What the user could supply to resolve a NEED_CONFIG, named exactly. */
  readonly missing_inputs: readonly string[];
  /** What this answer does NOT establish. Shown, never hidden in a tooltip. */
  readonly limitations: readonly string[];
  readonly traversal: TraversalReport;
}

export interface DonePayload {
  readonly total_ms: number;
  readonly stage_timings: Readonly<Record<string, number>>;
  /**
   * Optional in the type, required on the wire: an engine that ends a run
   * without one has not delivered an answer envelope, and the UI says that
   * rather than rendering an empty one as though it were complete.
   */
  readonly envelope?: AnswerEnvelope;
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
  | { readonly event: "error"; readonly data: ErrorPayload }
  | { readonly event: "listing"; readonly data: ListingPayload };

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
  listing: "listing",
};
