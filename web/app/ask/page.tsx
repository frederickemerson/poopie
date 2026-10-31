"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { BlastRadius } from "@/components/blast/BlastRadius";
import { ReplayNotice } from "@/components/ReplayNotice";
import { BackendStatus } from "@/components/BackendStatus";
import { AnswerEnvelopePanel } from "@/components/centre/AnswerEnvelopePanel";
import { AnswerStream } from "@/components/centre/AnswerStream";
import { RefusalCard } from "@/components/centre/RefusalCard";
import type { FocusRequest } from "@/components/centre/RefusalResolver";
import { SupersededBanner } from "@/components/centre/SupersededBanner";
import { DevToolbar } from "@/components/DevToolbar";
import { EntityChips } from "@/components/left/EntityChips";
import { PlanPanel } from "@/components/left/PlanPanel";
import { QueryBar } from "@/components/left/QueryBar";
import { LatencyBadges } from "@/components/LatencyBadges";
import { EvidenceTabs, type EvidenceTabId } from "@/components/right/EvidenceTabs";
import { CarryNote } from "@/components/thread/CarryNote";
import { SuppliedNotice } from "@/components/thread/SuppliedNotice";
import { Thread } from "@/components/thread/Thread";
import { Disclosure } from "@/components/ui/Disclosure";
import { Tabs } from "@/components/ui/Tabs";
import type { BlastRevisionRef } from "@/lib/blast";
import { resolveCitation, type ResolvedCitation } from "@/lib/citation";
import { CONTRACT_VERSION } from "@/lib/contract";
import {
  contextFromPlan,
  decisionSubject,
  followUp,
  missingFields,
  missingFromQuestion,
  NO_CONTEXT,
  type AskIntent,
  type SuppliedFact,
} from "@/lib/conversation";
import { snapshotTurn, threadContext, type Turn } from "@/lib/conversationTurn";
import { findAd, revisionForAdNumber } from "@/lib/corpus";
import {
  DEFAULT_ENGINE_SOURCE,
  readStoredEngineSource,
  storeEngineSource,
  type EngineSource,
} from "@/lib/engineSource";
import { isProofTreeUnavailable } from "@/lib/events";
import { LIVE_DEMOS, liveDemo, tailNumberIn } from "@/lib/liveDemos";
import { DEFAULT_SCENARIO_ID, scenario, type ScenarioId } from "@/lib/mockStream";
import { useBackendHealth } from "@/lib/useBackendHealth";
import { useEngineStream } from "@/lib/useEngineStream";

type Workspace = "workspace" | "blast";

/** The question for a demo slot, under whichever engine is selected. */
function demoQuestion(source: EngineSource, id: ScenarioId): { query: string; tail: string | null } {
  if (source === "engine") {
    const demo = liveDemo(id);
    return { query: demo.query, tail: demo.tail_number };
  }
  return { query: scenario(id).query, tail: null };
}

