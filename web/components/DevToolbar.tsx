"use client";

import { SCENARIOS, type ScenarioId } from "@/lib/mockStream";
import { useMotionPrefs } from "@/lib/motion";

interface DevToolbarProps {
  readonly active: ScenarioId;
  readonly onReplay: (id: ScenarioId) => void;
  readonly streaming: boolean;
}

const SWITCH =
  "t-label flex items-center gap-1.5 border border-line px-2 py-[5px] text-ink-2 transition-colors hover:border-line-strong hover:text-ink";

/** The judge-facing control strip: replay any scenario, kill motion, flip theme. */
export function DevToolbar({ active, onReplay, streaming }: DevToolbarProps) {
  const { reduced, toggleReduced, theme, toggleTheme } = useMotionPrefs();

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="t-label text-ink-3">replay</span>
      <div className="flex items-stretch border border-line" role="group" aria-label="replay a scenario">
        {SCENARIOS.map((s, i) => {
          const on = s.id === active;
          return (
            <button
              key={s.id}
              type="button"
              onClick={() => onReplay(s.id)}
              aria-pressed={on}
              title={`${s.label} — ${s.watch_for}`}
              className={[
                "t-mono px-2 py-[5px] font-semibold tracking-tight transition-colors",
                i > 0 ? "border-l border-line" : "",
                on ? "bg-accent-dim text-ink" : "text-ink-3 hover:text-ink",
              ].join(" ")}
            >
              {i + 1}
              <span className="t-label ml-1.5 hidden !tracking-[0.06em] lg:inline">
                {s.refusal_code ?? "clean"}
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
