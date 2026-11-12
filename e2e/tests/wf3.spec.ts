import { expect, test } from "@playwright/test";

import {
  ADMIN,
  EMPLOYEE,
  advanceClock,
  assigneeName,
  emailOf,
  reportIncident,
  signIn,
  tokenFor,
} from "./helpers";

const SECOND_REPORTER = "kabir.jain@campus.edu";
const THIRD_REPORTER = "anika.chopra@campus.edu";
const EVERYONE = "Many people or everyone";
const BLOCKED = "I am blocked";
const FEES = "Fee Payment Portal";
/** Gold P1 response target (§5.2): escalation happens just after each one passes (BR-08). */
const P1_RESPONSE_SECONDS = 5 * 60;

/**
 * Workflow 3 (blueprint §11, §14): the Fee Payment Portal is down. Three people report it in
 * their own words; the duplicates are linked, the dependency graph points at the database,
 * and nobody acknowledging the P1 walks it up the escalation chain. Runs on the fake clock.
 */
test("WF3: three payment tickets → duplicates linked → correlation → escalation", async ({
  browser,
}) => {
  test.setTimeout(240_000);

  // The shared service fails first: a P1 on the Database Cluster.
  const devika = await signIn(browser, EMPLOYEE);
  const database = await reportIncident(devika.page, {
    title: "Database cluster not responding",
    description: "Every query to the main database times out since 9 am.",
    service: "Database Cluster",
    impact: EVERYONE,
    urgency: BLOCKED,
  });

  // INC101 of the brief.
  const first = await reportIncident(devika.page, {
    title: "Payment application unavailable",
    description: "The fee payment page will not open at all.",
    service: FEES,
    impact: EVERYONE,
    urgency: BLOCKED,
  });

  // INC102: someone else, other words. The form shows the open ticket while they type,
  // and they carry on anyway — it is only advice.
  const kabir = await signIn(browser, SECOND_REPORTER);
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
  const kabirHint = kabir.page.getByTestId("similar-incidents");
  await expect(kabirHint).toContainText(first);
  await expect(kabirHint).toContainText("same service");
  await kabir.page.getByLabel(EVERYONE).check();
  await kabir.page.getByLabel(BLOCKED).check();
  await kabir.page.getByRole("button", { name: "Submit incident" }).click();
  await kabir.page.waitForURL(/\/incidents\/INC-\d{4}-\d{4}$/);
  const second = kabir.page.url().split("/").at(-1) ?? "";

  // INC103: this reporter follows the existing ticket instead of filing another.
  const anika = await signIn(browser, THIRD_REPORTER);
  await anika.page
    .getByRole("link", { name: "Report an incident" })
    .first()
    .click();
  await anika.page
    .getByLabel("What is the problem, in one line?")
    .fill("Unable to make payment");
  await anika.page
    .getByLabel("What happened?")
    .fill("Cannot pay my semester fees online.");
  await anika.page
    .getByLabel("Which service is affected?")
    .selectOption({ label: FEES });
  await anika.page.getByLabel(EVERYONE).check();
  await anika.page.getByLabel(BLOCKED).check();
  const anikaHint = anika.page.getByTestId("similar-incidents");
  await expect(anikaHint).toContainText(first);
  await anikaHint
    .getByRole("listitem")
    .filter({ hasText: first })
    .getByRole("button", { name: "Follow this instead" })
    .click();
  await anika.page.getByRole("button", { name: `Follow ${first}` }).click();
  await anika.page.waitForURL(/\/incidents\/INC-\d{4}-\d{4}$/);
  await expect(anika.page.getByTestId("linked-duplicate")).toContainText(
    `same problem as ${first}`,
  );

  // The technician holding INC102 sees the possible duplicate and confirms it.
  const assignee = await assigneeName(kabir.page);
  const tech = await signIn(browser, await emailOf(kabir.page, assignee));
  await tech.page.goto(`/technician/incidents/${second}`);
  const candidate = tech.page
    .getByTestId("possible-duplicate")
    .filter({ hasText: first });
  await expect(candidate).toContainText("same service");
  await candidate.getByRole("button", { name: "Confirm duplicate…" }).click();
  await candidate
    .getByRole("button", { name: `Cancel ${second} as its duplicate` })
    .click();
  await expect(
    tech.page
      .getByTestId("incident-status-bar")
      .getByText("Cancelled", { exact: true }),
  ).toBeVisible();

  // Kabir is told where his report went.
  await kabir.page.reload();
  await expect(kabir.page.getByTestId("linked-duplicate")).toContainText(first);

  // The admin opens INC101: two reports are linked to it, and the dependency graph names
  // the database outage as the likely root cause.
  const admin = await signIn(browser, ADMIN);
  await admin.page.goto(`/admin/incidents/${first}`);
  await expect(admin.page.getByTestId("duplicate-count")).toContainText(
    "2 other reports",
  );
  await expect(admin.page.getByTestId("root-cause-hint")).toContainText(
    "Database Cluster",
  );
  await expect(
    admin.page.getByTestId("related-incident").filter({ hasText: database }),
  ).toContainText("Fee Payment Portal → Database Cluster");

  // Nobody acknowledges the P1. Just after each response target it moves up a level:
  // Team Lead, then Administrator (BR-08).
  const token = await tokenFor(admin.page, ADMIN);
  const once = await advanceClock(admin.page, token, P1_RESPONSE_SECONDS + 1);
  expect(once.escalated).toContain(first);
  await admin.page.reload();
  await expect(admin.page.getByText("Escalated · level 1")).toBeVisible();

  const twice = await advanceClock(admin.page, token, P1_RESPONSE_SECONDS);
  expect(twice.escalated).toContain(first);
  await admin.page.reload();
  await expect(admin.page.getByText("Escalated · level 2")).toBeVisible();

  // Every step is on the incident's audit trail (BR-10).
  const trail = admin.page
    .locator("section", { hasText: "Audit trail" })
    .last();
  await expect(trail).toContainText(/escalated/i);
});
