import {
  expect,
  type Browser,
  type BrowserContext,
  type Page,
} from "@playwright/test";

/** Every seeded account has this password (README: demo accounts). */
export const PASSWORD = "demo1234";
export const EMPLOYEE = "employee@campus.edu";
export const ADMIN = "admin@campus.edu";

const API = "http://127.0.0.1:8000";

export interface Session {
  context: BrowserContext;
  page: Page;
}

/** Sign in through the real form, in a browser context of its own (one person per tab). */
export async function signIn(
  browser: Browser,
  email: string,
): Promise<Session> {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByTestId("current-user")).toBeVisible();
  return { context, page };
}

/**
 * The sign-in email of the person with this name. Assignment picks whoever scores best, so a
 * test learns the assignee's name from the screen and looks up how that person signs in.
 */
export async function emailOf(page: Page, fullName: string): Promise<string> {
  const login = await page.request.post(`${API}/auth/login`, {
    data: { email: ADMIN, password: PASSWORD },
  });
  const { access_token: token } = (await login.json()) as {
    access_token: string;
  };
  const users = await page.request.get(`${API}/users`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const found = (
    (await users.json()) as { full_name: string; email: string }[]
  ).find((user) => user.full_name === fullName);
  if (found === undefined) throw new Error(`No user called ${fullName}`);
  return found.email;
}

export interface Report {
  title: string;
  description: string;
  service: string;
  impact: string;
  urgency: string;
}

/** Fill and submit the intake form; resolves on the new incident's page with its id. */
export async function reportIncident(
  page: Page,
  report: Report,
): Promise<string> {
  await page.getByRole("link", { name: "Report an incident" }).first().click();
  await page.getByLabel("What is the problem, in one line?").fill(report.title);
  await page.getByLabel("What happened?").fill(report.description);
  await page
    .getByLabel("Which service is affected?")
    .selectOption({ label: report.service });
  await page.getByLabel(report.impact).check();
  await page.getByLabel(report.urgency).check();
  await page.getByRole("button", { name: "Submit incident" }).click();
  await page.waitForURL(/\/incidents\/INC-\d{4}-\d{4}$/);
  return page.url().split("/").at(-1) ?? "";
}

/** The value shown beside a label in the incident's Details card. */
export async function detail(page: Page, label: string): Promise<string> {
  const value = page
    .locator("dt", { hasText: label })
    .locator("xpath=following-sibling::dd[1]");
  return (await value.innerText()).trim();
}

/** Who the incident on screen is assigned to, once the name has loaded. */
export async function assigneeName(page: Page): Promise<string> {
  await expect
    .poll(() => detail(page, "Assigned to"), {
      message: "the incident should be assigned",
    })
    .toMatch(/^(?!Unassigned$|…$|User \d+$).+/);
  return detail(page, "Assigned to");
}

/** A bearer token for ``email``, for the few steps a person would not click (moving time). */
export async function tokenFor(page: Page, email: string): Promise<string> {
  const login = await page.request.post(`${API}/auth/login`, {
    data: { email, password: PASSWORD },
  });
  expect(login.ok()).toBeTruthy();
  const { access_token: token } = (await login.json()) as {
    access_token: string;
  };
  return token;
}

/** D-009: move the fake clock forward and run the SLA monitor, as the scheduler would. */
export async function advanceClock(
  page: Page,
  token: string,
  seconds: number,
): Promise<{ escalated: string[] }> {
  const moved = await page.request.post(`${API}/dev/clock/advance`, {
    data: { seconds, tick: true },
    headers: { Authorization: `Bearer ${token}` },
    timeout: 120_000,
  });
  expect(moved.ok(), await moved.text()).toBeTruthy();
  return (await moved.json()) as { escalated: string[] };
}
