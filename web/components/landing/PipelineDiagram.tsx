"use client";

import { useMotionPrefs } from "@/lib/motion";

/**
 * The engine, drawn as the path one question takes through it.
 *
 * This is the landing page's central claim made visible: two model calls at the
 * edges, and everything that decides the answer in plain code between them. The
 * two model stages are drawn dashed and the deciding stages solid, so the thing
 * the product is actually asserting -- the model never decides -- is read off
 * the picture rather than taken on trust from a sentence underneath it.
 *
 * It animates on mount rather than on scroll: it sits in the hero, so there is
 * no scroll event to wait for, and a mount animation cannot leave the picture
 * stuck invisible the way a missed IntersectionObserver can. The keyframes end
 * at the element's natural state, so if animations never run at all -- reduced
 * motion, no CSS animation support -- the diagram is simply there.
 *
 * Drawn as inline SVG rather than React Flow: it is a fixed illustration, not a
 * graph anyone pans, and shipping a graph engine to draw seven boxes would cost
 * more than the whole rest of the page.
 */

interface Stage {
  readonly id: string;
  readonly label: string;
  readonly note: string;
  /** A model writes this stage; everything else is deterministic code. */
  readonly model?: boolean;
}

const STAGES: readonly Stage[] = [
  { id: "q", label: "question", note: "plain English" },
  { id: "plan", label: "query plan", note: "Haiku", model: true },
  { id: "entities", label: "entity pass", note: "regex + table" },
  { id: "retrieval", label: "graph retrieval", note: "FTS5 + dense" },
  { id: "rules", label: "rules engine", note: "applicability" },
  { id: "verify", label: "citation gate", note: "drops uncited" },
  { id: "answer", label: "answer", note: "Sonnet, cited", model: true },
];

const COL = 176;
const BOX_W = 140;
const BOX_H = 56;
const Y = 54;
const WIDTH = COL * (STAGES.length - 1) + BOX_W;
const HEIGHT = 150;

export function PipelineDiagram() {
  const { reduced } = useMotionPrefs();

  return (
    <figure className="flex flex-col gap-3">
      <div className="overflow-x-auto">
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          className="h-auto w-full min-w-[760px]"
          role="img"
          aria-labelledby="pipeline-title pipeline-desc"
        >
          <title id="pipeline-title">How one question is answered</title>
          <desc id="pipeline-desc">
            Seven stages in order: question, query plan written by Claude Haiku, entity
            pass, graph retrieval, rules engine, citation gate, and the final answer
            written by Claude Sonnet. Only the first and last stages involve a language
            model; applicability is decided by the rules engine in between.
          </desc>

          {STAGES.slice(0, -1).map((stage, i) => {
            const x1 = i * COL + BOX_W;
            const x2 = (i + 1) * COL;
            return (
              <line
                key={`edge-${stage.id}`}
                x1={x1}
                y1={Y + BOX_H / 2}
                x2={x2}
                y2={Y + BOX_H / 2}
                stroke="var(--c-line-strong)"
                strokeWidth={1}
                className={reduced ? undefined : "pipe-edge"}
                style={reduced ? undefined : { animationDelay: `${0.12 * i + 0.1}s` }}
              />
            );
          })}

          {STAGES.map((stage, i) => {
            const x = i * COL;
            return (
              <g
                key={stage.id}
                className={reduced ? undefined : "pipe-node"}
                style={reduced ? undefined : { animationDelay: `${0.12 * i}s` }}
              >
                <rect
                  x={x}
                  y={Y}
                  width={BOX_W}
                  height={BOX_H}
                  fill="var(--c-raised)"
                  stroke={stage.model ? "var(--c-accent)" : "var(--c-line-strong)"}
                  strokeWidth={1}
                  strokeDasharray={stage.model ? "3 3" : undefined}
                />
                <text
                  x={x + 12}
                  y={Y + 23}
                  fill="var(--c-ink)"
                  style={{ font: "500 13px var(--font-inter), sans-serif" }}
                >
                  {stage.label}
                </text>
                <text
                  x={x + 12}
                  y={Y + 41}
                  fill="var(--c-ink-3)"
                  style={{ font: "400 11px var(--font-plex-mono), monospace" }}
                >
                  {stage.note}
                </text>
                <text
                  x={x + BOX_W - 12}
                  y={Y - 10}
                  textAnchor="end"
                  fill={stage.model ? "var(--c-accent)" : "var(--c-ink-3)"}
                  style={{
                    font: "500 10px var(--font-plex-mono), monospace",
                    letterSpacing: "0.08em",
                  }}
                >
                  {String(i + 1).padStart(2, "0")}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      <figcaption className="t-caption flex flex-wrap items-center gap-x-4 gap-y-1 text-ink-2">
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="inline-block h-0 w-5 border-t border-dashed border-accent" />
          written by a model
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="inline-block h-0 w-5 border-t border-line-strong" />
          decided by code
        </span>
      </figcaption>
    </figure>
  );
}
