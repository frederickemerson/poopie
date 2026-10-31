"use client";

/**
 * Motion and theme preferences. The reduced-motion switch genuinely disables
 * motion: it sets data-reduced-motion on <html> (which zeroes every CSS
 * transition and keyframe), wraps the tree in a MotionConfig, and makes `dur()`
 * return 0 so Framer Motion tweens complete on the first frame.
 */
import { MotionConfig } from "framer-motion";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type Theme = "dark" | "light";

interface Prefs {
  readonly reduced: boolean;
  readonly theme: Theme;
  toggleReduced: () => void;
  toggleTheme: () => void;
  /** Seconds for a Framer transition; 0 under reduced motion. */
  dur: (ms: number) => number;
  /** Per-item stagger in seconds; 0 under reduced motion. */
  stagger: (ms: number) => number;
}

const MotionPrefs = createContext<Prefs | null>(null);

const STORE_MOTION = "autsg.reduced-motion";
const STORE_THEME = "autsg.theme";

/** Hard ceiling from the brief: no transition may exceed 400 ms. */
export const MAX_MOTION_MS = 400;

export function MotionPrefsProvider({ children }: { children: ReactNode }) {
  const [reduced, setReduced] = useState(false);
  // Light is the designed surface and the value layout.tsx renders on the
  // server, so starting there means the first paint is already correct. This
  // defaulted to "dark" while the server rendered "light", which overwrote the
  // attribute on hydration and made the light theme unreachable.
  const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => {
    const storedMotion = window.localStorage.getItem(STORE_MOTION);
    const systemReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    setReduced(storedMotion === null ? systemReduced : storedMotion === "true");
    // Stored choice first, then the operating system's, matching how reduced
    // motion resolves immediately above.
    const storedTheme = window.localStorage.getItem(STORE_THEME);
    if (storedTheme === "light" || storedTheme === "dark") {
      setTheme(storedTheme);
    } else if (window.matchMedia("(prefers-color-scheme: dark)").matches) {
      setTheme("dark");
    }
  }, []);

  useEffect(() => {
    document.documentElement.dataset.reducedMotion = String(reduced);
    document.documentElement.dataset.theme = theme;
  }, [reduced, theme]);

  const toggleReduced = useCallback(() => {
    setReduced((prev) => {
      window.localStorage.setItem(STORE_MOTION, String(!prev));
      return !prev;
    });
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme((prev) => {
      const next = prev === "dark" ? "light" : "dark";
      window.localStorage.setItem(STORE_THEME, next);
      return next;
    });
  }, []);

  const value = useMemo<Prefs>(
    () => ({
      reduced,
      theme,
      toggleReduced,
      toggleTheme,
      dur: (ms) => (reduced ? 0 : Math.min(ms, MAX_MOTION_MS) / 1000),
      stagger: (ms) => (reduced ? 0 : ms / 1000),
    }),
    [reduced, theme, toggleReduced, toggleTheme],
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
