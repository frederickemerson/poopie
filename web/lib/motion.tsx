"use client";

/**
 * Motion preferences. The reduced-motion switch genuinely disables motion: it
 * sets data-reduced-motion on <html> (which zeroes every CSS transition and
 * keyframe), wraps the tree in a MotionConfig, and makes `dur()` return 0 so
 * Framer Motion tweens complete on the first frame.
 *
 * There is deliberately no theme axis. The product ships one surface, light,
 * pinned by `data-theme="light"` in layout.tsx and rendered identically on the
 * server and the client. Reading `prefers-color-scheme` here used to flip a
 * dark-preference machine to a second palette, which meant the designed surface
 * was not the one most people saw.
 */
import { MotionConfig } from "framer-motion";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

interface Prefs {
  readonly reduced: boolean;
  toggleReduced: () => void;
  /** Seconds for a Framer transition; 0 under reduced motion. */
  dur: (ms: number) => number;
  /** Per-item stagger in seconds; 0 under reduced motion. */
  stagger: (ms: number) => number;
}

const MotionPrefs = createContext<Prefs | null>(null);

const STORE_MOTION = "poopie.reduced-motion";

/** Hard ceiling from the brief: no transition may exceed 400 ms. */
export const MAX_MOTION_MS = 400;

export function MotionPrefsProvider({ children }: { children: ReactNode }) {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const storedMotion = window.localStorage.getItem(STORE_MOTION);
    const systemReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    setReduced(storedMotion === null ? systemReduced : storedMotion === "true");
  }, []);

  useEffect(() => {
    document.documentElement.dataset.reducedMotion = String(reduced);
  }, [reduced]);

  const toggleReduced = useCallback(() => {
    setReduced((prev) => {
      window.localStorage.setItem(STORE_MOTION, String(!prev));
      return !prev;
    });
  }, []);

  const value = useMemo<Prefs>(
    () => ({
      reduced,
      toggleReduced,
      dur: (ms) => (reduced ? 0 : Math.min(ms, MAX_MOTION_MS) / 1000),
      stagger: (ms) => (reduced ? 0 : ms / 1000),
    }),
    [reduced, toggleReduced],
  );

  return (
    <MotionPrefs.Provider value={value}>
      <MotionConfig reducedMotion={reduced ? "always" : "never"} transition={{ duration: value.dur(220) }}>
        {children}
      </MotionConfig>
    </MotionPrefs.Provider>
  );
}

export function useMotionPrefs(): Prefs {
  const ctx = useContext(MotionPrefs);
  if (!ctx) throw new Error("useMotionPrefs outside MotionPrefsProvider");
  return ctx;
}
