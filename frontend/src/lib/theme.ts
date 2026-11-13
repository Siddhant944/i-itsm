import { useCallback, useEffect, useState } from "react";

import type { Portal } from "../auth/portal";

/** What the person picked; "system" follows the operating system's light or dark setting. */
export type ThemeChoice = "system" | "light" | "dark";
export type Theme = "light" | "dark";

export const THEME_CHOICES: readonly ThemeChoice[] = ["light", "dark", "system"];

/**
 * Each portal opens in its own theme until someone picks (D-040): the technician console is a
 * dark operations screen, the employee and admin portals are light. Together with the layout
 * and the accent this keeps the three portals visibly different (brief: "Difference in GUI").
 */
export const DEFAULT_THEME: Record<Portal, Theme> = {
  employee: "light",
  technician: "dark",
  admin: "light",
};

const storageKey = (portal: Portal) => `i-itsm.theme.${portal}`;

function isChoice(value: unknown): value is ThemeChoice {
  return value === "system" || value === "light" || value === "dark";
}

/** The stored choice, or null. Storage can be missing or refused (private windows). */
export function readChoice(portal: Portal): ThemeChoice | null {
  try {
    const value = window.localStorage.getItem(storageKey(portal));
    return isChoice(value) ? value : null;
  } catch {
    return null;
  }
}

function writeChoice(portal: Portal, choice: ThemeChoice): void {
  try {
    window.localStorage.setItem(storageKey(portal), choice);
  } catch {
    // Not remembered; the choice still applies until the page is reloaded.
  }
}

export function resolveTheme(
  choice: ThemeChoice | null,
  portal: Portal,
  systemDark: boolean,
): Theme {
  if (choice === null) return DEFAULT_THEME[portal];
  if (choice === "system") return systemDark ? "dark" : "light";
  return choice;
}

const DARK_QUERY = "(prefers-color-scheme: dark)";

/** jsdom (the unit tests) has no matchMedia. */
function systemPrefersDark(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(DARK_QUERY).matches;
}

export interface ThemeState {
  /** What is picked; null until the person picks, which means the portal's own default. */
  choice: ThemeChoice | null;
  theme: Theme;
  setChoice: (choice: ThemeChoice) => void;
}

/** One portal's theme: the remembered choice, the operating system's setting, and a setter. */
export function useTheme(portal: Portal): ThemeState {
  const [choice, setStored] = useState<ThemeChoice | null>(() => readChoice(portal));
  const [systemDark, setSystemDark] = useState(systemPrefersDark);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia(DARK_QUERY);
    const onChange = (event: MediaQueryListEvent) => {
      setSystemDark(event.matches);
    };
    query.addEventListener("change", onChange);
    return () => {
      query.removeEventListener("change", onChange);
    };
  }, []);
  const setChoice = useCallback(
    (next: ThemeChoice) => {
      writeChoice(portal, next);
      setStored(next);
    },
    [portal],
  );
  return { choice, theme: resolveTheme(choice, portal, systemDark), setChoice };
}

/**
 * Puts the portal and theme on <html> as well as the portal's own frame, so the page behind the
 * frame, scrollbars and native controls match. Signed out, <html> goes back to the system theme.
 */
export function useDocumentTheme(portal: Portal, theme: Theme): void {
  useEffect(() => {
    const root = document.documentElement;
    root.dataset.portal = portal;
    root.dataset.theme = theme;
    return () => {
      delete root.dataset.portal;
      delete root.dataset.theme;
    };
  }, [portal, theme]);
}
