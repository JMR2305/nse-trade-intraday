/**
 * E2E: Health card shows DEGRADED in the live browser
 *
 * Task 64 — confirms the wiring from API response → React state → DOM
 * is intact end-to-end in a real browser.  A unit test can verify the
 * logic; only a browser test can catch:
 *   - wrong React Query key (query fires but result goes to the wrong hook)
 *   - prop not forwarded to <StatusBadge>
 *   - isAlert guard miscalculated (banner never mounts)
 *   - wrong data-testid (selector drift)
 *
 * Approach: intercept the two API calls the page makes on mount
 * (/api/portfolio/health and /api/portfolio/snapshot), return controlled
 * responses, then assert the DOM reflects DEGRADED state.
 */

import { test, expect } from "@playwright/test";

// ── Mock payloads ─────────────────────────────────────────────────────────────

const DEGRADED_HEALTH = {
  status: "DEGRADED",
  initialized: true,
  paper_mode: true,
  auto_paper_enabled: false,
  liveness: true,
  readiness: true,
  degraded: true,
  failure_reason:
    "Exposure limits using hardcoded defaults — check PortfolioConfig import",
  unresolved_discrepancies: 0,
  limits_from_config: false,
  degraded_reasons: [
    "Exposure limits using hardcoded defaults — check PortfolioConfig import",
  ],
  state_freshness_s: 10,
  email_transport_configured: false,
  checked_at: new Date().toISOString(),
};

const MINIMAL_SNAPSHOT = {
  status: "READY",
  paper_mode: true,
  snapshotted_at: new Date().toISOString(),
  equity: 100_000,
  cash: 100_000,
  buying_power: 100_000,
  invested_value: 0,
  initial_capital: 100_000,
  unrealised_pnl: 0,
  realised_pnl_today: 0,
  total_pnl: 0,
  peak_equity: 100_000,
  drawdown_amount: 0,
  drawdown_pct: 0,
  open_positions: [],
  open_position_count: 0,
  closed_positions_today: 0,
  instrument_limit_pct: 20,
  sector_limit_pct: 35,
  limits_from_config: false,
  sector_exposures: [],
  exposure_warnings: [],
};

const MINIMAL_CONFIG = {
  loaded: false,
  limits_from_config: false,
  config: {},
  error: "PortfolioConfig unavailable",
  fetched_at: new Date().toISOString(),
  overrides: {},
  overridden_fields: [],
};

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Intercept all three API calls the Portfolio page makes on mount.
 *
 * IMPORTANT — Playwright evaluates page.route() handlers in LIFO order
 * (most-recently-registered wins).  The catch-all must therefore be
 * registered FIRST so that the more-specific routes registered afterward
 * take precedence over it.
 */
async function interceptPortfolioApis(page: import("@playwright/test").Page) {
  // 1. Catch-all first (lowest priority — checked last in LIFO order).
  //    Returns an empty-but-valid response for any /api/* URL that the three
  //    specific handlers below don't match.
  await page.route("**/api/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
  );

  // 2. Specific routes registered AFTER the catch-all so they are tried first.
  await page.route("**/api/portfolio/config", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(MINIMAL_CONFIG),
    }),
  );

  await page.route("**/api/portfolio/snapshot", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(MINIMAL_SNAPSHOT),
    }),
  );

  await page.route("**/api/portfolio/health", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(DEGRADED_HEALTH),
    }),
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe("Portfolio health card — DEGRADED state", () => {
  test.beforeEach(async ({ page }) => {
    await interceptPortfolioApis(page);
  });

  /**
   * The Portfolio Live page is mounted at the wouter route /portfolio-live
   * under the Vite base path /trading-dashboard.  Full URL is therefore
   * /trading-dashboard/portfolio-live (no trailing slash needed).
   */
  const PORTFOLIO_URL = "/trading-dashboard/portfolio-live";

  test("badge-portfolio-status shows DEGRADED", async ({ page }) => {
    await page.goto(PORTFOLIO_URL);

    const badge = page.getByTestId("badge-portfolio-status");
    await expect(badge).toBeVisible({ timeout: 10_000 });
    await expect(badge).toHaveText(/DEGRADED/i);
  });

  test("banner-portfolio-alert is visible when status is DEGRADED", async ({
    page,
  }) => {
    await page.goto(PORTFOLIO_URL);

    const banner = page.getByTestId("banner-portfolio-alert");
    await expect(banner).toBeVisible({ timeout: 10_000 });
  });

  test("health card shows PortfolioConfig warning text", async ({ page }) => {
    await page.goto(PORTFOLIO_URL);

    // The warning text must appear somewhere on the page — either inside the
    // banner (failure_reason) or inside the health card (degraded_reasons row).
    const warningText =
      "Exposure limits using hardcoded defaults — check PortfolioConfig import";

    await expect(
      page.locator(`text=${warningText}`).first(),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("banner contains the DEGRADED status label", async ({ page }) => {
    await page.goto(PORTFOLIO_URL);

    const banner = page.getByTestId("banner-portfolio-alert");
    await expect(banner).toBeVisible({ timeout: 10_000 });
    await expect(banner).toContainText("DEGRADED");
  });
});
