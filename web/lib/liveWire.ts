/**
 * The live FastAPI payloads, and the one place they are reshaped for the UI.
 *
 * The contract pins every SSE event name and every top-level payload key. It
 * deliberately does not pin the *inner* shape of `entities`, `proof_tree`,
 * `detail`, `scores`, `kept` or `dropped`, and the running service and the mock
 * stream picked different inner shapes for all six. Normalising here, at the
 * wire boundary, means the reducer and every component keep working against the
 * single set of types in events.ts; nothing downstream has to know which source
 * produced the run.
 *
 * Two rules hold throughout: no field is invented to fill a gap the engine left
 * empty, and nothing is reshaped unless the live form is recognisably different.
 * Mock payloads already arrive in the UI shape and pass through untouched, which
 * is what keeps the dev toggle honest.
 */
import { formatCitationId, sameParagraph } from "./citation";
import { REFUSAL_SEMANTICS, RULE_FIELD } from "./contract";
import type {
  AnswerStatus,
  Decision,
  RefusalCode,
  RuleField,
  RuleOperator,
  SseEventName,
  TraversalOutcome,
} from "./contract";
import type {
  AnswerEnvelope,
  DecisionPayload,
  DonePayload,
  DropReason,
  EngineEvent,
  Entity,
  EntityField,
  ExternalDocumentRef,
  ParagraphNode,
  ProofAircraft,
  ProofTreeNode,
  RefusalPayload,
  RetrievalPayload,
  RevisionStageNote,
  VerificationPayload,
} from "./events";

/* ------------------------------------------------------------------ utils --- */

type Json = Record<string, unknown>;

const isObject = (v: unknown): v is Json => typeof v === "object" && v !== null && !Array.isArray(v);
const asString = (v: unknown): string | null => (typeof v === "string" && v !== "" ? v : null);
const asNumber = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const asArray = (v: unknown): readonly unknown[] => (Array.isArray(v) ? v : []);
const strings = (v: unknown): readonly string[] =>
  asArray(v).filter((x): x is string => typeof x === "string");

/** A rule's `value` is a scalar in the AD text or a list of listed variants. */
function joinRuleValue(v: unknown): string | undefined {
  if (typeof v === "string") return v === "" ? undefined : v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (Array.isArray(v)) {
    const parts = v.map((x) => (typeof x === "string" ? x : JSON.stringify(x)));
    return parts.length > 0 ? parts.join(", ") : undefined;
  }
  return undefined;
}

/* --------------------------------------------------------------- entities --- */

/**
 * The live entity pass returns one bucket per kind, not a flat list of spans.
 * Every bucket maps onto an EntityField; the span is located in the query text
 * the caller submitted, so a chip still points at the characters it was read
 * from, and no confidence is fabricated for a deterministic matcher.
 */
const ENTITY_BUCKETS: Readonly<Record<string, EntityField>> = {
  ad_numbers: "ad_number",
  docket_ids: "docket_id",
  amendments: "amendment",
  tail_numbers: "tail_number",
  serial_numbers: "serial_number",
  models: "model",
  typecodes: "typecode",
  manufacturers: "manufacturer",
  operators: "operator",
  ata_chapters: "ata_chapter",
  foreign_ads: "foreign_ad",
  ambiguous: "ambiguous",
};

function spanIn(query: string, value: string): readonly [number, number] {
  const at = query.toLowerCase().indexOf(value.toLowerCase());
  return at < 0 ? [0, 0] : [at, at + value.length];
}

export function normaliseEntities(raw: unknown, query: string): readonly Entity[] {
  if (Array.isArray(raw)) return raw as readonly Entity[];
  if (!isObject(raw)) return [];
  const out: Entity[] = [];
  for (const [bucket, field] of Object.entries(ENTITY_BUCKETS)) {
    for (const value of strings(raw[bucket])) {
      out.push({ field, value, span: spanIn(query, value) });
    }
  }
  return out;
}

/* -------------------------------------------------------------- retrieval --- */

const PARAGRAPH_KEYS = [
  "paragraph_id",
  "revision_id",
  "ad_number",
  "label",
  "role",
  "heading",
  "text",
  "char_start",
  "char_end",
  "ordinal",
] as const;

