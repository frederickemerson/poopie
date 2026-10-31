/**
 * Conversation state for a stateless engine.
 *
 * `POST /stream` takes a question and an optional tail number. There is no
 * conversation API, no session and no server-side history, so everything a
 * follow-up needs has to be IN the question text. This module owns the one job
 * that follows from that: turning a thread of turns into a single self-contained
 * question, and recording exactly what was added so the user can see it.
 *
 * Two rules are enforced here rather than in the components:
 *
 *  1. **Nothing is added to a question invisibly.** Every function that extends
 *     a question returns the appended text alongside it, so the caller is
 *     obliged to show it. The thread renders `carried` and `supplied` as
 *     separate, attributed fragments - never folded into the user's own words.
 *  2. **A value the user supplied is never presented as corpus evidence.** It
 *     travels as a `SuppliedFact` with `source: "user"` all the way into the
 *     archived turn, so any answer resting on it is labelled wherever it shows.
 *
 * Verified against the live engine on 2026-10-31: re-asking with a field value
 * stated in the question does NOT change the applicability verdict. The
 * applicability stage reads field values from the fleet record only, so
 * `aircraft_value` stays null and the condition's outcome stays `unknown`. The
 * UI therefore states that plainly instead of implying the re-ask resolves the
 * refusal. See SUPPLIED_VALUE_LIMIT.
 */
import type { RuleField } from "./contract";
import type {
  DecisionPayload,
  ExternalDocumentRef,
  ProofTreeNode,
  QueryPlan,
  RefusalPayload,
} from "./events";
import { isProofTreeUnavailable } from "./events";

/* ------------------------------------------------------------- supplied --- */

/**
 * Something the user typed that was put into a question. It is carried through
 * the thread so every surface that shows an answer resting on it can say where
 * it came from. `source` is a single literal rather than a boolean because the
 * only honest answer to "where did this come from?" is a named origin.
 */
export interface SuppliedFact {
  readonly source: "user";
  /** "value" is a field answer; "document" is applicability text pasted in. */
  readonly kind: "value" | "document";
  /** What it answers: a rule field name, or the document it came from. */
  readonly label: string;
  /** Verbatim, as the user typed it. Never reworded. */
  readonly text: string;
}

/** A question to send, plus everything the UI added to the user's own words. */
export interface AskIntent {
  /** The user's own words, unmodified. */
  readonly asked: string;
  /** The full text sent to the engine: `asked` plus the additions below. */
  readonly question: string;
  /** Subject restated from an earlier turn, or null when nothing was carried. */
  readonly carried: string | null;
  readonly supplied: readonly SuppliedFact[];
}

/**
 * The gap the re-ask cannot close, stated once and reused. Written here rather
 * than in a component so every surface says the same thing: a chip that
 * silently did nothing would be exactly the failure this product exists to
 * avoid, and so would one that implied it had worked.
 */
export const SUPPLIED_VALUE_LIMIT =
  "The engine reads field values from the fleet record only, so the verdict will not change until it accepts a supplied value. Your answer is recorded in the thread and put to the answer stage, attributed to you.";

export const SUPPLIED_DOCUMENT_LIMIT =
  "Text you paste is yours, not the corpus. It is quoted in the question and attributed to you, and the applicability gate still refuses: nothing here is extracted into a rule.";

/* -------------------------------------------------------------- carrying --- */

/** The subject of a turn: what a follow-up has to restate to stay about it. */
export interface CarriedContext {
  readonly adNumber: string | null;
  readonly tailNumber: string | null;
}

export const NO_CONTEXT: CarriedContext = { adNumber: null, tailNumber: null };

export function contextFromPlan(plan: QueryPlan | null): CarriedContext {
  if (!plan) return NO_CONTEXT;
  return {
    adNumber: plan.ad_number,
    tailNumber: plan.aircraft.tail_number,
  };
}

export function hasContext(context: CarriedContext): boolean {
  return context.adNumber !== null || context.tailNumber !== null;
}

/**
 * Does the question name a document of its own? Matched on the shape of an AD
 * number or a docket id rather than on the previous turn's value, because the
 * question that matters is "has the user named a subject?", not "has the user
 * named *this* subject". A question that names a different AD must not have the
 * last one appended to it, which is exactly what matching on the old value
 * would do.
 */
