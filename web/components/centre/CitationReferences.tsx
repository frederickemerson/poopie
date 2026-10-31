"use client";

import { motion } from "framer-motion";
import {
  NOT_RECORDED,
  formatReference,
  paragraphRef,
  referenceOf,
  stageWording,
  type ResolvedCitation,
} from "@/lib/citation";
import type { HumanReference } from "@/lib/events";
import { useMotionPrefs } from "@/lib/motion";

interface CitationReferencesProps {
  /** Citation id -> the number its pill carries, in first-use order. */
  readonly numbering: ReadonlyMap<string, number>;
  readonly citations: readonly ResolvedCitation[];
  readonly activeCitationId: string | null;
  readonly onFocusCitation: (c: ResolvedCitation | null) => void;
}

/**
 * The reference list: what each numbered citation is, on paper.
 *
 * The citation id is an exact character anchor and nobody can look one up in a
 * library. This block is the other half the challenge rubric asks for - "cite
 * record_id plus the Federal Register citation and page range, and the section
 * of the full document" - rendered as body text under the answer rather than
 * hidden in a tooltip, because a reference you have to hover to read is not a
 * reference you can check.
 *
 * A field the source does not hold is printed as "not recorded". There is no
 * path here that prints a page number the engine did not receive.
 */
export function CitationReferences({
  numbering,
  citations,
  activeCitationId,
  onFocusCitation,
}: CitationReferencesProps) {
  const { dur } = useMotionPrefs();
  if (citations.length === 0) return null;

  const rows = [...citations]
    .sort((a, b) => (numbering.get(a.id) ?? 0) - (numbering.get(b.id) ?? 0))
    .map((citation) => ({
      citation,
      n: numbering.get(citation.id) ?? 0,
      reference: referenceOf(citation),
    }));

  return (
    <motion.section
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: dur(200) }}
      aria-label="citation references"
      className="border-t border-line pt-2"
    >
      <p className="t-label mb-1.5">sources · what each citation is on paper</p>
      <ol className="flex flex-col gap-1.5">
        {rows.map(({ citation, n, reference }) => (
          <li
            key={citation.id}
            onMouseEnter={() => onFocusCitation(citation)}
            onMouseLeave={() => onFocusCitation(null)}
            className={[
              "grid grid-cols-[18px_1fr] gap-2 border-l-2 pl-2",
              activeCitationId === citation.id ? "border-accent" : "border-transparent",
            ].join(" ")}
          >
            <span className="t-mono !text-[10px] font-semibold tabular-nums text-ink-2">{n}</span>
            <div className="min-w-0">
              {reference ? (
                <ReferenceLine reference={reference} />
              ) : (
                <p className="t-mono text-ink-3">
                  {citation.ref.revision_id} {paragraphRef(citation.ref.label)} &middot; paper
                  reference {NOT_RECORDED} by this engine build
                </p>
              )}
              <p className="t-mono text-ink-3">
                exact span {citation.ref.char_start}&ndash;{citation.ref.char_end}, verified verbatim
              </p>
            </div>
          </li>
        ))}
      </ol>
    </motion.section>
  );
}

/**
 * One reference, with the stage stated in words. A proposal carries the
 * sentence that says it obliges nobody; that is a contract rule, not styling.
 */
function ReferenceLine({ reference }: { readonly reference: HumanReference }) {
  const stage = stageWording(reference.document_stage);
  return (
    <>
      <p className="t-body text-ink">{formatReference(reference)}</p>
      <p className={reference.is_proposal ? "t-body text-maybe" : "t-mono text-ink-3"}>
        {stage.sentence}
      </p>
      {reference.not_recorded.length > 0 ? (
        <p className="t-mono text-ink-3">
          {NOT_RECORDED} in the source: {reference.not_recorded.join(", ")}
        </p>
      ) : null}
    </>
  );
}
