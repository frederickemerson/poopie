"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { BlastRadius } from "@/components/blast/BlastRadius";
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
import { resolveCitation, type ResolvedCitation } from "@/lib/citation";
import { CONTRACT_VERSION } from "@/lib/contract";
import { findAd, revisionForAdNumber } from "@/lib/corpus";
import { DEFAULT_SCENARIO_ID, scenario, type ScenarioId } from "@/lib/mockStream";
import { useEngineStream } from "@/lib/useEngineStream";

type Workspace = "workspace" | "blast";

export default function Page() {
  const { state, run } = useEngineStream();
  const [scenarioId, setScenarioId] = useState<ScenarioId>(DEFAULT_SCENARIO_ID);
  const [query, setQuery] = useState<string>(scenario(DEFAULT_SCENARIO_ID).query);
  const [typeIn, setTypeIn] = useState<{ text: string; nonce: number } | null>(null);
  const [workspace, setWorkspace] = useState<Workspace>("workspace");
  const [evidenceTab, setEvidenceTab] = useState<EvidenceTabId>("proof");
  const [citation, setCitation] = useState<ResolvedCitation | null>(null);
  const [focusRevisionId, setFocusRevisionId] = useState<string | null>(null);

  const replay = useCallback((id: ScenarioId) => {
    const s = scenario(id);
    setScenarioId(id);
    setCitation(null);
    setFocusRevisionId(null);
    setEvidenceTab("proof");
    setWorkspace("workspace");
    setTypeIn({ text: s.query, nonce: Date.now() });
  }, []);

  // The opening run. Everything the UI shows afterwards came off the stream.
  useEffect(() => {
    replay(DEFAULT_SCENARIO_ID);
  }, [replay]);

  const submit = useCallback(() => {
    const active = scenario(scenarioId);
    const edited = query.trim() !== active.query.trim();
    run(edited ? { query } : { query, scenario: scenarioId });
    setCitation(null);
  }, [query, run, scenarioId]);

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
    state.refusal?.code === "SUPERSEDED" && "superseded_warning" in state.refusal.detail
      ? state.refusal.detail.superseded_warning
      : null;
  const blockingRefusal = state.refusal && !superseded ? state.refusal : null;

  const subjectLabel =
    state.plan?.aircraft.tail_number ?? state.plan?.aircraft.model ?? null;

  const openCurrentRevision = useCallback((revisionId: string) => {
    setFocusRevisionId(revisionId);
    setEvidenceTab("revisions");
  }, []);

  const supplyValue = useCallback(() => {
    replay("clean");
  }, [replay]);

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
            <LatencyBadges stageMs={state.stageMs} totalMs={state.done?.total_ms ?? null} />
            <DevToolbar active={scenarioId} onReplay={replay} streaming={state.status === "streaming"} />
          </div>
        </div>
        <div className="flex items-end justify-between gap-4 border-t border-line px-3">
          <Tabs
            tabs={[
              { id: "workspace", label: "workspace" },
              { id: "blast", label: "blast radius", badge: "86 aircraft" },
            ]}
            active={workspace}
            onChange={setWorkspace}
            ariaLabel="view"
          />
          <p className="t-mono py-1.5 text-ink-3">{scenario(scenarioId).watch_for}</p>
        </div>
      </header>

      {workspace === "blast" ? (
        <BlastRadius preferredAdNumber={ad?.ad_number ?? null} />
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
                onSupplyValue={supplyValue}
              />
            ) : null}

            {state.deltas.length === 0 && !state.refusal ? (
              <p className="t-mono px-4 py-3 text-ink-3">
                {state.status === "streaming" ? "retrieving and deciding…" : "ask a question."}
              </p>
            ) : null}

            <AnswerStream
              answer={state.answer}
              dropped={state.dropped}
              awaiting={state.awaitingVerification}
              activeCitationId={citation?.id ?? null}
              onFocusCitation={setCitation}
            />

            {state.failure ? (
              <p className="t-mono mx-4 mb-4 border border-line-strong px-3 py-2 text-ink-2">
                stream error: {state.failure}
              </p>
            ) : null}

            <footer className="mt-2 border-t border-line px-4 py-2">
              <p className="t-mono text-ink-3">
                Every sentence above carries at least one citation that resolves to a paragraph in
                this run&rsquo;s retrieved set. Applicability was decided by the rules engine, not by
                the language model.
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
