"use client";

import { useEffect, useRef, useState } from "react";
import { useMotionPrefs } from "@/lib/motion";

interface QueryBarProps {
  readonly value: string;
  readonly onChange: (next: string) => void;
  readonly onSubmit: () => void;
  readonly streaming: boolean;
  /** When this changes, the text types itself in, then the run starts. */
  readonly typeIn: { readonly text: string; readonly nonce: number } | null;
}

const TYPE_MS = 11;

/**
 * The question, in plain English. When a scenario is replayed the text types
 * itself in so the chips arrive the way they do for a real operator; under
 * reduced motion the text is set in one step and the run starts immediately.
 */
export function QueryBar({ value, onChange, onSubmit, streaming, typeIn }: QueryBarProps) {
  const { reduced } = useMotionPrefs();
  const [typing, setTyping] = useState(false);
  const ref = useRef<HTMLTextAreaElement | null>(null);
  const submitRef = useRef(onSubmit);
  submitRef.current = onSubmit;
  const changeRef = useRef(onChange);
  changeRef.current = onChange;

  useEffect(() => {
    if (!typeIn) return;
    const { text } = typeIn;
    if (reduced) {
      changeRef.current(text);
      submitRef.current();
      return;
    }
    setTyping(true);
    let i = 0;
    const id = window.setInterval(() => {
      i += 1;
      changeRef.current(text.slice(0, i));
      if (i >= text.length) {
        window.clearInterval(id);
        setTyping(false);
        submitRef.current();
      }
    }, TYPE_MS);
    return () => {
      window.clearInterval(id);
      setTyping(false);
    };
  }, [typeIn, reduced]);

  return (
    <form
      className="flex flex-col gap-2 p-3"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <label htmlFor="query" className="t-label">
        question
      </label>
      <textarea
        id="query"
        ref={ref}
        rows={3}
        value={value}
        spellCheck={false}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            onSubmit();
          }
        }}
        placeholder="Which ADs apply to N117UW, an A320-214 with MSN 1224?"
        className="t-body w-full resize-none border border-line bg-sunken px-2.5 py-2 text-ink placeholder:text-ink-3 focus:border-line-strong"
      />
      <div className="flex items-center justify-between gap-2">
        <span className="t-mono text-ink-3">
          {typing ? "typing…" : streaming ? "streaming" : "↵ to ask"}
        </span>
        <button
          type="submit"
          disabled={streaming || typing || value.trim().length === 0}
          className="t-label border border-line-strong bg-sunken px-3 py-1.5 text-ink transition-colors hover:border-accent disabled:cursor-not-allowed disabled:text-ink-3 disabled:hover:border-line-strong"
        >
          ask
        </button>
      </div>
    </form>
  );
}
