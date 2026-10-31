"use client";

import { motion } from "framer-motion";
import type { ResolvedCitation } from "@/lib/citation";
import { useMotionPrefs } from "@/lib/motion";
import type { DecisionPayload, ProofTreeNode } from "@/lib/events";
import { DecisionChip, StatusGlyph, TONE } from "../ui/StatusGlyph";

interface ProofTreeProps {
  readonly decision: DecisionPayload | null;
  readonly resolve: (citationId: string) => ResolvedCitation | null;
  readonly onFocusCitation: (c: ResolvedCitation | null) => void;
  readonly subjectLabel: string | null;
}

const RESOLVE_STEP_MS = 120;

/**
 * The applicability proof. One row per condition, each resolving in sequence to
 * tick, cross or question mark, with the aircraft's value set against the rule's
 * value. The question mark is an outcome, not a failure: it means the fleet
 * record does not carry the field the AD conditions on.
 */
export function ProofTree({ decision, resolve, onFocusCitation, subjectLabel }: ProofTreeProps) {
  const { dur, stagger } = useMotionPrefs();

  if (!decision) {
    return <p className="t-mono px-3 py-3 text-ink-3">awaiting the applicability decision&hellip;</p>;
  }

  const tree = decision.proof_tree;
  const children = tree.children ?? [];

  return (
    <div className="flex flex-col px-3 py-3">
      <header className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="t-mono truncate font-semibold text-ink">{tree.label}</p>
          <p className="t-label mt-0.5">
            {tree.kind === "all" ? "all conditions must hold" : "any condition may hold"}
            {subjectLabel ? ` · against ${subjectLabel}` : ""}
          </p>
        </div>
        <motion.div
          initial={{ opacity: 0, scale: 0.94 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: dur(200), delay: stagger(RESOLVE_STEP_MS) * children.length }}
        >
          <DecisionChip decision={decision.decision} />
        </motion.div>
      </header>

      <ol className="relative flex flex-col" aria-label="applicability conditions">
        <span aria-hidden className="absolute bottom-3 left-[7px] top-0 w-px bg-line" />
        {children.map((node, i) => (
          <ConditionRow
            key={node.id}
            node={node}
            delay={stagger(RESOLVE_STEP_MS) * i}
            duration={dur(200)}
            resolve={resolve}
            onFocusCitation={onFocusCitation}
          />
        ))}
      </ol>

      <dl className="t-mono mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 border-t border-line pt-2 text-ink-3">
        <dt>fired rules</dt>
        <dd className="text-ink-2">
          {decision.fired_rule_ids.length > 0 ? decision.fired_rule_ids.join("  ") : "none"}
        </dd>
        <dt>unknown fields</dt>
        <dd className={decision.unknown_fields.length > 0 ? "text-maybe" : "text-ink-2"}>
          {decision.unknown_fields.length > 0 ? decision.unknown_fields.join(", ") : "none"}
        </dd>
        <dt>decided by</dt>
        <dd className="text-ink-2">rules engine, {decision.stage_ms} ms</dd>
      </dl>
    </div>
  );
}

interface ConditionRowProps {
  readonly node: ProofTreeNode;
  readonly delay: number;
  readonly duration: number;
  readonly resolve: (citationId: string) => ResolvedCitation | null;
  readonly onFocusCitation: (c: ResolvedCitation | null) => void;
}

function ConditionRow({ node, delay, duration, resolve, onFocusCitation }: ConditionRowProps) {
  const tone = TONE[node.decision];
  const citation = node.citation_id ? resolve(node.citation_id) : null;
  const have = node.aircraft_value;
  const ariaValue = have === null || have === undefined ? "not in the fleet record" : have;

  return (
    <motion.li
      initial={{ opacity: 0, x: -6 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration, delay, ease: [0.2, 0.8, 0.2, 1] }}
      className="relative pl-6"
    >
      <span aria-hidden className="absolute left-[7px] top-[13px] h-px w-3 bg-line" />
      <div
        tabIndex={0}
        role="group"
        aria-label={`${node.label}; aircraft value ${ariaValue}; ${node.decision}`}
        onMouseEnter={() => citation && onFocusCitation(citation)}
        onMouseLeave={() => citation && onFocusCitation(null)}
        onFocus={() => citation && onFocusCitation(citation)}
        onBlur={() => citation && onFocusCitation(null)}
        className="group border-b border-line py-1.5 pr-1"
      >
        <div className="flex items-start gap-2">
          <motion.span
            initial={{ scale: 0.4, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ duration, delay: delay + duration * 0.35, type: "spring", stiffness: 420, damping: 26 }}
            className="mt-[1px]"
          >
            <StatusGlyph decision={node.decision} size={15} />
          </motion.span>
          <div className="min-w-0 flex-1">
            <p className="t-body leading-snug text-ink">{node.label}</p>
            <p className="t-mono mt-0.5 flex flex-wrap items-baseline gap-x-2 text-ink-3">
              {node.field ? <span className="text-ink-3">{node.field}</span> : null}
              <span className={have === null || have === undefined ? "text-maybe" : `font-semibold ${tone.text}`}>
                {have === null || have === undefined ? "not in fleet record" : have}
              </span>
              {node.rule_value ? (
                <>
                  <span aria-hidden className="text-ink-3">
                    vs
                  </span>
                  <span className="truncate text-ink-2" title={node.rule_value}>
                    {node.rule_value.length > 54 ? `${node.rule_value.slice(0, 54)}…` : node.rule_value}
                  </span>
                </>
              ) : null}
            </p>
            {node.unparsed_reason ? (
              <p className="t-body mt-1 border-l-2 border-maybe pl-2 text-maybe">
                {node.unparsed_reason}
              </p>
            ) : null}
            {citation ? (
              <p className="t-mono mt-1 truncate text-ink-3 opacity-0 transition-opacity group-hover:opacity-100 group-focus:opacity-100">
                &ldquo;{citation.quote.length > 72 ? `${citation.quote.slice(0, 72)}…` : citation.quote}&rdquo;
              </p>
            ) : null}
          </div>
        </div>
      </div>
    </motion.li>
  );
}
