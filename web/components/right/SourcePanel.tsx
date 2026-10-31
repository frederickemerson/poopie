"use client";

import { AnimatePresence, motion } from "framer-motion";
import {
  NOT_RECORDED,
  citationLabel,
  formatReference,
  paragraphRef,
  referenceOf,
  stageWording,
  type ResolvedCitation,
} from "@/lib/citation";
import { useMotionPrefs } from "@/lib/motion";
import type { ParagraphNode } from "@/lib/events";
import { QuoteSpan } from "../ui/QuoteSpan";

interface SourcePanelProps {
  readonly citation: ResolvedCitation | null;
  readonly paragraphs: readonly ParagraphNode[];
  readonly scores: Readonly<Record<string, number>>;
}

/**
 * The source paragraph for whichever citation is under the cursor, with the
 * exact character span marked. With nothing hovered it lists the retrieved set
 * and its fused scores, so the evidence is browsable rather than only reactive.
 */
export function SourcePanel({ citation, paragraphs, scores }: SourcePanelProps) {
  const { dur } = useMotionPrefs();
  const reference = citation ? referenceOf(citation) : undefined;
  const stage = stageWording(reference?.document_stage);

  return (
    <div className="relative min-h-0 flex-1 overflow-y-auto">
      <AnimatePresence mode="wait" initial={false}>
        {citation ? (
          <motion.article
            key={citation.id}
            initial={{ opacity: 0, x: 14 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 8 }}
            transition={{ duration: dur(190), ease: [0.2, 0.8, 0.2, 1] }}
            className="px-3 py-3"
          >
            <header className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="t-mono font-semibold text-ink">
                {paragraphRef(citation.paragraph.label)} {citation.paragraph.heading}
              </h3>
              <span className="t-label !tracking-[0.06em]">{citation.paragraph.role}</span>
            </header>
            {/*
              The paper reference first, then the character anchor. Both, in
              that order: the reference is what a reader can check against the
              Federal Register, the anchor is what the verifier checked.
            */}
            {reference ? (
              <p
                className={[
                  "t-body mb-1 border-l-2 pl-2",
                  reference.is_proposal ? "border-maybe text-maybe" : "border-line-strong text-ink-2",
                ].join(" ")}
              >
                {formatReference(reference)}
                <span className="t-mono block text-ink-3">{stage.sentence}</span>
              </p>
            ) : (
              <p className="t-mono mb-1 text-ink-3">paper reference {NOT_RECORDED}</p>
            )}
            <p className="t-mono mb-2 text-ink-3">{citationLabel(citation.ref)}</p>
            <QuoteSpan
              text={citation.paragraph.text}
              start={citation.local_start}
              end={citation.local_end}
            />
            <dl className="t-mono mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 border-t border-line pt-2 text-ink-3">
              <dt>document</dt>
              <dd className="text-ink-2">{reference?.handle ?? citation.ref.revision_id}</dd>
              <dt>FR citation</dt>
              <dd className="text-ink-2">
                {reference?.fr_citation ?? reference?.source_citation_text ?? NOT_RECORDED}
              </dd>
              <dt>pages</dt>
              <dd className="text-ink-2">{reference?.page_range ?? NOT_RECORDED}</dd>
              <dt>document stage</dt>
              <dd className="text-ink-2">{reference?.document_stage ?? NOT_RECORDED}</dd>
              <dt>paragraph span</dt>
              <dd className="text-ink-2">
                {citation.paragraph.char_start}&ndash;{citation.paragraph.char_end} in revision text
              </dd>
              <dt>cited span</dt>
              <dd className="text-ink-2">
                {citation.ref.char_start}&ndash;{citation.ref.char_end} ({citation.quote.length} chars)
              </dd>
              <dt>fused score</dt>
              <dd className="text-ink-2">
                {(scores[citation.paragraph.paragraph_id] ?? 0).toFixed(3)}
              </dd>
            </dl>
          </motion.article>
        ) : (
          <motion.div
            key="retrieved-set"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: dur(150) }}
            className="px-3 py-3"
          >
            <p className="t-label mb-2">
              retrieved set &middot; {paragraphs.length} paragraph{paragraphs.length === 1 ? "" : "s"}
            </p>
            {paragraphs.length === 0 ? (
              <p className="t-mono text-ink-3">awaiting retrieval&hellip;</p>
            ) : (
              <ul className="flex flex-col">
                {paragraphs.map((p) => (
                  <li
                    key={p.paragraph_id}
                    className="grid grid-cols-[1fr_auto] items-baseline gap-2 border-b border-line py-1.5 last:border-b-0"
                  >
                    <div className="min-w-0">
                      <p className="t-mono truncate text-ink">
                        {paragraphRef(p.label)} {p.heading}
                      </p>
                      {/*
                        The stage rides on every retrieved paragraph, not just
                        on the cited ones: a proposal in the retrieved set has
                        to be recognisable as a proposal before any sentence
                        rests on it.
                      */}
                      <p
                        className={[
                          "t-mono truncate",
                          p.human_reference?.is_proposal ? "text-maybe" : "text-ink-3",
                        ].join(" ")}
                      >
                        {p.human_reference
                          ? formatReference(p.human_reference)
                          : `${p.paragraph_id} · stage ${NOT_RECORDED}`}
                      </p>
                    </div>
                    <span className="t-mono tabular-nums text-ink-2">
                      {(scores[p.paragraph_id] ?? 0).toFixed(3)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <p className="t-body mt-3 text-ink-3">
              Hover a citation pill in the answer to slide its paragraph in here with the cited
              character span marked.
            </p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
