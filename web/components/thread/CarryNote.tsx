"use client";

import type { CarriedContext } from "@/lib/conversation";

interface CarryNoteProps {
  /** What a follow-up would carry: only the parts the question lacks. */
  readonly carry: CarriedContext;
  readonly enabled: boolean;
  readonly onToggle: (next: boolean) => void;
}

/**
 * What the next question will say that the user did not type.
 *
 * The engine is stateless: it reads the question and nothing else, so a
 * follow-up like "when is it due?" has to restate its own subject. That
 * restatement is shown here, before it is sent, with a switch to turn it off -
 * because the alternative is editing someone's words behind their back, which
 * in a system whose whole claim is traceability would be the worst possible
 * place to be quietly helpful.
 */
export function CarryNote({ carry, enabled, onToggle }: CarryNoteProps) {
  const parts = [
    carry.adNumber === null ? null : `AD ${carry.adNumber}`,
    carry.tailNumber === null ? null : carry.tailNumber,
  ].filter((part): part is string => part !== null);

  if (parts.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <p className="t-mono text-ink-2">
        {enabled ? "carrying forward into your next question:" : "not carrying forward:"}{" "}
        <span className={enabled ? "text-ink" : "text-ink-3 line-through decoration-1"}>
          {parts.join(" · ")}
        </span>
      </p>
      <label className="t-label flex cursor-pointer items-center gap-1.5 text-ink-2">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(event) => onToggle(event.target.checked)}
          className="size-3.5 shrink-0 accent-[var(--c-accent)]"
        />
        carry the subject forward
      </label>
    </div>
  );
}
