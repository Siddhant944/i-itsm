import { defineConfig, devices } from "@playwright/test";

/**
 * The demo rehearsal (docs/DEMO_SCRIPT.md, "Rehearse first"). It runs against an instance that
 * `make demo-reset` is already serving, on the real ×10 clock, and starts no servers of its own.
 * It changes the demo data, so run `make demo-reset` again before recording.
 */
export default defineConfig({
  testDir: ".",
  fullyParallel: false,
  workers: 1,
  timeout: 240_000,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