export default function Page() {
  const { state, run } = useEngineStream();
  const health = useBackendHealth();
  const [source, setSource] = useState<EngineSource>(DEFAULT_ENGINE_SOURCE);
  const [scenarioId, setScenarioId] = useState<ScenarioId>(DEFAULT_SCENARIO_ID);
  // Empty. The page opens on a question nobody has asked yet, and the only
  // text that ever reaches the engine is text the reader put there: a composer
  // arriving pre-filled reads as an answer already in waiting, and invites the
  // reader to press ask on a question that was not theirs.
  const [query, setQuery] = useState<string>("");
  const [typeIn, setTypeIn] = useState<{ text: string; nonce: number } | null>(null);
  const [workspace, setWorkspace] = useState<Workspace>("workspace");
  const [evidenceTab, setEvidenceTab] = useState<EvidenceTabId>("proof");
  const [citation, setCitation] = useState<ResolvedCitation | null>(null);
  const [focusRevisionId, setFocusRevisionId] = useState<string | null>(null);
  // Revisions the engine itself surfaced, newest first. The blast grid may only
  // be asked about one of these, so it can never show a revision no run read.
  const [revisions, setRevisions] = useState<readonly BlastRevisionRef[]>([]);

  /* ------------------------------------------------------------ the thread --
     The engine holds no conversation: `useEngineStream` keeps exactly one run
     and a new question resets it. So the thread is kept here, as snapshots
     taken at the moment the next question is asked. That ordering is what
     makes the archive honest -- an earlier turn keeps the citations it was
     actually decided on rather than being re-resolved against a later run. */
  const [turns, setTurns] = useState<readonly Turn[]>([]);
  /** The user's own words for the run on screen, before anything was appended. */
  const [liveAsked, setLiveAsked] = useState("");
  const [liveCarried, setLiveCarried] = useState<string | null>(null);
  const [liveSupplied, setLiveSupplied] = useState<readonly SuppliedFact[]>([]);
  const [carryEnabled, setCarryEnabled] = useState(true);
  const [focusRequest, setFocusRequest] = useState<FocusRequest | null>(null);

  // The stored engine choice is read after mount, not during render: the
  // server has no localStorage, and reading it during render would make the
  // first client paint disagree with the server's.
  useEffect(() => {
    setSource(readStoredEngineSource());
  }, []);

  /**
   * The one way a question reaches the engine.
   *
   * It archives whatever is on screen first, then starts the run, so the
   * thread grows by exactly one entry per question and the live turn is never
   * rendered twice. The question text is passed through explicitly rather than
   * read back out of `query` state, because a resolver can hand over several
   * hundred characters of pasted document text and waiting a render for state
   * to settle would send the previous question.
   */
  const ask = useCallback(
    (intent: AskIntent) => {
      const text = intent.question.trim();
      if (text === "") return;

      setTurns((prev) => {
        const archived = snapshotTurn(state, liveAsked, liveCarried, liveSupplied);
        return archived === null ? prev : [...prev, archived];
      });

      setLiveAsked(intent.asked);
      setLiveCarried(intent.carried);
      setLiveSupplied(intent.supplied);
      // The composer empties: the question is now in the thread above it, where
      // it can be read and copied, and a follow-up should not have to clear the
      // last question out of the box before it can be typed.
      setQuery("");
      setCitation(null);
      setFocusRequest(null);

      if (source === "mock") {
        const demo = demoQuestion(source, scenarioId);
        const edited = text !== demo.query.trim();
        run(edited ? { query: text, source } : { query: text, source, scenario: scenarioId });
        return;
      }
      const demo = demoQuestion(source, scenarioId);
      const edited = text !== demo.query.trim();
      run({
        query: text,
        source,
        tailNumber: edited ? tailNumberIn(text) : demo.tail,
      });
    },
    [liveAsked, liveCarried, liveSupplied, run, scenarioId, source, state],
  );

  const start = useCallback(
    (nextSource: EngineSource, id: ScenarioId) => {
      const { query: text } = demoQuestion(nextSource, id);
      setScenarioId(id);
      setFocusRevisionId(null);
      setEvidenceTab("proof");
      setWorkspace("workspace");
      setTypeIn({ text, nonce: Date.now() });
    },
    [],
  );

  const replay = useCallback((id: ScenarioId) => start(source, id), [source, start]);

  const changeSource = useCallback(
    (next: EngineSource) => {
      setSource(next);
      storeEngineSource(next);
      setRevisions([]);
      // A thread of answers from the other engine would be a thread about a
      // different corpus. It is dropped rather than left to look continuous.
      setTurns([]);
      setLiveAsked("");
      setLiveCarried(null);
      setLiveSupplied([]);
      setQuery("");
    },
    [],
  );

  /**
   * What a contextless follow-up would restate, given everything asked so far.
   *
   * The run on screen comes first and the archive second: a turn only enters
   * `turns` when the next question is asked, so reading the archive alone would
   * carry the subject of the turn before last.
   */
  const context = useMemo(() => {
    const live = contextFromPlan(state.plan);
    const prior = threadContext(turns);
    return {
      adNumber: live.adNumber ?? prior.adNumber,
      tailNumber: live.tailNumber ?? prior.tailNumber,
    };
  }, [state.plan, turns]);
  const carry = useMemo(
    () => (carryEnabled ? missingFromQuestion(query, context) : NO_CONTEXT),
    [carryEnabled, context, query],
  );

  /**
   * The composer. A follow-up is made self-contained before it is sent.
   *
   * `text` is supplied by the type-in path, which sets the value and submits in
   * one tick; falling back to `query` state there would send the question one
   * character short.
   */
  const submit = useCallback(
    (text?: string) => {
      const asked = (text ?? query).trim();
      // Enter in an empty box must not send the carried subject on its own: a
      // bare "This is about AD 2026-20-10." is not a question.
      if (asked === "") return;
      ask(followUp(asked, carryEnabled ? context : NO_CONTEXT));
    },
    [ask, carryEnabled, context, query],
  );

  // Collect every revision the engine named, so blast radius has somewhere real
  // to point. The decided one goes first: it is the one with a proof behind it.
  useEffect(() => {
    const tree = state.decision?.proof_tree ?? null;
    const decided = tree && !isProofTreeUnavailable(tree) ? (tree.revision_id ?? null) : null;
    const seen = new Map<string, BlastRevisionRef>();
    for (const paragraph of state.paragraphs) {
      if (seen.has(paragraph.revision_id)) continue;
      seen.set(paragraph.revision_id, {
        revision_id: paragraph.revision_id,
        ad_number: paragraph.ad_number ?? null,
        decided: paragraph.revision_id === decided,
      });
    }
    if (seen.size === 0) return;
    setRevisions((prev) => {
      const merged = new Map(prev.map((r) => [r.revision_id, r]));
      for (const [id, ref] of seen) {
        const existing = merged.get(id);
        merged.set(id, {
          revision_id: id,
          ad_number: ref.ad_number ?? existing?.ad_number ?? null,
          decided: ref.decided || existing?.decided === true,
        });
      }
      return [...merged.values()].sort((a, b) => Number(b.decided) - Number(a.decided));
    });
  }, [state.decision, state.paragraphs]);

  const ad = useMemo(() => findAd(state.plan?.ad_number ?? null), [state.plan]);
  const askedRevision = useMemo(
    () => (ad ? revisionForAdNumber(ad, state.plan?.ad_number ?? null) : null),
    [ad, state.plan],
  );
  const resolve = useCallback(
    (id: string) => resolveCitation(id, state.paragraphs),
    [state.paragraphs],
  );

  const superseded =
    state.refusal?.code === "SUPERSEDED" &&
    typeof state.refusal.detail !== "string" &&
    "superseded_warning" in state.refusal.detail
      ? state.refusal.detail.superseded_warning
      : null;
  const blockingRefusal = state.refusal && !superseded ? state.refusal : null;

  const tree = state.decision?.proof_tree ?? null;
  const externalDocuments =
    tree && !isProofTreeUnavailable(tree) ? (tree.external_documents ?? []) : [];

  const subjectLabel =
    state.plan?.aircraft.tail_number ?? state.plan?.aircraft.model ?? null;

  const openCurrentRevision = useCallback((revisionId: string) => {
    setFocusRevisionId(revisionId);
    setEvidenceTab("revisions");
  }, []);

  /**
   * The fields the engine itself named as unanswerable from the fleet record,
   * each paired with the rule it could not evaluate. Taken from
   * `decision.unknown_fields` rather than inferred from amber proof rows: the
   * contract already distinguishes "the user can clear this" from "a human has
   * to read the clause", and re-deriving it from the tree would lose that.
   */
  const missing = useMemo(
    () => missingFields(state.decision, state.refusal),
    [state.decision, state.refusal],
  );
  const decidedAircraft = useMemo(() => decisionSubject(state.decision), [state.decision]);

  const focusMissingInput = useCallback((field: string) => {
    setFocusRequest({ field, nonce: Date.now() });
  }, []);

  const envelope = state.done?.envelope ?? null;

  // Is there anything to read yet? The composer is the whole page until there
  // is, and a quiet strip under the thread once there is -- the question stays
  // the thing you act on either way.
  const hasResult =
    state.answer.length > 0 ||
    state.deltas.length > 0 ||
    state.refusal !== null ||
    state.decisionUnavailable !== null ||
    state.paragraphs.length > 0 ||
    state.status === "streaming";

  const streaming = state.status === "streaming";

  /** Changes as the live turn gains content, so the thread can re-pin scroll. */
  const liveKey =
    state.runId * 1_000 + state.answer.length + state.deltas.length + (state.refusal ? 1 : 0);

  const suggestions = useMemo(
    () => LIVE_DEMOS.slice(0, 3).map((d) => d.query),
    [],
  );

  // Quoted only when the engine reported it. A page that states a corpus size
  // of its own would keep stating it after the next ingest changed it.
  const corpusBlurb = useMemo(() => {
    const c = health.health?.corpus;
    if (!c?.ad_numbers || !c.federal_register_pages) return "";
    return `It reads ${c.ad_numbers.toLocaleString()} airworthiness directives across ${c.federal_register_pages.toLocaleString()} Federal Register pages.`;
  }, [health.health?.corpus]);

  /**
   * A suggestion fills the composer and stops there. It never submits: the
   * reader presses ask, and can edit the question first. Whatever is in the box
   * at that moment is what is asked - a suggestion is a starting point, not a
   * question the page asks on the reader's behalf.
   */
  const fillComposer = useCallback((question: string) => {
    setQuery(question);
  }, []);

  const showThread = turns.length > 0 || hasResult;

  return (
    <>
      <a
        href="#answer"
        className="t-label sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:border focus:border-accent focus:bg-raised focus:px-3 focus:py-2 focus:text-ink"
      >
        Skip to the newest answer
      </a>
      <main className="flex min-h-dvh flex-col bg-bg lg:h-dvh lg:overflow-hidden">
        <header className="shrink-0 border-b border-line bg-raised">
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2">
            <div className="flex items-baseline gap-2.5">
              <span className="t-mono !text-[15px] font-bold tracking-[-0.02em] text-ink">
                poopie
              </span>
              <span className="t-label">airworthiness directive answer engine</span>
            </div>
            <div className="ml-auto flex flex-wrap items-center gap-x-4 gap-y-2">
              {source === "engine" ? <BackendStatus {...health} /> : null}
              <Tabs
                tabs={[
                  { id: "workspace", label: "answer" },
                  {
                    id: "blast",
                    label: "fleet",
                    badge: source === "engine" ? "live fleet" : "86 aircraft",
                  },
                ]}
                active={workspace}
                onChange={setWorkspace}
                ariaLabel="view"
              />
            </div>
          </div>
        </header>

        {source === "mock" ? <ReplayNotice /> : null}

        {workspace === "blast" ? (
          <BlastRadius
            source={source}
            revisions={revisions}
            preferredAdNumber={ad?.ad_number ?? null}
          />
        ) : (
          <div className="flex flex-1 flex-col lg:grid lg:min-h-0 lg:grid-cols-[minmax(0,1fr)_404px]">
            {/* The thread, at a width prose can be read at. */}
            <div className="flex flex-col lg:min-h-0">
              {!showThread ? (
                <div className="flex-1 lg:min-h-0 lg:overflow-y-auto">
                  <div className="mx-auto w-full max-w-[74ch] px-4 py-6 lg:px-8 lg:py-10">
                    <div className="flex flex-col gap-6">
                      <div className="flex flex-col gap-2">
                        <h1 className="t-heading text-ink">
                          What do you want to know today?
                        </h1>
                        <p className="t-body max-w-[58ch] text-ink-2">
                          Which directives apply, what you must do, and by when — ask in plain
                          English, then keep asking. {corpusBlurb} The answer is decided by a
                          rules engine, never by the language model, and every sentence carries a
                          citation you can open.
                        </p>
                      </div>
                      <QueryBar
                        value={query}
                        onChange={setQuery}
                        onSubmit={submit}
                        // `showThread` is false here, and it is true whenever
                        // the run is streaming, so the hero is never the
                        // streaming state. TypeScript narrows this for us.
                        streaming={false}
                        typeIn={typeIn}
                        variant="hero"
                        suggestions={suggestions}
                        onPick={fillComposer}
                      />
                    </div>
                  </div>
                </div>
              ) : (
                <Thread turns={turns} liveKey={liveKey} askKey={state.runId}>
                  {/* The live turn. The only one that is announced. */}
                  <div className="flex flex-col gap-5">
                    {liveAsked ? (
                      <header className="flex flex-col gap-1.5">
                        <p className="t-label">you asked</p>
                        <p className="t-subhead text-ink">{liveAsked}</p>
                        {liveCarried ? (
                          <p className="t-mono text-ink-3">
                            carried forward into the question: {liveCarried}
                          </p>
                        ) : null}
                      </header>
                    ) : null}

                    {/* Above everything it could possibly support, so no
                        sentence resting on it can be read first. */}
                    <SuppliedNotice supplied={liveSupplied} placement="live" />

                    {superseded ? (
                      <SupersededBanner
                        detail={superseded}
                        onOpenCurrent={openCurrentRevision}
                      />
                    ) : null}

                    {blockingRefusal ? (
                      <RefusalCard
                        refusal={blockingRefusal}
                        paragraphs={state.paragraphs}
                        externalDocuments={externalDocuments}
                        missing={missing}
                        subject={decidedAircraft}
                        asked={liveAsked || state.query}
                        onAsk={ask}
                        busy={streaming}
                        focusRequest={focusRequest}
                      />
                    ) : null}

                    {state.decisionUnavailable && !blockingRefusal ? (
                      <section
                        aria-label="no applicability decision"
                        className="border border-line-strong bg-sunken/60 px-3.5 py-3"
                      >
                        <p className="t-label mb-1">no applicability decision</p>
                        <p className="t-body text-ink">{state.decisionUnavailable}</p>
                        <p className="t-body mt-2 text-ink-2">
                          Applicability is decided against one aircraft. Name a tail number
                          or a serial number and the rules engine can run; a model alone
                          matches hundreds of records and the engine will not pick one for
                          you.
                        </p>
                      </section>
                    ) : null}

                    {state.withheldCount > 0 && state.answerWithheldBy ? (
                      <p className="t-body border border-dashed border-line-strong px-3.5 py-2.5 text-ink-2">
                        {state.withheldCount} sentence
                        {state.withheldCount === 1 ? "" : "s"} passed citation verification
                        but {state.answerWithheldBy} withholds the answer, so none is shown.
                        The evidence they cited is in the evidence panel.
                      </p>
                    ) : null}

                    {/*
                      The answer is what the page is for, so it is the region a
                      screen reader is told about as it arrives. "polite" waits
                      for a pause rather than interrupting, and aria-busy marks
                      the stream so a reader is not walked through a half-written
                      sentence.

                      Only the newest turn carries this. Archived turns are plain
                      articles: a thread that re-announced itself every time a
                      question was asked would be unusable with a reader.
                    */}
                    <section
                      id="answer"
                      aria-label="newest answer"
                      aria-live="polite"
                      aria-busy={streaming}
                    >
                      {state.deltas.length === 0 &&
                      !state.refusal &&
                      !state.decisionUnavailable ? (
                        <p className="t-mono text-ink-3">
                          {streaming ? "retrieving and deciding…" : "ask a question."}
                        </p>
                      ) : null}
                      <AnswerStream
                        answer={state.answer}
                        dropped={state.dropped}
                        awaiting={state.awaitingVerification}
                        activeCitationId={citation?.id ?? null}
                        onFocusCitation={setCitation}
                      />
                    </section>

                    {envelope ? (
                      <AnswerEnvelopePanel
                        envelope={envelope}
                        onFocusMissingInput={
                          blockingRefusal?.code === "NEED_CONFIG" ? focusMissingInput : undefined
                        }
                      />
                    ) : null}

                    {state.failure ? (
                      <p className="t-mono border border-line-strong px-3 py-2 text-ink-2">
                        stream error: {state.failure}
                      </p>
                    ) : null}

                    {/* How the question was read. Collapsed: it explains the
                        answer, it is not the answer. */}
                    <Disclosure
                      label="how this question was read"
                      meta={`${state.entities.length} entities · ${
                        state.plan ? state.plan.intent : "no plan"
                      }`}
                    >
                      <div className="flex flex-col gap-3 p-3">
                        {state.entities.length === 0 ? (
                          <p className="t-mono text-ink-3">awaiting entity pass&hellip;</p>
                        ) : (
                          <EntityChips entities={state.entities} query={state.query} />
                        )}
                        <PlanPanel
                          plan={state.plan}
                          planModel={state.planModel}
                          unknownFields={state.decision?.unknown_fields ?? []}
                        />
                      </div>
                    </Disclosure>

                    {/*
                      The citation claim is only true of sentences that are on
                      screen, so it is not made when none are. Saying "every
                      sentence above carries a citation" above an empty answer
                      would be the exact kind of vacuous reassurance this
                      product exists to avoid.
                    */}
                    <p className="t-mono border-t border-line pt-3 text-ink-3">
                      {state.answer.length > 0
                        ? "Every sentence above carries at least one citation that resolves to a paragraph in this run’s retrieved set. "
                        : "No answer prose is shown for this run. "}
                      Applicability was decided by the rules engine, not by the language
                      model.
                    </p>
                  </div>
                </Thread>
              )}

              {showThread ? (
                <div className="shrink-0 border-t border-line bg-raised px-4 py-3 lg:px-8">
                  <div className="mx-auto flex w-full max-w-[74ch] flex-col gap-2">
                    <CarryNote
                      carry={carry}
                      enabled={carryEnabled}
                      onToggle={setCarryEnabled}
                    />
                    <QueryBar
                      value={query}
                      onChange={setQuery}
                      onSubmit={submit}
                      streaming={streaming}
                      typeIn={typeIn}
                    />
                  </div>
                </div>
              ) : null}
            </div>

            {/* The proof. One instance, beside the newest turn on a wide screen
                and under it on a narrow one, so nothing is unreachable on a
                phone. It holds the current run's retrieved set only, which is
                why an archived turn's citations are references rather than
                buttons into it. */}
            <aside
              aria-label="evidence"
              className="flex min-h-0 flex-col border-t border-line lg:border-l lg:border-t-0"
            >
              <EvidenceTabs
                state={state}
                ad={ad}
                askedRevisionId={askedRevision?.built.revision.revision_id ?? null}
                focusRevisionId={focusRevisionId}
                activeTab={evidenceTab}
                onTabChange={setEvidenceTab}
                citation={citation}
                onFocusCitation={setCitation}
                resolve={resolve}
                subjectLabel={subjectLabel}
              />
            </aside>
          </div>
        )}

        {/* The machinery, demoted to a strip. It is how you audit the run, not
            what you came to read. */}
        <footer className="shrink-0 border-t border-line bg-raised">
          <div className="flex flex-wrap items-end gap-x-5 gap-y-2 px-4 py-1.5">
            <LatencyBadges stageMs={state.stageMs} totalMs={state.done?.total_ms ?? null} />
            <div className="ml-auto flex flex-wrap items-center gap-x-4 gap-y-2">
              <span className="t-mono text-ink-3">
                {turns.length === 0
                  ? `contract ${CONTRACT_VERSION}`
                  : `${turns.length + 1} turns · contract ${CONTRACT_VERSION}`}
              </span>
              <DevToolbar
                active={scenarioId}
                onReplay={replay}
                streaming={streaming}
                source={source}
                onSourceChange={changeSource}
              />
            </div>
          </div>
        </footer>
      </main>
    </>
  );
}
