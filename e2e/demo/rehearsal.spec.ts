import { expect, test, type Page } from "@playwright/test";

import {
  ADMIN,
  EMPLOYEE,
  assigneeName,
  emailOf,
  reportIncident,
  signIn,
  tokenFor,
} from "../tests/helpers";

/**
 * Walks docs/DEMO_SCRIPT.md shot by shot on a fresh `make demo-reset` instance: the staged
 * incidents, the three workflows and the admin tour, with Workflow 3's escalations timed on the
 * real ×10 clock. If this passes, the takes will behave as the script says.
 */
test.describe.configure({ mode: "serial" });

const API = "http://127.0.0.1:8000";
const FEES = "Fee Payment Portal";
const EVERYONE = "Many people or everyone";
const BLOCKED = "I am blocked";

let wf1 = "";

async function apiGet<T>(page: Page, token: string, path: string): Promise<T> {
  const response = await page.request.get(`${API}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(response.ok(), `${path}: ${String(response.status())}`).toBeTruthy();
  return (await response.json()) as T;
}

test("staged: the look-alike and the Wi-Fi ticket are in place", async ({
  browser,
}) => {
  const admin = await signIn(browser, ADMIN);
  const token = await tokenFor(admin.page, ADMIN);
  const lookalike = await apiGet<{ title: string; status: string }>(
    admin.page,
    token,
    "/incidents/INC-2026-0421",
  );
  expect(lookalike.title).toBe("Fee payment portal page is very slow");
  const wifi = await apiGet<{ title: string; status: string }>(
    admin.page,
    token,
    "/incidents/INC-2026-0422",
  );
  expect(wifi.title).toBe("Wi-Fi keeps dropping in the library reading room");
  expect(wifi.status).toBe("ASSIGNED");
  // D-041: the old outages are settled, so the map starts green and Workflow 3 turns it red.
  await admin.page.goto("/admin/health");
  await expect(admin.page.locator('[data-state="ok"]').first()).toBeVisible();
  await expect(
    admin.page.locator('[data-state="outage"], [data-state="degraded"]'),
  ).toHaveCount(0);
  await admin.page.goto("/admin/audit");
  await admin.page.getByRole("button", { name: "Verify integrity" }).click();
  await expect(admin.page.getByTestId("integrity-result")).toContainText("✓");
  await admin.context.close();
});

test("shots 4–5, Workflow 1: report, AI suggestion, duplicate hint, P1, assignment", async ({
  browser,
}) => {
  const devika = await signIn(browser, EMPLOYEE);
  const page = devika.page;
  await page.getByRole("link", { name: "Report an incident" }).first().click();
  await page
    .getByLabel("What is the problem, in one line?")
    .fill("Fee payment page fails at checkout");
  await page
    .getByLabel("What happened?")
    .fill(
      "The fee portal shows an error when I try to pay my semester fee; the payment does not go through.",
    );
  await page
    .getByLabel("Which service is affected?")
    .selectOption({ label: FEES });
  await expect(page.getByTestId("ai-suggestion")).toContainText(
    "Suggested category",
  );
  await expect(page.getByTestId("ai-suggestion")).toContainText("%");
  await expect(page.getByTestId("similar-incidents")).toContainText(
    "INC-2026-0421",
  );
  await page.getByLabel(EVERYONE).check();
  await page.getByLabel(BLOCKED).check();
  await page.getByRole("button", { name: "Submit incident" }).click();
  await page.waitForURL(/\/incidents\/INC-\d{4}-\d{4}$/);
  wf1 = page.url().split("/").at(-1) ?? "";
  await expect(page.getByTestId("incident-status-bar")).toContainText("P1");
  await expect(page.getByTestId("key-facts")).toContainText("Respond by");
  const assignee = await assigneeName(page);

  const admin = await signIn(browser, ADMIN);
  await admin.page.goto(`/admin/incidents/${wf1}`);
  await expect(admin.page.getByTestId("candidate").first()).toBeVisible();

  const tech = await signIn(browser, await emailOf(page, assignee));
  await expect(
    tech.page.getByRole("table", { name: "My queue" }),
  ).toContainText(wf1);
  for (const session of [devika, admin, tech]) await session.context.close();
});

test("shot 6, Workflow 3: follow instead, duplicate, correlation, health map, escalation", async ({
  browser,
}) => {
  expect(wf1, "Workflow 1 runs first").not.toBe("");
  const devika = await signIn(browser, EMPLOYEE);
  // (a) Devika reports a payment problem; another employee starts a similar one and follows it.
  const payment = await reportIncident(devika.page, {
    title: "Payment application unavailable",
    description: "The fee payment page will not open at all.",
    service: FEES,
    impact: EVERYONE,
    urgency: BLOCKED,
  });
  const kabir = await signIn(browser, "kabir.jain@campus.edu");
  await kabir.page
    .getByRole("link", { name: "Report an incident" })
    .first()
    .click();
  await kabir.page
    .getByLabel("What is the problem, in one line?")
    .fill("Payment transaction failing");
  await kabir.page
    .getByLabel("What happened?")
    .fill("My fee payment fails at the last step.");
  await kabir.page
    .getByLabel("Which service is affected?")
    .selectOption({ label: FEES });
  await kabir.page.getByLabel(EVERYONE).check();
  await kabir.page.getByLabel(BLOCKED).check();
  const hint = kabir.page.getByTestId("similar-incidents");
  await expect(hint).toContainText(payment);
  await hint
    .getByRole("listitem")
    .filter({ hasText: payment })
    .getByRole("button", { name: "Follow this instead" })
    .click();
  await kabir.page.getByRole("button", { name: `Follow ${payment}` }).click();
  await expect(kabir.page.getByTestId("linked-duplicate")).toContainText(
    payment,
  );

  // (b) The technician holding a payment ticket sees the other one as a possible duplicate.
  const holder = await signIn(
    browser,
    await emailOf(devika.page, await assigneeName(devika.page)),
  );
  await holder.page.goto(`/technician/incidents/${payment}`);
  await expect(
    holder.page.getByTestId("possible-duplicate").first(),
  ).toBeVisible();

  // (c) The database P1, reported by a third employee: the escalation clock starts now.
  const anika = await signIn(browser, "anika.chopra@campus.edu");
  const database = await reportIncident(anika.page, {
    title: "Database cluster not responding",
    description: "Every query to the main database times out since 9 am.",
    service: "Database Cluster",
    impact: EVERYONE,
    urgency: BLOCKED,
  });
  const reportedAt = Date.now();

  // (d) Correlation on the fee-portal incident, then the health map.
  const admin = await signIn(browser, ADMIN);
  await admin.page.goto(`/admin/incidents/${payment}`);
  await expect(admin.page.getByTestId("root-cause-hint")).toContainText(
    "Database Cluster",
  );
  await admin.page.goto("/admin/health");
  await expect(
    admin.page.locator('[data-state="outage"]', {
      hasText: "Database Cluster",
    }),
  ).toBeVisible();

  // (e) Nobody acknowledges: level 1, 2 and 3 on the ×10 clock, about 30, 60 and 90 s in.
  const token = await tokenFor(admin.page, ADMIN);
  const seen: string[] = [];
  for (const level of [1, 2, 3]) {
    await expect
      .poll(
        async () =>
          (
            await apiGet<{ escalation_level: number }>(
              admin.page,
              token,
              `/incidents/${database}`,
            )
          ).escalation_level,
        { timeout: 150_000, intervals: [2_000] },
      )
      .toBeGreaterThanOrEqual(level);
    seen.push(
      `level ${String(level)} after ${String(Math.round((Date.now() - reportedAt) / 1000))} s`,
    );
  }
  test.info().annotations.push({
    type: "escalation timing",
    description: seen.join(", "),
  });
  console.log(
    `Workflow 3 escalation (real seconds after the report): ${seen.join(", ")}`,
  );
  await admin.page.goto("/admin/violations");
  await expect(admin.page.getByRole("main")).toContainText(database);
  for (const session of [devika, kabir, holder, anika, admin])
    await session.context.close();
});

test("shot 8: the admin tour", async ({ browser }) => {
  const admin = await signIn(browser, ADMIN);
  const page = admin.page;
  await page.goto("/admin/config/categories");
  await page.getByRole("button", { name: "Add a category" }).click();
  await page.getByLabel("Name").fill("Printer");
  await page.getByRole("button", { name: "Add category" }).click();
  await expect(page.getByRole("main")).toContainText("Printer");
  for (const path of [
    "/admin/config/sla",
    "/admin/config/assignment",
    "/admin/incidents",
    "/admin/dashboard",
  ]) {
    await page.goto(path);
    await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
    await expect(page.getByRole("alert")).toHaveCount(0);
  }
  await admin.context.close();

  const devika = await signIn(browser, EMPLOYEE);
  await devika.page
    .getByRole("link", { name: "Report an incident" })
    .first()
    .click();
  await expect(
    devika.page
      .getByLabel("Category", { exact: true })
      .locator("option", { hasText: "Printer" }),
  ).toHaveCount(1);
  await devika.context.close();
});

test("shot 9, Workflow 2: the staged Wi-Fi ticket from acknowledgement to closure", async ({
  browser,
}) => {
  const id = "INC-2026-0422";
  const employee = await signIn(browser, EMPLOYEE);
  const reporter = employee.page;
  const technician = await signIn(browser, "technician@campus.edu");
  const tech = technician.page;
  await tech.getByRole("table", { name: "My queue" }).getByText(id).click();
  const actions = tech.getByTestId("actions");
  const status = (page: Page, text: string) =>
    expect(
      page.getByTestId("incident-status-bar").getByText(text, { exact: true }),
    ).toBeVisible();

  await actions.getByRole("button", { name: "Acknowledge" }).click();
  await status(tech, "Acknowledged");
  await actions.getByRole("button", { name: "Start work" }).click();
  await status(tech, "In progress");
  await actions.getByRole("button", { name: "Request information" }).click();
  await tech
    .getByLabel("What do you need to know?")
    .fill("Which floor and which device?");
  await tech.getByRole("button", { name: "Send request" }).click();
  await expect(tech.getByTestId("sla-chip")).toHaveText("SLA paused");

  await reporter.goto(`/employee/incidents/${id}`);
  await expect(
    reporter.getByText("The technician needs more information from you"),
  ).toBeVisible();
  await reporter
    .getByLabel("Your message")
    .fill("First floor, my laptop and my phone.");
  await reporter.getByRole("button", { name: "Send" }).click();
  await status(reporter, "In progress");

  await tech.reload();
  await expect(tech.getByTestId("past-fix").first()).toBeVisible();
  await actions.getByRole("button", { name: "Resolve" }).click();
  await tech
    .getByLabel("What fixed it?")
    .fill("Restarted the first-floor access point.");
  await tech.getByRole("button", { name: "Mark as resolved" }).click();
  await status(tech, "Resolved");

  await reporter.reload();
  await reporter.getByRole("button", { name: "No, it is not fixed" }).click();
  await reporter
    .getByLabel("What is still wrong?")
    .fill("It still drops near the windows.");
  await reporter.getByRole("button", { name: "Reopen the incident" }).click();
  await status(reporter, "In progress");

  await tech.reload();
  await actions.getByRole("button", { name: "Resolve" }).click();
  await tech
    .getByLabel("What fixed it?")
    .fill("Added a second access point by the windows.");
  await tech.getByRole("button", { name: "Mark as resolved" }).click();
  await status(tech, "Resolved");

  await reporter.reload();
  await reporter.getByRole("button", { name: "Yes, confirm the fix" }).click();
  await reporter.getByRole("button", { name: "5 out of 5" }).click();
  await reporter.getByRole("button", { name: "Confirm and rate" }).click();
  await expect(reporter.getByText(/Fix verified · rated 5\/5/)).toBeVisible();

  await tech.reload();
  await actions.getByRole("button", { name: "Close incident" }).click();
  await status(tech, "Closed");

  await reporter.getByRole("link", { name: "Report by chat" }).click();
  await expect(reporter.getByRole("main")).toBeVisible();
  await expect(reporter.getByRole("alert")).toHaveCount(0);
  for (const session of [employee, technician]) await session.context.close();
});
