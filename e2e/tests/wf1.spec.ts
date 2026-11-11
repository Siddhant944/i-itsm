import { expect, test } from "@playwright/test";

import {
  ADMIN,
  EMPLOYEE,
  assigneeName,
  detail,
  emailOf,
  reportIncident,
  signIn,
} from "./helpers";

/**
 * Workflow 1 (blueprint §14): report → classification → priority → SLA → smart assignment →
 * notification, ending on the audit trail.
 */
test("WF1: a reported incident is classified, prioritised, put on an SLA and assigned", async ({
  browser,
}) => {
  const employee = await signIn(browser, EMPLOYEE);
  const page = employee.page;
  await expect(
    page.getByRole("heading", { name: "My incidents" }),
  ).toBeVisible();

  // The AI's category is offered with its confidence, and applied only when asked.
  await page.getByRole("link", { name: "Report an incident" }).first().click();
  await page
    .getByLabel("What is the problem, in one line?")
    .fill("Wifi keeps dropping");
  await page
    .getByLabel("What happened?")
    .fill("The wifi network disconnects every few minutes in the library.");
  const suggestion = page.getByTestId("ai-suggestion");
  await expect(suggestion).toContainText("Suggested category: Network");
  await expect(suggestion).toContainText("confidence");
  await expect(page.getByLabel("Category")).toHaveValue("");
  await suggestion.getByRole("button", { name: "Use this suggestion" }).click();
  await expect(suggestion).toContainText("Applied");

  await page
    .getByLabel("Which service is affected?")
    .selectOption({ label: "Campus Wi-Fi" });
  await page.getByLabel("Many people or everyone").check();
  await page.getByLabel("I am blocked").check();
  await page.getByRole("button", { name: "Submit incident" }).click();
  await page.waitForURL(/\/incidents\/INC-\d{4}-\d{4}$/);
  const id = page.url().split("/").at(-1) ?? "";

  // Classified, prioritised from the three plain-language answers, on the clock and assigned.
  await expect(
    page.getByRole("heading", { name: "Wifi keeps dropping" }),
  ).toBeVisible();
  await expect(page.getByText("Assigned", { exact: true })).toBeVisible();
  await expect(page.getByText(/^P[12] /)).toBeVisible();
  await expect(page.getByTestId("sla-chip")).toContainText("Response due in");
  expect(await detail(page, "Category")).toBe("Network");
  const assignee = await assigneeName(page);

  // The incident is in the reporter's list.
  await page.getByRole("link", { name: "My incidents" }).click();
  await expect(page.getByRole("table", { name: "My incidents" })).toContainText(
    id,
  );

  // The assignee was notified in-app and finds it in their queue.
  const technician = await signIn(browser, await emailOf(page, assignee));
  await expect(
    technician.page.getByRole("table", { name: "My queue" }),
  ).toContainText(id);
  await technician.page
    .getByRole("button", { name: /Notifications, \d+ unread/ })
    .click();
  await expect(
    technician.page.getByRole("region", { name: "Notifications" }),
  ).toContainText(id);

  // An admin finds it by id and reads its audit trail.
  const admin = await signIn(browser, ADMIN);
  await admin.page
    .getByRole("link", { name: "Incidents", exact: true })
    .click();
  await admin.page.getByLabel("Incident ID").fill(id);
  await admin.page.getByRole("button", { name: "Apply filters" }).click();
  await expect(admin.page.getByTestId("result-count")).toContainText(
    "1 incident ",
  );
  await admin.page
    .getByRole("table", { name: "Search results" })
    .getByText(id)
    .click();
  const trail = admin.page
    .locator("section", { hasText: "Audit trail" })
    .last();
  await expect(trail).toContainText("Incident created");
  await expect(trail).toContainText("Incident state changed");
  // Smart assignment shows who it would pick and why.
  await expect(admin.page.getByTestId("candidate").first()).toContainText(
    "skills",
  );

  await Promise.all(
    [employee, technician, admin].map((s) => s.context.close()),
  );
});

test("WF1: another employee cannot open someone else's incident (BR-01)", async ({
  browser,
}) => {
  const owner = await signIn(browser, EMPLOYEE);
  const id = await reportIncident(owner.page, {
    title: "Printer out of toner",
    description: "The printer on the second floor prints blank pages.",
    service: "Printing Service",
    impact: "Just me",
    urgency: "I have a workaround",
  });

  const other = await owner.context.browser()?.newContext();
  if (other === undefined) throw new Error("no browser");
  const page = await other.newPage();
  await page.goto("/register");
  await page.getByLabel("Full name").fill("Curious Colleague");
  await page
    .getByLabel("Email")
    .fill(`curious.${String(Date.now())}@campus.edu`);
  await page.getByLabel("Password").fill("a long password");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(
    page.getByRole("heading", { name: "My incidents" }),
  ).toBeVisible();
  await expect(
    page.getByText("You have not reported anything yet"),
  ).toBeVisible();

  await page.goto(`/employee/incidents/${id}`);
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Printer out of toner" }),
  ).toHaveCount(0);

  await Promise.all([owner.context.close(), other.close()]);
});
