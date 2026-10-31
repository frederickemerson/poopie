"use client";

import { ENGINE_SOURCES, SOURCE_LABEL, type EngineSource } from "@/lib/engineSource";
import { liveDemo } from "@/lib/liveDemos";
import { SCENARIOS, type ScenarioId } from "@/lib/mockStream";
import { useMotionPrefs } from "@/lib/motion";

interface DevToolbarProps {
  readonly active: ScenarioId;
  readonly onReplay: (id: ScenarioId) => void;
  readonly streaming: boolean;
  readonly source: EngineSource;
  readonly onSourceChange: (source: EngineSource) => void;
}

const SWITCH =
  "t-label flex items-center gap-1.5 border border-line px-2 py-[5px] text-ink-2 transition-colors hover:border-line-strong hover:text-ink";

/**
 * The judge-facing control strip: pick the engine, run any demo question, kill
 * motion, flip theme.
 *
 * The source switch is deliberately prominent. Everything on screen means
 * something different depending on which engine produced it, so the control
 * that decides that cannot be hidden.
 */
export function DevToolbar({
  active,
  onReplay,
  streaming,
  source,
  onSourceChange,
}: DevToolbarProps) {
  const { reduced, toggleReduced, theme, toggleTheme } = useMotionPrefs();

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="flex items-stretch border border-line" role="group" aria-label="engine source">
        {ENGINE_SOURCES.map((s, i) => (
          <button
            key={s}
            type="button"
            onClick={() => onSourceChange(s)}
            aria-pressed={s === source}
            title={
              s === "engine"
                ? "run questions against the FastAPI engine"
                : "replay a recorded scenario — the fallback if the engine dies mid-demo"
            }
            className={[
              "t-label px-2 py-[5px] transition-colors",
              i > 0 ? "border-l border-line" : "",
              s === source ? "bg-accent-dim text-ink" : "text-ink-3 hover:text-ink",
            ].join(" ")}
          >
            {SOURCE_LABEL[s]}
          </button>
        ))}
      </div>

      <span className="t-label text-ink-3">{source === "engine" ? "ask" : "replay"}</span>
      <div className="flex items-stretch border border-line" role="group" aria-label="run a demo question">
        {SCENARIOS.map((s, i) => {
          const on = s.id === active;
          const demo = liveDemo(s.id);
          const label = source === "engine" ? demo.observed_refusal : s.refusal_code;
          return (
            <button
              key={s.id}
              type="button"
              onClick={() => onReplay(s.id)}
              aria-pressed={on}
              title={source === "engine" ? `${demo.label} — ${demo.watch_for}` : `${s.label} — ${s.watch_for}`}
              className={[
                "t-mono px-2 py-[5px] font-semibold tracking-tight transition-colors",
                i > 0 ? "border-l border-line" : "",
                on ? "bg-accent-dim text-ink" : "text-ink-3 hover:text-ink",
              ].join(" ")}
            >
              {i + 1}
              <span className="t-label ml-1.5 hidden !tracking-[0.06em] lg:inline">
                {label ?? "decided"}
              </span>
            </button>
          );
        })}
      </div>
      <button type="button" onClick={() => onReplay(active)} className={SWITCH} title="replay the current scenario">
        <span aria-hidden>{streaming ? "■" : "▶"}</span>
        {streaming ? "streaming" : "run"}
      </button>
      <button
        type="button"
        onClick={toggleReduced}
        aria-pressed={reduced}
        className={`${SWITCH} ${reduced ? "!border-accent !text-ink" : ""}`}
        title="disable every transition and keyframe"
      >
        <span aria-hidden>{reduced ? "◉" : "○"}</span>
        motion {reduced ? "off" : "on"}
      </button>
      <button type="button" onClick={toggleTheme} className={SWITCH} title="switch theme">
        <span aria-hidden>{theme === "dark" ? "◑" : "◐"}</span>
        {theme}
      </button>
    </div>
  );
}
