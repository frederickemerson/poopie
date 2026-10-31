"use client";

/**
 * One engine run, folded into view state. Two rules are enforced here rather
 * than in the components, so no component can break them:
 *
 *  1. An answer sentence is exposed only after the `verification` event names it
 *     in `kept`. Nothing unverified ever reaches the answer column.
 *  2. A citation is exposed only if it resolves to a paragraph that was in this
 *     run's retrieved set, which is the contract's citation rule 2.
 */
import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";
import { resolveCitation, type ResolvedCitation } from "./citation";
import type { SseEventName } from "./contract";
import { EVENT_STAGE } from "./events";
import type {
  AnswerDeltaPayload,
  DecisionPayload,
  DonePayload,
  EngineEvent,
  Entity,
  ParagraphNode,
  QueryPlan,
  RefusalPayload,
  VerificationPayload,
} from "./events";
import { openEngineStream } from "./sseClient";

export type RunStatus = "idle" | "streaming" | "settled" | "failed";

export interface EngineState {
  readonly status: RunStatus;
  readonly runId: number;
  readonly query: string;
  readonly entities: readonly Entity[];
  readonly plan: QueryPlan | null;
  readonly planModel: string | null;
  readonly paragraphs: readonly ParagraphNode[];
  readonly scores: Readonly<Record<string, number>>;
  readonly decision: DecisionPayload | null;
  readonly deltas: readonly AnswerDeltaPayload[];
  readonly verification: VerificationPayload | null;
  readonly refusal: RefusalPayload | null;
  readonly done: DonePayload | null;
  readonly failure: string | null;
  readonly stageMs: Readonly<Record<string, number>>;
  /** ms since run start, per event name - drives the retrieval trace. */
  readonly seenAt: Readonly<Partial<Record<SseEventName, number>>>;
}

const EMPTY: EngineState = {
  status: "idle",
  runId: 0,
  query: "",
  entities: [],
  plan: null,
  planModel: null,
  paragraphs: [],
  scores: {},
  decision: null,
  deltas: [],
  verification: null,
  refusal: null,
  done: null,
  failure: null,
  stageMs: {},
  seenAt: {},
};

type Action =
  | { type: "start"; query: string; runId: number }
  | { type: "event"; event: EngineEvent; elapsed: number }
  | { type: "reset" };

function stamp(state: EngineState, event: EngineEvent, elapsed: number): EngineState {
  const seenAt = { ...state.seenAt, [event.event]: elapsed };
  const stageMs =
    "stage_ms" in event.data && typeof event.data.stage_ms === "number"
      ? { ...state.stageMs, [EVENT_STAGE[event.event]]: event.data.stage_ms }
      : state.stageMs;
  return { ...state, seenAt, stageMs };
}

function reducer(state: EngineState, action: Action): EngineState {
  switch (action.type) {
    case "reset":
      return EMPTY;
    case "start":
      return { ...EMPTY, status: "streaming", query: action.query, runId: action.runId };
    case "event": {
      const next = stamp(state, action.event, action.elapsed);
      const { event } = action;
      switch (event.event) {
        case "entities":
          return { ...next, entities: event.data.entities };
        case "query_plan":
          return { ...next, plan: event.data.plan, planModel: event.data.model };
        case "retrieval":
          return { ...next, paragraphs: event.data.paragraphs, scores: event.data.scores };
        case "decision":
          return { ...next, decision: event.data };
        case "answer_delta":
          return { ...next, deltas: [...next.deltas, event.data] };
        case "verification":
          return { ...next, verification: event.data };
        case "refusal":
          return { ...next, refusal: event.data };
        case "done":
          return { ...next, status: "settled", done: event.data };
        case "error":
          return { ...next, status: "failed", failure: event.data.message };
        default:
          return next;
      }
    }
    default:
      return state;
  }
}

export interface VerifiedSentence {
  readonly index: number;
  readonly sentence: string;
  readonly citations: readonly ResolvedCitation[];
  /** Citation ids the engine sent that do not resolve to a retrieved paragraph. */
  readonly unresolved: readonly string[];
}

export interface DroppedSentence {
  readonly index: number;
  readonly reason: string;
}

export interface EngineView extends EngineState {
  /** Verified sentences only. Empty until the verification event lands. */
  readonly answer: readonly VerifiedSentence[];
  /** Reasons only. The dropped text itself is deliberately not exposed. */
  readonly dropped: readonly DroppedSentence[];
  readonly awaitingVerification: readonly AnswerDeltaPayload[];
  readonly answerBlocked: boolean;
}

export function useEngineStream() {
  const [state, dispatch] = useReducer(reducer, EMPTY);
  const cancelRef = useRef<(() => void) | null>(null);
  const startedRef = useRef<number>(0);
  const runRef = useRef<number>(0);

  const stop = useCallback(() => {
    cancelRef.current?.();
    cancelRef.current = null;
  }, []);

  const run = useCallback(
    (params: { query: string; scenario?: string }) => {
      stop();
      runRef.current += 1;
      startedRef.current = performance.now();
      dispatch({ type: "start", query: params.query, runId: runRef.current });
      cancelRef.current = openEngineStream(
        { query: params.query, scenario: params.scenario },
        {
          onEvent: (event) =>
            dispatch({
              type: "event",
              event,
              elapsed: Math.round(performance.now() - startedRef.current),
            }),
          onTransportError: (message) =>
            dispatch({
              type: "event",
              event: { event: "error", data: { message } },
              elapsed: Math.round(performance.now() - startedRef.current),
            }),
        },
      );
    },
    [stop],
  );

  useEffect(() => stop, [stop]);

  const view = useMemo<EngineView>(() => {
    const { verification, deltas, paragraphs, refusal } = state;
    const answer: VerifiedSentence[] = [];
    const dropped: DroppedSentence[] = [];

    if (verification) {
      for (const index of verification.kept) {
        const delta = deltas.find((d) => d.index === index);
        if (!delta) continue;
        const citations: ResolvedCitation[] = [];
        const unresolved: string[] = [];
        for (const id of delta.citation_ids) {
          const hit = resolveCitation(id, paragraphs);
          if (hit) citations.push(hit);
          else unresolved.push(id);
        }
        // Contract rule: every shown sentence carries >=1 resolving citation.
        if (citations.length === 0) {
          dropped.push({
            index,
            reason: "no citation resolved to a paragraph in the retrieved set",
          });
          continue;
        }
        answer.push({ index, sentence: delta.sentence, citations, unresolved });
      }
      for (const index of verification.dropped) {
        dropped.push({
          index,
          reason: verification.drop_reasons[String(index)] ?? "dropped by the verifier",
        });
      }
    }

    const blocked = refusal !== null && answer.length === 0 && verification === null;

    return {
      ...state,
      answer: answer.sort((a, b) => a.index - b.index),
      dropped: dropped.sort((a, b) => a.index - b.index),
      awaitingVerification: verification ? [] : deltas,
      answerBlocked: blocked,
    };
  }, [state]);

  return { state: view, run, stop, reset: () => dispatch({ type: "reset" }) };
}
