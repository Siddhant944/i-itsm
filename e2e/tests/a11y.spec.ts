import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { ADMIN, EMPLOYEE, signIn } from "./helpers";

/**
 * P5.6: every screen of the three portals passes axe-core's WCAG 2.1 A/AA rules with no serious
 * or critical violation — labels on every control, names on every button, enough contrast.
 * Minor and moderate findings are printed, not failed, so the gate stays one we can keep.
 */
const PORTALS = [
  {
    email: EMPLOYEE,
    screens: ["/employee/incidents", "/employee/report"],
  },
  {
    email: "lead@campus.edu",
    screens: [
      "/technician/queue",
      "/technician/team",
      "/technician/workload",
      "/technician/report",
      "/technician/reports",
    ],
  },
  {
    email: ADMIN,
    screens: [
      "/admin/dashboard",
      "/admin/incidents",
      "/admin/violations",
      "/admin/audit",
      "/admin/users",
      "/admin/config/categories",
      "/admin/config/services",
      "/admin/config/sla",
      "/admin/config/assignment",
    ],
  },
];

for (const { email, screens } of PORTALS) {
  test(`every screen ${email} can reach has no serious accessibility problem`, async ({
    browser,
  }) => {
    const { page, context } = await signIn(browser, email);
    const problems: string[] = [];
    for (const path of screens) {
      await page.goto(path);
      await expect(page.locator("main")).toBeVisible();
      // Wait for the screen's data, not its skeleton.
      await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
      const { violations } = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .analyze();
      const serious = violations.filter(
        (v) => v.impact === "serious" || v.impact === "critical",
      );
      for (const v of violations) {
        console.log(
          `${path}: ${v.impact ?? "?"} ${v.id} (${v.nodes.length}) ${v.nodes
            .slice(0, 2)
            .map((n) => n.target.join(" "))
            .join(" | ")}`,
        );
      }
      problems.push(...serious.map((v) => `${path} ${v.id}: ${v.help}`));
    }
    await context.close();
    expect(problems).toEqual([]);
  });
}