const AD_SHAPE = /\b(?:AD\s*)?\d{4}-\d{2}-\d{2}\b|\bFAA-\d{4}-\d{3,}\b/i;

/** The same, for an aircraft: an N-registration. */
const TAIL_SHAPE = /\bN[0-9][0-9A-Z]{1,4}\b/i;

/**
 * What a follow-up still needs from the previous turn: the slots it names no
 * value of its own for. A question that already identifies an aircraft gets no
 * aircraft appended, whichever aircraft it is.
 */
export function missingFromQuestion(
  question: string,
  context: CarriedContext,
): CarriedContext {
  return {
    adNumber:
      context.adNumber !== null && !AD_SHAPE.test(question) ? context.adNumber : null,
    tailNumber:
      context.tailNumber !== null && !TAIL_SHAPE.test(question) ? context.tailNumber : null,
  };
}

/** The sentence that restates a subject, or null when there is nothing to say. */
export function carrySentence(context: CarriedContext): string | null {
  const { adNumber, tailNumber } = context;
  if (adNumber !== null && tailNumber !== null) {
    return `This is about AD ${adNumber} and aircraft ${tailNumber}.`;
  }
  if (adNumber !== null) return `This is about AD ${adNumber}.`;
  if (tailNumber !== null) return `This is about aircraft ${tailNumber}.`;
  return null;
}

/**
 * A follow-up, made self-contained. The engine is stateless and reads only the
 * question, so the subject of the previous turn is restated in the text; the
 * restatement is returned separately so the caller shows it rather than
 * rewriting the user's words behind their back.
 */
export function followUp(asked: string, context: CarriedContext): AskIntent {
  const trimmed = asked.trim();
  const carried = carrySentence(missingFromQuestion(trimmed, context));
  return {
    asked: trimmed,
    question: carried === null ? trimmed : `${trimmed} ${carried}`,
    carried,
    supplied: [],
  };
}

/* -------------------------------------------------------- missing fields --- */

/**
 * A field the engine itself said it could not answer, with the rule it could
 * not evaluate. `field` comes from `decision.unknown_fields` - the engine's own
 * list - and the rest from the matching proof-tree condition, so no label here
 * is derived from free text.
 */
export interface MissingField {
  readonly field: RuleField;
  readonly operator: string | null;
  /** The rule's value as written in the AD. */
  readonly ruleValue: string | null;
  readonly sourceQuote: string | null;
  /** The engine's own reason the record could not answer it. */
  readonly reason: string | null;
  /** The contract's own question for this field, when the engine sent one. */
  readonly question: string | null;
}

function conditionsOf(decision: DecisionPayload | null): readonly ProofTreeNode[] {
  const tree = decision?.proof_tree ?? null;
  if (!tree || isProofTreeUnavailable(tree)) return [];
  return tree.children ?? [];
}

/**
 * The fields a NEED_CONFIG is blocked on. Taken from `unknown_fields`, which is
 * the engine's own enumeration, rather than inferred by scanning the proof tree
 * for amber rows: a condition can be CANNOT_DETERMINE for reasons the user
 * cannot clear, and the contract already distinguishes the two.
 *
 * `refusal` is read only as a fallback. The live service sends `detail` as a
 * sentence and puts the rule in the proof tree; the recorded stream sends the
 * contract's keyed `which_value` object and a tree that may not carry the
 * condition. Both are covered rather than one being reshaped into the other.
 */
export function missingFields(
  decision: DecisionPayload | null,
  refusal?: RefusalPayload | null,
): readonly MissingField[] {
  const keyed =
    refusal?.code === "NEED_CONFIG" &&
    typeof refusal.detail !== "string" &&
    "which_value" in refusal.detail
      ? refusal.detail.which_value
      : null;

  const conditions = conditionsOf(decision ?? null);
  const fields: readonly RuleField[] =
    decision && decision.unknown_fields.length > 0
      ? decision.unknown_fields
      : keyed
        ? [keyed.field]
        : [];

  return fields.map((field) => {
    const condition = conditions.find((c) => c.field === field);
    const named = keyed?.field === field ? keyed : null;
    return {
      field,
      operator: condition?.operator ?? null,
      ruleValue: condition?.rule_value ?? named?.rule_value ?? null,
      sourceQuote: condition?.source_quote ?? named?.source_quote ?? null,
      reason: condition?.reason ?? null,
      question: named?.question ?? null,
    };
  });
}

