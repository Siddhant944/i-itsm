import { expect, test, type WebSocket } from "@playwright/test";

import { ADMIN, EMPLOYEE, PASSWORD, reportIncident, signIn } from "./helpers";

/**
 * P4.8: a signed-in screen holds a WebSocket through the same /api proxy, and a change
 * someone else commits arrives on it as a push naming the incident, with no content.
 */
test("live updates arrive over a WebSocket after the change commits", async ({
  browser,
}) => {
  const context = await browser.newContext();
  const page = await context.newPage();
  // Vite's hot-reload socket opens too, and React mounts effects twice in development, so
  // the first API socket may be closed at once: use whichever one the server greets.
  const greeted = new Promise<WebSocket>((resolve) => {
    page.on("websocket", (candidate) => {
      if (!/\/api\/ws$/.test(candidate.url())) return;
      candidate.on("framereceived", (frame) => {
        if (frame.payload.toString().includes('"ready"')) resolve(candidate);
      });
    });
  });
  await page.goto("/login");
  await page.getByLabel("Email").fill(ADMIN);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  const socket = await greeted;

  const pushed = socket.waitForEvent("framereceived", {
    predicate: (frame) =>
      frame.payload.toString().includes('"type":"incident"'),
  });
  const employee = await signIn(browser, EMPLOYEE);
  const id = await reportIncident(employee.page, {
    title: "Seminar hall projector flickers",
    description:
      "The projector in the seminar hall flickers every few seconds.",
    service: "Campus Wi-Fi",
    impact: "Just me",
    urgency: "It works, but badly",
  });
  const frame = JSON.parse((await pushed).payload.toString()) as Record<
    string,
    string
  >;
  expect(frame.incident_id).toBe(id);
  expect(Object.keys(frame).sort()).toEqual(["incident_id", "status", "type"]);
});
