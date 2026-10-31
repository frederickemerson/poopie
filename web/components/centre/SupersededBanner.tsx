"use client";

import { motion } from "framer-motion";
import { useMotionPrefs } from "@/lib/motion";
import type { SupersededDetail } from "@/lib/events";

interface SupersededBannerProps {
  readonly detail: SupersededDetail;
  readonly onOpenCurrent: (revisionId: string) => void;
}

/**
 * SUPERSEDED is the one refusal code with blocks_answer=false, so it renders as
 * a banner over an answer that is still shown, not as a card instead of one.
 */
export function SupersededBanner({ detail, onOpenCurrent }: SupersededBannerProps) {
  const { dur } = useMotionPrefs();
  return (
    <motion.aside
      initial={{ opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: dur(200) }}
      aria-label="superseded revision warning"
      className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-maybe/50 bg-maybe-bg/50 px-4 py-2"
    >
      <span className="t-mono !text-[11px] font-bold text-maybe">SUPERSEDED</span>
      <span className="t-body flex-1 text-ink-2">{detail.note}</span>
      <button
        type="button"
        onClick={() => onOpenCurrent(detail.current_revision_id)}
        className="t-label border border-maybe/60 px-2 py-1 text-maybe transition-colors hover:border-maybe hover:text-ink"
      >
        open {detail.current_ad_number} &rarr;
      </button>
    </motion.aside>
  );
}
