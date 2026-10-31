"use client";

import { AnimatePresence } from "framer-motion";
import { useEffect, useMemo, useRef, useState } from "react";
import { evaluateFleet } from "@/lib/applicability";
import type { Decision } from "@/lib/contract";
import { ADS, type AdEntry } from "@/lib/corpus";
import { FLEET, FLEET_OPERATORS, FLEET_PROVENANCE, aircraftByTail } from "@/lib/fleet";
import { useMotionPrefs } from "@/lib/motion";
import { AircraftDrawer } from "./AircraftDrawer";
import { FLEET_TONE, FleetCell } from "./FleetCell";

const PULSE_MS = 1500;
const DECISIONS: readonly Decision[] = ["APPLIES", "CANNOT_DETERMINE", "DOES_NOT_APPLY"];

interface BlastRadiusProps {
  /** AD the current answer is about, so the tab opens on something relevant. */
  readonly preferredAdNumber: string | null;
}

/**
 * The fleet, grouped by operator, 86 real aircraft from the OpenSky public
 * database. Picking an AD runs the rules engine over every record and the cells
 * flip in a wave. Switching revision re-runs it and pulses only the cells whose
 * outcome changed, which is the whole point: a revision that "reduces the
 * applicability" should be visible as a handful of cells, not a repaint.
 */