/**
 * Live hits carry retrieval telemetry alongside the Paragraph node fields
 * (`score`, `keyword_rank`, `dense_rank`, `dense_cosine`, `ad_number`). Only the
 * node fields are kept; `ordinal` is absent on the wire because hits come back
 * in fused-score order, so the hit index stands in for it.
 */
function normaliseParagraph(raw: unknown, index: number): ParagraphNode | null {
  if (!isObject(raw)) return null;
  const picked: Json = {};
  for (const key of PARAGRAPH_KEYS) {
    if (raw[key] !== undefined) picked[key] = raw[key];
  }
  if (asString(picked.paragraph_id) === null) return null;
  if (picked.ordinal === undefined) picked.ordinal = index;
  return picked as unknown as ParagraphNode;
}

export function normaliseRetrieval(raw: unknown): RetrievalPayload {
  const data = isObject(raw) ? raw : {};
  const paragraphs = asArray(data.paragraphs)
    .map(normaliseParagraph)
    .filter((p): p is ParagraphNode => p !== null);

  // The live service sends scores positionally, one per hit; the mock sends a
  // map keyed by paragraph_id. Both end up keyed, because the components look a
  // score up by paragraph.
  let scores: Record<string, number> = {};
  if (Array.isArray(data.scores)) {
    paragraphs.forEach((p, i) => {
      const score = asNumber(data.scores ? (data.scores as unknown[])[i] : null);
      if (score !== null) scores[p.paragraph_id] = score;
    });
  } else if (isObject(data.scores)) {
    scores = Object.fromEntries(
      Object.entries(data.scores).filter((e): e is [string, number] => typeof e[1] === "number"),
    );
  }

  return { paragraphs, scores, stage_ms: asNumber(data.stage_ms) ?? 0 };
}

/* --------------------------------------------------------------- decision --- */

/**
 * The rules engine reports a condition's outcome as satisfied / not satisfied /
 * not knowable. Those are the three enums.decision values seen from the
 * condition's point of view, which is the colouring the proof tree already uses:
 * green means this condition holds.
 */
const OUTCOME_DECISION: Readonly<Record<string, Decision>> = {
  pass: "APPLIES",
  fail: "DOES_NOT_APPLY",
  unknown: "CANNOT_DETERMINE",
};

function conditionLabel(field: string | null, operator: string | null, value: string | undefined): string {
  const name = (field ?? "condition").replace(/_/g, " ");
  switch (operator) {
    case "model_matches":
      return "model is a listed variant";
    case "serial_in_range":
      return `MSN in ${value ?? "the listed range"}`;
    case "serial_not_in_range":
      return `MSN outside ${value ?? "the listed range"}`;
    case "exists":
      return `${name} present in record`;
    case "not_exists":
      return `${name} absent from record`;
    case "unparsed":
      return `${name} clause not parsed`;
    case "neq":
    case "not_in":
      return `${name} is not ${value ?? "the listed value"}`;
    default:
      return `${name} is ${value ?? "the listed value"}`;
  }
}

/**
 * Build a contract-shaped citation id for a condition. The engine gives the
 * paragraph and the verbatim source quote but no character offsets, so the span
 * is located in the retrieved paragraph's own text and offset by that
 * paragraph's start. If the quote is not found verbatim, no citation is
 * produced: an unresolvable citation is worse than none.
 */
function citationFor(
  paragraphId: string | null,
  quote: string | null,
  paragraphs: readonly ParagraphNode[],
): string | undefined {
  if (paragraphId === null || quote === null) return undefined;
  const paragraph = paragraphs.find((p) => sameParagraph(p.paragraph_id, paragraphId));
  if (!paragraph) return undefined;
  const at = paragraph.text.indexOf(quote);
  if (at < 0) return undefined;
  return formatCitationId({
    revision_id: paragraph.revision_id,
    label: paragraph.label,
    char_start: paragraph.char_start + at,
    char_end: paragraph.char_start + at + quote.length,
  });
}

