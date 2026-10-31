"use client";

import { motion } from "framer-motion";
import { citationLabel, type ResolvedCitation } from "@/lib/citation";
import { useMotionPrefs } from "@/lib/motion";

interface CitationPillProps {
  readonly n: number;
  readonly citation: ResolvedCitation;
  readonly active: boolean;
  readonly onFocusCitation: (c: ResolvedCitation | null) => void;
}

/**
 * A numbered citation. Hover or keyboard focus slides the source paragraph into
 * the evidence column with this exact character span highlighted; the pill only
 * exists because the span resolved inside a retrieved paragraph.
 */
export function CitationPill({ n, citation, active, onFocusCitation }: CitationPillProps) {
  const { dur } = useMotionPrefs();
  return (
    <motion.button
      type="button"
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: dur(160) }}
      onMouseEnter={() => onFocusCitation(citation)}
      onMouseLeave={() => onFocusCitation(null)}
      onFocus={() => onFocusCitation(citation)}
      onBlur={() => onFocusCitation(null)}
      onClick={() => onFocusCitation(citation)}
      aria-label={`citation ${n}: ${citationLabel(citation.ref)}`}
      title={`${citationLabel(citation.ref)}\n“${citation.quote}”`}
      className={[
        "mx-[2px] inline-flex h-[17px] min-w-[17px] translate-y-[-1px] items-center justify-center rounded-sm border px-1 align-middle",
        "t-mono !text-[10px] font-semibold tabular-nums transition-colors",
        active
          ? "border-accent bg-accent-dim text-ink"
          : "border-line-strong bg-sunken text-ink-2 hover:border-accent hover:text-ink",
      ].join(" ")}
    >
      {n}
    </motion.button>
  );
}
