import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests for the three demo workflows (blueprint §14).
 * Starts the API on a freshly seeded throwaway SQLite database and the Vite dev server, unless
 * they already run. The workflows share that database, so they run one at a time, in order.
 */
const isCI = Boolean(process.env.CI);

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  forbidOnly: isCI,
  retries: isCI ? 1 : 0,
  reporter: isCI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      // Migrates and seeds a throwaway SQLite database, then serves the API on :8000.
      command: "uv run scripts/dev.py e2e-api",
      cwd: "..",
      url: "http://127.0.0.1:8000/health",
      reuseExistingServer: !isCI,
      timeout: 180_000,
    },
    {
      command: "npm run dev -- --host 127.0.0.1",
      cwd: "../frontend",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: !isCI,
      timeout: 60_000,
    },
  ],
});
