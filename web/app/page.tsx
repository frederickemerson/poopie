"use client";

import { motion } from "framer-motion";
import Link from "next/link";
import { useEffect, useState } from "react";
import { PipelineDiagram } from "@/components/landing/PipelineDiagram";
import { Reveal } from "@/components/landing/Reveal";
import { VerdictSpecimen } from "@/components/landing/VerdictSpecimen";
import { useMotionPrefs } from "@/lib/motion";
import type { CorpusSummary } from "@/lib/useBackendHealth";

/** What the engine is for, in the order an engineer meets it. */
const STEPS: readonly { readonly title: string; readonly body: string }[] = [
  {
    title: "Ask in plain English",
    body: "“Which ADs apply to N117UW, an A320-214 with MSN 1224?” No query language, no docket numbers to look up first.",
  },
  {
    title: "The question is read, not guessed at",
    body: "A tail number, a model, a serial, a docket — each is pulled out by a table lookup and a structured query plan, so what the engine thinks you asked is on screen before it answers.",
  },
  {
    title: "Retrieval is filtered by the graph",
    body: "Keyword and dense search over 28,735 paragraphs, fused, then narrowed to the directives whose own rules name your aircraft. Nothing else is read.",
  },
  {
    title: "A rules engine decides, not the model",
    body: "Applicability is evaluated against the directive's own conditions — model, serial range, fitted equipment — and the pass or fail of every condition is shown as a proof tree.",
  },
  {
    title: "Every sentence is held to a citation",
    body: "A verifier re-checks each sentence against the paragraph it cites and drops the ones that do not hold. What survives is what you read.",
  },
  {
    title: "It refuses when it should",
    body: "If applicability is delegated to a document this engine does not hold, or your question names no aircraft, it says so and names who can resolve it — rather than writing a confident paragraph.",
  },
];

const REFUSALS: readonly { readonly code: string; readonly meaning: string }[] = [
  { code: "EXTERNAL_SOURCE_REQUIRED", meaning: "a document we do not hold decides this" },
  { code: "NEED_CONFIG", meaning: "you can clear this in seconds — here is what is missing" },
  { code: "NO_EVIDENCE", meaning: "this corpus does not hold it" },
  { code: "OUT_OF_SCOPE", meaning: "this was never an AD question" },
  { code: "CANNOT_DETERMINE", meaning: "the clause did not parse; we will not guess it" },
  { code: "SUPERSEDED", meaning: "answered, but a newer revision exists" },
];

function useCorpus(): CorpusSummary | null {
  const [corpus, setCorpus] = useState<CorpusSummary | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/health", { signal: controller.signal })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => setCorpus(d?.corpus ?? null))
      .catch(() => {
        /* The page states no figure rather than a stale one. */
      });
    return () => controller.abort();
  }, []);
  return corpus;
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div className="flex flex-col gap-1 border-t border-line-strong pt-3">
      <span className="t-figure tabular-nums text-ink">{value}</span>
      <span className="t-label">{label}</span>
    </div>
  );
}

