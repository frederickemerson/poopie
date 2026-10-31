"use client";

import "@xyflow/react/dist/style.css";
import { Background, BackgroundVariant, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import { useMemo } from "react";
import { LATENCY_TARGETS_MS } from "@/lib/contract";
import { isProofTreeUnavailable } from "@/lib/events";
import { useMotionPrefs } from "@/lib/motion";
import type { EngineView } from "@/lib/useEngineStream";

interface TraceData extends Record<string, unknown> {
  readonly kind: string;
  readonly heading: string;
  readonly lines: readonly string[];
  readonly stage: string;
  readonly stage_ms: number | null;
  readonly target: number | null;
  readonly lit: boolean;
  readonly elapsed: number | null;
}

/**
 * The graph path the engine actually walked: Aircraft -> Rule -> Revision ->
 * Paragraph. A node lights only when the event that produced it has arrived, and
 * carries that event's stage_ms against the contract's target for the stage.
 */
function TraceNode({ data }: NodeProps<Node<TraceData>>) {
  const over = data.stage_ms !== null && data.target !== null && data.stage_ms > data.target;
  return (
    <div
      className={[
        "w-[196px] border bg-raised px-2.5 py-2 transition-all duration-200",
        data.lit ? "border-accent" : "border-line opacity-45",
      ].join(" ")}
      style={data.lit ? { boxShadow: "0 0 0 3px var(--c-accent-dim)" } : undefined}
    >
      <Handle type="target" position={Position.Left} />
      <div className="flex items-baseline justify-between gap-2">
        <span className="t-label !tracking-[0.1em]">{data.kind}</span>
        <span className={`t-mono tabular-nums ${over ? "font-semibold text-accent" : "text-ink-3"}`}>
          {data.stage_ms === null ? "—" : `${data.stage_ms}ms`}
          {over ? <span aria-hidden> &#9650;</span> : null}
        </span>
      </div>
      <p className="t-mono mt-0.5 truncate font-semibold text-ink">{data.heading}</p>
      {data.lines.map((line) => (
        <p key={line} className="t-mono truncate text-ink-3">
          {line}
        </p>
      ))}
      <p className="t-label mt-1 !tracking-[0.06em]">
        {data.stage}
        {data.elapsed !== null ? ` · t+${data.elapsed}ms` : ""}
      </p>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

const nodeTypes = { trace: TraceNode };

export function RetrievalTrace({ state }: { readonly state: EngineView }) {
  const { reduced } = useMotionPrefs();

  const { nodes, edges } = useMemo(() => {
    const plan = state.plan;
    const retrieved = state.paragraphs;
    const revisionIds = [...new Set(retrieved.map((p) => p.revision_id))];
    const decision = state.decision;
    // null when there is no decision at all, which is not the same as zero
    // conditions and must not render as "0".
    const tree = decision?.proof_tree ?? null;
    const conditionCount =
      tree === null || isProofTreeUnavailable(tree) ? null : (tree.children?.length ?? 0);

    const defs: readonly { id: string; data: TraceData; x: number; y: number }[] = [
      {
        id: "aircraft",
        x: 0,
        y: 0,
        data: {
          kind: "Aircraft",
          heading: plan?.aircraft.tail_number ?? plan?.aircraft.model ?? "—",
          lines: [
            plan?.aircraft.model ? `model ${plan.aircraft.model}` : "model not supplied",
            plan?.aircraft.serial_number ? `MSN ${plan.aircraft.serial_number}` : "MSN not supplied",
          ],
          stage: "entity_pass",
          stage_ms: state.stageMs.entity_pass ?? null,
          target: LATENCY_TARGETS_MS.entity_pass,
          lit: state.entities.length > 0,
          elapsed: state.seenAt.entities ?? null,
        },
      },
      {
        id: "rule",
        x: 236,
        y: 0,
        data: {
          kind: "Rule",
          heading: conditionCount === null ? "—" : `${conditionCount} conditions`,
          lines: decision
            ? [
                `fired ${decision.fired_rule_ids.length}`,
                decision.unknown_fields.length > 0
                  ? `unknown ${decision.unknown_fields.join(", ")}`
                  : "no unknown fields",
              ]
            : ["awaiting decision"],
          stage: "applicability",
          stage_ms: state.stageMs.applicability ?? null,
          target: LATENCY_TARGETS_MS.applicability,
          lit: decision !== null,
          elapsed: state.seenAt.decision ?? null,
        },
      },
      {
        id: "revision",
        x: 0,
        y: 132,
        data: {
          kind: "Revision",
          heading: revisionIds[0] ?? "—",
          lines:
            revisionIds.length > 1
              ? [`+${revisionIds.length - 1} more in chain`, `plan scope ${plan?.revision_scope ?? "—"}`]
              : [`plan scope ${plan?.revision_scope ?? "—"}`],
          stage: "retrieval",
          stage_ms: state.stageMs.retrieval ?? null,
          target: LATENCY_TARGETS_MS.retrieval,
          lit: retrieved.length > 0,
          elapsed: state.seenAt.retrieval ?? null,
        },
      },
      {
        id: "paragraph",
        x: 236,
        y: 132,
        data: {
          kind: "Paragraph",
          heading: `${retrieved.length} retrieved`,
          lines: [
            retrieved
              .slice(0, 4)
              .map((p) => `(${p.label})`)
              .join(" ") || "—",
            state.verification
              ? `verify kept ${state.verification.kept.length} / dropped ${state.verification.dropped.length}`
              : "awaiting verify",
          ],
          stage: "retrieval → verify",
          stage_ms: state.stageMs.verify ?? null,
          target: LATENCY_TARGETS_MS.verify,
          lit: retrieved.length > 0,
          elapsed: state.seenAt.verification ?? state.seenAt.retrieval ?? null,
        },
      },
    ];

    const flowNodes: Node<TraceData>[] = defs.map((d) => ({
      id: d.id,
      type: "trace",
      position: { x: d.x, y: d.y },
      data: d.data,
      draggable: false,
      selectable: false,
      connectable: false,
    }));

    const lit = (id: string) => defs.find((d) => d.id === id)?.data.lit ?? false;
    const edge = (id: string, source: string, target: string, label: string): Edge => ({
      id,
      source,
      target,
      label,
      animated: !reduced && lit(source) && lit(target),
      style: {
        stroke: lit(source) && lit(target) ? "var(--c-accent)" : "var(--c-line)",
        strokeWidth: 1.4,
      },
      labelStyle: { fill: "var(--c-ink-3)", fontSize: 9, letterSpacing: "0.06em" },
      labelBgStyle: { fill: "var(--c-raised)" },
    });

    return {
      nodes: flowNodes,
      edges: [
        edge("e1", "aircraft", "rule", "evaluated by"),
        edge("e2", "rule", "revision", "applies_if"),
        edge("e3", "revision", "paragraph", "has_paragraph"),
      ],
    };
  }, [state, reduced]);

  return (
    <div className="flex flex-col">
      <div className="h-[250px] border-b border-line bg-sunken">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.14 }}
          proOptions={{ hideAttribution: true }}
          nodesDraggable={false}
          nodesConnectable={false}
          panOnDrag
          zoomOnScroll={false}
          minZoom={0.5}
          maxZoom={1.3}
          aria-label="retrieval trace graph"
        >
          <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="var(--c-line)" />
        </ReactFlow>
      </div>
      <dl className="t-mono grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 px-3 py-2 text-ink-3">
        <dt>traversal</dt>
        <dd className="text-ink-2">
          Aircraft &rarr; Rule &rarr; Revision &rarr; Paragraph; edge labels are the contract&rsquo;s
          edge types
        </dd>
        <dt>total</dt>
        <dd className="text-ink-2">
          {state.done ? `${state.done.total_ms} ms` : state.status === "streaming" ? "streaming…" : "—"}
        </dd>
      </dl>
    </div>
  );
}
