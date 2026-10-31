"use client";

/**
 * contract.answer_envelope, on screen.
 *
 * A refusal is a delivered answer, so this renders for REFUSED runs too: the
 * envelope is where "what this does not establish" lives, and that is the half
 * of the product a plausible-sounding answer would have hidden. `limitations` is
 * therefore body text, never a tooltip - an AD that is adopted but not yet
 * effective imposes no obligation today, and the reader has to see that without
 * hovering anything.
 */
import { motion } from "framer-motion";
import type { AnswerStatus } from "@/lib/contract";
import type { AnswerEnvelope } from "@/lib/events";
import { useMotionPrefs } from "@/lib/motion";

interface AnswerEnvelopePanelProps {
  readonly envelope: AnswerEnvelope;
  /**
   * NEED_CONFIG is resolvable by the user. This moves focus to the input for
   * that field on the refusal card; it does not re-ask on its own, because a
   * one-click re-ask would have to put a value in the question, and the only
   * value this panel knows is the rule's own - asserting that would be the UI
   * inventing a fact about the aircraft.
   */
  readonly onFocusMissingInput?: (field: string) => void;
}

const STATUS_WORD: Readonly<Record<AnswerStatus, string>> = {
  ANSWERED: "every drafted sentence survived verification",
  PARTIAL: "part of the question is answered; the rest is withheld",
  REFUSED: "no prose was written — the engine declined to answer",
};

const Row = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <div className="grid grid-cols-1 items-baseline gap-x-2 gap-y-0.5 sm:grid-cols-[112px_minmax(0,1fr)] border-t border-line px-3 py-1.5">
    <span className="t-label !tracking-[0.06em] break-words">{label}</span>
    <div className="t-body min-w-0 text-ink-2">{children}</div>
  </div>
);

export function AnswerEnvelopePanel({ envelope, onFocusMissingInput }: AnswerEnvelopePanelProps) {
  const { dur } = useMotionPrefs();
  const { revision_status: revision, traversal } = envelope;
  const stage = envelope.document_stage.replace(/_/g, " ").toLowerCase();

  return (
    <motion.section
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: dur(220), ease: [0.2, 0.8, 0.2, 1] }}
      aria-label="answer envelope"
      className="m-4 border border-line-strong bg-raised"
    >
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-3 py-2">
        <h3 className="t-mono !text-[13px] font-bold tracking-tight text-ink">
          {envelope.answer_status}
        </h3>
        <span className="t-label !tracking-[0.06em] text-ink-3">
          {STATUS_WORD[envelope.answer_status]}
        </span>
      </header>

      {envelope.limitations.length > 0 ? (
        <div className="border-b border-maybe/40 bg-maybe-bg/40 px-3 py-2.5">
          <p className="t-label mb-1.5 text-maybe">what this answer does not establish</p>
          <ul className="flex flex-col gap-1.5">
            {envelope.limitations.map((limitation) => (
              <li key={limitation} className="t-body border-l-2 border-maybe pl-2 text-ink">
                {limitation}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {envelope.missing_inputs.length > 0 ? (
        <div className="border-b border-line px-3 py-2.5">
          <p className="t-label mb-1.5">what would settle this</p>
          <ul className="flex flex-wrap gap-1.5">
            {envelope.missing_inputs.map((field) => (
              <li key={field}>
                <button
                  type="button"
                  onClick={() => onFocusMissingInput?.(field)}
                  disabled={onFocusMissingInput === undefined}
                  title={`answer the ${field} question on the refusal card`}
                  className="t-mono border border-line-strong bg-sunken px-2 py-1 font-semibold text-ink enabled:hover:border-accent disabled:cursor-default"
                >
                  {field}
                </button>
              </li>
            ))}
          </ul>
          {/*
            Said plainly rather than implied: POST /stream takes a question and a
            tail number, and the applicability stage reads the field values from
            the fleet record. There is no channel for a supplied equipment or
            modification value yet, so re-asking with it stated does not change
            the verdict. Naming that gap is the point of this product; a chip
            that silently did nothing would not be.
          */}
          <p className="t-mono mt-2 text-ink-3">
            A technician can answer this at the aircraft in seconds &mdash; which is why the code is
            NEED_CONFIG and not CANNOT_DETERMINE. Each field above has an input on the refusal card.
            The engine does not yet accept the value: its applicability stage reads these fields from
            the fleet record only, so re-asking with the value stated shows the same verdict until
            that input exists, and your answer is carried in the thread attributed to you.
          </p>
        </div>
      ) : null}

      <Row label="document stage">
        <span className="text-ink">{stage === "" ? "not reported" : stage}</span>
      </Row>

      <Row label="revision">
        <span className="t-mono text-ink">{revision.revision_id ?? "not reported"}</span>
        <span className="t-mono ml-2 text-ink-3">
          {revision.current
            ? "current"
            : `superseded${revision.superseded_by ? ` by ${revision.superseded_by}` : ""}`}
        </span>
      </Row>

      <Row label="applicability">
        <span className="t-mono text-ink">
          {envelope.applicability_result ?? "no decision — no aircraft was resolved"}
        </span>
      </Row>

      <Row label="citations">
        {envelope.citations.length === 0
          ? "none — no sentence survived with a resolving citation"
          : envelope.citations.length === 1
            ? "1 verified sentence, carrying at least one citation resolved in code"
            : `${envelope.citations.length} verified sentences, each carrying at least one citation resolved in code`}
      </Row>

      <Row label="traversal">
        {traversal.outcome === null ? (
          <span>{traversal.reason ?? "not attempted"}</span>
        ) : (
          <>
            <span className="t-mono text-ink">{traversal.outcome}</span>
            {traversal.followed.length > 0 ? (
              <span className="t-mono ml-2 text-ink-3">
                followed {traversal.followed.length}
              </span>
            ) : null}
            {traversal.missing.length > 0 ? (
              <span className="t-mono ml-2 text-maybe">
                missing {traversal.missing.join(", ")}
              </span>
            ) : null}
          </>
        )}
      </Row>
    </motion.section>
  );
}
