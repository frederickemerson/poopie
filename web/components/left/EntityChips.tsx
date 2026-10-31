"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useMotionPrefs } from "@/lib/motion";
import type { Entity } from "@/lib/events";

interface EntityChipsProps {
  readonly entities: readonly Entity[];
  readonly query: string;
}

/**
 * Chips land as the `entities` event arrives - one chip per extracted span, with
 * the slice of the query it was read from. Nothing here is speculative: a chip
 * exists only because the entity pass emitted it.
 */
export function EntityChips({ entities, query }: EntityChipsProps) {
  const { dur, stagger } = useMotionPrefs();

  return (
    <ul className="flex flex-wrap gap-1.5" aria-label="entities parsed from the query">
      <AnimatePresence initial={false}>
        {entities.map((e, i) => {
          const read = query.slice(e.span[0], e.span[1]);
          return (
            <motion.li
              key={`${e.field}:${e.value}`}
              initial={{ opacity: 0, y: -4, scale: 0.97 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, scale: 0.97 }}
              transition={{ duration: dur(200), delay: stagger(50) * i, ease: [0.2, 0.8, 0.2, 1] }}
              className="flex items-baseline gap-1.5 border border-line bg-sunken px-1.5 py-1"
              title={`read "${read || e.value}" at characters ${e.span[0]}-${e.span[1]}, ${
                e.confidence === undefined
                  ? "deterministic match (the entity pass publishes no score)"
                  : `confidence ${e.confidence.toFixed(2)}`
              }`}
            >
              <span className="t-label !tracking-[0.06em]">{e.field.replace(/_/g, " ")}</span>
              <span className="t-mono font-semibold text-ink">{e.value}</span>
            </motion.li>
          );
        })}
      </AnimatePresence>
    </ul>
  );
}
