"use client";

import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useMotionPrefs } from "@/lib/motion";

interface RevealProps {
  readonly children: ReactNode;
  readonly delay?: number;
  readonly className?: string;
  /** Rendered element. Keeps landmarks semantic rather than wrapping in divs. */
  readonly as?: "div" | "section" | "li" | "header" | "footer";
}

/** Nothing below this point on first paint can flash, so it is safe to hide. */
const FOLD_SLACK_PX = 80;
/** If the observer has not fired by now, show the content anyway. */
const FAILSAFE_MS = 2_500;

/**
 * Entry on scroll: a heavy, slightly late fade-up.
 *
 * Written so that **content is never hidden behind an animation that might not
 * run**. The markup renders visible; the hidden state is applied in an effect,
 * and only to elements that are below the fold when they mount, so there is
 * nothing to flash. That means no JavaScript, a failed hydration, a broken
 * IntersectionObserver or a reduced-motion preference all end at "the text is
 * on screen" rather than at a blank page.
 *
 * The naive version of this -- Framer's `whileInView` with an `initial` opacity
 * of 0 -- fails exactly that way: jump to an anchor, restore a scroll position,
 * or deep-link past a section and it never intersects, so it stays invisible
 * permanently. A failsafe timer covers the rest.
 *
 * Only transform and opacity are animated, so it stays on the compositor.
 */
export function Reveal({ children, delay = 0, className = "", as = "div" }: RevealProps) {
  const { reduced } = useMotionPrefs();
  const ref = useRef<HTMLElement | null>(null);
  // Starts shown. Only an effect that has proved it can animate hides it.
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el || reduced || typeof IntersectionObserver === "undefined") return;

    // Already on screen (or scrolled past): leave it alone.
    if (el.getBoundingClientRect().top < window.innerHeight - FOLD_SLACK_PX) return;

    setHidden(true);
    let failsafe = 0;
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((e) => e.isIntersecting)) return;
        setHidden(false);
        observer.disconnect();
        window.clearTimeout(failsafe);
      },
      { rootMargin: "-80px 0px" },
    );
    observer.observe(el);
    failsafe = window.setTimeout(() => {
      setHidden(false);
      observer.disconnect();
    }, FAILSAFE_MS);

    return () => {
      observer.disconnect();
      window.clearTimeout(failsafe);
    };
  }, [reduced]);

  const Component = as;
  return (
    <Component
      ref={ref as never}
      className={className}
      style={
        reduced
          ? undefined
          : {
              opacity: hidden ? 0 : 1,
              transform: hidden ? "translateY(18px)" : "none",
              transition: `opacity 600ms cubic-bezier(0.32,0.72,0,1) ${delay}s, transform 600ms cubic-bezier(0.32,0.72,0,1) ${delay}s`,
            }
      }
    >
      {children}
    </Component>
  );
}
