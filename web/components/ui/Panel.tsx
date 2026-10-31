import type { ReactNode } from "react";

interface PanelProps {
  readonly label: string;
  readonly meta?: ReactNode;
  readonly children: ReactNode;
  readonly className?: string;
  readonly bodyClassName?: string;
  /**
   * Which tier of the page this panel belongs to.
   *
   * "grounds" is the default and the common case: why the verdict is what it
   * is. "verdict" is for the one panel holding the thing that was actually
   * asked for, and it is the only one that gets heading-scale type.
   *
   * This engine emits a great deal at once -- entities, a plan, retrieval
   * scores, a decision, refusals, sentences, verification drops, an envelope.
   * Rendering all of it at one weight is what makes a page read as a data
   * dump, and no amount of typography fixes it afterwards.
   */
  readonly tier?: "verdict" | "grounds";
}

/** The one container in the product: hairline box, label strip, dense body. */
export function Panel({
  label,
  meta,
  children,
  className = "",
  bodyClassName = "",
  tier = "grounds",
}: PanelProps) {
  const isVerdict = tier === "verdict";
  return (
    <section className={`flex min-h-0 flex-col border border-line bg-raised ${className}`}>
      <header
        className={`flex shrink-0 items-baseline justify-between gap-3 border-b border-line px-3 ${
          isVerdict ? "py-2.5" : "py-[7px]"
        }`}
      >
        <h2 className={isVerdict ? "t-subhead text-ink" : "t-label"}>{label}</h2>
        {meta ? <div className="t-mono shrink-0 text-ink-3">{meta}</div> : null}
      </header>
      <div className={`min-h-0 flex-1 ${bodyClassName}`}>{children}</div>
    </section>
  );
}