/**
 * The documents a decision is actually blocked on.
 *
 * The proof tree's `external_documents` is the authoritative list and is used
 * whenever it has one. The recorded stream carries the contract's keyed
 * `external_doc_needed` instead, which names a foreign AD; it is mapped onto
 * the same shape from its own fields rather than being parsed out of prose.
 */
export function blockingDocuments(
  refusal: RefusalPayload,
  externalDocuments: readonly ExternalDocumentRef[],
): readonly ExternalDocumentRef[] {
  const unheld = externalDocuments.filter((doc) => doc.held !== true);
  if (unheld.length > 0) return unheld;
  if (
    refusal.code !== "EXTERNAL_SOURCE_REQUIRED" ||
    typeof refusal.detail === "string" ||
    !("external_doc_needed" in refusal.detail)
  ) {
    return [];
  }
  const needed = refusal.detail.external_doc_needed;
  if (needed.held) return [];
  return [
    {
      doc_type: "ForeignAd",
      // The AD number alone: it is the publisher's own identifier, and it is
      // what a reader types into the authority's search. The authority is kept
      // in `doc_type` and spelled out in `label` instead of being prefixed
      // here, where it would end up in the lookup query.
      doc_id: needed.ad_number,
      label: `${needed.authority} AD ${needed.ad_number}`,
      dated: needed.dated,
      held: false,
      source_quote: needed.delegated_quote,
    },
  ];
}

/** "part_number" reads as "part number" in a sentence. */
export function fieldWords(field: string): string {
  return field.replace(/_/g, " ");
}

/**
 * The question the user is actually being asked, phrased from the rule the
 * engine could not evaluate - its own operator and its own value - rather than
 * from the bare field name, which would ask "what is its equipment?".
 */
export function fieldPrompt(missing: MissingField): string {
  if (missing.question !== null) return missing.question;
  const named = missing.ruleValue ?? fieldWords(missing.field);
  if (missing.operator === "exists") return `Is it fitted with ${named}?`;
  if (missing.operator === "not_exists") return `Is it free of ${named}?`;
  if (missing.operator === "serial_in_range" || missing.operator === "serial_not_in_range") {
    return `What is its serial number? The rule reads ${named}.`;
  }
  return `What is its ${fieldWords(missing.field)}? The rule reads ${named}.`;
}

/** A hint for the input, taken from the rule's own value where there is one. */
export function fieldPlaceholder(missing: MissingField): string {
  if (missing.operator === "exists" || missing.operator === "not_exists") {
    return "yes / no, or the part fitted";
  }
  return missing.ruleValue === null ? fieldWords(missing.field) : missing.ruleValue;
}

/**
 * The user's answer, as a sentence the engine can read. Phrased from the rule's
 * operator so "exists" becomes "is fitted with" rather than "its equipment is".
 *
 * A yes/no answer to an `exists` rule is expanded against the rule's own value,
 * because "yes" alone states nothing the engine can read.
 */
export function assertionFor(
  missing: MissingField,
  value: string,
  subject: string | null,
): string {
  const it = subject ?? "It";
  const answer = value.trim();
  const named = missing.ruleValue ?? fieldWords(missing.field);
  const yes = /^(y|yes|true|fitted|installed)$/i.test(answer);
  const no = /^(n|no|false|none|not fitted)$/i.test(answer);

  if (missing.operator === "exists" || missing.operator === "not_exists") {
    if (yes) return `${it} is fitted with ${named}.`;
    if (no) return `${it} is not fitted with ${named}.`;
    return `${it} is fitted with ${answer}.`;
  }
  // "Its model", but "N220CY's model". Built rather than patched afterwards: a
  // regex that added an apostrophe to anything ending in s turned "Its" into
  // "It's", which is a different word.
  const possessive = subject === null ? "Its" : `${subject}’s`;
  return `${possessive} ${fieldWords(missing.field)} is ${answer}.`;
}

/** The aircraft the decision was made against, for phrasing an assertion. */
export function decisionSubject(decision: DecisionPayload | null): string | null {
  const tree = decision?.proof_tree ?? null;
  if (!tree || isProofTreeUnavailable(tree)) return null;
  return tree.aircraft?.tail_number ?? null;
}