function normaliseCondition(
  raw: unknown,
  index: number,
  paragraphs: readonly ParagraphNode[],
): ProofTreeNode | null {
  if (!isObject(raw)) return null;
  const operator = asString(raw.operator);
  const field = asString(raw.field);
  const value = joinRuleValue(raw.value);
  const outcome = asString(raw.outcome) ?? "unknown";
  const reason = asString(raw.reason);
  const sourceQuote = asString(raw.source_quote);
  const paragraphId = asString(raw.paragraph_id);

  return {
    id: asString(raw.rule_id) ?? `condition-${index}`,
    kind: "condition",
    label: conditionLabel(field, operator, value),
    decision: OUTCOME_DECISION[outcome] ?? "CANNOT_DETERMINE",
    ...(field === null ? {} : { field: field as RuleField }),
    ...(operator === null ? {} : { operator: operator as RuleOperator }),
    ...(value === undefined ? {} : { rule_value: value }),
    aircraft_value: typeof raw.aircraft_value === "string" ? raw.aircraft_value : null,
    ...(sourceQuote === null ? {} : { source_quote: sourceQuote }),
    ...(() => {
      const id = citationFor(paragraphId, sourceQuote, paragraphs);
      return id === undefined ? {} : { citation_id: id };
    })(),
    // An unparsed clause is the one case where the reason is the headline, so it
    // keeps the amber callout the tree already has for it.
    unparsed_reason: operator === "unparsed" ? reason : null,
    reason,
  };
}

function normaliseExternalDocument(raw: unknown): ExternalDocumentRef | null {
  if (!isObject(raw)) return null;
  return {
    doc_type: asString(raw.doc_type),
    doc_id: asString(raw.doc_id),
    label: asString(raw.label),
    dated: asString(raw.dated),
    held: raw.held === true,
    scope: asString(raw.scope),
    role: asString(raw.role),
    paragraph_id: asString(raw.paragraph_id),
    source_quote: asString(raw.source_quote),
  };
}

/**
 * A delegated document is not a rule, but it is the reason the determination
 * stops, so it becomes a condition row of its own. Without this the proof tree
 * would show every condition satisfied next to a refusal, which reads as a
 * contradiction.
 */
function externalCondition(
  doc: ExternalDocumentRef,
  index: number,
  paragraphs: readonly ParagraphNode[],
): ProofTreeNode {
  const name = doc.label ?? doc.doc_id ?? "a document outside this corpus";
  const quote = doc.source_quote ?? null;
  const citation = citationFor(doc.paragraph_id ?? null, quote, paragraphs);
  return {
    id: `delegated-${doc.doc_id ?? index}`,
    kind: "condition",
    label: `as identified in ${name}`,
    decision: "CANNOT_DETERMINE",
    rule_value: doc.dated === null || doc.dated === undefined ? name : `${name} (${doc.dated})`,
    aircraft_value: null,
    ...(quote === null ? {} : { source_quote: quote }),
    ...(citation === undefined ? {} : { citation_id: citation }),
    unparsed_reason: `the affected set is defined inside ${name}, which this corpus does not hold`,
    reason: null,
    external_ref: doc.doc_id ?? null,
  };
}

function normaliseStage(raw: unknown): RevisionStageNote | null {
  if (!isObject(raw)) return null;
  return {
    document_stage: asString(raw.document_stage),
    effective_on: asString(raw.effective_on),
    superseded_by: asString(raw.superseded_by),
    imposes_obligation_now: raw.imposes_obligation_now === true,
    explanation: asString(raw.explanation),
  };
}

function normaliseAircraft(raw: unknown): ProofAircraft | null {
  if (!isObject(raw)) return null;
  const keys = ["tail_number", "manufacturer", "model", "typecode", "serial_number", "operator"] as const;
  const out: Record<string, string | null> = {};
  for (const key of keys) out[key] = asString(raw[key]);
  return out as ProofAircraft;
}

