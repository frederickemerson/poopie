"use client";

import { motion } from "framer-motion";
import Link from "next/link";
import { useEffect, useState } from "react";
import { NameBand } from "@/components/landing/NameBand";
import { Otto } from "@/components/landing/Otto";
import { PipelineDiagram } from "@/components/landing/PipelineDiagram";
import { Reveal } from "@/components/landing/Reveal";
import { SpeedBand } from "@/components/landing/SpeedBand";
import { VerdictSpecimen } from "@/components/landing/VerdictSpecimen";
import { useMotionPrefs } from "@/lib/motion";
import type { CorpusSummary } from "@/lib/useBackendHealth";

/** Why the question is hard before anyone writes a line of software. */
const PROBLEMS: readonly { readonly title: string; readonly body: string }[] = [
  {
    title: "The answer is per aircraft, not per model",
    body: "A directive names serial ranges, fitted part numbers, engine variants and modification states. Two 737-800s delivered the same week can land on opposite sides of the same AD.",
  },
  {
    title: "The revision you found may not be the one in force",
    body: "Directives supersede one another, and the superseding document does not always repeat what it changed. A decision made against a stale revision is a finding waiting to happen.",
  },
  {
    title: "Often the directive does not contain the answer",
    body: "Applicability is routinely delegated to a manufacturer service bulletin that the AD only names. If you do not hold that document, the honest answer is that it cannot yet be decided.",
  },
];

/** The claims, and the reason each one is true. */
const STRENGTHS: readonly { readonly title: string; readonly body: string }[] = [
  {
    title: "It answers for a tail number",
    body: "Give it N117UW. It reads that airframe's model, serial, operator and fitted equipment from the fleet record, then evaluates the directive's own conditions against them one at a time.",
  },
  {
    title: "A sentence without a citation never reaches you",
    body: "Every drafted sentence is re-checked against the exact span it cites. Sentences that do not hold are dropped, and if too few survive, the answer is withheld rather than padded out.",
  },
  {
    title: "The proof is the answer, not a footnote",
    body: "Each condition is shown with the value the directive requires, the value your aircraft has, the outcome, and the sentence it came from. You can audit the verdict without opening the AD.",
  },
  {
    title: "It refuses in six specific ways",
    body: "A bare “I don’t know” sends you nowhere. Each refusal names what is missing and who can clear it — you, the manufacturer, or a document nobody has loaded yet.",
  },
  {
    title: "Supersession is tracked, not assumed",
    body: "It knows which revision is current and will tell you when it has answered from a directive a newer one replaces, instead of quietly handing you last year's obligation.",
  },
  {
    title: "Applicability is never decided by a model",
    body: "A model reads your question and writes the final prose. The deciding — retrieval, conditions, supersession, verification — is ordinary code, so the same question gives the same verdict every time.",
  },
];