export function BlastRadius({ preferredAdNumber }: BlastRadiusProps) {
  const { dur, stagger, reduced } = useMotionPrefs();
  const [adNumber, setAdNumber] = useState<string>(
    () => ADS.find((a) => a.ad_number === preferredAdNumber)?.ad_number ?? ADS[0]?.ad_number ?? "",
  );
  const ad: AdEntry = ADS.find((a) => a.ad_number === adNumber) ?? ADS[0]!;
  const [revisionIndex, setRevisionIndex] = useState(ad.revisions.length - 1);
  const [openTail, setOpenTail] = useState<string | null>(null);

  const entry = ad.revisions[Math.min(revisionIndex, ad.revisions.length - 1)] ?? ad.revisions[0]!;

  const { verdicts, elapsedMs } = useMemo(() => {
    const t0 = performance.now();
    const rows = evaluateFleet(ad, entry, FLEET);
    return { verdicts: rows, elapsedMs: performance.now() - t0 };
  }, [ad, entry]);

  const byTail = useMemo(() => new Map(verdicts.map((v) => [v.tail_number, v])), [verdicts]);

  // Changed-cell detection, scoped to one AD: switching AD is a wave, switching
  // revision inside an AD is a pulse on the difference only.
  const prev = useRef<{ ad: string; map: Map<string, Decision> } | null>(null);
  const [changed, setChanged] = useState<ReadonlySet<string>>(new Set());

  useEffect(() => {
    const map = new Map(verdicts.map((v) => [v.tail_number, v.decision]));
    const before = prev.current;
    if (before && before.ad === ad.ad_number) {
      const diff = new Set<string>();
      for (const [tail, decision] of map) {
        if (before.map.get(tail) !== decision) diff.add(tail);
      }
      setChanged(diff);
      if (diff.size > 0 && !reduced) {
        const t = window.setTimeout(() => setChanged(new Set()), PULSE_MS);
        prev.current = { ad: ad.ad_number, map };
        return () => window.clearTimeout(t);
      }
    } else {
      setChanged(new Set());
    }
    prev.current = { ad: ad.ad_number, map };
    return undefined;
  }, [verdicts, ad.ad_number, reduced]);

  useEffect(() => {
    setRevisionIndex(ad.revisions.length - 1);
  }, [ad]);

  const tally = useMemo(() => {
    const out: Record<Decision, number> = { APPLIES: 0, DOES_NOT_APPLY: 0, CANNOT_DETERMINE: 0 };
    for (const v of verdicts) out[v.decision] += 1;
    return out;
  }, [verdicts]);

  const open = openTail ? aircraftByTail(openTail) : undefined;

  return (
    <div className="flex min-h-0 flex-1">
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
        <header className="sticky top-0 z-10 border-b border-line bg-raised">
          <div className="flex flex-wrap items-end gap-x-6 gap-y-3 px-4 py-3">
            <div>
              <p className="t-label mb-1.5">airworthiness directive</p>
              <div className="flex items-stretch border border-line">
                {ADS.map((a, i) => (
                  <button
                    key={a.ad_number}
                    type="button"
                    onClick={() => setAdNumber(a.ad_number)}
                    aria-pressed={a.ad_number === ad.ad_number}
                    title={`${a.title} · ${a.make} · ${a.subject}`}
                    className={[
                      "t-mono px-2.5 py-1.5 text-left font-semibold tracking-tight transition-colors",
                      i > 0 ? "border-l border-line" : "",
                      a.ad_number === ad.ad_number ? "bg-accent-dim text-ink" : "text-ink-3 hover:text-ink",
                    ].join(" ")}
                  >
                    {a.ad_number}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <p className="t-label mb-1.5">revision</p>
              <div className="flex items-stretch border border-line">
                {ad.revisions.map((r, i) => {
                  const rev = r.built.revision;
                  const on = i === revisionIndex;
                  return (
                    <button
                      key={rev.revision_id}
                      type="button"
                      onClick={() => setRevisionIndex(i)}
                      aria-pressed={on}
                      title={`AD ${rev.ad_number}, ${rev.is_current ? "current" : "superseded"}, published ${rev.publication_date}`}
                      className={[
                        "t-mono px-2.5 py-1.5 font-semibold tracking-tight transition-colors",
                        i > 0 ? "border-l border-line" : "",
                        on ? "bg-accent-dim text-ink" : "text-ink-3 hover:text-ink",
                      ].join(" ")}
                    >
                      {rev.ad_number}
                      <span className="t-label ml-1.5 !tracking-[0.06em]">
                        {rev.is_current ? "current" : "superseded"}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>

            <dl className="flex items-stretch gap-0 border border-line">
              {DECISIONS.map((d, i) => (
                <div key={d} className={`px-3 py-1.5 ${i > 0 ? "border-l border-line" : ""}`}>
                  <dt className="t-label !tracking-[0.06em] flex items-center gap-1.5">
                    <span
                      aria-hidden
                      className={`grid h-3.5 w-3.5 place-items-center border text-[9px] leading-none ${FLEET_TONE[d].cell}`}
                    >
                      {FLEET_TONE[d].glyph}
                    </span>
                    {FLEET_TONE[d].word}
                  </dt>
                  <dd className="t-mono !text-[15px] font-bold tabular-nums text-ink">{tally[d]}</dd>
                </div>
              ))}
            </dl>

            <p className="t-mono ml-auto max-w-[280px] text-right text-ink-3">
              rules engine over {FLEET.length} records in {elapsedMs.toFixed(1)} ms
              <br />
              {ad.title}
            </p>
          </div>
          <p className="t-mono border-t border-line px-4 py-1.5 text-ink-3">
            {FLEET_PROVENANCE.dataset}, retrieved {FLEET_PROVENANCE.retrieved} &middot;{" "}
            {FLEET_PROVENANCE.aircraft} aircraft, {FLEET_PROVENANCE.operators} operators &middot; the
            dataset carries no {FLEET_PROVENANCE.absent_fields.join(", ")} fields, which is why amber
            cells exist &middot; red here means <em className="not-italic text-no">affected</em>, not
            &ldquo;condition satisfied&rdquo;
          </p>
        </header>

        <div key={`${ad.ad_number}:${entry.built.revision.revision_id}`} className="flex flex-col gap-4 px-4 py-4">
          {FLEET_OPERATORS.map((operator) => {
            const members = FLEET.filter((a) => a.operator === operator);
            const affected = members.filter((a) => byTail.get(a.tail_number)?.decision === "APPLIES").length;
            const amber = members.filter(
              (a) => byTail.get(a.tail_number)?.decision === "CANNOT_DETERMINE",
            ).length;
            return (
              <section key={operator} role="grid" aria-label={`${operator} fleet`}>
                <header className="mb-2 flex items-baseline gap-3 border-b border-line pb-1">
                  <h3 className="t-mono font-semibold text-ink">{operator}</h3>
                  <span className="t-label">{members.length} aircraft</span>
                  <span className="t-mono text-ink-3">
                    {affected} affected
                    {amber > 0 ? ` · ${amber} cannot determine` : ""}
                  </span>
                </header>
                <div role="row" className="flex flex-wrap gap-1">
                  {members.map((aircraft, i) => {
                    const v = byTail.get(aircraft.tail_number);
                    if (!v) return null;
                    return (
                      <FleetCell
                        key={aircraft.tail_number}
                        aircraft={aircraft}
                        decision={v.decision}
                        unknownFields={v.unknown_fields}
                        changed={changed.has(aircraft.tail_number)}
                        selected={openTail === aircraft.tail_number}
                        delay={stagger(9) * i}
                        duration={dur(230)}
                        onOpen={setOpenTail}
                      />
                    );
                  })}
                </div>
              </section>
            );
          })}
        </div>
      </div>

      <AnimatePresence>
        {open ? (
          <AircraftDrawer
            key={open.tail_number}
            aircraft={open}
            ad={ad}
            entry={entry}
            onClose={() => setOpenTail(null)}
          />
        ) : null}
      </AnimatePresence>
    </div>
  );
}
