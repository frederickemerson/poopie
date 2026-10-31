"use client";

import { motion } from "framer-motion";
import { useEffect, useMemo, useRef } from "react";
import { evaluate } from "@/lib/applicability";
import { resolveCitation } from "@/lib/citation";
import type { AdEntry, RevisionEntry } from "@/lib/corpus";
import type { FleetAircraft } from "@/lib/fleet";
import { useMotionPrefs } from "@/lib/motion";
import { ProofTree } from "../right/ProofTree";

interface AircraftDrawerProps {
  readonly aircraft: FleetAircraft;
  readonly ad: AdEntry;
  readonly entry: RevisionEntry;
  readonly onClose: () => void;
}

const Field = ({ label, value }: { label: string; value: string }) => (
  <div className="flex items-baseline justify-between gap-2 border-b border-line py-1">
    <span className="t-label !tracking-[0.06em]">{label}</span>
    <span className="t-mono truncate text-ink">{value}</span>
  </div>
);

/** One aircraft's proof, opened from its grid cell. */
export function AircraftDrawer({ aircraft, ad, entry, onClose }: AircraftDrawerProps) {
  const { dur } = useMotionPrefs();
  const ref = useRef<HTMLDivElement | null>(null);

  const { payload, elapsed } = useMemo(() => {
    const t0 = performance.now();
    const verdict = evaluate(ad, entry, aircraft);
    const ms = performance.now() - t0;
    return {
      payload: {
        decision: verdict.decision,
        fired_rule_ids: verdict.fired_rule_ids,
        unknown_fields: verdict.unknown_fields,
        proof_tree: verdict.proof_tree,
        stage_ms: Math.max(1, Math.round(ms)),
      },
      elapsed: ms,
    };
  }, [aircraft, ad, entry]);
  void elapsed;

  const paragraphs = entry.built.paragraphs;

  useEffect(() => {
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <motion.aside
      ref={ref}
      tabIndex={-1}
      role="dialog"
      aria-label={`applicability proof for ${aircraft.tail_number}`}
      initial={{ opacity: 0, x: 24 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 24 }}
      transition={{ duration: dur(220), ease: [0.2, 0.8, 0.2, 1] }}
      className="flex w-[380px] shrink-0 flex-col overflow-y-auto border-l border-line bg-raised"
    >
      <header className="sticky top-0 z-10 flex items-center justify-between gap-2 border-b border-line bg-raised px-3 py-2">
        <div className="min-w-0">
          <p className="t-mono !text-[14px] font-bold text-ink">{aircraft.tail_number}</p>
          <p className="t-label mt-0.5">{aircraft.operator}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="close proof"
          className="t-label border border-line px-2 py-1 text-ink-2 hover:border-line-strong hover:text-ink"
        >
          close
        </button>
      </header>

      <div className="px-3 py-2">
        <p className="t-label mb-1">fleet record &middot; OpenSky</p>
        <Field label="model" value={aircraft.model} />
        <Field label="typecode" value={aircraft.typecode} />
        <Field label="MSN" value={aircraft.serial_number} />
        <Field label="manufacturer" value={aircraft.manufacturer} />
        <Field label="icao24" value={aircraft.icao24} />
        <Field label="built" value={aircraft.built_year === null ? "not in record" : String(aircraft.built_year)} />
        <Field label="equipment" value={aircraft.equipment === null ? "not in record" : aircraft.equipment.join(", ")} />
        <Field
          label="modification"
          value={aircraft.modification === null ? "not in record" : aircraft.modification.join(", ")}
        />
      </div>

      <div className="border-t border-line">
        <p className="t-label px-3 pt-2">
          {ad.ad_number} &middot; revision {entry.built.revision.revision_id}
        </p>
        <ProofTree
          decision={payload}
          resolve={(id) => resolveCitation(id, paragraphs)}
          onFocusCitation={() => undefined}
          subjectLabel={aircraft.tail_number}
          /* This drawer is opened from one aircraft row, so applicability is
             exactly what was asked, whatever the query plan said. */
          applicabilityAsked
        />
      </div>
    </motion.aside>
  );
}
