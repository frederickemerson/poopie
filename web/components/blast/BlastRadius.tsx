"use client";

/**
 * Blast radius: one AD revision across the whole fleet at once.
 *
 * With the live engine this is GET /blast/{revision_id} - the engine's own rules
 * engine over every built fleet record. With the recorded source it is the
 * in-browser grid over the four ADs in lib/corpus, which is what keeps the demo
 * standing if the backend dies.
 */
import type { BlastRevisionRef } from "@/lib/blast";
import type { EngineSource } from "@/lib/engineSource";
import { LiveBlastRadius } from "./LiveBlastRadius";
import { MockBlastRadius } from "./MockBlastRadius";

interface BlastRadiusProps {
  readonly source: EngineSource;
  /** Revisions the live runs in this session surfaced. */
  readonly revisions: readonly BlastRevisionRef[];
  /** Recorded mode only: opens the tab on the AD the answer is about. */
  readonly preferredAdNumber: string | null;
}

export function BlastRadius({ source, revisions, preferredAdNumber }: BlastRadiusProps) {
  if (source === "mock") return <MockBlastRadius preferredAdNumber={preferredAdNumber} />;
  return <LiveBlastRadius revisions={revisions} />;
}
