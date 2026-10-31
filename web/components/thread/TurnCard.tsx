"use client";

import { citationLabel, formatReference, referenceOf } from "@/lib/citation";
import type { Turn } from "@/lib/conversationTurn";
import { SuppliedNotice } from "./SuppliedNotice";

interface TurnCardProps {
  readonly turn: Turn;
  readonly index: number;
}

/**
 * A finished turn in the thread.
 *
 * Deliberately quieter than the live turn: the verdict on screen is the newest
 * one, and an earlier answer re-rendered at full weight would compete with it.
 * So the sentences stay at body size, the citations become a static reference
 * line rather than pills, and the proof panels are not repeated - the evidence
 * column belongs to the run that is current.
 *
 * Citations here are shown as the reference the engine composed, not as buttons
 * that open the evidence column, because that column holds the current run's
 * retrieved set. A pill from three turns ago that opened today's paragraphs
 * would be the UI implying a resolution it has not performed.
 *
 * No aria-live, and no aria-busy: only the newest turn is announced. A thread
 * that re-announced itself on every question would be unusable with a reader.
 */
export function TurnCard({ turn, index }: TurnCardProps) {
  const refused = turn.refusal;
  const answered = turn.answer.length > 0;

  return (
    <article
      aria-label={`turn ${index + 1}`}
      className="flex flex-col gap-3 border-b border-line pb-6"
    >
      {/* The question, as the user wrote it, with anything the UI added to it
          shown separately. Never merged: the whole point of showing the carry
          is that the user can see their words were not rewritten. */}
      <header className="flex flex-col gap-1.5">
        <p className="t-label">you asked</p>
        <p className="t-subhead text-ink">{turn.asked}</p>
        {turn.carried ? (
          <p className="t-mono text-ink-3">
            carried forward into the question: {turn.carried}
          </p>
        ) : null}
      </header>

      {turn.supplied.length > 0 ? (
        <SuppliedNotice supplied={turn.supplied} placement="archived" />
      ) : null}

      {refused ? (
        <div className="border-l-2 border-accent pl-3">
          <p className="t-mono font-bold text-accent">{refused.code}</p>
          <p className="t-body text-ink">
            {typeof refused.detail === "string"
              ? refused.detail
              : refused.resolvable_by}
          </p>
          {turn.withheldCount > 0 ? (
            <p className="t-mono mt-1 text-ink-3">
              {turn.withheldCount} verified sentence
              {turn.withheldCount === 1 ? "" : "s"} withheld by {turn.withheldBy}
            </p>
          ) : null}
        </div>
      ) : null}

      {answered ? (
        <div className="flex flex-col gap-2">
          {turn.answer.map((sentence) => (
            <div key={sentence.index} className="flex flex-col gap-1">
              <p className="t-body text-ink">{sentence.sentence}</p>
              <ul className="flex flex-col gap-0.5">
                {sentence.citations.map((citation) => {
                  const reference = referenceOf(citation);
                  return (
                    <li key={citation.id} className="t-mono text-ink-3">
                      {reference
                        ? formatReference(reference)
                        : citationLabel(citation.ref)}
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>
      ) : null}

      {/* An archived listing is summarised, not redrawn. The thread keeps the
          bounds the rows were read under - a top-N of this corpus, ending at
          its own last publication date - because that is the part a reader
          scrolling back could otherwise mistake for a live feed. */}
      {turn.listing ? (
        <div className="border-l-2 border-line-strong pl-3">
          <p className="t-body text-ink">
            A listing of the {turn.listing.rows.length} most recently published{" "}
            {turn.listing.rows.length === 1 ? "directive" : "directives"} in this corpus, which
            runs to {turn.listing.corpus_latest} and holds{" "}
            <span className="t-figure">{turn.listing.total_available.toLocaleString()}</span> in
            all.
          </p>
          {turn.listing.rows.length > 0 ? (
            <p className="t-mono mt-1 break-words text-ink-3">
              {turn.listing.rows.map((row) => row.ad_number).join(" · ")}
            </p>
          ) : null}
        </div>
      ) : null}

      {!answered && !refused && turn.decisionUnavailable ? (
        <p className="t-body border-l-2 border-line-strong pl-3 text-ink">
          {turn.decisionUnavailable}
        </p>
      ) : null}

      {turn.failure ? (
        <p className="t-mono border border-line-strong px-3 py-2 text-ink-2">
          stream error: {turn.failure}
        </p>
      ) : null}

      {!answered && !refused && !turn.listing && !turn.decisionUnavailable && !turn.failure ? (
        <p className="t-mono text-ink-3">no answer prose was shown for this turn.</p>
      ) : null}
    </article>
  );
}
