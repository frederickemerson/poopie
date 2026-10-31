"use client";

import { motion } from "framer-motion";
import { useMotionPrefs } from "@/lib/motion";
import type { RuleField } from "@/lib/contract";
import type { QueryPlan } from "@/lib/events";

interface PlanPanelProps {
  readonly plan: QueryPlan | null;
  readonly planModel: string | null;
  readonly unknownFields: readonly RuleField[];
}

interface Slot {
  readonly key: string;
  readonly label: string;
  readonly value: string | null;
}

function slotsOf(plan: QueryPlan): readonly Slot[] {
  return [
    { key: "intent", label: "intent", value: plan.intent },
    { key: "ad_number", label: "AD", value: plan.ad_number },
    { key: "docket_id", label: "docket", value: plan.docket_id },
    { key: "manufacturer", label: "manufacturer", value: plan.aircraft.manufacturer },
    { key: "model", label: "model", value: plan.aircraft.model },
    { key: "typecode", label: "typecode", value: plan.aircraft.typecode },
    { key: "serial_number", label: "MSN", value: plan.aircraft.serial_number },
    { key: "tail_number", label: "tail", value: plan.aircraft.tail_number },
    { key: "revision_scope", label: "revisions", value: plan.revision_scope },
  ];
}

/**
 * The query plan, slot by slot. A slot the plan called ambiguous, or that the
 * rules engine reported in unknown_fields, holds the amber state - which is what
 * a NEED_CONFIG refusal looks like before it fires.
 */
export function PlanPanel({ plan, planModel, unknownFields }: PlanPanelProps) {
  const { dur, stagger } = useMotionPrefs();

  if (!plan) {
    return (
      <p className="t-mono px-3 py-3 text-ink-3">
        awaiting query_plan&hellip;
      </p>
    );
  }

  const flagged = new Set<string>(unknownFields);
  for (const a of plan.ambiguities) {
    const key = a.split(":")[0]?.trim();
    if (key) flagged.add(key);
  }

  return (
    <div className="flex flex-col">
      <dl className="grid grid-cols-[86px_1fr] gap-x-2">
        {slotsOf(plan).map((slot, i) => {
          const amber = slot.value === null && flagged.has(slot.key);
          return (
            <motion.div
              key={slot.key}
              initial={{ opacity: 0, x: -5 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: dur(180), delay: stagger(26) * i }}
              className="col-span-2 grid grid-cols-subgrid items-baseline border-b border-line px-3 py-[5px] last:border-b-0"
            >
              <dt className="t-label !tracking-[0.06em]">{slot.label}</dt>
              <dd
                className={[
                  "t-mono truncate",
                  slot.value === null ? "text-ink-3" : "text-ink",
                  amber ? "pulse-ring -mx-1 inline-block rounded-sm border border-dashed border-maybe px-1 !text-maybe" : "",
                ].join(" ")}
                style={amber ? ({ "--ring-c": "var(--c-maybe)" } as React.CSSProperties) : undefined}
                title={amber ? "missing or ambiguous - this is the NEED_CONFIG state before it fires" : undefined}
              >
                {slot.value ?? (amber ? "not supplied" : "—")}
              </dd>
            </motion.div>
          );
        })}
      </dl>

      {plan.ambiguities.length > 0 ? (
        <ul className="border-t border-line px-3 py-2" aria-label="ambiguities the plan recorded">
          {plan.ambiguities.map((a) => (
            <li key={a} className="t-body flex gap-2 py-0.5 text-maybe">
              <span aria-hidden className="shrink-0 font-semibold">
                ?
              </span>
              <span className="text-ink-2">{a}</span>
            </li>
          ))}
        </ul>
      ) : null}

      {planModel ? (
        <p className="t-mono border-t border-line px-3 py-1.5 text-ink-3">
          plan by {planModel} &middot; the plan reads the question; the rules engine decides
        </p>
      ) : null}
    </div>
  );
}
