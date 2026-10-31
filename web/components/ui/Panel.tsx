import type { ReactNode } from "react";

interface PanelProps {
  readonly label: string;
  readonly meta?: ReactNode;
  readonly children: ReactNode;
  readonly className?: string;
  readonly bodyClassName?: string;
}

/** The one container in the product: hairline box, label strip, dense body. */
export function Panel({ label, meta, children, className = "", bodyClassName = "" }: PanelProps) {
  return (
    <section className={`flex min-h-0 flex-col border border-line bg-raised ${className}`}>
      <header className="flex shrink-0 items-center justify-between gap-3 border-b border-line px-3 py-[7px]">
        <h2 className="t-label">{label}</h2>
        {meta ? <div className="t-mono shrink-0 text-ink-3">{meta}</div> : null}
      </header>
      <div className={`min-h-0 flex-1 ${bodyClassName}`}>{children}</div>
    </section>
  );
}
