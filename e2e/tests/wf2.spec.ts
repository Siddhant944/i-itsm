import { expect, test } from "@playwright/test";

import {
  ADMIN,
  EMPLOYEE,
  assigneeName,
  emailOf,
  reportIncident,
  signIn,
} from "./helpers";

/**
 * Workflow 2 (blueprint §14): acknowledge → request info (clock paused) → reply → resolve →
 * reject → resolve → verify and rate → closed, with an illegal transition refused on the way.
 */
test("WF2: an incident is worked from acknowledgement to closure", async ({
  browser,
}) => {
  const employee = await signIn(browser, EMPLOYEE);
  const reporter = employee.page;
  const id = await reportIncident(reporter, {
    title: "Cannot sign in to the LMS",
    description: "The login page says my account is locked since this morning.",
    service: "Learning Management System",
    impact: "Just me",
    urgency: "It works, but badly",
  });
  const assignee = await assigneeName(reporter);

  const technician = await signIn(browser, await emailOf(reporter, assignee));
  const tech = technician.page;
  await tech.getByRole("table", { name: "My queue" }).getByText(id).click();
  const actions = tech.getByTestId("actions");

  // Only the next legal step is offered: no resolving an incident nobody has acknowledged.
  await expect(actions.getByRole("button", { name: "Resolve" })).toHaveCount(0);
  await actions.getByRole("button", { name: "Acknowledge" }).click();
  await expect(
    tech.getByText("Acknowledged", { exact: true }).first(),
  ).toBeVisible();
  await expect(tech.getByTestId("sla-chip")).toContainText("Resolution due in");

  // ...and the API refuses it too, whatever the screen shows.
  const refused = await tech.evaluate(async (incidentId) => {
    const response = await fetch(`/api/incidents/${incidentId}/resolve`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${window.sessionStorage.getItem("iitsm.token") ?? ""}`,
      },
      body: JSON.stringify({ summary: "Skipping ahead" }),
    });
    const body = (await response.json()) as { error: { code: string } };
    return { status: response.status, code: body.error.code };
  }, id);
  expect(refused).toEqual({ status: 409, code: "invalid_state_transition" });

  await actions.getByRole("button", { name: "Start work" }).click();
  await expect(tech.getByText("In progress", { exact: true })).toBeVisible();

  // Asking the reporter pauses the SLA clock.
  await actions.getByRole("button", { name: "Request information" }).click();
  await tech
    .getByLabel("What do you need to know?")
    .fill("Which browser are you using?");
  await tech.getByRole("button", { name: "Send request" }).click();
  await expect(tech.getByText("On hold", { exact: true })).toBeVisible();
  await expect(tech.getByTestId("sla-chip")).toHaveText("SLA paused");

  // The reporter sees the question, replies, and the incident resumes (D-006).
  await reporter.reload();
  await expect(
    reporter.getByText("The technician needs more information from you"),
  ).toBeVisible();
  await expect(
    reporter.getByText("Which browser are you using?").first(),
  ).toBeVisible();
  await reporter.getByLabel("Your message").fill("Firefox on the lab PCs.");
  await reporter.getByRole("button", { name: "Send" }).click();
  await expect(
    reporter.getByText("In progress", { exact: true }),
  ).toBeVisible();

  // First fix, which the reporter rejects.
  await tech.reload();
  await expect(tech.getByText("Firefox on the lab PCs.")).toBeVisible();
  await tech
    .getByTestId("actions")
    .getByRole("button", { name: "Resolve" })
    .click();
  await tech.getByLabel("What fixed it?").fill("Unlocked the account.");
  await tech.getByRole("button", { name: "Mark as resolved" }).click();
  await expect(
    tech.getByText("Resolved", { exact: true }).first(),
  ).toBeVisible();

  await reporter.reload();
  await reporter.getByRole("button", { name: "No, it is not fixed" }).click();
  await reporter.getByLabel("What is still wrong?").fill("Still locked out.");
  await reporter.getByRole("button", { name: "Reopen the incident" }).click();
  await expect(
    reporter.getByText("In progress", { exact: true }),
  ).toBeVisible();
  await expect(reporter.getByText("Reopened ×1")).toBeVisible();

  // Second fix, verified and rated.
  await tech.reload();
  await tech
    .getByTestId("actions")
    .getByRole("button", { name: "Resolve" })
    .click();
  await tech
    .getByLabel("What fixed it?")
    .fill("Reset the password and cleared the lockout.");
  await tech.getByRole("button", { name: "Mark as resolved" }).click();
  await expect(
    tech.getByText("Resolved", { exact: true }).first(),
  ).toBeVisible();

  await reporter.reload();
  await reporter.getByRole("button", { name: "Yes, confirm the fix" }).click();
  await reporter.getByRole("button", { name: "5 out of 5" }).click();
  await reporter.getByRole("button", { name: "Confirm and rate" }).click();
  await expect(reporter.getByText(/Fix verified · rated 5\/5/)).toBeVisible();

  await tech.reload();
  await tech
    .getByTestId("actions")
    .getByRole("button", { name: "Close incident" })
    .click();
  await expect(tech.getByText("Closed", { exact: true }).first()).toBeVisible();
  await expect(
    tech.getByText("Nothing to do on this incident right now."),
  ).toBeVisible();

  // The whole story is on the audit trail, and the chain verifies.
  const admin = await signIn(browser, ADMIN);
  await admin.page.goto(`/admin/incidents/${id}`);
  const trail = admin.page
    .locator("section", { hasText: "Audit trail" })
    .last();
  await expect(trail.getByText("Incident state changed")).toHaveCount(11);
  await admin.page.getByRole("link", { name: "Audit log" }).click();
  await admin.page.getByRole("button", { name: "Verify integrity" }).click();
  await expect(admin.page.getByTestId("integrity-result")).toContainText(
    "the chain is intact",
  );

  await Promise.all(
    [employee, technician, admin].map((s) => s.context.close()),
  );
});
