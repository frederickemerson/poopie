"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useMemo } from "react";
import type { ResolvedCitation } from "@/lib/citation";
import { useMotionPrefs } from "@/lib/motion";
import type { AnswerDeltaPayload } from "@/lib/events";
import type { DroppedSentence, VerifiedSentence } from "@/lib/useEngineStream";
import { CitationPill } from "./CitationPill";

interface AnswerStreamProps {
  readonly answer: readonly VerifiedSentence[];
  readonly dropped: readonly DroppedSentence[];
  readonly awaiting: readonly AnswerDeltaPayload[];
  readonly activeCitationId: string | null;
  readonly onFocusCitation: (c: ResolvedCitation | null) => void;
}

/**
 * The answer. Sentences arrive over `answer_delta` but are held back as unnamed
 * rows until the `verification` event names them in `kept`: no unverified prose
 * is ever drawn, and a sentence in `dropped` is never rendered at all - only the
 * reason it was dropped.
 */
export function AnswerStream({
  answer,
  dropped,
  awaiting,
  activeCitationId,
  onFocusCitation,
}: AnswerStreamProps) {
  const { dur, stagger, reduced } = useMotionPrefs();

  const numbering = useMemo(() => {
    const map = new Map<string, number>();
    for (const s of answer) {
      for (const c of s.citations) if (!map.has(c.id)) map.set(c.id, map.size + 1);
    }
    return map;
  }, [answer]);

  return (
    <div className="flex flex-col gap-3 px-4 py-3">
      <AnimatePresence initial={false}>
        {awaiting.map((d, i) => (
          <motion.div
            key={`pending-${d.index}`}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: dur(180), delay: stagger(40) * i }}
            className="relative overflow-hidden border-l-2 border-line-strong bg-sunken/60 pl-3"
          >
            <div className="flex items-center gap-2 py-2">
              <span className="t-mono text-ink-3">s{d.index}</span>
              <span className="t-label">held for verification</span>
              <span className="t-mono text-ink-3">
                {d.citation_ids.length} citation{d.citation_ids.length === 1 ? "" : "s"}
              </span>
            </div>
            <div className={`relative h-[2px] w-full overflow-hidden bg-line ${reduced ? "" : "scanline"}`} />
          </motion.div>
        ))}
      </AnimatePresence>

      {answer.map((s, i) => (
        <motion.p
          key={`kept-${s.index}`}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: dur(140), delay: stagger(130) * i }}
          className="t-answer text-ink"
        >
          {s.sentence.split(" ").map((word, w) => (
            <motion.span
              key={`${s.index}-${w}`}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: dur(120), delay: stagger(130) * i + stagger(13) * w }}
            >
              {word}{" "}
            </motion.span>
          ))}
          <span className="whitespace-nowrap">
            {s.citations.map((c) => (
              <CitationPill
                key={c.id}
                n={numbering.get(c.id) ?? 0}
                citation={c}
                active={activeCitationId === c.id}
                onFocusCitation={onFocusCitation}
              />
            ))}
          </span>
        </motion.p>
      ))}

      {dropped.length > 0 ? (
        <motion.div
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: dur(200), delay: stagger(130) * answer.length }}
          className="border border-dashed border-line-strong px-3 py-2"
        >
          <p className="t-label mb-1">dropped by the verifier &middot; not rendered</p>
          <ul>
            {dropped.map((d) => (
              <li key={d.index} className="t-mono flex gap-2 py-0.5 text-ink-3">
                <span className="shrink-0 text-ink-2">s{d.index}</span>
                <span>{d.reason}</span>
              </li>
            ))}
          </ul>
        </motion.div>
      ) : null}
    </div>
  );
}
