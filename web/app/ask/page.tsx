"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { BlastRadius } from "@/components/blast/BlastRadius";
import { BackendStatus } from "@/components/BackendStatus";
import { AnswerEnvelopePanel } from "@/components/centre/AnswerEnvelopePanel";
import { AnswerStream } from "@/components/centre/AnswerStream";
import { RefusalCard } from "@/components/centre/RefusalCard";
import { SupersededBanner } from "@/components/centre/SupersededBanner";
import { DevToolbar } from "@/components/DevToolbar";
import { EntityChips } from "@/components/left/EntityChips";
import { PlanPanel } from "@/components/left/PlanPanel";
import { QueryBar } from "@/components/left/QueryBar";
import { LatencyBadges } from "@/components/LatencyBadges";
import { EvidenceTabs, type EvidenceTabId } from "@/components/right/EvidenceTabs";
import { Disclosure } from "@/components/ui/Disclosure";
import { Panel } from "@/components/ui/Panel";
import { Tabs } from "@/components/ui/Tabs";
import type { BlastRevisionRef } from "@/lib/blast";
import { resolveCitation, type ResolvedCitation } from "@/lib/citation";
import { CONTRACT_VERSION } from "@/lib/contract";
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
  const [query, setQuery] = useState<string>(demoQuestion(DEFAULT_ENGINE_SOURCE, DEFAULT_SCENARIO_ID).query);
  const [typeIn, setTypeIn] = useState<{ text: string; nonce: number } | null>(null);
  const [workspace, setWorkspace] = useState<Workspace>("workspace");
  const [evidenceTab, setEvidenceTab] = useState<EvidenceTabId>("proof");
  const [citation, setCitation] = useState<ResolvedCitation | null>(null);
  const [focusRevisionId, setFocusRevisionId] = useState<string | null>(null);
  // Revisions the engine itself surfaced, newest first. The blast grid may only
  // be asked about one of these, so it can never show a revision no run read.
  const [revisions, setRevisions] = useState<readonly BlastRevisionRef[]>([]);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setSource(readStoredEngineSource());
    setHydrated(true);
  }, []);

  const start = useCallback(
    (nextSource: EngineSource, id: ScenarioId) => {
      const { query: text } = demoQuestion(nextSource, id);
      setScenarioId(id);
      setCitation(null);
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
      start(next, scenarioId);
    },
    [scenarioId, start],
  );

  // The opening run. Everything the UI shows afterwards came off the stream.
  useEffect(() => {
    if (!hydrated) return;
    start(source, DEFAULT_SCENARIO_ID);
    // Only on first hydration: later runs are driven by the toolbar and the bar.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hydrated]);

  const submit = useCallback(() => {
    const demo = demoQuestion(source, scenarioId);
    const edited = query.trim() !== demo.query.trim();
    if (source === "mock") {
      run(edited ? { query, source } : { query, source, scenario: scenarioId });
    } else {
      run({ query, source, tailNumber: edited ? tailNumberIn(query) : demo.tail });
    }
    setCitation(null);
  }, [query, run, scenarioId, source]);

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
   * NEED_CONFIG is the code the user can clear. Supplying the value re-asks the
   * question with the value stated in it, so the engine reads it and decides
   * again. The UI never folds a supplied value into a decision itself.
   *
   * The assertion is phrased from the rule the engine could not evaluate - its
   * own operator and its own value, taken from the proof tree - rather than from
   * the bare field name, which would send back "given it has equipment".
   */
  const supplyValue = useCallback(
    (field: string, value?: string) => {
      if (source === "mock") {
        replay("clean");
        return;
      }
      const condition =
        tree && !isProofTreeUnavailable(tree)
          ? (tree.children ?? []).find((c) => c.field === field)
          : undefined;
      const subject = tree && !isProofTreeUnavailable(tree) ? tree.aircraft?.tail_number : null;
      const named = value?.trim() || condition?.rule_value || field;
      const assertion =
        condition?.operator === "exists" || condition?.operator === "not_exists"
          ? `${subject ?? "It"} is fitted with ${named}.`
          : `Its ${field.replace(/_/g, " ")} is ${named}.`;
      const restated = `${query.trim().replace(/\s+$/, "")} ${assertion}`;
      setQuery(restated);
      setTypeIn({ text: restated, nonce: Date.now() });
    },
    [query, replay, source, tree],
  );

  const envelope = state.done?.envelope ?? null;

  // Is there anything to read yet? The composer is the whole page until there
  // is, and a quiet strip under the answer once there is -- the question stays
  // the thing you act on either way.
  const hasResult =
    state.answer.length > 0 ||
    state.deltas.length > 0 ||
    state.refusal !== null ||
    state.decisionUnavailable !== null ||
    state.paragraphs.length > 0 ||
    state.status === "streaming";

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

  const askDirectly = useCallback((question: string) => {
    setQuery(question);
    setTypeIn({ text: question, nonce: Date.now() });
  }, []);

  return (
    <>
      <a
        href="#answer"
        className="t-label sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:border focus:border-accent focus:bg-raised focus:px-3 focus:py-2 focus:text-ink"
      >
        Skip to the answer
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

        {workspace === "blast" ? (
          <BlastRadius
            source={source}
            revisions={revisions}
            preferredAdNumber={ad?.ad_number ?? null}
          />
        ) : (
          <div className="flex flex-1 flex-col lg:grid lg:min-h-0 lg:grid-cols-[minmax(0,1fr)_404px]">
            {/* The answer, on its own, at a width prose can be read at. */}
            <div className="flex flex-col lg:min-h-0">
              <div className="flex-1 lg:min-h-0 lg:overflow-y-auto">
                <div className="mx-auto w-full max-w-[74ch] px-4 py-6 lg:px-8 lg:py-10">
                  {!hasResult ? (
                    <div className="flex flex-col gap-6">
                      <div className="flex flex-col gap-2">
                        <h1 className="t-heading text-ink">
                          Which directives apply, what must you do, and by when?
                        </h1>
                        <p className="t-body max-w-[58ch] text-ink-2">
                          Ask in plain English. {corpusBlurb} The answer is decided by a
                          rules engine, never by the language model, and every sentence
                          carries a citation you can open.
                        </p>
                      </div>
                      <QueryBar
                        value={query}
                        onChange={setQuery}
                        onSubmit={submit}
                        // `hasResult` is false here, and it is true whenever the
                        // run is streaming, so the hero is never the streaming
                        // state. TypeScript narrows this for us.
                        streaming={false}
                        typeIn={typeIn}
                        variant="hero"
                        suggestions={suggestions}
                        onPick={askDirectly}
                      />
                    </div>
                  ) : (
                    <div className="flex flex-col gap-5">
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
                          onSupplyValue={supplyValue}
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
                      */}
                      <section
                        id="answer"
                        aria-label="answer"
                        aria-live="polite"
                        aria-busy={state.status === "streaming"}
                      >
                        {state.deltas.length === 0 &&
                        !state.refusal &&
                        !state.decisionUnavailable ? (
                          <p className="t-mono text-ink-3">
                            {state.status === "streaming"
                              ? "retrieving and deciding\u2026"
                              : "ask a question."}
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
                          onSupplyValue={
                            source === "engine" ? (field) => supplyValue(field) : undefined
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
                        meta={`${state.entities.length} entities \u00b7 ${
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
                          ? "Every sentence above carries at least one citation that resolves to a paragraph in this run\u2019s retrieved set. "
                          : "No answer prose is shown for this run. "}
                        Applicability was decided by the rules engine, not by the language
                        model.
                      </p>
                    </div>
                  )}
                </div>
              </div>

              {hasResult ? (
                <div className="shrink-0 border-t border-line bg-raised px-4 py-3 lg:px-8">
                  <div className="mx-auto w-full max-w-[74ch]">
                    <QueryBar
                      value={query}
                      onChange={setQuery}
                      onSubmit={submit}
                      streaming={state.status === "streaming"}
                      typeIn={typeIn}
                    />
                  </div>
                </div>
              ) : null}
            </div>

            {/* The proof. One instance, beside the answer on a wide screen and
                under it on a narrow one, so nothing is unreachable on a phone. */}
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
              <span className="t-mono text-ink-3">contract {CONTRACT_VERSION}</span>
              <DevToolbar
                active={scenarioId}
                onReplay={replay}
                streaming={state.status === "streaming"}
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
