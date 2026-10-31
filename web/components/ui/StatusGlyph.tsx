import type { Decision } from "@/lib/contract";

export interface Tone {
  readonly glyph: string;
  readonly text: string;
  readonly bg: string;
  readonly border: string;
  readonly ring: string;
  readonly word: string;
}

/**
 * The three outcomes of the rules engine, and the only three places colour is
 * allowed to mean something. CANNOT_DETERMINE is a first-class outcome, which is
 * why it gets a glyph and a word of its own rather than an error style.
 */
export const TONE: Readonly<Record<Decision, Tone>> = {
  APPLIES: {
    glyph: "✓",
    text: "text-ok",
    bg: "bg-ok-bg",
    border: "border-ok",
    ring: "var(--c-ok)",
    word: "applies",
  },
  DOES_NOT_APPLY: {
    glyph: "✕",
    text: "text-no",
    bg: "bg-no-bg",
    border: "border-no",
    ring: "var(--c-no)",
    word: "does not apply",
  },
  CANNOT_DETERMINE: {
    glyph: "?",
    text: "text-maybe",
    bg: "bg-maybe-bg",
    border: "border-maybe",
    ring: "var(--c-maybe)",
    word: "cannot determine",
  },
};

interface StatusGlyphProps {
  readonly decision: Decision;
  readonly size?: number;
  readonly title?: string;
}

export function StatusGlyph({ decision, size = 16, title }: StatusGlyphProps) {
  const tone = TONE[decision];
  return (
    <span
      role="img"
      aria-label={`${decision}: ${tone.word}`}
      title={title ?? decision}
      style={{ width: size, height: size, fontSize: size * 0.72 }}
      className={`inline-grid shrink-0 place-items-center rounded-full border font-semibold leading-none ${tone.text} ${tone.bg} ${tone.border}`}
    >
      {tone.glyph}
    </span>
  );
}

export function DecisionChip({ decision }: { readonly decision: Decision }) {
  const tone = TONE[decision];
  return (
    <span
      className={`inline-flex items-center gap-1.5 border px-1.5 py-0.5 ${tone.text} ${tone.bg} ${tone.border}`}
    >
      <span aria-hidden className="font-semibold leading-none">
        {tone.glyph}
      </span>
      <span className="t-mono font-semibold tracking-tight">{decision}</span>
    </span>
  );
}
