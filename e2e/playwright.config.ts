import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests for the three demo workflows (blueprint §14).
 * Starts the API on a throwaway SQLite database and the Vite dev server, unless they already run.
 */
const isCI = Boolean(process.env.CI);

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
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
      command: "uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000",
      cwd: "../backend",
      url: "http://127.0.0.1:8000/health",
      env: { APP_ENV: "test", DATABASE_URL: "sqlite:///./e2e.db" },
      reuseExistingServer: !isCI,
      timeout: 60_000,
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
