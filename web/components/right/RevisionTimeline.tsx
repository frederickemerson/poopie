"use client";

import { motion } from "framer-motion";
import { useMemo, useState } from "react";
import { useMotionPrefs } from "@/lib/motion";
import type { AdEntry } from "@/lib/corpus";
import { buildChain, diffApplicability, type ChainNode } from "@/lib/revisionChain";

interface RevisionTimelineProps {
  readonly ad: AdEntry | null;
  /** Revision the current answer is about, highlighted on the line. */
  readonly askedRevisionId: string | null;
  readonly focusRevisionId: string | null;
}

/**
 * The supersession chain, left to right. The current revision glows, superseded
 * ones fade, and the proposal that became each final rule sits in front of it.
 * Selecting a node diffs its applicability Rules against the revision before it.
 */
export function RevisionTimeline({ ad, askedRevisionId, focusRevisionId }: RevisionTimelineProps) {
  const { dur, stagger } = useMotionPrefs();
  const chain = useMemo(() => (ad ? buildChain(ad) : []), [ad]);
  const [picked, setPicked] = useState<string | null>(null);

  const selectedId = picked ?? (focusRevisionId ? `rev:${focusRevisionId}` : null) ?? chain.at(-1)?.id ?? null;
  const selected = chain.find((n) => n.id === selectedId) ?? null;

  const diff = useMemo(() => {
    if (!ad || !selected?.revision_id) return null;
    const index = ad.revisions.findIndex((r) => r.built.revision.revision_id === selected.revision_id);
    if (index < 0) return null;
    const after = ad.revisions[index];
    if (!after) return null;
    return diffApplicability(ad.revisions[index - 1] ?? null, after);
  }, [ad, selected]);

  if (!ad) {
    return <p className="t-mono px-3 py-3 text-ink-3">no AD in scope yet&hellip;</p>;
  }

  return (
    <div className="flex flex-col">
      <div className="overflow-x-auto px-3 pb-1 pt-4">
        <ol className="relative flex min-w-max items-start gap-0">
          <span aria-hidden className="absolute left-2 right-2 top-[11px] h-px bg-line" />
          {chain.map((node, i) => (
            <TimelineNode
              key={node.id}
              node={node}
              asked={node.revision_id !== null && node.revision_id === askedRevisionId}
              selected={node.id === selectedId}
              onSelect={() => setPicked(node.id)}
              delay={stagger(60) * i}
              duration={dur(220)}
            />
          ))}
        </ol>
      </div>

      {diff ? (
        <div className="border-t border-line">
          <div className="flex items-baseline justify-between gap-2 px-3 py-2">
            <p className="t-label">applicability diff</p>
            <p className="t-mono text-ink-3">
              {diff.before_label ? `${diff.before_label} → ${diff.after_label}` : `${diff.after_label} (first revision)`}
            </p>
          </div>
          <table className="w-full border-t border-line">
            <thead>
              <tr className="t-label">
                <th scope="col" className="w-[92px] px-3 py-1 text-left font-semibold">
                  field
                </th>
                <th scope="col" className="px-2 py-1 text-left font-semibold">
                  before
                </th>
                <th scope="col" className="px-2 py-1 text-left font-semibold">
                  after
                </th>
              </tr>
            </thead>
            <tbody>
              {diff.rows.map((row) => (
                <tr key={row.field} className="border-t border-line align-baseline">
                  <th scope="row" className="t-mono px-3 py-1 text-left font-normal text-ink-3">
                    {row.field}
                  </th>
                  <td className="t-mono px-2 py-1 text-ink-3">
                    {row.before === null ? (
                      "—"
                    ) : row.change === "changed" || row.change === "removed" ? (
                      <s className="decoration-line-strong">{row.before}</s>
                    ) : (
                      row.before
                    )}
                  </td>
                  <td
                    className={`t-mono px-2 py-1 ${row.change === "same" ? "text-ink-2" : "font-semibold text-accent"}`}
                  >
                    {row.after ?? "—"}
                    {row.change !== "same" ? (
                      <span className="t-label ml-2 !tracking-[0.06em] text-ink-3">{row.change}</span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="border-t border-line px-3 py-2">
            <p className="t-label mb-1">paragraph (c), as published</p>
            {diff.before_text ? (
              <p className="t-body mb-2 text-ink-3">
                <span className="t-label mr-1.5 !tracking-[0.06em]">was</span>
                <s className="decoration-line-strong">{diff.before_text}</s>
              </p>
            ) : null}
            <p className="t-body text-ink-2">
              <span className="t-label mr-1.5 !tracking-[0.06em] text-accent">now</span>
              {diff.after_text}
            </p>
          </div>
        </div>
      ) : null}
    </div>
  );
}

interface TimelineNodeProps {
  readonly node: ChainNode;
  readonly asked: boolean;
  readonly selected: boolean;
  readonly onSelect: () => void;
  readonly delay: number;
  readonly duration: number;
}

function TimelineNode({ node, asked, selected, onSelect, delay, duration }: TimelineNodeProps) {
  const faded = node.superseded;
  const glow = node.is_current;
  return (
    <motion.li
      initial={{ opacity: 0, y: 5 }}
      animate={{ opacity: faded ? 0.52 : 1, y: 0 }}
      transition={{ duration, delay }}
      className="flex w-[168px] shrink-0 flex-col items-start pr-4"
    >
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        aria-label={`${node.title}, ${node.kind === "proposal" ? "proposed rule" : "final rule"}, ${node.date}${glow ? ", current revision" : ""}${faded ? ", superseded" : ""}`}
        className="group flex w-full flex-col items-start text-left"
      >
        <span
          aria-hidden
          className={[
            "relative mb-2 block h-[9px] w-[9px] rounded-full border",
            node.kind === "proposal" ? "border-dashed" : "",
            glow
              ? "border-accent bg-accent shadow-[0_0_0_4px_var(--c-accent-dim)]"
              : selected
                ? "border-accent bg-raised"
                : "border-line-strong bg-raised group-hover:border-accent",
          ].join(" ")}
        />
        <span className={`t-mono font-semibold ${selected ? "text-ink" : "text-ink-2"}`}>{node.title}</span>
        <span className="t-label mt-0.5 !tracking-[0.06em]">
          {node.kind === "proposal" ? "proposed" : glow ? "current" : faded ? "superseded" : "final"}
        </span>
        <span className="t-mono mt-1 text-ink-3">{node.date}</span>
        {node.amendment ? <span className="t-mono text-ink-3">amdt {node.amendment}</span> : null}
        {node.comments_due_date ? (
          <span className="t-mono text-ink-3">comments {node.comments_due_date}</span>
        ) : null}
        {asked ? <span className="t-label mt-1 !tracking-[0.06em] text-maybe">you asked about this</span> : null}
        {node.text_source === "derived" ? (
          <span className="t-label mt-1 !tracking-[0.06em] text-ink-3" title="paragraph text written in Federal Register house style for the demo corpus">
            derived text
          </span>
        ) : null}
      </button>
    </motion.li>
  );
}
