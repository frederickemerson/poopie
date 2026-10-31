"use client";

import { useCallback, type KeyboardEvent } from "react";

export interface TabSpec<T extends string> {
  readonly id: T;
  readonly label: string;
  readonly badge?: string;
}

interface TabsProps<T extends string> {
  readonly tabs: readonly TabSpec<T>[];
  readonly active: T;
  readonly onChange: (id: T) => void;
  readonly ariaLabel: string;
  readonly className?: string;
}

/** Roving-tabindex tablist: arrows move, Home/End jump, Enter/Space select. */
export function Tabs<T extends string>({ tabs, active, onChange, ariaLabel, className = "" }: TabsProps<T>) {
  const onKeyDown = useCallback(
    (e: KeyboardEvent<HTMLDivElement>) => {
      const i = tabs.findIndex((t) => t.id === active);
      const go = (n: number) => {
        const next = tabs[(n + tabs.length) % tabs.length];
        if (next) {
          onChange(next.id);
          e.preventDefault();
        }
      };
      if (e.key === "ArrowRight" || e.key === "ArrowDown") go(i + 1);
      if (e.key === "ArrowLeft" || e.key === "ArrowUp") go(i - 1);
      if (e.key === "Home") go(0);
      if (e.key === "End") go(tabs.length - 1);
    },
    [active, onChange, tabs],
  );

  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      onKeyDown={onKeyDown}
      className={`flex items-stretch gap-0 ${className}`}
    >
      {tabs.map((tab) => {
        const selected = tab.id === active;
        return (
          <button
            key={tab.id}
            role="tab"
            type="button"
            id={`tab-${tab.id}`}
            aria-selected={selected}
            aria-controls={`panel-${tab.id}`}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(tab.id)}
            className={[
              "t-label relative px-3 py-2 transition-colors",
              selected ? "text-ink" : "text-ink-3 hover:text-ink-2",
            ].join(" ")}
          >
            {tab.label}
            {tab.badge ? <span className="t-mono ml-1.5 text-ink-3">{tab.badge}</span> : null}
            <span
              aria-hidden
              className={`absolute inset-x-0 bottom-0 h-[2px] ${selected ? "bg-accent" : "bg-transparent"}`}
            />
          </button>
        );
      })}
    </div>
  );
}