/** The product surface, stated as the things an engineer actually types. */
// Each of these was run against the engine and the note says what it actually
// returned -- three answers of different kinds, and the refusal. An example
// question is a promise, and the page previously made four the engine could
// not keep, one of them about AD 2019-08-11, which is not in this corpus and
// so could only ever refuse.
const ASKS: readonly { readonly q: string; readonly note: string }[] = [
  {
    q: "What is the unsafe condition addressed by AD 2009-17-05?",
    note: "answered from the directive's own paragraphs, every sentence cited",
  },
  {
    q: "Is AD 2004-21-08 the current revision, or has it been superseded?",
    note: "the supersession chain, ending at what is in force and when",
  },
  {
    q: "What must I do for AD 2024-13-05, and by when?",
    note: "refused: the compliance steps live in a Boeing bulletin this corpus does not hold",
  },
  {
    q: "What are the latest ADs?",
    note: "the newest directives in this corpus, ordered in code from the index",
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
            className="mx-auto flex max-w-[1180px] items-center gap-3 px-5 py-3 lg:px-8"
          >
            <Otto size={26} decorative />
            <span className="t-mono !text-[15px] font-bold tracking-[-0.02em] text-ink">
              poopie
            </span>
            <span className="t-label hidden sm:inline">
              plane operations &amp; original parts indexing engine
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
          {/* Hero: the problem, then the product. */}
          <section className="mx-auto max-w-[1180px] px-5 pb-16 pt-16 lg:px-8 lg:pb-24 lg:pt-28">
            <div className="grid items-start gap-12 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
              <div>
                <Reveal className="flex flex-col gap-5">
                  <span className="t-label w-max border border-line-strong px-2.5 py-1 text-accent">
                    airworthiness compliance
                  </span>
                  <h1 className="t-display max-w-[22ch] text-ink">
                    &ldquo;Does this directive apply to this aircraft?&rdquo; should not
                    take an afternoon.
                  </h1>
                  <p className="t-answer max-w-[62ch] text-ink-2">
                    Ask it in plain English and get the verdict, what you must do, the
                    deadline, and the revision that is current &mdash; with the paragraph
                    and the deciding condition shown beside it. When it cannot know, it
                    says so and names who can resolve it.
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
                    href="#problem"
                    className="t-label border border-line-strong px-5 py-2.5 text-ink transition-colors duration-300 hover:border-accent focus-visible:border-accent"
                  >
                    why it is hard
                  </a>
                </Reveal>
              </div>

              <Reveal delay={0.18} className="w-full lg:pt-12">
                <VerdictSpecimen />
              </Reveal>
            </div>
          </section>

          {/* The name. */}
          <section
            aria-labelledby="name-heading"
            className="border-y border-line bg-raised"
          >
            <div className="mx-auto max-w-[1180px] px-5 py-14 lg:px-8 lg:py-20">
              <h2 id="name-heading" className="sr-only">
                What poopie stands for
              </h2>
              <Reveal>
                <NameBand />
              </Reveal>
            </div>
          </section>

          {/* The problem. */}
          <section aria-labelledby="problem-heading" id="problem">
            <div className="mx-auto max-w-[1180px] px-5 py-14 lg:px-8 lg:py-24">
              <Reveal className="flex flex-col gap-4">
                <span className="t-label w-max border border-line-strong px-2.5 py-1 text-accent">
                  the problem
                </span>
                <h2 id="problem-heading" className="t-heading max-w-[26ch] text-ink">
                  Applicability is buried in prose, and the stakes run both ways.
                </h2>
                <p className="t-answer max-w-[62ch] text-ink-2">
                  Decide wrongly in one direction and a serviceable aircraft sits on the
                  ground. Decide wrongly in the other and an unairworthy one flies. Today
                  the work is keyword search across thousands of pages of Federal Register
                  text, done under a dispatch deadline.
                </p>
              </Reveal>

              <ol className="mt-10 grid gap-x-10 gap-y-9 md:grid-cols-3">
                {PROBLEMS.map((p, i) => (
                  <Reveal as="li" key={p.title} delay={0.06 * i} className="flex flex-col gap-2.5">
                    <span
                      aria-hidden
                      className="t-mono text-accent"
                      style={{ letterSpacing: "0.08em" }}
                    >
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <h3 className="t-subhead text-ink">{p.title}</h3>
                    <p className="t-body text-ink-2">{p.body}</p>
                  </Reveal>
                ))}
              </ol>
            </div>
          </section>

          {/* Why this tool. */}
          <section
            aria-labelledby="why-heading"
            className="border-y border-line bg-raised"
          >
            <div className="mx-auto max-w-[1180px] px-5 py-14 lg:px-8 lg:py-20">
              <Reveal className="flex flex-col gap-4">
                <span className="t-label w-max border border-line-strong px-2.5 py-1 text-accent">
                  why poopie
                </span>
                <h2 id="why-heading" className="t-heading max-w-[28ch] text-ink">
                  Built for the part of the job that has to be defensible.
                </h2>
                <p className="t-body max-w-[62ch] text-ink-2">
                  An answer an engineer can sign off on has to show its working. Every
                  choice below exists so the verdict survives the question
                  &ldquo;how do you know?&rdquo;
                </p>
              </Reveal>

              <ul className="mt-10 grid gap-x-10 gap-y-9 md:grid-cols-2">
                {STRENGTHS.map((s, i) => (
                  <Reveal as="li" key={s.title} delay={0.05 * i} className="flex gap-4">
                    <span aria-hidden className="mt-1.5 h-1.5 w-1.5 shrink-0 bg-accent" />
                    <div className="flex flex-col gap-1.5">
                      <h3 className="t-subhead text-ink">{s.title}</h3>
                      <p className="t-body max-w-[48ch] text-ink-2">{s.body}</p>
                    </div>
                  </Reveal>
                ))}
              </ul>
            </div>
          </section>

          {/* Speed. */}
          <section aria-labelledby="speed-heading">
            <div className="mx-auto max-w-[1180px] px-5 py-14 lg:px-8 lg:py-24">
              <Reveal className="flex flex-col gap-4">
                <span className="t-label w-max border border-line-strong px-2.5 py-1 text-accent">
                  speed
                </span>
                <h2 id="speed-heading" className="t-heading max-w-[24ch] text-ink">
                  The deciding takes half a millisecond.
                </h2>
                <p className="t-answer max-w-[64ch] text-ink-2">
                  Retrieval across the whole corpus, the applicability verdict and the
                  citation check run together in about a tenth of a second. Nearly all
                  the wait you feel is the two model calls at either end &mdash; and a
                  refusal never reaches the longer one.
                </p>
              </Reveal>
              <Reveal delay={0.1} className="mt-10">
                <SpeedBand />
              </Reveal>
            </div>
          </section>

          {/* What you can ask. */}
          <section aria-labelledby="ask-heading">
            <div className="mx-auto max-w-[1180px] px-5 py-14 lg:px-8 lg:py-24">
              <Reveal className="flex flex-col gap-4">
                <span className="t-label w-max border border-line-strong px-2.5 py-1 text-accent">
                  what you can ask
                </span>
                <h2 id="ask-heading" className="t-heading max-w-[24ch] text-ink">
                  One textbox. No query language, no docket to look up first.
                </h2>
                <p className="t-answer max-w-[64ch] text-ink-2">
                  These four were run against the engine and the note says what came back.
                  One of them refuses, which is the behaviour and not the exception: the
                  evidence for it sits in a Boeing bulletin this corpus does not hold, and
                  saying so is an honest answer where a guess would not be.
                </p>
              </Reveal>

              <ul className="mt-9 grid gap-px border border-line-strong bg-line-strong">
                {ASKS.map((a, i) => (
                  <Reveal
                    as="li"
                    key={a.q}
                    delay={0.05 * i}
                    className="flex flex-col gap-1.5 bg-raised px-4 py-4 sm:flex-row sm:items-baseline sm:justify-between sm:gap-6"
                  >
                    <span className="t-mono text-ink">{a.q}</span>
                    <span className="t-caption shrink-0 text-ink-3">{a.note}</span>
                  </Reveal>
                ))}
              </ul>
            </div>
          </section>

          {/* What it reads. */}
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
                  engine &mdash; it will not print a number it cannot stand behind.
                </p>
              </Reveal>
            </div>
          </section>

          {/* Refusals. */}
          <section aria-labelledby="refusal-heading">
            <div className="mx-auto max-w-[1180px] px-5 py-14 lg:px-8 lg:py-24">
              <Reveal className="flex flex-col gap-4">
                <span className="t-label w-max border border-line-strong px-2.5 py-1 text-accent">
                  the part most tools skip
                </span>
                <h2 id="refusal-heading" className="t-heading max-w-[26ch] text-ink">
                  A refusal names who can resolve it.
                </h2>
                <p className="t-body max-w-[62ch] text-ink-2">
                  &ldquo;I don&rsquo;t know&rdquo; is not one answer, it is six different
                  ones, and they send you to six different places. The engine emits the
                  code that is true and blocks the answer rather than writing around the
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

          {/* Under the hood, briefly. */}
          <section
            aria-labelledby="pipeline-heading"
            className="border-y border-line bg-raised"
          >
            <div className="mx-auto max-w-[1180px] px-5 py-14 lg:px-8 lg:py-20">
              <Reveal className="flex flex-col gap-3">
                <span className="t-label text-ink-2">under the hood</span>
                <h2 id="pipeline-heading" className="t-subhead max-w-[46ch] text-ink">
                  Seven stages. A model writes the first and the last; code decides
                  everything in between.
                </h2>
              </Reveal>
              <Reveal delay={0.1} className="mt-8">
                <PipelineDiagram />
              </Reveal>
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
            <Otto size={22} decorative />
            <span className="t-mono text-ink-3">
              poopie &mdash; plane operations &amp; original parts indexing engine
            </span>
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
