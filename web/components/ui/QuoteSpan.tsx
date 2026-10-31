interface QuoteSpanProps {
  readonly text: string;
  readonly start: number;
  readonly end: number;
  readonly className?: string;
}

/**
 * Paragraph text with one exact character span marked. The span is always
 * computed from a citation id, never searched for, so what is highlighted is
 * literally what was cited.
 */
export function QuoteSpan({ text, start, end, className = "" }: QuoteSpanProps) {
  const a = Math.max(0, Math.min(start, text.length));
  const b = Math.max(a, Math.min(end, text.length));
  return (
    <p className={`t-body whitespace-pre-wrap text-ink-2 ${className}`}>
      {text.slice(0, a)}
      <mark className="bg-hl px-[1px] text-ink">{text.slice(a, b)}</mark>
      {text.slice(b)}
    </p>
  );
}

/** Same thing when all you hold is a verbatim quote rather than offsets. */
export function QuoteInText({ text, quote, className = "" }: { text: string; quote: string; className?: string }) {
  const at = text.indexOf(quote);
  if (at < 0) return <p className={`t-body text-ink-2 ${className}`}>{text}</p>;
  return <QuoteSpan text={text} start={at} end={at + quote.length} className={className} />;
}
