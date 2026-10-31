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
import { liveDemo, tailNumberIn } from "@/lib/liveDemos";
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

  return (
    <main className="flex h-dvh flex-col overflow-hidden bg-bg">
      <header className="shrink-0 border-b border-line bg-raised">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2">
          <div className="flex items-baseline gap-2.5">
            <span className="t-mono !text-[15px] font-bold tracking-[-0.02em] text-ink">AUTSG</span>
            <span className="t-label">airworthiness directive answer engine</span>
            <span className="t-mono text-ink-3">contract {CONTRACT_VERSION}</span>
          </div>
          <div className="ml-auto flex flex-wrap items-center gap-x-5 gap-y-2">
            {source === "engine" ? <BackendStatus {...health} /> : null}
            <LatencyBadges stageMs={state.stageMs} totalMs={state.done?.total_ms ?? null} />
            <DevToolbar
              active={scenarioId}
              onReplay={replay}
              streaming={state.status === "streaming"}
              source={source}
              onSourceChange={changeSource}
            />
          </div>
        </div>
        <div className="flex items-end justify-between gap-4 border-t border-line px-3">
          <Tabs
            tabs={[
              { id: "workspace", label: "workspace" },
              {
                id: "blast",
                label: "blast radius",
                badge: source === "engine" ? "live fleet" : "86 aircraft",
              },
            ]}
            active={workspace}
            onChange={setWorkspace}
            ariaLabel="view"
          />
          <p className="t-mono py-1.5 text-ink-3">
            {source === "engine" ? liveDemo(scenarioId).watch_for : scenario(scenarioId).watch_for}
          </p>
        </div>
      </header>

      {workspace === "blast" ? (
        <BlastRadius
          source={source}
          revisions={revisions}
          preferredAdNumber={ad?.ad_number ?? null}
        />
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-[320px_minmax(0,1fr)_430px] gap-2 p-2">
          {/* LEFT - the question and what the engine read in it */}
          <div className="flex min-h-0 flex-col gap-2 overflow-y-auto">
            <Panel label="query" meta={state.status === "streaming" ? "streaming" : state.status}>
              <QueryBar
                value={query}
                onChange={setQuery}
                onSubmit={submit}
                streaming={state.status === "streaming"}
                typeIn={typeIn}
              />
            </Panel>
            <Panel label="entities" meta={`${state.entities.length} parsed`} bodyClassName="p-3">
              {state.entities.length === 0 ? (
                <p className="t-mono text-ink-3">awaiting entity pass&hellip;</p>
              ) : (
                <EntityChips entities={state.entities} query={state.query} />
              )}
            </Panel>
            <Panel label="query plan" meta={state.plan ? state.plan.intent : "—"}>
              <PlanPanel
                plan={state.plan}
                planModel={state.planModel}
                unknownFields={state.decision?.unknown_fields ?? []}
              />
            </Panel>
          </div>

          {/* CENTRE - the answer, and nothing that has not been verified */}
          <Panel
            label="answer"
            tier="verdict"
            meta={
              state.verification
                ? `verified ${state.verification.kept.length} · dropped ${state.verification.dropped.length} · ${state.verification.stage_ms} ms`
                : state.deltas.length > 0
                  ? `${state.deltas.length} held for verification`
                  : "—"
            }
            bodyClassName="overflow-y-auto"
          >
            {superseded ? (
              <SupersededBanner detail={superseded} onOpenCurrent={openCurrentRevision} />
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
                className="m-4 border border-line-strong bg-sunken/60 px-3 py-2.5"
              >
                <p className="t-label mb-1">no applicability decision</p>
                <p className="t-body text-ink">{state.decisionUnavailable}</p>
                <p className="t-body mt-2 text-ink-2">
                  Applicability is decided against one aircraft. Name a tail number or a serial
                  number and the rules engine can run; a model alone matches hundreds of records and
                  the engine will not pick one for you.
                </p>
              </section>
            ) : null}

            {state.deltas.length === 0 && !state.refusal && !state.decisionUnavailable ? (
              <p className="t-mono px-4 py-3 text-ink-3">
                {state.status === "streaming" ? "retrieving and deciding…" : "ask a question."}
              </p>
            ) : null}

            {state.withheldCount > 0 && state.answerWithheldBy ? (
              <p className="t-body mx-4 mt-2 border border-dashed border-line-strong px-3 py-2 text-ink-2">
                {state.withheldCount} sentence{state.withheldCount === 1 ? "" : "s"} passed citation
                verification but {state.answerWithheldBy} withholds the answer, so none is shown.
                The evidence they cited is in the panel on the right.
              </p>
            ) : null}

            <AnswerStream
              answer={state.answer}
              dropped={state.dropped}
              awaiting={state.awaitingVerification}
              activeCitationId={citation?.id ?? null}
              onFocusCitation={setCitation}
            />

            {envelope ? (
              <AnswerEnvelopePanel
                envelope={envelope}
                onSupplyValue={source === "engine" ? (field) => supplyValue(field) : undefined}
              />
            ) : null}

            {state.failure ? (
              <p className="t-mono mx-4 mb-4 border border-line-strong px-3 py-2 text-ink-2">
                stream error: {state.failure}
              </p>
            ) : null}

            {/*
              The citation claim is only true of sentences that are on screen, so
              it is not made when none are. Saying "every sentence above carries a
              citation" above an empty answer would be the exact kind of vacuous
              reassurance this product exists to avoid.
            */}
            <footer className="mt-2 border-t border-line px-4 py-2">
              <p className="t-mono text-ink-3">
                {state.answer.length > 0
                  ? "Every sentence above carries at least one citation that resolves to a paragraph in this run\u2019s retrieved set. "
                  : "No answer prose is shown for this run. "}
                Applicability was decided by the rules engine, not by the language model.
              </p>
            </footer>
          </Panel>

          {/* RIGHT - the evidence */}
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
        </div>
      )}
    </main>
  );
}
