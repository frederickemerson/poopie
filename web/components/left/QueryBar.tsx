"use client";

import { useEffect, useRef, useState } from "react";
import { useMotionPrefs } from "@/lib/motion";

interface QueryBarProps {
  readonly value: string;
  readonly onChange: (next: string) => void;
  /**
   * Ask. The text is passed explicitly when the composer knows it, because the
   * type-in effect sets the value and submits in the same tick: React has not
   * re-rendered yet, so a handler closing over the value state would send the
   * question one character short.
   */
  readonly onSubmit: (text?: string) => void;
  readonly streaming: boolean;
  /** When this changes, the text types itself in, then the run starts. */
  readonly typeIn: { readonly text: string; readonly nonce: number } | null;
  /**
   * "hero" is the empty state: the question is the only thing on the page, so
   * it gets the page's largest input and the examples sit under it. "docked"
   * is every state after that, where an answer is already on screen and the
   * composer is a quiet strip at the bottom of it.
   */
  readonly variant?: "hero" | "docked";
  /** Example questions, offered only when there is nothing to read yet. */
  readonly suggestions?: readonly string[];
  readonly onPick?: (question: string) => void;
}

const TYPE_MS = 11;

/**
 * The question, in plain English, and the only way into the engine.
 *
 * When a scenario is replayed the text types itself in so the chips arrive the
 * way they do for a real operator; under reduced motion the text is set in one
 * step and the run starts immediately.
 */
export function QueryBar({
  value,
  onChange,
  onSubmit,
  streaming,
  typeIn,
  variant = "docked",
  suggestions = [],
  onPick,
}: QueryBarProps) {
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
      submitRef.current(text);
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
        submitRef.current(text);
      }
    }, TYPE_MS);
    return () => {
      window.clearInterval(id);
      setTyping(false);
    };
  }, [typeIn, reduced]);

  // The box grows with the question instead of scrolling inside three fixed
  // rows: an engineer pasting a tail number, a model and a serial should be
  // able to see all of it before pressing ask.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  }, [value]);

  const hero = variant === "hero";
  const busy = streaming || typing;

  return (
    <div className="flex flex-col gap-3">
      <form
        className="group relative flex flex-col border border-line-strong bg-sunken focus-within:border-accent"
        onSubmit={(e) => {
          e.preventDefault();
          onSubmit();
        }}
      >
        <label htmlFor="query" className="sr-only">
          Ask about an airworthiness directive
        </label>
        <textarea
          id="query"
          ref={ref}
          rows={hero ? 2 : 1}
          value={value}
          spellCheck={false}
          aria-describedby="query-hint"
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              onSubmit();
            }
          }}
          placeholder="Which ADs apply to N117UW, an A320-214 with MSN 1224?"
          className={`w-full resize-none bg-transparent px-3.5 pt-3 text-ink outline-none placeholder:text-ink-3 ${
            hero ? "t-answer" : "t-body"
          }`}
        />
        <div className="flex items-center justify-between gap-3 px-3.5 pb-2.5 pt-1">
          <p id="query-hint" className="t-mono text-ink-3">
            {typing
              ? "typing…"
              : streaming
                ? "streaming…"
                : "Enter to ask · Shift+Enter for a new line"}
          </p>
          <button
            type="submit"
            disabled={busy || value.trim().length === 0}
            className="t-label border border-line-strong bg-raised px-3.5 py-1.5 text-ink transition-colors hover:border-accent focus-visible:border-accent disabled:cursor-not-allowed disabled:text-ink-3 disabled:hover:border-line-strong"
          >
            {busy ? "asking…" : "ask"}
          </button>
        </div>
      </form>

      {/*
        Suggestions, and nothing more. Picking one writes it into the box above
        and leaves it there to be edited or sent: it never asks on the reader's
        behalf, which is why the box starts empty and why these sit under it
        rather than in it.
      */}
      {hero && suggestions.length > 0 ? (
        <div className="flex flex-col gap-2">
          <p className="t-label">or start from one of these</p>
          <ul className="flex flex-col gap-1.5">
            {suggestions.map((question) => (
              <li key={question}>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    onPick?.(question);
                    // Land the caret in the question, so it can be edited
                    // before it is asked rather than only accepted.
                    const el = ref.current;
                    el?.focus();
                    window.requestAnimationFrame(() => {
                      const length = el?.value.length ?? 0;
                      el?.setSelectionRange(length, length);
                    });
                  }}
                  className="group/pick t-body flex w-full items-baseline gap-2 border border-line bg-raised px-3 py-2 text-left text-ink-2 transition-colors hover:border-line-strong hover:text-ink focus-visible:border-accent disabled:cursor-not-allowed"
                >
                  <span aria-hidden className="t-mono shrink-0 text-ink-3">
                    &rarr;
                  </span>
                  <span>{question}</span>
                </button>
              </li>
            ))}
          </ul>
          <p className="t-mono text-ink-3">
            these fill the box above &middot; edit it, then press ask
          </p>
        </div>
      ) : null}
    </div>
  );
}
