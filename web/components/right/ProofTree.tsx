"use client";

import { motion } from "framer-motion";
import { formatReference, referenceOf, type ResolvedCitation } from "@/lib/citation";
import { useMotionPrefs } from "@/lib/motion";
import { isProofTreeUnavailable, type DecisionPayload, type ProofTreeNode } from "@/lib/events";
import { DecisionChip, StatusGlyph, TONE } from "../ui/StatusGlyph";

interface ProofTreeProps {
  readonly decision: DecisionPayload | null;
  readonly resolve: (citationId: string) => ResolvedCitation | null;
  readonly onFocusCitation: (c: ResolvedCitation | null) => void;
  readonly subjectLabel: string | null;
  /**
   * Whether the question actually asked for an applicability decision, read
   * from the query plan's own intent and aircraft fields. Someone who asked
   * what an AD's unsafe condition is has not failed to supply a tail number;
   * they asked a different question, and telling them the rules engine did not
   * run reads as a shortfall in their question rather than a fact about ours.
   */
  readonly applicabilityAsked: boolean;
}

const RESOLVE_STEP_MS = 120;

/**
 * The applicability proof. One row per condition, each resolving in sequence to
 * tick, cross or question mark, with the aircraft's value set against the rule's
 * value. The question mark is an outcome, not a failure: it means the fleet
 * record does not carry the field the AD conditions on.
 */
export function ProofTree({
  decision,
  resolve,
  onFocusCitation,
  subjectLabel,
  applicabilityAsked,
}: ProofTreeProps) {
  const { dur, stagger } = useMotionPrefs();

  if (!decision) {
    return <p className="t-mono px-3 py-3 text-ink-3">awaiting the applicability decision&hellip;</p>;
  }

  if (isProofTreeUnavailable(decision.proof_tree)) {
    if (!applicabilityAsked) {
      return (
        <p className="t-body px-3 py-3 text-ink-3">
          This question did not ask whether a directive applies to an aircraft, so the
          rules engine did not run. Name a tail number or a serial number to get a
          verdict with its conditions.
        </p>
      );
    }
    return <NoDecision reason={decision.proof_tree.unavailable} stageMs={decision.stage_ms} />;
  }

  const tree = decision.proof_tree;
  const children = tree.children ?? [];
  const aircraft = tree.aircraft ?? null;
  const stage = tree.stage ?? null;
  const subject = aircraft?.tail_number ?? subjectLabel;

  return (
    <div className="flex flex-col px-3 py-3">
      <header className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="t-mono truncate font-semibold text-ink">{tree.label}</p>
          <p className="t-label mt-0.5">
            {tree.kind === "all" ? "all conditions must hold" : "any condition may hold"}
            {subject ? ` · against ${subject}` : ""}
          </p>
        </div>
        <motion.div
          initial={{ opacity: 0, scale: 0.94 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: dur(200), delay: stagger(RESOLVE_STEP_MS) * children.length }}
        >
          {decision.decision === null ? (
            <span className="t-mono border border-line px-1.5 py-0.5 text-ink-3">no decision</span>
          ) : (
            <DecisionChip decision={decision.decision} />
          )}
        </motion.div>
      </header>

      {aircraft ? <FleetRecordRow aircraft={aircraft} /> : null}

      {stage?.document_stage ? (
        <p
          className="t-body mb-3 border-l-2 border-line-strong pl-2 text-ink-2"
          title="legal stage of the revision, derived from effective_on and superseded_by"
        >
          <span className="t-mono font-semibold text-ink">
            {stage.document_stage.replace(/_/g, " ").toLowerCase()}
          </span>
          {stage.explanation ? ` — ${stage.explanation}` : null}
        </p>
      ) : null}

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

      {children.length === 0 ? (
        <p className="t-body text-ink-2">
          The engine returned no conditions for this revision, so there is nothing to check against.
        </p>
      ) : null}

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

/**
 * No decision, said plainly. The engine reports exactly which precondition was
 * missing - no aircraft resolved, no rules extracted for the retrieved revision
 * - and that sentence is the content. Rendering a spinner or an empty panel here
 * would turn a definite answer into an apparent hang.
 */
function NoDecision({ reason, stageMs }: { readonly reason: string; readonly stageMs: number }) {
  const { dur } = useMotionPrefs();
  return (
    <motion.section
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: dur(200), ease: [0.2, 0.8, 0.2, 1] }}
      aria-label="no applicability decision"
      className="m-3 border border-line-strong bg-sunken/60"
    >
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-3 py-2">
        <span aria-hidden className="t-mono !text-[13px] font-bold text-ink-3">
          &#9671;
        </span>
        <h3 className="t-mono !text-[13px] font-bold tracking-tight text-ink">
          no applicability decision
        </h3>
        <span className="t-label !tracking-[0.06em] text-ink-3">rules engine did not run</span>
      </header>
      <div className="px-3 py-2.5">
        <p className="t-body text-ink">{reason}</p>
        <p className="t-body mt-2 text-ink-2">
          This is the engine declining to decide, not a failure to respond. Retrieval and the cited
          paragraphs below are still real; only the applicability verdict is absent, because one of
          its inputs was.
        </p>
      </div>
      <p className="t-mono border-t border-line px-3 py-1.5 text-ink-3">
        reported by the applicability stage in {stageMs} ms
      </p>
    </motion.section>
  );
}

