/**
 * Corpus builder. Assembles a Revision's plain text from its paragraphs so that
 * Paragraph.char_start / char_end and every citation span are computed, never
 * typed by hand. `cite()` throws at module load if a quote is not a verbatim
 * substring of the paragraph it is attributed to, which is the contract's
 * source-quote invariant enforced in the UI layer as well as the engine.
 */
import { formatCitationId } from "../citation";
import type { ParagraphRole } from "../contract";
import type { ParagraphNode, RevisionNode } from "../events";

export interface ParagraphSeed {
  readonly label: string;
  readonly role: ParagraphRole;
  readonly heading: string;
  readonly text: string;
}

export interface BuiltRevision {
  readonly revision: RevisionNode;
  readonly paragraphs: readonly ParagraphNode[];
  readonly plain_text: string;
  /** Verbatim quote -> citation id, for the paragraph it was taken from. */
  cite(label: string, quote: string): string;
  paragraph(label: string): ParagraphNode;
}

const JOIN = "\n\n";

export function buildRevision(
  revision: RevisionNode,
  seeds: readonly ParagraphSeed[],
): BuiltRevision {
  const paragraphs: ParagraphNode[] = [];
  let cursor = 0;
  seeds.forEach((seed, ordinal) => {
    const char_start = cursor;
    const char_end = char_start + seed.text.length;
    paragraphs.push({
      paragraph_id: `${revision.revision_id}#${seed.label}`,
      revision_id: revision.revision_id,
      label: seed.label,
      role: seed.role,
      heading: seed.heading,
      text: seed.text,
      char_start,
      char_end,
      ordinal,
    });
    cursor = char_end + JOIN.length;
  });
  const plain_text = seeds.map((s) => s.text).join(JOIN);

  const byLabel = new Map(paragraphs.map((p) => [p.label, p]));

  function paragraph(label: string): ParagraphNode {
    const p = byLabel.get(label);
    if (!p) throw new Error(`${revision.revision_id}: no paragraph (${label})`);
    return p;
  }

  function cite(label: string, quote: string): string {
    const p = paragraph(label);
    const at = p.text.indexOf(quote);
    if (at < 0) {
      throw new Error(
        `${p.paragraph_id}: quote is not a verbatim substring of the paragraph: ${JSON.stringify(
          quote.slice(0, 60),
        )}`,
      );
    }
    return formatCitationId({
      revision_id: revision.revision_id,
      label,
      char_start: p.char_start + at,
      char_end: p.char_start + at + quote.length,
    });
  }

  return { revision, paragraphs, plain_text, cite, paragraph };
}
