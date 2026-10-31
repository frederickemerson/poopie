interface OttoProps {
  /** Rendered width in pixels. The drawing scales from a single viewBox. */
  readonly size?: number;
  readonly className?: string;
  /**
   * A decorative instance sits beside a wordmark that already names the
   * product, so it is hidden from assistive technology instead of being
   * announced twice.
   */
  readonly decorative?: boolean;
}

const VB_W = 120;
const VB_H = 156;

/**
 * Otto.
 *
 * Built from the same primitives as the pipeline diagram -- boxes, hairlines,
 * one accent -- so he belongs to the design system rather than sitting on top
 * of it. No image asset: at roughly two kilobytes of inline SVG he costs less
 * than a request, scales to any size without a second file, and takes every
 * colour from the design tokens rather than hard-coding one.
 *
 * He is perched on three hairlines, which are the corpus.
 */
export function Otto({ size = 120, className = "", decorative = false }: OttoProps) {
  const label = decorative ? {} : { role: "img" as const, "aria-label": "the poopie owl" };

  return (
    <svg
      {...label}
      aria-hidden={decorative || undefined}
      focusable="false"
      viewBox={`0 0 ${VB_W} ${VB_H}`}
      width={size}
      height={Math.round((size * VB_H) / VB_W)}
      className={`otto shrink-0 ${className}`}
    >
      <g
        fill="none"
        stroke="var(--c-line-strong)"
        strokeWidth={1.6}
        strokeLinecap="square"
      >
        {/* The corpus he sits on. */}
        <path d="M16 141 H104" />
        <path d="M21 147 H99" opacity={0.6} />
        <path d="M26 153 H94" opacity={0.32} />

        {/* Feet. */}
        <path d="M50 130 V138 M44 138 H56" />
        <path d="M70 130 V138 M64 138 H76" />

        {/* Body, drawn before the head so the head overlaps it. */}
        <rect x={28} y={84} width={64} height={46} rx={16} fill="var(--c-raised)" />
        <path d="M37 96 Q31 112 39 125" opacity={0.7} />
        <path d="M83 96 Q89 112 81 125" opacity={0.7} />

        <g className="otto-head">
          {/* Ear tufts. */}
          <path d="M26 35 L33 16 L45 32" fill="var(--c-raised)" />
          <path d="M94 35 L87 16 L75 32" fill="var(--c-raised)" />

          <rect x={20} y={30} width={80} height={58} rx={12} fill="var(--c-raised)" />

          {/* Facial discs. */}
          <circle cx={44} cy={56} r={12} fill="var(--c-bg)" />
          <circle cx={76} cy={56} r={12} fill="var(--c-bg)" />

          <g className="otto-look">
            <circle className="otto-pupil" cx={44} cy={56} r={4.6} fill="var(--c-accent)" stroke="none" />
            <circle className="otto-pupil" cx={76} cy={56} r={4.6} fill="var(--c-accent)" stroke="none" />
          </g>

          {/* Beak, tucked between the discs and drawn over them. */}
          <path d="M54 62 H66 L60 73 Z" fill="var(--c-raised)" />
        </g>
      </g>
    </svg>
  );
}
