"use client";

import { motion } from "framer-motion";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Turn } from "@/lib/conversationTurn";
import { useMotionPrefs } from "@/lib/motion";
import { TurnCard } from "./TurnCard";

interface ThreadProps {
  /** Finished turns, oldest first. The live turn is `children`. */
  readonly turns: readonly Turn[];
  /** Changes whenever the live turn gains content, to follow the stream. */
  readonly liveKey: number;
  /** Changes once per question asked, to bring the new turn to the top. */
  readonly askKey: number;
  readonly children: React.ReactNode;
}

/** Within this far of the bottom still counts as reading the newest turn. */
const PIN_SLACK_PX = 96;

/**
 * A scroll event this soon after one we caused is ours, not the reader's.
 * Scrolling programmatically fires the same event a wheel does, and without
 * this the view would read its own scroll as the reader asking to follow.
 */
const PROGRAMMATIC_MS = 150;

/**
 * The thread, and the scroll contract that makes it readable.
 *
 * Three rules, and the second is the one that matters:
 *
 *  1. The column is the scroll container on a wide screen and the page scrolls
 *     on a narrow one, so this resolves which one is actually scrollable rather
 *     than assuming.
 *  2. A new question brings the **top** of its turn to the top of the view, and
 *     leaves the reader there. A verdict here is tall - a refusal card with
 *     inputs, an envelope, a disclosure - so following the stream to the bottom
 *     would scroll the answer off the top while they were reading it.
 *  3. Following resumes only when the reader asks for it: by scrolling to the
 *     bottom themselves, or by pressing the button that says so.
 */
function useThreadScroll(liveKey: number, askKey: number) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const liveRef = useRef<HTMLDivElement | null>(null);
  const pinnedRef = useRef(true);
  /** While set, streaming content is not followed. See rule 2. */
  const anchoredRef = useRef(false);
  /** When we last scrolled the view ourselves. See PROGRAMMATIC_MS. */
  const movedAtRef = useRef(0);
  const [pinned, setPinned] = useState(true);

  /** The element that actually scrolls, or null when the window does. */
  const scroller = useCallback((): HTMLDivElement | null => {
    const el = scrollRef.current;
    if (!el) return null;
    return el.scrollHeight > el.clientHeight + 1 ? el : null;
  }, []);

  const measure = useCallback(
    (fromReader: boolean) => {
      const el = scroller();
      const distance = el
        ? el.scrollHeight - el.scrollTop - el.clientHeight
        : document.documentElement.scrollHeight - window.scrollY - window.innerHeight;
      const atBottom = distance < PIN_SLACK_PX;
      pinnedRef.current = atBottom;
      // Only the reader reaching the bottom releases the anchor. Our own
      // scroll, measured a frame later, must not be mistaken for consent.
      if (fromReader && atBottom) anchoredRef.current = false;
      setPinned((prev) => (prev === atBottom ? prev : atBottom));
    },
    [scroller],
  );

  const handleScroll = useCallback(() => {
    measure(performance.now() - movedAtRef.current > PROGRAMMATIC_MS);
  }, [measure]);

  const toBottom = useCallback(() => {
    anchoredRef.current = false;
    movedAtRef.current = performance.now();
    const el = scroller();
    if (el) el.scrollTop = el.scrollHeight;
    else window.scrollTo({ top: document.documentElement.scrollHeight });
    measure(false);
  }, [measure, scroller]);

  /** Bring the live turn's first line to the top of whatever is scrolling. */
  const toLiveTop = useCallback(() => {
    const live = liveRef.current;
    if (!live) return;
    movedAtRef.current = performance.now();
    const el = scroller();
    if (el) {
      const delta = live.getBoundingClientRect().top - el.getBoundingClientRect().top;
      el.scrollTop = Math.min(el.scrollTop + delta, el.scrollHeight);
    } else {
      window.scrollTo({ top: Math.max(0, window.scrollY + live.getBoundingClientRect().top - 12) });
    }
    measure(false);
  }, [measure, scroller]);

  useEffect(() => {
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, [handleScroll]);

  // A question was asked: show it, from its first line down, and stay there.
  useLayoutEffect(() => {
    toLiveTop();
    anchoredRef.current = true;
  }, [askKey, toLiveTop]);

  // The live turn grows a sentence at a time. Watching the content box rather
  // than re-running on every render keeps this correct while streaming without
  // the component having to know what changed.
  useEffect(() => {
    const content = contentRef.current;
    if (!content || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      if (pinnedRef.current && !anchoredRef.current) toBottom();
      else measure(false);
    });
    observer.observe(content);
    return () => observer.disconnect();
  }, [measure, toBottom]);

  useEffect(() => {
    if (pinnedRef.current && !anchoredRef.current) toBottom();
  }, [liveKey, toBottom]);

  return { scrollRef, contentRef, liveRef, pinned, toBottom, handleScroll };
}

export function Thread({ turns, liveKey, askKey, children }: ThreadProps) {
  const { dur } = useMotionPrefs();
  const { scrollRef, contentRef, liveRef, pinned, toBottom, handleScroll } = useThreadScroll(
    liveKey,
    askKey,
  );

  return (
    <div className="relative flex flex-1 flex-col lg:min-h-0">
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 lg:min-h-0 lg:overflow-y-auto"
      >
        <div
          ref={contentRef}
          className="mx-auto flex w-full max-w-[74ch] flex-col gap-6 px-4 py-6 lg:px-8 lg:py-10"
        >
          {turns.map((turn, index) => (
            <motion.div
              key={turn.id}
              // Starts most of the way visible and only finishes the fade: if
              // the animation never runs, the turn is on screen rather than
              // invisible, which is the rule every entry here follows.
              initial={{ opacity: 0.4 }}
              animate={{ opacity: 1 }}
              transition={{ duration: dur(200) }}
            >
              <TurnCard turn={turn} index={index} />
            </motion.div>
          ))}
          <div ref={liveRef}>{children}</div>
        </div>
      </div>

      {/* Only offered when there is something below to follow. A reader already
          at the bottom is not told they are behind. */}
      {!pinned ? (
        <button
          type="button"
          onClick={toBottom}
          // Pinned to the right rather than centred: centred, it sits on top of
          // the prose it is offering to scroll, and covers a line of it.
          className="t-label absolute bottom-4 right-4 border border-line-strong bg-raised px-3 py-1.5 text-ink-2 transition-colors hover:border-accent hover:text-ink focus-visible:border-accent"
        >
          follow the newest turn &darr;
        </button>
      ) : null}
    </div>
  );
}
