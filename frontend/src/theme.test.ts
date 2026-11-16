/// <reference types="node" />
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { DEFAULT_THEME, readChoice, resolveTheme } from "./lib/theme";

// Read from disk: the test run turns CSS imports into empty modules (vite.config.ts: css false).
const css = readFileSync(join(__dirname, "index.css"), "utf8");

/** The custom properties declared in the first rule whose selector is exactly `selector`. */
function block(selector: string): Record<string, string> {
  const start = css.indexOf(`${selector} {`);
  if (start < 0) throw new Error(`no rule for ${selector}`);
  const body = css.slice(css.indexOf("{", start) + 1, css.indexOf("}", start));
  return Object.fromEntries(
    [...body.matchAll(/--([\w-]+):\s*(#[0-9a-f]{6})/gi)].map((m) => [m[1] ?? "", m[2] ?? ""]),
  );
}

/** The tokens one portal sees in one theme, built the way the cascade builds them. */
function tokens(portal: string, theme: "light" | "dark"): Record<string, string> {
  const own = block(`[data-portal="${portal}"]`);
  const override =
    `[data-portal="${portal}"][data-theme="${theme}"]` in OVERRIDES(portal)
      ? block(`[data-portal="${portal}"][data-theme="${theme}"]`)
      : {};
  return {
    ...block(":root"),
    ...(theme === "dark" ? block('[data-theme="dark"]') : {}),
    ...own,
    ...override,
  };
}

function OVERRIDES(portal: string): Record<string, true> {
  const found: Record<string, true> = {};
  for (const theme of ["light", "dark"]) {
    const selector = `[data-portal="${portal}"][data-theme="${theme}"]`;
    if (css.includes(`${selector} {`)) found[selector] = true;
  }
  return found;
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * (r ?? 0) + 0.7152 * (g ?? 0) + 0.0722 * (b ?? 0);
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return ((hi ?? 0) + 0.05) / ((lo ?? 0) + 0.05);
}

/** Every text-on-background pair the components use: [text token, background token]. */
const TEXT_PAIRS: readonly [string, string][] = [
  ["ink", "page"],
  ["ink", "surface"],
  ["ink", "raised"],
  ["muted", "page"],
  ["muted", "surface"],
  ["muted", "raised"],
  ["accent", "surface"],
  ["accent", "page"],
  ["accent-ink", "accent"],
  ["accent-ink", "accent-strong"],
  ["accent-strong", "accent-soft"],
  ["nav-ink", "nav"],
  ["nav-ink", "nav-active"],
  ["good", "good-soft"],
  ["warn", "warn-soft"],
  ["bad", "bad-soft"],
  ["info", "info-soft"],
  ["neutral", "neutral-soft"],
  ["good", "surface"],
  ["bad", "surface"],
  ["warn", "surface"],
  ["ink", "good-soft"],
  ["ink", "warn-soft"],
  ["ink", "bad-soft"],
  ["inverse-ink", "inverse"],
];

const PORTALS = ["employee", "technician", "admin"] as const;

describe("D-040 themes", () => {
  for (const portal of PORTALS) {
    for (const theme of ["light", "dark"] as const) {
      it(`keeps every text pair at 4.5:1 or more in the ${theme} ${portal} portal (WCAG 1.4.3)`, () => {
        const t = tokens(portal, theme);
        const failures = TEXT_PAIRS.filter(([fg, bg]) => {
          const [a, b] = [t[fg], t[bg]];
          if (a === undefined || b === undefined) throw new Error(`missing --${fg} or --${bg}`);
          return contrast(a, b) < 4.5;
        }).map(([fg, bg]) => `${fg} on ${bg}: ${contrast(t[fg] ?? "", t[bg] ?? "").toFixed(2)}`);
        expect(failures).toEqual([]);
      });
    }
  }

  it("keeps the signed-out pages readable when the system is dark", () => {
    const t = { ...block(":root"), ...block(":root:not([data-theme])") };
    const failures = TEXT_PAIRS.filter(([fg, bg]) => contrast(t[fg] ?? "", t[bg] ?? "") < 4.5);
    expect(failures).toEqual([]);
  });

  it("keeps white text readable on the solid danger and success fills in both themes", () => {
    for (const theme of ["light", "dark"] as const) {
      const t = tokens("admin", theme);
      expect(contrast("#ffffff", t.danger ?? "")).toBeGreaterThanOrEqual(4.5);
      expect(contrast("#ffffff", t.success ?? "")).toBeGreaterThanOrEqual(4.5);
      // The active sidebar link is white on the active colour.
      for (const portal of PORTALS) {
        expect(
          contrast("#ffffff", tokens(portal, theme)["nav-active"] ?? ""),
        ).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it("keeps the three portals apart in each theme: a different accent and navigation colour", () => {
    for (const theme of ["light", "dark"] as const) {
      const accents = new Set(PORTALS.map((p) => tokens(p, theme).accent));
      const navs = new Set(PORTALS.map((p) => tokens(p, theme).nav));
      expect(accents.size).toBe(3);
      expect(navs.size).toBe(3);
    }
  });

  it("opens each portal in its own theme until someone picks", () => {
    expect(DEFAULT_THEME).toEqual({ employee: "light", technician: "dark", admin: "light" });
    expect(resolveTheme(null, "technician", false)).toBe("dark");
    expect(resolveTheme("light", "technician", true)).toBe("light");
    expect(resolveTheme("system", "employee", true)).toBe("dark");
    expect(resolveTheme("system", "employee", false)).toBe("light");
  });

  it("ignores a stored value that is not a theme", () => {
    window.localStorage.setItem("i-itsm.theme.admin", "purple");
    expect(readChoice("admin")).toBeNull();
    window.localStorage.removeItem("i-itsm.theme.admin");
  });
});
