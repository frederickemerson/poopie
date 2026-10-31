/**
 * One finished turn, frozen.
 *
 * `useEngineStream` holds exactly one run: starting another resets it. The
 * thread therefore keeps its own copies, taken at the moment a new question is
 * asked, so an earlier answer stays readable with the citations it was actually
 * decided on rather than being re-resolved against a later run's retrieved set.
 *
 * A turn is a snapshot, not a view onto live state: everything it needs is
 * copied in, including the user-supplied facts the answer rested on.
 */
import type { RefusalCode } from "./contract";
import type { AnswerEnvelope, ListingPayload, QueryPlan, RefusalPayload } from "./events";
import type { CarriedContext, SuppliedFact } from "./conversation";
import { contextFromPlan } from "./conversation";
import type { DroppedSentence, EngineView, VerifiedSentence } from "./useEngineStream";

export interface Turn {
  readonly id: number;
  /** The user's own words. */
  readonly asked: string;
  /** Restated subject appended to make the question self-contained, if any. */
  readonly carried: string | null;
  /** The full text the engine was sent. */
  readonly question: string;
  readonly supplied: readonly SuppliedFact[];
  readonly answer: readonly VerifiedSentence[];
  readonly dropped: readonly DroppedSentence[];
  /** The corpus listing this turn answered with, if it answered with one. */
  readonly listing: ListingPayload | null;
  readonly refusal: RefusalPayload | null;
  readonly withheldBy: RefusalCode | null;
  readonly withheldCount: number;
  readonly decisionUnavailable: string | null;
  readonly envelope: AnswerEnvelope | null;
  readonly failure: string | null;
  readonly plan: QueryPlan | null;
  /** The subject a later follow-up can carry forward from this turn. */
  readonly context: CarriedContext;
}

/** Did this run put anything on screen that is worth keeping in the thread? */
export function hasOutcome(state: EngineView): boolean {
  return (
    state.answer.length > 0 ||
    state.deltas.length > 0 ||
    state.listing !== null ||
    state.refusal !== null ||
    state.decisionUnavailable !== null ||
    state.failure !== null ||
    state.done !== null
  );
}

/**
 * Freeze the run on screen into a thread entry. Returns null when the run never
 * produced an outcome - an abandoned question is not a turn, and archiving one
 * would fill the thread with empty cards.
 */
export function snapshotTurn(
  state: EngineView,
  asked: string,
  carried: string | null,
  supplied: readonly SuppliedFact[],
): Turn | null {
  if (!hasOutcome(state)) return null;
  return {
    id: state.runId,
    asked: asked.trim() === "" ? state.query : asked,
    carried,
    question: state.query,
    supplied,
    answer: state.answer,
    dropped: state.dropped,
    listing: state.listing,
    refusal: state.refusal,
    withheldBy: state.answerWithheldBy,
    withheldCount: state.withheldCount,
    decisionUnavailable: state.decisionUnavailable,
    envelope: state.done?.envelope ?? null,
    failure: state.failure,
    plan: state.plan,
    context: contextFromPlan(state.plan),
  };
}

/**
 * The subject the next question should carry. The newest turn that named one
 * wins: a follow-up is about what was just discussed, and a turn that resolved
 * no AD (a refused or out-of-scope one) must not erase the subject the turn
 * before it established.
 */
export function threadContext(turns: readonly Turn[]): CarriedContext {
  let adNumber: string | null = null;
  let tailNumber: string | null = null;
  for (let i = turns.length - 1; i >= 0; i -= 1) {
    const turn = turns[i];
    if (!turn) continue;
    adNumber ??= turn.context.adNumber;
    tailNumber ??= turn.context.tailNumber;
    if (adNumber !== null && tailNumber !== null) break;
  }
  return { adNumber, tailNumber };
}
