"use client";

/**
 * The real fleet grid: the engine's own rules engine, run over every aircraft in
 * the built fleet for one revision, fetched from GET /blast/{revision_id}.
 *
 * Cells are grouped by operator. Amber means the rules engine withheld the
 * decision, and the cell says which field blocked it and why that field is
 * unanswerable - which is the honest half of the argument and the reason the
 * amber count is large rather than hidden.
 */
import { AnimatePresence } from "framer-motion";
import { useEffect, useMemo, useState } from "react";
import {
  explainCell,
  explainUnknownField,
  fetchBlastMatrix,
  groupByOperator,
  unknownFieldTally,
  type BlastCell,
  type BlastMatrix,
  type BlastRevisionRef,
} from "@/lib/blast";
import type { Decision } from "@/lib/contract";
import { FLEET_PROVENANCE } from "@/lib/fleet";
import { useMotionPrefs } from "@/lib/motion";
import { BlastCellDrawer } from "./BlastCellDrawer";
import { FLEET_TONE, FleetCell } from "./FleetCell";

const DECISIONS: readonly Decision[] = ["APPLIES", "CANNOT_DETERMINE", "DOES_NOT_APPLY"];

/**
 * Cell wave. Each group staggers independently, so the whole grid lands inside
 * the 400 ms motion ceiling; the step count is clamped so a large operator
 * cannot stretch the wave past it.
 */
const CELL_STEP_MS = 4;
const CELL_STEP_LIMIT = 40;
const CELL_DURATION_MS = 200;

interface LiveBlastRadiusProps {
  /** Revisions this session's runs have surfaced, newest first. */
  readonly revisions: readonly BlastRevisionRef[];
}

/** The cell shape FleetCell wants, from a live blast cell. */
function asFleetAircraft(cell: BlastCell) {
  return {
    tail_number: cell.tail_number,
    icao24: "",
    manufacturer: "",
    model: cell.model ?? "model not in record",
    typecode: "",
    // The fleet matrix carries no serial number; empty means "not in this
    // payload" and the cell label omits it rather than claiming it is unknown.
    serial_number: "",
    operator: cell.operator ?? "not in record",
    built_year: null,
    equipment: null,
    modification: null,
  };
}