export default function Landing() {
  const { reduced } = useMotionPrefs();
  const corpus = useCorpus();
  const n = (v: number | undefined) => (v === undefined ? "—" : v.toLocaleString());

  return (
    <>
      <a
        href="#main"
        className="t-label sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:border focus:border-accent focus:bg-raised focus:px-3 focus:py-2 focus:text-ink"
      >
        Skip to content
      </a>

      <div className="min-h-dvh bg-bg">
        <header className="sticky top-0 z-30 border-b border-line bg-raised/85 backdrop-blur-md">
          <nav
            aria-label="Main"
            className="mx-auto flex max-w-[1180px] items-center gap-4 px-5 py-3 lg:px-8"
          >
            <span className="t-mono !text-[15px] font-bold tracking-[-0.02em] text-ink">
              poopie
            </span>
            <span className="t-label hidden sm:inline">
              airworthiness directive answer engine
            </span>
            <Link
              href="/ask"
              className="group ml-auto flex items-center gap-2 border border-line-strong bg-sunken px-3.5 py-1.5 transition-colors duration-300 hover:border-accent focus-visible:border-accent"
            >
              <span className="t-label text-ink">ask a question</span>
              <span
                aria-hidden
                className="inline-block text-ink-2 transition-transform duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] group-hover:translate-x-0.5 group-hover:text-accent"
              >
                &rarr;
              </span>
            </Link>
          </nav>
        </header>

        <main id="main">
          {/* Hero */}
          <section className="mx-auto max-w-[1180px] px-5 pb-16 pt-16 lg:px-8 lg:pb-24 lg:pt-28">
            <div className="grid items-start gap-12 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
            <div>
            <Reveal className="flex flex-col gap-5">
              <span className="t-label w-max border border-line-strong px-2.5 py-1 text-accent">
                traceable by construction
              </span>
              <h1 className="t-display max-w-[20ch] text-ink">
                Which directives apply, what must you do, and by when.
              </h1>
              <p className="t-answer max-w-[62ch] text-ink-2">
                Ask in plain English. A knowledge graph and ordinary code find the answer,
                a rules engine decides it, and the proof is on screen beside it —
                paragraph, condition, revision.
              </p>
            </Reveal>

            <Reveal delay={0.12} className="mt-8 flex flex-wrap items-center gap-3">
              <Link
                href="/ask"
                className="group flex items-center gap-3 border border-ink bg-ink px-5 py-2.5 text-bg transition-transform duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] active:scale-[0.98]"
              >
                <span className="t-label !text-[12px] text-bg">ask a question</span>
                <span
                  aria-hidden
                  className="inline-block transition-transform duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] group-hover:translate-x-1"
                >
                  &rarr;
                </span>
              </Link>
              <a
                href="#how"
                className="t-label border border-line-strong px-5 py-2.5 text-ink transition-colors duration-300 hover:border-accent focus-visible:border-accent"
              >
                how it works
              </a>
            </Reveal>

            </div>
            <Reveal delay={0.18} className="w-full lg:pt-12">
              <VerdictSpecimen />
            </Reveal>
            </div>

            <Reveal delay={0.24} className="mt-16">
              <PipelineDiagram />
            </Reveal>
          </section>

          {/* What it reads */}
          <section
            aria-labelledby="corpus-heading"
            className="border-y border-line bg-raised"
          >
            <div className="mx-auto max-w-[1180px] px-5 py-14 lg:px-8 lg:py-20">
              <Reveal>
                <h2 id="corpus-heading" className="t-heading max-w-[24ch] text-ink">
                  It reads the directives themselves, not summaries of them.
                </h2>
              </Reveal>
              <Reveal delay={0.1}>
                <dl className="mt-10 grid grid-cols-2 gap-x-6 gap-y-8 md:grid-cols-4">
                  <Stat value={n(corpus?.ad_numbers)} label="airworthiness directives" />
                  <Stat
                    value={n(corpus?.federal_register_pages)}
                    label="Federal Register pages"
                  />
                  <Stat value={n(corpus?.paragraphs)} label="indexed paragraphs" />
                  <Stat value={n(corpus?.proposals)} label="proposals (NPRMs)" />
                </dl>
              </Reveal>
              <Reveal delay={0.16}>
                <p className="t-caption mt-6 max-w-[64ch] text-ink-3">
                  Counted from the engine that loaded them, live, rather than quoted from a
                  document that can go stale. A dash means this page could not reach the
                  engine — it will not print a number it cannot stand behind.
                </p>
              </Reveal>
            </div>
          </section>

          {/* How it works */}
          <section aria-labelledby="how-heading" id="how">
            <div className="mx-auto max-w-[1180px] px-5 py-14 lg:px-8 lg:py-24">
              <Reveal>
                <h2 id="how-heading" className="t-heading max-w-[22ch] text-ink">
                  Six steps, and a model writes only two of them.
                </h2>
              </Reveal>
              <ol className="mt-10 grid gap-x-10 gap-y-9 md:grid-cols-2">
                {STEPS.map((step, i) => (
                  <Reveal as="li" key={step.title} delay={0.06 * i} className="flex gap-4">
                    <span
                      aria-hidden
                      className="t-mono shrink-0 pt-0.5 text-accent"
                      style={{ letterSpacing: "0.08em" }}
                    >
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <div className="flex flex-col gap-1.5">
                      <h3 className="t-subhead text-ink">{step.title}</h3>
                      <p className="t-body max-w-[46ch] text-ink-2">{step.body}</p>
                    </div>
                  </Reveal>
                ))}
              </ol>
            </div>
          </section>

          {/* Refusals */}
          <section
            aria-labelledby="refusal-heading"
            className="border-y border-line bg-raised"
          >
            <div className="mx-auto max-w-[1180px] px-5 py-14 lg:px-8 lg:py-20">
              <Reveal className="flex flex-col gap-4">
                <span className="t-label w-max border border-line-strong px-2.5 py-1 text-accent">
                  the part most engines skip
                </span>
                <h2 id="refusal-heading" className="t-heading max-w-[26ch] text-ink">
                  A refusal names who can resolve it.
                </h2>
                <p className="t-body max-w-[62ch] text-ink-2">
                  &ldquo;I don&rsquo;t know&rdquo; is not one answer, it is six different
                  ones, and they send you to six different places. The engine emits the
                  code that is true, and blocks the answer rather than writing around the
                  gap.
                </p>
              </Reveal>
              <ul className="mt-9 grid gap-px border border-line-strong bg-line-strong sm:grid-cols-2">
                {REFUSALS.map((r, i) => (
                  <Reveal
                    as="li"
                    key={r.code}
                    delay={0.05 * i}
                    className="flex flex-col gap-1 bg-raised px-4 py-3.5"
                  >
                    <code className="t-mono text-accent">{r.code}</code>
                    <span className="t-body text-ink-2">{r.meaning}</span>
                  </Reveal>
                ))}
              </ul>
            </div>
          </section>

          {/* CTA */}
          <section className="mx-auto max-w-[1180px] px-5 py-20 lg:px-8 lg:py-28">
            <Reveal className="flex flex-col items-start gap-6">
              <h2 className="t-heading max-w-[18ch] text-ink">
                Ask it something you already know the answer to.
              </h2>
              <p className="t-body max-w-[54ch] text-ink-2">
                That is the only honest way to judge it. Then ask it something it cannot
                answer, and watch it say so.
              </p>
              <motion.div
                whileHover={reduced ? undefined : { scale: 1.015 }}
                whileTap={reduced ? undefined : { scale: 0.985 }}
                transition={{ duration: 0.3, ease: [0.32, 0.72, 0, 1] }}
              >
                <Link
                  href="/ask"
                  className="group flex items-center gap-3 border border-ink bg-ink px-6 py-3 text-bg"
                >
                  <span className="t-label !text-[12px] text-bg">open the engine</span>
                  <span
                    aria-hidden
                    className="inline-block transition-transform duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] group-hover:translate-x-1"
                  >
                    &rarr;
                  </span>
                </Link>
              </motion.div>
            </Reveal>
          </section>
        </main>

        <footer className="border-t border-line bg-raised">
          <div className="mx-auto flex max-w-[1180px] flex-wrap items-center gap-x-5 gap-y-2 px-5 py-5 lg:px-8">
            <span className="t-mono text-ink-3">poopie</span>
            <span className="t-caption text-ink-3">
              Answers are generated from FAA source text and are not a substitute for the
              directive itself.
            </span>
            <Link href="/ask" className="t-label ml-auto text-ink-2 hover:text-accent">
              ask a question &rarr;
            </Link>
          </div>
        </footer>
      </div>
    </>
  );
}