export function normaliseDecision(raw: unknown, paragraphs: readonly ParagraphNode[]): DecisionPayload {
  const data = isObject(raw) ? raw : {};
  const stage_ms = asNumber(data.stage_ms) ?? 0;
  const decision = asString(data.decision) as Decision | null;
  const fired_rule_ids = strings(data.fired_rule_ids);
  const unknown_fields = strings(data.unknown_fields) as readonly RuleField[];
  const tree = data.proof_tree;

  // No decision at all: the engine says why, and that sentence is the payload.
  if (isObject(tree) && typeof tree.unavailable === "string") {
    return {
      decision: null,
      fired_rule_ids,
      unknown_fields,
      proof_tree: { unavailable: tree.unavailable },
      stage_ms,
    };
  }

  // Mock payloads already carry a built tree.
  if (isObject(tree) && typeof tree.kind === "string") {
    return {
      decision,
      fired_rule_ids,
      unknown_fields,
      proof_tree: tree as unknown as ProofTreeNode,
      stage_ms,
    };
  }

  if (!isObject(tree)) {
    return {
      decision,
      fired_rule_ids,
      unknown_fields,
      proof_tree: { unavailable: "The decision event carried no proof tree." },
      stage_ms,
    };
  }

  const externalDocuments = asArray(tree.external_documents)
    .map(normaliseExternalDocument)
    .filter((d): d is ExternalDocumentRef => d !== null);

  const children: ProofTreeNode[] = [
    ...asArray(tree.conditions)
      .map((c, i) => normaliseCondition(c, i, paragraphs))
      .filter((c): c is ProofTreeNode => c !== null),
    ...externalDocuments
      .filter((d) => d.held !== true)
      .map((d, i) => externalCondition(d, i, paragraphs)),
  ];

  const revisionId = asString(tree.revision_id);
  const treeDecision = (asString(tree.decision) as Decision | null) ?? decision;

  return {
    decision: treeDecision,
    fired_rule_ids: strings(tree.fired_rule_ids).length > 0 ? strings(tree.fired_rule_ids) : fired_rule_ids,
    unknown_fields:
      strings(tree.unknown_fields).length > 0
        ? (strings(tree.unknown_fields) as readonly RuleField[])
        : unknown_fields,
    proof_tree: {
      id: revisionId === null ? "applicability" : `${revisionId}#applicability`,
      kind: "all",
      label: revisionId === null ? "Applicability" : `Applicability of revision ${revisionId}`,
      decision: treeDecision ?? "CANNOT_DETERMINE",
      revision_id: revisionId,
      aircraft: normaliseAircraft(tree.aircraft),
      stage: normaliseStage(tree.stage),
      external_documents: externalDocuments,
      children,
    },
    stage_ms,
  };
}

/* ----------------------------------------------------------- verification --- */

function normaliseDropReason(raw: unknown, fallbackIndex: number): DropReason | null {
  if (!isObject(raw)) return null;
  return {
    index: asNumber(raw.index) ?? fallbackIndex,
    citation_id: asString(raw.citation_id),
    reason: asString(raw.reason) ?? "dropped by the verifier",
    detail: asString(raw.detail),
  };
}

export function normaliseVerification(raw: unknown): VerificationPayload {
  const data = isObject(raw) ? raw : {};
  const stage_ms = asNumber(data.stage_ms) ?? 0;
  const drop_reasons = asArray(data.drop_reasons)
    .map(normaliseDropReason)
    .filter((d): d is DropReason => d !== null);

  if (Array.isArray(data.kept) || Array.isArray(data.dropped)) {
    return {
      kept: asArray(data.kept).filter((v): v is number => typeof v === "number"),
      dropped: asArray(data.dropped).filter((v): v is number => typeof v === "number"),
      drop_reasons,
      stage_ms,
      counted: null,
    };
  }

  // Counts, not indices. They stay counts: expanding a count into a set of
  // sentence indices would be a guess about which sentence survived.
  return {
    kept: [],
    dropped: [],
    drop_reasons,
    stage_ms,
    counted: { kept: asNumber(data.kept) ?? 0, dropped: asNumber(data.dropped) ?? 0 },
  };
}

/* ---------------------------------------------------------------- refusal --- */

/**
 * `resolvable_by` arrives as a sentence from the rules engine
 * ("the engineer supplies the value") and as a list of field names from the
 * verifier gate (often empty). Both become one sentence; an empty list falls
 * back to the contract's own resolvable_by for that code rather than rendering
 * blank, because "who can fix this" is the whole point of a refusal code.
 */
export function normaliseRefusal(raw: unknown): RefusalPayload {
  const data = isObject(raw) ? raw : {};
  const code = (asString(data.code) ?? "NO_EVIDENCE") as RefusalCode;
  const listed = strings(data.resolvable_by);
  const resolvable =
    asString(data.resolvable_by) ??
    (listed.length > 0 ? listed.join(", ") : REFUSAL_SEMANTICS[code]?.resolvable_by) ??
    "";

  return {
    code,
    detail: (typeof data.detail === "string" ? data.detail : data.detail) as RefusalPayload["detail"],
    resolvable_by: resolvable,
    evidence_paragraph_ids: strings(data.evidence_paragraph_ids),
  };
}

/* ------------------------------------------------------------------- done --- */

