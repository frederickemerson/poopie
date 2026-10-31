/**
 * Corpus builder. Assembles a Revision's plain text from its paragraphs so that
 * Paragraph.char_start / char_end and every citation span are computed, never
 * typed by hand. `cite()` throws at module load if a quote is not a verbatim
 * substring of the paragraph it is attributed to, which is the contract's
 * source-quote invariant enforced in the UI layer as well as the engine.
 */
import { formatCitationId, paragraphRef, stageWording } from "../citation";
import type { DocumentStage, ParagraphRole } from "../contract";
import type { HumanReference, ParagraphNode, RevisionNode } from "../events";

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

/**
 * Legal stage of a recorded revision, by the same three rules as
 * engine/graph/stage.py, which is the source of truth: superseded wins over
 * effectiveness, no effective date means UNKNOWN, and nothing is read from
 * prose. Mirrored here so a recorded scenario renders exactly as a live one.
 */
function revisionStage(revision: RevisionNode, today: Date): DocumentStage {
  if (revision.superseded_by) return "SUPERSEDED";
  const effective = revision.effective_on ? new Date(`${revision.effective_on}T00:00:00Z`) : null;
  if (!effective || Number.isNaN(effective.getTime())) return "UNKNOWN";
  return effective.getTime() <= today.getTime() ? "EFFECTIVE" : "ADOPTED_NOT_YET_EFFECTIVE";
}

/**
 * The human reference the live engine attaches to a retrieved paragraph,
 * assembled for a recorded one. Null revision fields stay null: a derived
 * revision has no Federal Register citation and says so.
 */
function referenceFor(
  revision: RevisionNode,
  paragraph: ParagraphNode,
  stage: DocumentStage,
): HumanReference {
  const pages =
    revision.start_page === null
      ? null
      : revision.end_page === null || revision.end_page === revision.start_page
        ? String(revision.start_page)
        : `${revision.start_page}-${revision.end_page}`;
  const notRecorded = [
    ...(revision.fr_citation ? [] : ["fr_citation"]),
    ...(pages ? [] : ["page_range"]),
  ];
  return {
    citation_id: `${paragraph.paragraph_id}@${paragraph.char_start}-${paragraph.char_end}`,
    document_id: revision.revision_id,
    source_kind: "REVISION",
    document_stage: stage,
    stage_note: stageWording(stage).sentence,
    is_proposal: stage === "PROPOSED",
    handle: revision.ad_number,
    ad_number: revision.ad_number,
    record_id: null,
    fr_citation: revision.fr_citation,
    page_range: pages,
    source_citation_text: null,
    paragraph_label: paragraph.label,
    paragraph_role: paragraph.role,
    federal_register_link: revision.full_text_xml_url,
    not_recorded: notRecorded,
    display: [
      revision.ad_number,
      revision.fr_citation ?? "FR citation not recorded",
      pages ? `pp. ${pages}` : "page range not recorded",
      `${paragraphRef(paragraph.label)} ${paragraph.role}`,
      stage,
    ].join(" · "),
  };
}

export function buildRevision(
  revision: RevisionNode,
  seeds: readonly ParagraphSeed[],
): BuiltRevision {
  const paragraphs: ParagraphNode[] = [];
  const stage = revisionStage(revision, new Date());
  let cursor = 0;
  seeds.forEach((seed, ordinal) => {
    const char_start = cursor;
    const char_end = char_start + seed.text.length;
    const base: ParagraphNode = {
      paragraph_id: `${revision.revision_id}#${seed.label}`,
      revision_id: revision.revision_id,
      ad_number: revision.ad_number,
      label: seed.label,
      role: seed.role,
      heading: seed.heading,
      text: seed.text,
      char_start,
      char_end,
      ordinal,
      citation_id: `${revision.revision_id}#${seed.label}@${char_start}-${char_end}`,
    };
    paragraphs.push({ ...base, human_reference: referenceFor(revision, base, stage) });
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
