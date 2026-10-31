/**
 * Where the time actually goes.
 *
 * Every figure here was measured against the running engine over twenty
 * consecutive live queries, with both model calls in the loop and nothing
 * served from cache. They are stated as measurements, with the sample size
 * attached, rather than rounded into a slogan -- the same rule the corpus
 * counts follow.
 *
 * The split is the honest version of "fast": the deciding is effectively
 * instantaneous, and essentially all of the wait is the two language model
 * calls at either end. Drawing it makes that readable at a glance, and reuses
 * the dashed-means-a-model convention from the pipeline diagram so the two
 * pictures agree.
 */

/** Measured 2026-10-31, n=20, against the live engine. Milliseconds. */
const MEASURED = {
  entityPass: 0.15,
  retrieval: 115.63,
  applicability: 0.5,
  verify: 0.34,
  queryPlan: 1072.38,
  answer: 2783.43,
  avgTotal: 2450,
  p50: 1627,
  p95: 4309,
  refusalAvg: 1204,
  n: 20,
} as const;

const OUR_CODE_MS =
  MEASURED.entityPass + MEASURED.retrieval + MEASURED.applicability + MEASURED.verify;
const ANSWERED_MS = OUR_CODE_MS + MEASURED.queryPlan + MEASURED.answer;

interface Segment {
  readonly label: string;
  readonly ms: number;
  readonly model: boolean;
  readonly fill: string;
}

const SEGMENTS: readonly Segment[] = [
  { label: "reading, retrieval, deciding, verifying", ms: OUR_CODE_MS, model: false, fill: "bg-accent" },
  { label: "query plan", ms: MEASURED.queryPlan, model: true, fill: "bg-accent-dim" },
  { label: "writing the answer", ms: MEASURED.answer, model: true, fill: "bg-sunken" },
];

const HEADLINES: readonly { readonly value: string; readonly label: string }[] = [
  { value: `${MEASURED.applicability} ms`, label: "to decide applicability" },
  { value: `${Math.round(OUR_CODE_MS)} ms`, label: "everything this engine decides" },
  { value: "1.2 s", label: "average refusal" },
  { value: "2.5 s", label: "average answered question" },
];

const pct = (ms: number) => (ms / ANSWERED_MS) * 100;
const share = (ms: number) => `${pct(ms).toFixed(1)}%`;

export function SpeedBand() {
  return (
    <div className="flex flex-col gap-10">
      <dl className="grid grid-cols-2 gap-x-6 gap-y-8 md:grid-cols-4">
        {HEADLINES.map((h) => (
          <div key={h.label} className="flex flex-col gap-1 border-t border-line-strong pt-3">
            <dt className="t-figure tabular-nums text-ink">{h.value}</dt>
            <dd className="t-label">{h.label}</dd>
          </div>
        ))}
      </dl>

      <figure className="flex flex-col gap-3">
        <div
          role="img"
          aria-label={`Of the ${(ANSWERED_MS / 1000).toFixed(1)} seconds an answered question takes, ${share(OUR_CODE_MS)} is this engine reading, retrieving, deciding and verifying. The remaining ${share(MEASURED.queryPlan + MEASURED.answer)} is the two language model calls.`}
          className="flex h-10 w-full overflow-hidden border border-line-strong"
        >
          {SEGMENTS.map((s) => (
            <div
              key={s.label}
              style={{ width: `${pct(s.ms)}%`, minWidth: s.model ? undefined : "5px" }}
              className={`${s.fill} ${
                s.model ? "border-r border-dashed border-accent last:border-r-0" : ""
              }`}
            />
          ))}
        </div>

        <figcaption className="sr-only">
          Time split for one answered question.
        </figcaption>

        <dl className="grid gap-px border border-line-strong bg-line-strong sm:grid-cols-3">
          {SEGMENTS.map((s) => (
            <div key={s.label} className="flex flex-col gap-1 bg-raised px-4 py-3">
              <dt className="t-label flex items-center gap-2 text-ink-2">
                <span
                  aria-hidden
                  className={
                    s.model
                      ? "inline-block h-0 w-5 border-t border-dashed border-accent"
                      : "inline-block h-[3px] w-5 bg-accent"
                  }
                />
                {s.model ? "a model" : "this engine"}
              </dt>
              <dd className="flex flex-col gap-0.5">
                <span className="t-body text-ink">{s.label}</span>
                <span className="t-mono tabular-nums text-ink-3">
                  {Math.round(s.ms).toLocaleString()} ms &middot; {share(s.ms)}
                </span>
              </dd>
            </div>
          ))}
        </dl>
      </figure>

      <p className="t-caption max-w-[72ch] text-ink-3">
        Measured against the running engine over {MEASURED.n} consecutive live queries,
        with both model calls in the loop and nothing served from cache. Median{" "}
        {(MEASURED.p50 / 1000).toFixed(1)} s, 95th percentile{" "}
        {(MEASURED.p95 / 1000).toFixed(1)} s. Refusals return fastest because they never
        reach the answer writer at all.
      </p>
    </div>
  );
}
