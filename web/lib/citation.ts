/**
 * Citation ids. One format, pinned by the contract:
 *   {revision_id}#{label}@{char_start}-{char_end}
 * char offsets index into the Revision's plain text, which is the same
 * coordinate system as Paragraph.char_start / char_end, so a span is resolved
 * inside a paragraph by subtracting the paragraph's own start.
 */
import { CITATION_ID_FORMAT, type DocumentStage } from "./contract";
import type { HumanReference, ParagraphNode } from "./events";

export interface CitationRef {
  readonly revision_id: string;
  readonly label: string;
  readonly char_start: number;
  readonly char_end: number;
  /** '{revision_id}#{label}', i.e. the Paragraph key the span belongs to. */
  readonly paragraph_id: string;
}

const PATTERN = /^(.+?)#(.+?)@(\d+)-(\d+)$/;

export function formatCitationId(ref: Omit<CitationRef, "paragraph_id">): string {
  return `${ref.revision_id}#${ref.label}@${ref.char_start}-${ref.char_end}`;
}

export function parseCitationId(id: string): CitationRef | null {
  const m = PATTERN.exec(id);
  if (!m) return null;
  const [, revision_id, label, start, end] = m;
  if (!revision_id || !label || start === undefined || end === undefined) return null;
  const char_start = Number.parseInt(start, 10);
  const char_end = Number.parseInt(end, 10);
  if (char_end < char_start) return null;
  return { revision_id, label, char_start, char_end, paragraph_id: `${revision_id}#${label}` };
}

export interface ResolvedCitation {
  readonly id: string;
  readonly ref: CitationRef;
  readonly paragraph: ParagraphNode;
  /** Offsets inside paragraph.text. */
  readonly local_start: number;
  readonly local_end: number;
  readonly quote: string;
}

/**
 * Resolve a citation against the retrieved paragraph set. Returns null when the
 * paragraph was not retrieved or the span falls outside it: the contract forbids
 * rendering either case as a citation.
 */
export function resolveCitation(
  id: string,
  paragraphs: readonly ParagraphNode[],
): ResolvedCitation | null {
  const ref = parseCitationId(id);
  if (!ref) return null;
  const paragraph = paragraphs.find((p) => sameParagraph(p.paragraph_id, ref.paragraph_id));
  if (!paragraph) return null;
  const local_start = ref.char_start - paragraph.char_start;
  const local_end = ref.char_end - paragraph.char_start;
  if (local_start < 0 || local_end > paragraph.text.length || local_end <= local_start) return null;
  return {
    id,
    ref,
    paragraph,
    local_start,
    local_end,
    quote: paragraph.text.slice(local_start, local_end),
  };
}

/** A paragraph label with any surrounding parentheses removed: "(c)" -> "c". */
export function bareLabel(label: string): string {
  return label.replace(/^\(+/, "").replace(/\)+$/, "");
}

/**
 * A paragraph label as one pilcrow reference. Labels arrive parenthesised from
 * one producer ("(c)") and bare from another ("c"), so the parens are added
 * once here instead of in each component, which produced "¶((c))".
 */
export function paragraphRef(label: string): string {
  return `¶(${bareLabel(label)})`;
}

/**
 * Whether two paragraph ids name the same paragraph, ignoring whether the label
 * is parenthesised.
 *
 * The id format is pinned as `{revision_id}#{label}`, but whether `label`
 * carries its parentheses is a producer choice, and the engine's own artifacts
 * currently disagree: extracted rules cite "2026-20103#(c)" while the rebuilt
 * paragraph set uses "2026-20103#c". Comparing on the bare label means a
 * citation still resolves across that difference instead of silently vanishing.
 */
export function sameParagraph(a: string, b: string): boolean {
  if (a === b) return true;
  const split = (id: string) => {
    const at = id.indexOf("#");
    return at < 0 ? [id, ""] : [id.slice(0, at), bareLabel(id.slice(at + 1))];
  };
  const [revA, labelA] = split(a);
  const [revB, labelB] = split(b);
  return revA === revB && labelA === labelB && labelA !== "";
}

/** Human form used on hover cards and in the source panel header. */
export function citationLabel(ref: CitationRef): string {
  return `${ref.revision_id} ${paragraphRef(ref.label)} @${ref.char_start}-${ref.char_end}`;
}

export const CITATION_FORMAT_HINT = CITATION_ID_FORMAT;

/* --------------------------------------------------- the findable reference */

/** Shown in place of a field the source does not hold. Never a placeholder number. */
export const NOT_RECORDED = "not recorded";

/**
 * How each contract document_stage is put to a reader.
 *
 * `word` is the short form a citation pill carries, `sentence` the plain
 * statement of what the stage means for an obligation. PROPOSED gets the word
 * "proposal" rather than an abbreviation: the one misreading this product must
 * never allow is a proposal read as a requirement, so that citation says what
 * it is in a word nobody has to decode.
 *
 * Keyed by DocumentStage, so adding a stage to contracts/contract.json fails
 * the TypeScript build here until it has been given wording.
 */
export const STAGE_WORDING: Readonly<
  Record<DocumentStage, { readonly word: string; readonly sentence: string }>
> = {
  PROPOSED: {
    word: "proposal",
    sentence: "a proposal open for comment — not a requirement, and nothing to comply with",
  },
  ADOPTED_NOT_YET_EFFECTIVE: {
    word: "not yet in force",
    sentence: "adopted but not yet effective — it imposes no obligation today",
  },
  EFFECTIVE: { word: "in force", sentence: "in force" },
  SUPERSEDED: { word: "superseded", sentence: "superseded — read the current revision" },
  UNKNOWN: {
    word: "stage unknown",
    sentence: "the effective date could not be determined from this document's metadata",
  },
};

/** The stage of a citation whose reference the engine did not send. */
export const STAGE_NOT_REPORTED = {
  word: "stage not sent",
  sentence: "this engine build sent no document stage for this citation",
} as const;

export function stageWording(stage: DocumentStage | null | undefined): {
  readonly word: string;
  readonly sentence: string;
} {
  if (!stage) return STAGE_NOT_REPORTED;
  return STAGE_WORDING[stage] ?? STAGE_NOT_REPORTED;
}

/**
 * The reference for a resolved citation, from the paragraph it resolved
 * against. Undefined when the engine sent none — the caller must then say so
 * rather than fill anything in.
 */
export function referenceOf(citation: ResolvedCitation): HumanReference | undefined {
  return citation.paragraph.human_reference;
}

/**
 * One line a reader can carry to a paper copy: the handle they already use,
 * the Federal Register citation, the page range, the section, and the stage.
 *
 * Absences are printed, not skipped. A reference with no page range reads
 * "page range not recorded", because a citation that quietly drops the page is
 * indistinguishable from one that never had it.
 */
export function formatReference(reference: HumanReference): string {
  const citation =
    reference.fr_citation ?? reference.source_citation_text ?? `FR citation ${NOT_RECORDED}`;
  const pages = reference.page_range ? `pp. ${reference.page_range}` : `page range ${NOT_RECORDED}`;
  const role = reference.paragraph_role ? ` ${reference.paragraph_role}` : "";
  const section = `${paragraphRef(reference.paragraph_label)}${role}`;
  return [reference.handle, citation, pages, section, stageWording(reference.document_stage).word]
    .join(" · ");
}
