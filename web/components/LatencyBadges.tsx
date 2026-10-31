"use client";

import { LATENCY_TARGETS_MS } from "@/lib/contract";

/**
 * Live per-stage latency against LATENCY_TARGETS_MS. Deliberately greyscale: a
 * stage over budget is marked with the non-semantic accent and a triangle, so
 * green / red / amber stay reserved for the three enums.decision outcomes.
 */
const STAGES: readonly { readonly key: keyof typeof LATENCY_TARGETS_MS; readonly label: string }[] = [
  { key: "entity_pass", label: "entities" },
  { key: "query_plan", label: "plan" },
  { key: "retrieval", label: "retrieval" },
  { key: "applicability", label: "rules" },
  { key: "verify", label: "verify" },
];

interface LatencyBadgesProps {
  readonly stageMs: Readonly<Record<string, number>>;
  readonly totalMs: number | null;
}

function Badge({ label, value, target }: { label: string; value: number | null; target: number }) {
  const over = value !== null && value > target;
  const pct = value === null ? 0 : Math.min(100, (value / Math.max(target, 1)) * 100);
  return (
    <div
      className="flex min-w-[64px] flex-col gap-1"
      title={`${label}: target ${target} ms${value === null ? "" : `, measured ${value} ms`}`}
    >
      <div className="flex items-baseline justify-between gap-1.5">
        <span className="t-label !tracking-[0.06em]">{label}</span>
        <span className={`t-mono tabular-nums ${over ? "font-semibold text-accent" : "text-ink-2"}`}>
          {value === null ? "—" : `${value}`}
          {over ? <span aria-hidden> &#9650;</span> : null}
        </span>
      </div>
      <div className="relative h-[3px] w-full bg-sunken" aria-hidden>
        <span
          className={`absolute inset-y-0 left-0 ${over ? "bg-accent" : "bg-line-strong"}`}
          style={{ width: `${pct}%`, transition: "width 220ms ease-out" }}
        />
        <span className="absolute inset-y-[-2px] w-px bg-line-strong" style={{ left: "100%" }} />
      </div>
      <span className="sr-only">
        {value === null ? "not measured" : `${value} milliseconds, target ${target}`}
      </span>
    </div>
  );
}

export function LatencyBadges({ stageMs, totalMs }: LatencyBadgesProps) {
  return (
    <div
      className="flex flex-wrap items-end gap-x-3 gap-y-1"
      aria-label="per-stage latency against contract targets"
    >
      {STAGES.map((s) => (
        <Badge key={s.key} label={s.label} value={stageMs[s.key] ?? null} target={LATENCY_TARGETS_MS[s.key]} />
      ))}
      <div className="h-7 w-px bg-line" aria-hidden />
      <Badge label="total p95" value={totalMs} target={LATENCY_TARGETS_MS.total_p95} />
    </div>
  );
}
