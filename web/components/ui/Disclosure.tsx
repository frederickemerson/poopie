import type { ReactNode } from "react";

interface DisclosureProps {
  readonly label: string;
  readonly meta?: ReactNode;
  readonly children: ReactNode;
  readonly defaultOpen?: boolean;
  readonly className?: string;
}

/**
 * A collapsed section for the machinery behind an answer.
 *
 * Built on native ``details``/``summary`` rather than a state hook and an
 * ``aria-expanded`` button: the element already announces its own expanded
 * state, is keyboard operable, and is findable by in-page browser search even
 * while closed. Hand-rolling it would mean reimplementing all three.
 */
export function Disclosure({
  label,
  meta,
  children,
  defaultOpen = false,
  className = "",
}: DisclosureProps) {
  return (
    <details
      open={defaultOpen}
      className={`group border border-line bg-raised [&[open]>summary]:border-b ${className}`}
    >
      <summary className="flex cursor-pointer list-none items-baseline justify-between gap-3 border-line px-3 py-2 marker:content-none hover:bg-sunken/60 focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent">
        <span className="t-label flex items-baseline gap-1.5 text-ink-2 group-hover:text-ink">
          <span aria-hidden className="inline-block transition-transform group-open:rotate-90">
            &rsaquo;
          </span>
          {label}
        </span>
        {meta ? <span className="t-mono shrink-0 text-ink-3">{meta}</span> : null}
      </summary>
      <div className="min-h-0">{children}</div>
    </details>
  );
}
