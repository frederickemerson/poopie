"use client";

/**
 * One live grid cell, opened.
 *
 * It shows only what GET /blast/{revision_id} returned for this aircraft. The
 * per-condition proof lives in the workspace proof tree, which is produced by a
 * query against one aircraft; this payload carries the decision and the fields
 * that blocked it, and the drawer says so rather than implying it has more.
 */
import { motion } from "framer-motion";
import { useEffect, useRef } from "react";
import { explainUnknownField, type BlastCell } from "@/lib/blast";
import { useMotionPrefs } from "@/lib/motion";
import { DecisionChip } from "../ui/StatusGlyph";

interface BlastCellDrawerProps {
  readonly cell: BlastCell;
  readonly revisionId: string;
  readonly onClose: () => void;
}

const Field = ({ label, value }: { label: string; value: string }) => (
  <div className="flex items-baseline justify-between gap-2 border-b border-line py-1">
    <span className="t-label !tracking-[0.06em]">{label}</span>
    <span className="t-mono truncate text-ink">{value}</span>
  </div>
);

export function BlastCellDrawer({ cell, revisionId, onClose }: BlastCellDrawerProps) {
  const { dur } = useMotionPrefs();
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    ref.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <motion.aside
      ref={ref}
      tabIndex={-1}
      role="dialog"
      aria-label={`fleet decision for ${cell.tail_number}`}
      initial={{ opacity: 0, x: 24 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 24 }}
      transition={{ duration: dur(220), ease: [0.2, 0.8, 0.2, 1] }}
      className="flex w-[360px] shrink-0 flex-col overflow-y-auto border-l border-line bg-raised"
    >
      <header className="sticky top-0 z-10 flex items-center justify-between gap-2 border-b border-line bg-raised px-3 py-2">
        <div className="min-w-0">
          <p className="t-mono !text-[14px] font-bold text-ink">{cell.tail_number}</p>
          <p className="t-label mt-0.5">{cell.operator ?? "operator not in record"}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="close fleet decision"
          className="t-label border border-line px-2 py-1 text-ink-2 hover:border-line-strong hover:text-ink"
        >
          close
        </button>
      </header>

      <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-2.5">
        <span className="t-label">rules engine</span>
        <DecisionChip decision={cell.decision} />
      </div>

      <div className="px-3 py-2">
        <p className="t-label mb-1">fleet record · OpenSky</p>
        <Field label="model" value={cell.model ?? "not in record"} />
        <Field label="operator" value={cell.operator ?? "not in record"} />
        <Field label="revision" value={revisionId} />
      </div>

      {cell.unknown_fields.length > 0 ? (
        <div className="border-t border-line px-3 py-2.5">
          <p className="t-label mb-2">undetermined because</p>
          <ul className="flex flex-col gap-2">
            {cell.unknown_fields.map((field) => (
              <li key={field} className="border-l-2 border-maybe pl-2">
                <p className="t-mono font-semibold text-maybe">{field}</p>
                <p className="t-body mt-0.5 text-ink-2">{explainUnknownField(field)}</p>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <p className="t-mono mt-auto border-t border-line px-3 py-2 text-ink-3">
        From GET /blast/{revisionId}. For the condition-by-condition proof, ask about{" "}
        {cell.tail_number} in the workspace: applicability is decided against one aircraft at a time.
      </p>
    </motion.aside>
  );
}
