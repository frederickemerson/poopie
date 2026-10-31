"use client";

import { motion } from "framer-motion";
import {
  citationLabel,
  formatReference,
  referenceOf,
  stageWording,
  type ResolvedCitation,
} from "@/lib/citation";
import type { DocumentStage } from "@/lib/contract";
import { useMotionPrefs } from "@/lib/motion";

interface CitationPillProps {
  readonly n: number;
  readonly citation: ResolvedCitation;
  readonly active: boolean;
  readonly onFocusCitation: (c: ResolvedCitation | null) => void;
}

/**
 * Colour and border per stage. A proposal is drawn with a dashed border and the
 * caution colour, which is the same visual language the envelope uses for
 * things that do not yet oblige anyone; an in-force AD is drawn plainly.
 *
 * Keyed by DocumentStage so a new contract stage fails the build here rather
 * than falling through to whatever the default happens to be.
 */
const STAGE_STYLE: Readonly<Record<DocumentStage, string>> = {
  PROPOSED: "border-dashed border-maybe bg-maybe-bg/40 text-maybe",
  ADOPTED_NOT_YET_EFFECTIVE: "border-maybe/70 bg-sunken text-ink-2",
  EFFECTIVE: "border-line-strong bg-sunken text-ink-2",
  SUPERSEDED: "border-line-strong bg-sunken text-ink-3 line-through decoration-1",
  UNKNOWN: "border-dashed border-line-strong bg-sunken text-ink-3",
};

const NO_STAGE_STYLE = "border-dashed border-line-strong bg-sunken text-ink-3";

/**
 * A numbered citation, carrying its document stage on its face.
 *
 * Two things are deliberate.
 *
 * The number is the exact anchor: the pill exists only because its character
 * span resolved verbatim inside a paragraph that was retrieved for this query.
 *
 * The stage word beside it is not decoration. contracts/contract.json requires
 * every rendered citation to show its document_stage and a citation to an NPRM
 * paragraph to read as a proposal, so the word is in the pill itself rather
 * than in a tooltip - a reader scanning the answer must not have to hover to
 * learn that a sentence rests on something nobody has to comply with. The full
 * paper reference (AD number or record_id, "91 FR 67442", the page range, the
 * paragraph and its role) is on the hover card and listed in full under the
 * answer by CitationReferences.
 */
export function CitationPill({ n, citation, active, onFocusCitation }: CitationPillProps) {
  const { dur } = useMotionPrefs();
  const reference = referenceOf(citation);
  const stage = stageWording(reference?.document_stage);
  const tone = reference ? STAGE_STYLE[reference.document_stage] ?? NO_STAGE_STYLE : NO_STAGE_STYLE;
  const paper = reference ? formatReference(reference) : "no human reference was sent";
  const describedAs = `citation ${n}: ${paper}. ${citationLabel(citation.ref)}`;

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
      aria-label={describedAs}
      title={`${paper}\n${stage.sentence}\n${citationLabel(citation.ref)}\n“${citation.quote}”`}
      className={[
        "mx-[2px] inline-flex h-[17px] translate-y-[-1px] items-baseline gap-1 rounded-sm border px-1 align-middle",
        "t-mono !text-[10px] font-semibold tabular-nums transition-colors",
        active ? "border-accent bg-accent-dim text-ink" : tone,
        active ? "" : "hover:border-accent hover:text-ink",
      ].join(" ")}
    >
      <span>{n}</span>
      <span aria-hidden className="font-normal !tracking-[0.02em] opacity-80">
        {stage.word}
      </span>
    </motion.button>
  );
}