/**
 * Re-ask with the values the user gave. Each one becomes both a sentence in the
 * question and an attributed `SuppliedFact`, so the thread can show that the
 * answer rests on the user's word and not on the corpus.
 */
export function askWithValues(
  asked: string,
  answers: readonly { readonly missing: MissingField; readonly value: string }[],
  subject: string | null,
): AskIntent {
  const trimmed = asked.trim();
  const stated = answers
    .filter((a) => a.value.trim() !== "")
    .map((a) => ({
      fact: {
        source: "user" as const,
        kind: "value" as const,
        label: fieldWords(a.missing.field),
        text: a.value.trim(),
      },
      sentence: assertionFor(a.missing, a.value, subject),
    }));
  if (stated.length === 0) {
    return { asked: trimmed, question: trimmed, carried: null, supplied: [] };
  }
  const added = stated.map((s) => s.sentence).join(" ");
  return {
    asked: trimmed,
    question: `${trimmed} ${added} I am supplying these values myself; they are not in the fleet record.`,
    carried: null,
    supplied: stated.map((s) => s.fact),
  };
}

/* ---------------------------------------------------------- external doc --- */

/** How a blocking document is named on screen and in a re-asked question. */
export function documentName(doc: ExternalDocumentRef): string {
  return doc.label ?? doc.doc_id ?? "a document outside this corpus";
}

/**
 * Re-ask with applicability text the user pasted from a document the corpus
 * does not hold. The question says, in the question itself, that the text is
 * the user's and that it is not held here - so no answer resting on it can read
 * as though the corpus had supplied it.
 */
export function askWithDocumentText(
  asked: string,
  doc: ExternalDocumentRef,
  text: string,
): AskIntent {
  const trimmed = asked.trim();
  const quoted = text.trim().replace(/\s+/g, " ");
  const name = documentName(doc);
  if (quoted === "") {
    return { asked: trimmed, question: trimmed, carried: null, supplied: [] };
  }
  return {
    asked: trimmed,
    question: `${trimmed} I am supplying the applicability text of ${name} myself, from outside this corpus; it reads: "${quoted}"`,
    carried: null,
    supplied: [{ source: "user", kind: "document", label: name, text: quoted }],
  };
}

/**
 * Where to go and read a document the corpus does not hold. Derived from the
 * document's own identifier, never from prose: an EASA AD is published by EASA,
 * a manufacturer bulletin is not public and the link says so rather than
 * sending the reader somewhere that will not have it.
 */
export interface DocumentLookup {
  readonly href: string;
  readonly label: string;
  readonly note: string;
}

/**
 * The document's own number, out of the engine's structured `doc_id`.
 *
 * The engine composes it as `issuer:number:revision` - "Boeing:737-25-1851
 * RB:Revision 1" - so the number is the middle segment. Taken that way rather
 * than by pattern-matching the label, because pasting the whole composed id
 * into a search box returns nothing: the colons and the issuer name are ours,
 * not the publisher's.
 */
export function documentNumber(doc: ExternalDocumentRef): string | null {
  const parts = (doc.doc_id ?? "")
    .split(":")
    .map((part) => part.trim())
    .filter((part) => part !== "");
  // `issuer:number` and `issuer:number:revision` both put the number second.
  const number = parts.length >= 2 ? parts[1] : parts[0];
  return number === undefined || number === "" ? null : number;
}

export function documentLookup(doc: ExternalDocumentRef): DocumentLookup {
  const number = documentNumber(doc);
  if (doc.doc_type === "ForeignAd" || /\bEASA\b/.test(doc.doc_id ?? "")) {
    return {
      href: number === null
        ? "https://ad.easa.europa.eu/"
        : `https://ad.easa.europa.eu/search/advanced?q=${encodeURIComponent(number)}`,
      label: "EASA AD publishing tool",
      note: "foreign ADs are published in full there, and in this AD's docket on regulations.gov",
    };
  }
  return {
    href: `https://www.regulations.gov/search?filter=${encodeURIComponent(number ?? "")}`,
    label: "search the AD docket on regulations.gov",
    note: "manufacturer service bulletins are not public; the docket copy, or your own controlled copy, is the authoritative text",
  };
}