/**
 * The `done` envelope. Its `evaluated_conditions` is the same proof tree the
 * decision event carries, so it goes through the same builder - the envelope and
 * the proof panel must never be able to show different trees.
 *
 * `missing_inputs` is validated against the contract's rule_field enum. The
 * contract says the field names "what the user could supply ... named exactly",
 * and the running engine currently mixes single characters into it (see the
 * report: engine/api/answer.py extends a list with a string). Anything that is
 * not a contract rule_field is not a field name, so it is not offered to the
 * user as one.
 */
function normaliseEnvelope(raw: unknown, paragraphs: readonly ParagraphNode[]): AnswerEnvelope | null {
  if (!isObject(raw)) return null;
  const conditions = raw.evaluated_conditions;
  const built = normaliseDecision(
    {
      decision: isObject(conditions) ? conditions.decision : null,
      fired_rule_ids: isObject(conditions) ? conditions.fired_rule_ids : [],
      unknown_fields: isObject(conditions) ? conditions.unknown_fields : [],
      proof_tree: conditions,
      stage_ms: 0,
    },
    paragraphs,
  );

  const status = asString(raw.answer_status);
  const revision = isObject(raw.revision_status) ? raw.revision_status : {};
  const traversal = isObject(raw.traversal) ? raw.traversal : {};
  const fields: ReadonlySet<string> = new Set(RULE_FIELD);

  return {
    answer_status: (status ?? "REFUSED") as AnswerStatus,
    document_stage: asString(raw.document_stage) ?? "",
    applicability_result: asString(raw.applicability_result) as Decision | null,
    evaluated_conditions: built.proof_tree,
    revision_status: {
      revision_id: asString(revision.revision_id),
      superseded_by: asString(revision.superseded_by),
      current: revision.current !== false,
    },
    citations: asArray(raw.citations)
      .filter(isObject)
      .map((c) => ({
        sentence_index: asNumber(c.sentence_index) ?? 0,
        text: asString(c.text) ?? "",
        citation_ids: strings(c.citation_ids),
        supporting_citation_id: asString(c.supporting_citation_id),
      })),
    missing_inputs: strings(raw.missing_inputs).filter((f) => fields.has(f)),
    limitations: strings(raw.limitations),
    traversal: {
      outcome: asString(traversal.outcome) as TraversalOutcome | null,
      reason: asString(traversal.reason),
      followed: strings(traversal.followed),
      missing: strings(traversal.missing),
    },
  };
}

/* -------------------------------------------------------------- the whole --- */

export interface EventNormaliser {
  (name: SseEventName, data: unknown): EngineEvent;
}

/**
 * One normaliser per run. It holds the query text (for entity spans) and the
 * retrieved paragraph set (for citation spans), because both arrive before the
 * events that need them.
 */
export function createEventNormaliser(query: string): EventNormaliser {
  let paragraphs: readonly ParagraphNode[] = [];

  return (name, data) => {
    switch (name) {
      case "entities": {
        const d = isObject(data) ? data : {};
        return {
          event: "entities",
          data: {
            entities: normaliseEntities(d.entities, query),
            stage_ms: asNumber(d.stage_ms) ?? 0,
          },
        };
      }
      case "retrieval": {
        const payload = normaliseRetrieval(data);
        paragraphs = payload.paragraphs;
        return { event: "retrieval", data: payload };
      }
      case "decision":
        return { event: "decision", data: normaliseDecision(data, paragraphs) };
      case "verification":
        return { event: "verification", data: normaliseVerification(data) };
      case "refusal":
        return { event: "refusal", data: normaliseRefusal(data) };
      case "done": {
        const d = isObject(data) ? data : {};
        const envelope = normaliseEnvelope(d.envelope, paragraphs);
        const payload: DonePayload = {
          total_ms: asNumber(d.total_ms) ?? 0,
          stage_timings: isObject(d.stage_timings)
            ? Object.fromEntries(
                Object.entries(d.stage_timings).filter(
                  (e): e is [string, number] => typeof e[1] === "number",
                ),
              )
            : {},
          ...(envelope === null ? {} : { envelope }),
        };
        return { event: "done", data: payload };
      }
      default:
        // query_plan, answer_delta, refusal and error already arrive in the
        // declared shape; `detail` is typed to accept the engine's sentence.
        return { event: name, data } as EngineEvent;
    }
  };
}
