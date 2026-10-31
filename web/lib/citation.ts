/**
 * Citation ids. One format, pinned by the contract:
 *   {revision_id}#{label}@{char_start}-{char_end}
 * char offsets index into the Revision's plain text, which is the same
 * coordinate system as Paragraph.char_start / char_end, so a span is resolved
 * inside a paragraph by subtracting the paragraph's own start.
 */
import { CITATION_ID_FORMAT } from "./contract";
import type { ParagraphNode } from "./events";

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
