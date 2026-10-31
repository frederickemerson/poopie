"use client";

import type { SuppliedFact } from "@/lib/conversation";

interface SuppliedNoticeProps {
  readonly supplied: readonly SuppliedFact[];
  /**
   * "live" sits above a streaming answer and warns before it is read; "archived"
   * sits inside a finished turn and keeps the attribution attached to it.
   */
  readonly placement?: "live" | "archived";
}

/**
 * What the user told the engine, attributed to the user.
 *
 * This exists because of one rule: text a person supplies must never be able to
 * read as though it came from the corpus. Every surface that can show an answer
 * resting on a supplied value shows this block above it, with the words
 * verbatim and the source named - not a tooltip, not a footnote, and not a
 * neutral "context" label that leaves the reader to guess who said it.
 *
 * It is drawn in the caution colour rather than in ember, because this is not a
 * refusal: it is a caveat on an answer, which is the same thing the envelope's
 * limitations are.
 */
export function SuppliedNotice({ supplied, placement = "live" }: SuppliedNoticeProps) {
  if (supplied.length === 0) return null;
  return (
    <section
      aria-label="values you supplied"
      className="border border-maybe/60 bg-maybe-bg/40"
    >
      <p className="t-label border-b border-maybe/40 px-3 py-1.5 text-maybe">
        supplied by you &middot; not from the corpus
      </p>
      <ul className="flex flex-col">
        {supplied.map((fact, i) => (
          <li
            key={`${fact.label}-${i}`}
            className="grid grid-cols-[1fr] gap-1 border-b border-maybe/25 px-3 py-2 last:border-b-0 sm:grid-cols-[132px_1fr] sm:gap-2"
          >
            <span className="t-mono text-ink-2">{fact.label}</span>
            <span className="t-body text-ink">
              {fact.kind === "document" ? `“${fact.text}”` : fact.text}
            </span>
          </li>
        ))}
      </ul>
      {placement === "live" ? (
        <p className="t-mono border-t border-maybe/40 px-3 py-1.5 text-ink-2">
          Anything below that rests on {supplied.length === 1 ? "this" : "these"} rests on your word,
          not on a retrieved paragraph.
        </p>
      ) : null}
    </section>
  );
}
