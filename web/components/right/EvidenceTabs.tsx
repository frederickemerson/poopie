"use client";

import dynamic from "next/dynamic";
import { useState } from "react";
import type { ResolvedCitation } from "@/lib/citation";
import type { AdEntry } from "@/lib/corpus";
import { isProofTreeUnavailable } from "@/lib/events";
import type { EngineView } from "@/lib/useEngineStream";
import { Panel } from "../ui/Panel";
import { Tabs, type TabSpec } from "../ui/Tabs";
import { ProofTree } from "./ProofTree";

/**
 * React Flow is by far the heaviest thing the page can load, and the trace tab
 * is the one tab most runs never open. Loading it on demand keeps it out of the
 * first paint of an answer; `ssr: false` because it measures the DOM it draws
 * into, so there is nothing for the server to render.
 */
const RetrievalTrace = dynamic(
  () => import("./RetrievalTrace").then((m) => ({ default: m.RetrievalTrace })),
  {
    ssr: false,
    loading: () => <p className="t-mono p-3 text-ink-3">loading retrieval trace&hellip;</p>,
  },
);
import { RevisionTimeline } from "./RevisionTimeline";
import { SourcePanel } from "./SourcePanel";

export type EvidenceTabId = "proof" | "revisions" | "trace";

interface EvidenceTabsProps {
  readonly state: EngineView;
  readonly ad: AdEntry | null;
  readonly askedRevisionId: string | null;
  readonly focusRevisionId: string | null;
  readonly activeTab: EvidenceTabId;
  readonly onTabChange: (id: EvidenceTabId) => void;
  readonly citation: ResolvedCitation | null;
  readonly onFocusCitation: (c: ResolvedCitation | null) => void;
  readonly resolve: (id: string) => ResolvedCitation | null;
  readonly subjectLabel: string | null;
}

export function EvidenceTabs({
  state,
  ad,
  askedRevisionId,
  focusRevisionId,
  activeTab,
  onTabChange,
  citation,
  onFocusCitation,
  resolve,
  subjectLabel,
}: EvidenceTabsProps) {
  // No decision is a state of its own, so the badge says so rather than "0".
  const tree = state.decision?.proof_tree ?? null;
  // The plan's own structured fields decide this, never the wording: an
  // applicability question either carries that intent or names one aircraft.
  // A null plan (no API key, budget capped) keeps today's behaviour.
  const plan = state.plan;
  const applicabilityAsked =
    plan === null ||
    plan.intent === "applicability" ||
    plan.intent === "fleet_impact" ||
    Boolean(plan.aircraft?.tail_number) ||
    Boolean(plan.aircraft?.serial_number);
  const proofBadge =
    tree === null
      ? undefined
      : isProofTreeUnavailable(tree)
        ? "none"
        : String(tree.children?.length ?? 0);

  const tabs: readonly TabSpec<EvidenceTabId>[] = [
    { id: "proof", label: "proof tree", badge: proofBadge },
    { id: "revisions", label: "revisions", badge: ad ? String(ad.revisions.length) : undefined },
    { id: "trace", label: "trace", badge: state.done ? `${state.done.total_ms}ms` : undefined },
  ];

  return (
    <div className="flex min-h-0 flex-col gap-2">
      <section className="flex min-h-0 flex-1 flex-col border border-line bg-raised">
        <header className="shrink-0 border-b border-line px-1">
          <Tabs tabs={tabs} active={activeTab} onChange={onTabChange} ariaLabel="evidence" />
        </header>
        <div
          id={`panel-${activeTab}`}
          role="tabpanel"
          aria-labelledby={`tab-${activeTab}`}
          className="min-h-0 flex-1 overflow-y-auto"
        >
          {activeTab === "proof" ? (
            <ProofTree
              decision={state.decision}
              resolve={resolve}
              onFocusCitation={onFocusCitation}
              subjectLabel={subjectLabel}
              applicabilityAsked={applicabilityAsked}
            />
          ) : null}
          {activeTab === "revisions" ? (
            <RevisionTimeline ad={ad} askedRevisionId={askedRevisionId} focusRevisionId={focusRevisionId} />
          ) : null}
          {activeTab === "trace" ? <RetrievalTrace state={state} /> : null}
        </div>
      </section>

      <Panel
        label="source paragraph"
        meta={citation ? citation.ref.revision_id : `${state.paragraphs.length} retrieved`}
        className="h-[38%] shrink-0"
        bodyClassName="flex min-h-0 flex-col"
      >
        <SourcePanel citation={citation} paragraphs={state.paragraphs} scores={state.scores} />
      </Panel>
    </div>
  );
}

/** Kept here so page.tsx does not need to know the tab ids. */
export function useEvidenceTab(initial: EvidenceTabId = "proof") {
  return useState<EvidenceTabId>(initial);
}
