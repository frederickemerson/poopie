"use client";

import { motion } from "framer-motion";
import type { Decision } from "@/lib/contract";
import type { FleetAircraft } from "@/lib/fleet";

/**
 * Fleet-impact colouring, which is deliberately NOT the proof-tree colouring.
 * In the proof tree green means "this condition is satisfied". Here red means
 * "this airplane is affected, so there is work to do", grey means it is not, and
 * amber means the fleet record cannot settle it. The legend says so on screen.
 */
export const FLEET_TONE: Readonly<Record<Decision, { cell: string; glyph: string; word: string; ring: string }>> = {
  APPLIES: {
    cell: "border-no bg-no-bg text-no",
    glyph: "◆",
    word: "affected",
    ring: "var(--c-no)",
  },
  DOES_NOT_APPLY: {
    cell: "border-line bg-sunken text-ink-3",
    glyph: "·",
    word: "not affected",
    ring: "var(--c-line-strong)",
  },
  CANNOT_DETERMINE: {
    cell: "border-maybe bg-maybe-bg text-maybe",
    glyph: "?",
    word: "cannot determine",
    ring: "var(--c-maybe)",
  },
};

interface FleetCellProps {
  readonly aircraft: FleetAircraft;
  readonly decision: Decision;
  readonly unknownFields: readonly string[];
  /**
   * Why the decision was withheld, one line per blocking field. Shown on hover
   * and read out in the accessible label, so an amber cell always says what
   * would have to be known to settle it.
   */
  readonly reason?: string;
  readonly changed: boolean;
  readonly selected: boolean;
  readonly delay: number;
  readonly duration: number;
  readonly onOpen: (tail: string) => void;
}

export function FleetCell({
  aircraft,
  decision,
  unknownFields,
  reason,
  changed,
  selected,
  delay,
  duration,
  onOpen,
}: FleetCellProps) {
  const tone = FLEET_TONE[decision];
  const fields = unknownFields.length > 0 ? ` (unknown: ${unknownFields.join(", ")})` : "";
  const why = reason && reason !== "" ? `\n${reason}` : "";
  // The fleet matrix payload carries no serial number, so the label leaves it
  // out rather than announcing its absence on all 478 cells.
  const msn = aircraft.serial_number === "" ? "" : `, MSN ${aircraft.serial_number}`;
  return (
    <motion.button
      type="button"
      role="gridcell"
      initial={{ opacity: 0, rotateY: -72, scale: 0.9 }}
      animate={{ opacity: 1, rotateY: 0, scale: 1 }}
      transition={{ duration, delay, ease: [0.2, 0.8, 0.2, 1] }}
      onClick={() => onOpen(aircraft.tail_number)}
      aria-label={`${aircraft.tail_number}, ${aircraft.operator}, ${aircraft.model}${msn}: ${decision}, ${tone.word}${fields}${why}`}
      title={`${aircraft.tail_number} · ${aircraft.model}${msn}\n${decision}${fields}${why}`}
      style={changed ? ({ "--ring-c": tone.ring } as React.CSSProperties) : undefined}
      className={[
        "grid h-[26px] w-[26px] place-items-center border text-[11px] font-semibold leading-none",
        tone.cell,
        changed ? "pulse-ring" : "",
        selected ? "outline outline-2 outline-offset-1 outline-accent" : "",
      ].join(" ")}
    >
      <span aria-hidden>{tone.glyph}</span>
    </motion.button>
  );
}
