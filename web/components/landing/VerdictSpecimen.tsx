/**
 * A worked example of the thing the product is for: a verdict, and the reason
 * it holds, condition by condition.
 *
 * Deliberately marked as an example in the markup and in the visible label.
 * A specimen that looked like live output would be the exact failure this
 * engine exists to avoid -- a confident, well-formatted claim with nothing
 * behind it -- so it says what it is.
 */

interface Condition {
  readonly field: string;
  readonly test: string;
  readonly held: boolean;
}

const CONDITIONS: readonly Condition[] = [
  { field: "model", test: "A320-214 in the listed models", held: true },
  { field: "serial_number", test: "MSN 1224 within 0981–1380", held: true },
  { field: "equipment", test: "RAT fitted per SB A320-29-1234", held: false },
];

export function VerdictSpecimen() {
  return (
    <figure className="flex flex-col border border-line-strong bg-raised">
      <figcaption className="flex items-baseline justify-between gap-3 border-b border-line px-3.5 py-2">
        <span className="t-label text-ink-2">example verdict</span>
        <span className="t-mono text-ink-3">AD 2026-20-03</span>
      </figcaption>

      <div className="flex flex-col gap-1 border-b border-line px-3.5 py-3">
        <span className="t-mono text-ink-3">N117UW &middot; A320-214 &middot; MSN 1224</span>
        <span className="t-subhead text-ink">Does not apply</span>
        <span className="t-caption text-ink-2">
          One condition fails, so the directive does not apply to this airframe.
        </span>
      </div>

      <ul className="flex flex-col">
        {CONDITIONS.map((c) => (
          <li
            key={c.field}
            className="flex items-baseline gap-2.5 border-b border-line px-3.5 py-2.5 last:border-b-0"
          >
            <span
              aria-hidden
              className={`t-mono shrink-0 ${c.held ? "text-ink-3" : "text-accent"}`}
            >
              {c.held ? "✓" : "✗"}
            </span>
            <span className="flex min-w-0 flex-col gap-0.5">
              <span className="t-mono text-ink-3">{c.field}</span>
              <span className="t-body text-ink">{c.test}</span>
            </span>
            <span className="sr-only">{c.held ? "condition holds" : "condition fails"}</span>
          </li>
        ))}
      </ul>
    </figure>
  );
}