/** The record the decision was made against, as the engine reported it. */
function FleetRecordRow({ aircraft }: { readonly aircraft: NonNullable<ProofTreeNode["aircraft"]> }) {
  const fields: readonly (readonly [string, string | null | undefined])[] = [
    ["tail", aircraft.tail_number],
    ["operator", aircraft.operator],
    ["model", aircraft.model],
    ["typecode", aircraft.typecode],
    ["MSN", aircraft.serial_number],
    ["mfr", aircraft.manufacturer],
  ];
  return (
    <dl className="t-mono mb-3 flex flex-wrap gap-x-3 gap-y-0.5 border border-line bg-sunken px-2 py-1.5 text-ink-3">
      {fields.map(([label, value]) => (
        <div key={label} className="flex items-baseline gap-1">
          <dt className="t-label !tracking-[0.06em]">{label}</dt>
          <dd className={value ? "text-ink-2" : "text-maybe"}>{value ?? "not in record"}</dd>
        </div>
      ))}
    </dl>
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
  const reference = citation ? referenceOf(citation) : undefined;
  const have = node.aircraft_value;
  const ariaValue = have === null || have === undefined ? "not in the fleet record" : have;
  // The unparsed callout already carries the reason; do not print it twice.
  const reason = node.reason && node.reason !== node.unparsed_reason ? node.reason : null;

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
            {reason ? <p className="t-body mt-1 text-ink-2">{reason}</p> : null}
            {node.external_ref ? (
              <p className="t-mono mt-1 text-maybe">
                document required: <span className="font-semibold">{node.external_ref}</span>
              </p>
            ) : null}
            {citation ? (
              <>
                <p className="t-mono mt-1 truncate text-ink-3 opacity-0 transition-opacity group-hover:opacity-100 group-focus:opacity-100">
                  &ldquo;{citation.quote.length > 72 ? `${citation.quote.slice(0, 72)}…` : citation.quote}&rdquo;
                </p>
                {/*
                  The tree header already states the revision's stage, but a
                  condition row is itself a rendered citation, and the contract
                  requires every one of those to show its stage. Stated here
                  too, so the row can be read on its own.
                */}
                <p className="t-mono truncate text-ink-3">
                  {reference
                    ? formatReference(reference)
                    : `${citation.ref.revision_id} · stage not sent`}
                </p>
              </>
            ) : null}
          </div>
        </div>
      </div>
    </motion.li>
  );
}
