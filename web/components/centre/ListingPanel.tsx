"use client";

/**
 * The `listing` answer kind, on screen.
 *
 * "What are the latest ADs?" used to refuse with OUT_OF_SCOPE. It now answers
 * with rows the engine ordered in pure code from the graph index - which means
 * the one thing this panel must never do is read like the Federal Register's
 * own front page. It cannot say "the latest ADs"; it can only say "the latest
 * this corpus holds, which runs to `corpus_latest`".
 *
 * So the bounds are stated above the rows, in body text, at full weight:
 *
 *   - `total_available`, because ten rows out of two thousand is a top-N and a
 *     reader who thinks it is the whole set has been misled by the layout;
 *   - `corpus_earliest`/`corpus_latest`, because the corpus has an end date and
 *     anything published after it is simply absent;
 *   - `ordered_by`, because "latest" is meaningless without the field it sorted.
 *
 * None of that is a tooltip or a footnote. An engine that exists to refuse
 * rather than guess cannot have its one listing screen imply a live feed.
 */
import { motion } from "framer-motion";
import type { ListingPayload, ListingRow } from "@/lib/events";
import { useMotionPrefs } from "@/lib/motion";

interface ListingPanelProps {
  readonly listing: ListingPayload;
}

/** The make and product type as one line, or null when the index holds neither. */
function productLabel(row: ListingRow): string | null {
  const parts = [row.make, row.product_type].filter(
    (part): part is string => part !== null && part.trim() !== "",
  );
  return parts.length === 0 ? null : parts.join(" · ");
}

/** Absent is said, never left blank: a blank cell reads as a value of nothing. */
function NotRecorded() {
  return <span className="text-ink-3">not recorded</span>;
}

interface CellProps {
  readonly label: string;
  readonly value: string;
}

/**
 * One datum with its field name. The label shows below `md`, where the row is
 * stacked and has no column header to sit under, and is hidden above it, where
 * the header strip names the column instead. Exactly one of the two is in the
 * tree at any width, so a screen reader always hears the field name once.
 */
function Cell({ label, value }: CellProps) {
  return (
    <div className="flex min-w-0 items-baseline gap-1.5">
      <span className="t-label shrink-0 !tracking-[0.06em] md:hidden">{label}</span>
      <span className="t-mono min-w-0 break-words text-ink-2">
        {value.trim() === "" ? <NotRecorded /> : value}
      </span>
    </div>
  );
}

/**
 * The five columns, shared by the header strip and every row so they align.
 * `display` is deliberately not in here: the strip is `hidden md:grid` and the
 * rows are `grid` at every width, and two unprefixed display utilities on one
 * element resolve by stylesheet order rather than by class order.
 */
const COLUMNS =
  "gap-x-3 gap-y-1 md:grid-cols-[96px_92px_92px_minmax(0,1fr)_120px] md:items-baseline md:gap-y-0";

function Row({ row }: { readonly row: ListingRow }) {
  const product = productLabel(row);
  return (
    <li className={`grid grid-cols-1 ${COLUMNS} border-t border-line px-3 py-2 md:py-1.5`}>
      <div className="flex flex-wrap items-baseline gap-x-2 md:flex-col md:items-start md:gap-y-0.5">
        <span className="t-mono font-semibold text-ink">{row.ad_number}</span>
        <span className={`t-label !tracking-[0.06em] ${row.is_current ? "" : "text-ink-3"}`}>
          {row.is_current ? "current" : "superseded"}
        </span>
      </div>
      <Cell label="published" value={row.publication_date} />
      <Cell label="effective" value={row.effective_on} />
      <div className="flex min-w-0 items-baseline gap-1.5">
        <span className="t-label shrink-0 !tracking-[0.06em] md:hidden">product</span>
        <span className="t-caption min-w-0 break-words">
          {product === null ? <NotRecorded /> : product}
        </span>
      </div>
      <Cell label="federal register" value={row.fr_citation} />
    </li>
  );
}

export function ListingPanel({ listing }: ListingPanelProps) {
  const { dur } = useMotionPrefs();
  const { rows, ordered_by: orderedBy, corpus_latest: latest, corpus_earliest: earliest } = listing;
  const shown = rows.length;
  const total = listing.total_available;

  return (
    <motion.section
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: dur(220), ease: [0.2, 0.8, 0.2, 1] }}
      aria-label="corpus listing"
      className="m-4 border border-line-strong bg-raised"
    >
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-3 py-2">
        <h3 className="t-mono !text-[13px] font-bold tracking-tight text-ink">CORPUS LISTING</h3>
        <span className="t-label !tracking-[0.06em] text-ink-3">ordered by {orderedBy}</span>
        <span className="t-mono ml-auto tabular-nums text-ink-3">{listing.stage_ms} ms</span>
      </header>

      {/* The scope, before the rows. Everything below is read in its terms. */}
      <div className="border-b border-line px-3 py-2.5">
        <p className="t-label mb-1.5">what this list is</p>
        <p className="t-answer text-ink">
          {shown === 0 ? (
            <>This corpus holds nothing to list, and it runs only to {latest} in any case.</>
          ) : (
            <>
              The {shown} most recently published {shown === 1 ? "directive" : "directives"} in
              this corpus, which runs to {latest}. It is the latest this engine holds &mdash; not
              the latest the FAA has published.
            </>
          )}
        </p>
        <p className="t-body mt-2 max-w-[68ch] text-ink-2">
          The corpus holds <span className="t-figure">{total.toLocaleString()}</span> published
          directives, from <span className="t-mono">{earliest}</span> to{" "}
          <span className="t-mono">{latest}</span>, ordered by {orderedBy}
          {shown === 0 ? (
            ". The ordering returned no rows for this question."
          ) : (
            <>
              ; the <span className="t-figure">{shown}</span> below are the head of that list.
            </>
          )}{" "}
          Anything published after <span className="t-mono">{latest}</span> is not in the corpus
          and therefore cannot appear here. This is not a live Federal Register feed.
        </p>
      </div>

      {shown === 0 ? null : (
        <>
          {/* Column names, from `md` up, where the rows line up as a table.
              Below that each row stacks and carries its own field labels. */}
          <div
            className={`hidden ${COLUMNS} border-b border-line bg-sunken/50 px-3 py-1.5 md:grid`}
          >
            <span className="t-label">ad number</span>
            <span className="t-label">published</span>
            <span className="t-label">effective</span>
            <span className="t-label">make / product</span>
            <span className="t-label">federal register</span>
          </div>

          <ol>
            {rows.map((row) => (
              <Row key={`${row.ad_number}-${row.publication_date}`} row={row} />
            ))}
          </ol>
        </>
      )}

      <p className="t-mono border-t border-line px-3 py-2 text-ink-3">
        These rows were ordered in code from the graph index. The language model neither wrote nor
        ranked them, and no applicability was decided: whether any of these apply to an aircraft is
        a separate question, asked one tail number at a time.
      </p>
    </motion.section>
  );
}
