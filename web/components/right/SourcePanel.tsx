"use client";

import { AnimatePresence, motion } from "framer-motion";
import { citationLabel, type ResolvedCitation } from "@/lib/citation";
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
                &para;({citation.paragraph.label}) {citation.paragraph.heading}
              </h3>
              <span className="t-label !tracking-[0.06em]">{citation.paragraph.role}</span>
            </header>
            <p className="t-mono mb-2 text-ink-3">{citationLabel(citation.ref)}</p>
            <QuoteSpan
              text={citation.paragraph.text}
              start={citation.local_start}
              end={citation.local_end}
            />
            <dl className="t-mono mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 border-t border-line pt-2 text-ink-3">
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
                        &para;({p.label}) {p.heading}
                      </p>
                      <p className="t-mono truncate text-ink-3">{p.paragraph_id}</p>
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
