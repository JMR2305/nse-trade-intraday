import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright configuration for trading-dashboard E2E tests.
 *
 * Uses the Nix-provided system Chromium so no separate `playwright install`
 * step is needed in this environment.
 *
 * The webServer block starts a throw-away Vite dev instance on port 5174
 * (distinct from the managed workflow port) so the tests are self-contained.
 */

const E2E_PORT = 5174;
const BASE_PATH = "/trading-dashboard/";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  retries: 0,
  reporter: [["list"], ["json", { outputFile: "e2e-results.json" }]],

  use: {
    baseURL: `http://localhost:${E2E_PORT}`,
    // Use the Nix-provided Chromium so no separate browser download is needed.
    launchOptions: {
      executablePath:
        process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ??
        "/nix/store/qa9cnw4v5xkxyip6mb9kxqfq1z4x2dx1-chromium-138.0.7204.100/bin/chromium",
      args: [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
      ],
    },
    trace: "retain-on-failure",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  webServer: {
    command: `PORT=${E2E_PORT} BASE_PATH=${BASE_PATH} pnpm exec vite --config vite.config.ts --host 0.0.0.0`,
    port: E2E_PORT,
    reuseExistingServer: false,
    timeout: 60_000,
    env: {
      PORT: String(E2E_PORT),
      BASE_PATH,
      NODE_ENV: "test",
    },
  },
});
