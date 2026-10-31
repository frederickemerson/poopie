"use client";

/**
 * The engine's health, on screen.
 *
 * A demo failure should be legible: the strip names the service, says whether
 * the corpus and the retrieval index are loaded, and says whether the LLM is
 * live or offline. It is greyscale plus the non-semantic accent, because green,
 * red and amber belong to the three enums.decision outcomes and nothing else.
 */
import { useState } from "react";
import type { HealthStatus, HealthView } from "@/lib/useBackendHealth";

const GLYPH: Readonly<Record<HealthStatus, string>> = {
  probing: "◌",
  ready: "●",
  degraded: "◍",
  unreachable: "○",
};

const WORD: Readonly<Record<HealthStatus, string>> = {
  probing: "probing",
  ready: "engine up",
  degraded: "engine degraded",
  unreachable: "engine down",
};

function Flag({ label, on, offWord }: { label: string; on: boolean; offWord: string }) {
  return (
    <span className="t-mono whitespace-nowrap text-ink-3">
      {label}{" "}
      <span className={on ? "font-semibold text-ink-2" : "font-semibold text-accent"}>
        {on ? "loaded" : offWord}
      </span>
    </span>
  );
}

export function BackendStatus({ health, status, checkedAt, refresh }: HealthView) {
  const [open, setOpen] = useState(false);
  const llm = health?.llm ?? null;
  const detail = health?.error ?? null;

  return (
    <div className="relative flex flex-wrap items-center gap-x-3 gap-y-1">
      <button
        type="button"
        onClick={() => {
          setOpen((v) => !v);
          refresh();
        }}
        aria-expanded={open}
        title={
          detail ??
          `${health?.origin ?? "engine"}${
            checkedAt === null ? "" : ` · checked ${new Date(checkedAt).toLocaleTimeString()}`
          }`
        }
        className={[
          "t-label flex items-center gap-1.5 border px-2 py-[5px] transition-colors",
          status === "ready"
            ? "border-line text-ink-2 hover:border-line-strong hover:text-ink"
            : "border-accent text-ink",
        ].join(" ")}
      >
        <span aria-hidden>{GLYPH[status]}</span>
        <span>{WORD[status]}</span>
      </button>

      {status === "unreachable" || status === "probing" ? null : (
        <>
          <Flag label="corpus" on={health?.corpus_loaded === true} offWord="not loaded" />
          <Flag label="index" on={health?.index_loaded === true} offWord="not loaded" />
          <span className="t-mono whitespace-nowrap text-ink-3">
            llm{" "}
            <span className={llm === "live" ? "font-semibold text-ink-2" : "font-semibold text-accent"}>
              {llm ?? "unreported"}
            </span>
          </span>
        </>
      )}

      {open ? (
        <div
          role="status"
          className="absolute right-0 top-full z-30 mt-1 w-[320px] border border-line-strong bg-raised p-3 shadow-lg"
        >
          <p className="t-label mb-1.5">engine health · GET /health</p>
          <dl className="t-mono grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-ink-3">
            <dt>service</dt>
            <dd className="truncate text-ink-2">{health?.origin ?? "unknown"}</dd>
            <dt>reachable</dt>
            <dd className="text-ink-2">{health?.reachable === true ? "yes" : "no"}</dd>
            <dt>corpus</dt>
            <dd className="text-ink-2">{String(health?.corpus_loaded ?? "unreported")}</dd>
            <dt>index</dt>
            <dd className="text-ink-2">{String(health?.index_loaded ?? "unreported")}</dd>
            <dt>llm</dt>
            <dd className="text-ink-2">{llm ?? "unreported"}</dd>
            {health?.spend ? (
              <>
                <dt>spend</dt>
                <dd className="text-ink-2">
                  ${(health.spend.spent_usd ?? 0).toFixed(4)} of ${health.spend.cap_usd ?? 0} ·{" "}
                  {health.spend.calls ?? 0} calls
                </dd>
              </>
            ) : null}
            <dt>checked</dt>
            <dd className="text-ink-2">
              {checkedAt === null ? "—" : new Date(checkedAt).toLocaleTimeString()}
            </dd>
          </dl>
          {detail ? <p className="t-body mt-2 border-t border-line pt-2 text-accent">{detail}</p> : null}
          {llm !== null && llm !== "live" ? (
            <p className="t-body mt-2 border-t border-line pt-2 text-ink-2">
              With the model offline the query-plan stage is skipped, so the plan panel stays empty.
              Entity extraction, retrieval and the rules engine are pure code and keep working.
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