export function LiveBlastRadius({ revisions }: LiveBlastRadiusProps) {
  const { dur, stagger } = useMotionPrefs();
  const [revisionId, setRevisionId] = useState<string | null>(revisions[0]?.revision_id ?? null);
  const [typed, setTyped] = useState("");
  const [matrix, setMatrix] = useState<BlastMatrix | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [openTail, setOpenTail] = useState<string | null>(null);
  const [elapsedMs, setElapsedMs] = useState<number | null>(null);

  // Follow the engine: when a run decides against a new revision, show it.
  useEffect(() => {
    const first = revisions[0]?.revision_id;
    if (first && revisionId === null) setRevisionId(first);
  }, [revisions, revisionId]);

  useEffect(() => {
    if (revisionId === null) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setOpenTail(null);
    const started = performance.now();

    fetchBlastMatrix(revisionId, controller.signal)
      .then((payload) => {
        if (controller.signal.aborted) return;
        setMatrix(payload);
        setElapsedMs(performance.now() - started);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setMatrix(null);
        setError(cause instanceof Error ? cause.message : "blast request failed");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => controller.abort();
  }, [revisionId]);

  const groups = useMemo(() => (matrix ? groupByOperator(matrix.cells) : []), [matrix]);
  const tally = useMemo(() => (matrix ? unknownFieldTally(matrix.cells) : []), [matrix]);
  const open = useMemo(
    () => matrix?.cells.find((c) => c.tail_number === openTail) ?? null,
    [matrix, openTail],
  );
  const total = matrix?.cells.length ?? 0;

  const submitTyped = (event: React.FormEvent) => {
    event.preventDefault();
    const next = typed.trim();
    if (next !== "") setRevisionId(next);
  };

  return (
    <div className="flex min-h-0 flex-1">
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
        <header className="sticky top-0 z-10 border-b border-line bg-raised">
          <div className="flex flex-wrap items-end gap-x-6 gap-y-3 px-4 py-3">
            <div>
              <p className="t-label mb-1.5">revision · from this session&rsquo;s runs</p>
              {revisions.length === 0 ? (
                <p className="t-mono max-w-[360px] text-ink-3">
                  no revision yet — the engine names one when a query retrieves an AD
                </p>
              ) : (
                <div className="flex items-stretch border border-line">
                  {revisions.map((r, i) => (
                    <button
                      key={r.revision_id}
                      type="button"
                      onClick={() => setRevisionId(r.revision_id)}
                      aria-pressed={r.revision_id === revisionId}
                      title={
                        r.decided
                          ? `${r.revision_id}: the rules engine decided against this revision`
                          : `${r.revision_id}: retrieved for a query in this session`
                      }
                      className={[
                        "t-mono px-2.5 py-1.5 text-left font-semibold tracking-tight transition-colors",
                        i > 0 ? "border-l border-line" : "",
                        r.revision_id === revisionId
                          ? "bg-accent-dim text-ink"
                          : "text-ink-3 hover:text-ink",
                      ].join(" ")}
                    >
                      {r.ad_number ?? r.revision_id}
                      <span className="t-label ml-1.5 !tracking-[0.06em]">{r.revision_id}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            <form onSubmit={submitTyped}>
              <label className="t-label mb-1.5 block" htmlFor="blast-revision">
                or a revision id
              </label>
              <div className="flex items-stretch">
                <input
                  id="blast-revision"
                  value={typed}
                  onChange={(e) => setTyped(e.target.value)}
                  placeholder="2026-21332"
                  className="t-mono w-[120px] border border-line bg-sunken px-2 py-1.5 text-ink placeholder:text-ink-3"
                />
                <button
                  type="submit"
                  className="t-label border border-l-0 border-line-strong bg-sunken px-2.5 text-ink hover:border-accent"
                >
                  run
                </button>
              </div>
            </form>

            <dl className="flex items-stretch border border-line">
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
                  <dd className="t-mono !text-[15px] font-bold tabular-nums text-ink">
                    {matrix ? matrix.counts[d] : "—"}
                  </dd>
                </div>
              ))}
            </dl>

            <p className="t-mono ml-auto max-w-[260px] text-right text-ink-3">
              {loading
                ? "running the rules engine…"
                : matrix
                  ? `rules engine over ${total} records${
                      elapsedMs === null ? "" : ` · round trip ${elapsedMs.toFixed(0)} ms`
                    }`
                  : "—"}
            </p>
          </div>

          <p className="t-mono border-t border-line px-4 py-1.5 text-ink-3">
            <span className="font-semibold text-ink-2">GET /blast/{revisionId ?? "…"}</span> &middot;{" "}
            {FLEET_PROVENANCE.dataset} &middot; {total} real aircraft, {groups.length} operators,
            decided by the engine&rsquo;s rules engine &middot; the dataset carries no{" "}
            {FLEET_PROVENANCE.absent_fields.join(", ")} columns, which is why amber cells exist
            &middot; red here means <em className="not-italic text-no">affected</em>, not
            &ldquo;condition satisfied&rdquo;
          </p>

          {tally.length > 0 ? (
            <ul className="flex flex-wrap gap-x-4 gap-y-1 border-t border-line px-4 py-1.5">
              {tally.map(({ field, count }) => (
                <li key={field} className="t-mono text-maybe" title={explainUnknownField(field)}>
                  {count} blocked on <span className="font-semibold">{field}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </header>

        {error ? (
          <div className="m-4 border border-accent px-3 py-2.5">
            <p className="t-label mb-1 text-ink">blast request failed</p>
            <p className="t-body text-ink-2">{error}</p>
          </div>
        ) : null}

        {revisionId === null ? (
          <p className="t-body m-4 max-w-[560px] text-ink-2">
            Ask a question in the workspace first. The grid is computed for one revision, and the
            revision is whichever one the engine actually retrieved — it is not chosen here, so the
            grid can never show a revision the engine did not read.
          </p>
        ) : null}

        {matrix && matrix.cells.length === 0 && !loading ? (
          <p className="t-body m-4 max-w-[560px] text-ink-2">
            The engine returned no cells for {matrix.revision_id}. The fleet is empty, or this
            revision is not one the applicability store holds rules for.
          </p>
        ) : null}

        <div key={matrix?.revision_id ?? "none"} className="flex flex-col gap-4 px-4 py-4">
          {groups.map((group) => (
            <section key={group.operator} role="grid" aria-label={`${group.operator} fleet`}>
              <header className="mb-2 flex items-baseline gap-3 border-b border-line pb-1">
                <h3 className="t-mono font-semibold text-ink">{group.operator}</h3>
                <span className="t-label">{group.cells.length} aircraft</span>
                <span className="t-mono text-ink-3">
                  {group.affected} affected
                  {group.undetermined > 0 ? ` · ${group.undetermined} cannot determine` : ""}
                </span>
              </header>
              <div role="row" className="flex flex-wrap gap-1">
                {group.cells.map((cell, i) => (
                  <FleetCell
                    key={cell.tail_number}
                    aircraft={asFleetAircraft(cell)}
                    decision={cell.decision}
                    unknownFields={cell.unknown_fields}
                    reason={explainCell(cell)}
                    changed={false}
                    selected={openTail === cell.tail_number}
                    delay={stagger(CELL_STEP_MS) * Math.min(i, CELL_STEP_LIMIT)}
                    duration={dur(CELL_DURATION_MS)}
                    onOpen={setOpenTail}
                  />
                ))}
              </div>
            </section>
          ))}
        </div>
      </div>

      <AnimatePresence>
        {open && matrix ? (
          <BlastCellDrawer
            key={open.tail_number}
            cell={open}
            revisionId={matrix.revision_id}
            onClose={() => setOpenTail(null)}
          />
        ) : null}
      </AnimatePresence>
    </div>
  );
}
