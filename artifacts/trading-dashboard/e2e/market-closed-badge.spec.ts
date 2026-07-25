/**
 * E2E: DataFreshnessBar shows MARKET_CLOSED in the live browser during weekends
 *
 * Task 116 — confirms the browser renders the MARKET_CLOSED badge (slate dot,
 * slate border/background, "MARKET_CLOSED" label) correctly, not just in unit
 * tests.  Unit tests verify the logic; only a browser test can catch:
 *   - wrong React Query key (query fires but result goes to the wrong hook)
 *   - DataStatus/colour map not wired to the rendered span
 *   - Tailwind class not applied (conditional string not matching)
 *   - data-testid selector drift
 *
 * Approach: intercept the two API calls DataFreshnessBar makes on mount
 * (/api/phase15/staleness and /api/live-data/scan/status), return a controlled
 * weekend payload (stale=true, current_time=Saturday UTC), then assert the DOM
 * reflects MARKET_CLOSED state with the correct colour class.
 *
 * The portfolio-live page is chosen because it is already exercised by the
 * health-card-degraded spec and is known to render DataFreshnessBar with
 * variant="scan".
 */

import { test, expect } from "@playwright/test";

// ── Mock payloads ─────────────────────────────────────────────────────────────

/**
 * Saturday 2026-07-25 10:00 UTC (IST = 15:30, which is after NSE close,
 * and the day-of-week is Saturday → isMarketOpen returns false).
 * Using a fixed timestamp makes the test deterministic regardless of
 * when it is run.
 */
const SATURDAY_UTC = "2026-07-25T10:00:00Z";

// Minimal but valid portfolio snapshot — all numeric fields must be present so
// PortfolioLive.tsx never calls .toFixed() on undefined.
const MINIMAL_SNAPSHOT = {
  status: "READY",
  paper_mode: true,
  snapshotted_at: SATURDAY_UTC,
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

const MINIMAL_HEALTH = {
  status: "HEALTHY",
  initialized: true,
  paper_mode: true,
  auto_paper_enabled: false,
  liveness: true,
  readiness: true,
  degraded: false,
  failure_reason: null,
  unresolved_discrepancies: 0,
  limits_from_config: true,
  degraded_reasons: [],
  state_freshness_s: 5,
  email_transport_configured: false,
  checked_at: SATURDAY_UTC,
};

const MINIMAL_CONFIG = {
  loaded: false,
  limits_from_config: false,
  config: {},
  error: null,
  fetched_at: SATURDAY_UTC,
  overrides: {},
  overridden_fields: [],
};

const WEEKEND_STALENESS = {
  success: true,
  current_time: SATURDAY_UTC,
  last_scan_time: "2026-07-24T10:00:00Z", // last Friday scan
  scan_age_seconds: 86_400, // 24 hours old
  scan_age_human: "24 hours",
  stale: true,
  buy_recommendations_disabled: true,
  warning: "Data is 24 hours old. Weekend — market closed.",
  label: "PAPER / RESEARCH ONLY",
};

const COMPLETED_SCAN_STATUS = {
  success: true,
  latest_scan: {
    scan_id: "test-scan-weekend-0001",
    status: "COMPLETED",
    started_at: "2026-07-24T09:55:00Z",
    completed_at: "2026-07-24T10:00:00Z",
    snapshot_ts: "2026-07-24T10:00:00Z",
    provider: "yfinance",
    symbols_requested: 50,
    symbols_received: 50,
    symbols_missing: 0,
    symbols_stale: 0,
    missing_symbols: [],
    stale_symbols: [],
    error: null,
    updated_at: "2026-07-24T10:00:00Z",
  },
};

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Intercept DataFreshnessBar's two API calls plus a catch-all for any other
 * /api/* requests the page makes.
 *
 * Playwright evaluates route handlers in LIFO order (most-recently-registered
 * wins), so the catch-all must be registered FIRST.
 */
async function interceptFreshnessApis(page: import("@playwright/test").Page) {
  // 1. Catch-all for any other /api/* requests (registered first = lowest priority).
  await page.route("**/api/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
  );

  // 2. Portfolio page APIs — these must be registered before the freshness
  //    routes so they are higher priority in LIFO order.
  //    All numeric fields must be present to avoid .toFixed() on undefined.
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
      body: JSON.stringify(MINIMAL_HEALTH),
    }),
  );

  // 3. DataFreshnessBar APIs — highest priority (registered last in LIFO).
  await page.route("**/api/phase15/staleness", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(WEEKEND_STALENESS),
    }),
  );

  await page.route("**/api/live-data/scan/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(COMPLETED_SCAN_STATUS),
    }),
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe("DataFreshnessBar — MARKET_CLOSED badge (weekend)", () => {
  /**
   * Portfolio live is mounted at /trading-dashboard/portfolio-live.
   * It renders <DataFreshnessBar variant="scan" /> so the staleness/scan-status
   * API calls are made on mount.
   */
  const PORTFOLIO_URL = "/trading-dashboard/portfolio-live";

  test.beforeEach(async ({ page }) => {
    await interceptFreshnessApis(page);
  });

  test('badge label reads "MARKET_CLOSED" when data is stale on a weekend', async ({
    page,
  }) => {
    await page.goto(PORTFOLIO_URL);

    const bar = page.getByTestId("data-freshness-bar");
    await expect(bar).toBeVisible({ timeout: 10_000 });

    // The status text rendered inside the bar must be MARKET_CLOSED.
    await expect(bar).toContainText("MARKET_CLOSED", { timeout: 10_000 });
  });

  test("bar container has the slate border/background classes for MARKET_CLOSED", async ({
    page,
  }) => {
    await page.goto(PORTFOLIO_URL);

    const bar = page.getByTestId("data-freshness-bar");
    await expect(bar).toBeVisible({ timeout: 10_000 });

    // Wait for the badge to resolve (not still showing "Loading…").
    await expect(bar).toContainText("MARKET_CLOSED", { timeout: 10_000 });

    // The container must carry the slate border and background classes that
    // distinguish MARKET_CLOSED from STALE (amber) or UNAVAILABLE (red).
    await expect(bar).toHaveClass(/border-slate-500\/40/);
    await expect(bar).toHaveClass(/bg-slate-500\/10/);
  });

  test("slate-400 text colour class is applied to the status span", async ({
    page,
  }) => {
    await page.goto(PORTFOLIO_URL);

    const bar = page.getByTestId("data-freshness-bar");
    await expect(bar).toBeVisible({ timeout: 10_000 });
    await expect(bar).toContainText("MARKET_CLOSED", { timeout: 10_000 });

    // The span that contains the status label must use the slate-400 colour
    // defined in DATA_STATUS_COLOR["MARKET_CLOSED"].
    const statusSpan = bar.locator(".text-slate-400").first();
    await expect(statusSpan).toBeVisible();
    await expect(statusSpan).toContainText("MARKET_CLOSED");
  });

  test("bar does NOT use amber/red classes (not STALE or UNAVAILABLE)", async ({
    page,
  }) => {
    await page.goto(PORTFOLIO_URL);

    const bar = page.getByTestId("data-freshness-bar");
    await expect(bar).toBeVisible({ timeout: 10_000 });
    await expect(bar).toContainText("MARKET_CLOSED", { timeout: 10_000 });

    // Negative assertions: the container must not carry amber (STALE/DELAYED)
    // or red (UNAVAILABLE) border/background classes.
    const classes = await bar.getAttribute("class") ?? "";
    expect(classes).not.toMatch(/border-warn|bg-warn-surface/);
    expect(classes).not.toMatch(/border-red-500|bg-red-500/);
  });

  test("detail panel opens and shows stale warning text", async ({ page }) => {
    await page.goto(PORTFOLIO_URL);

    const bar = page.getByTestId("data-freshness-bar");
    await expect(bar).toBeVisible({ timeout: 10_000 });
    await expect(bar).toContainText("MARKET_CLOSED", { timeout: 10_000 });

    // Open the expandable detail panel.
    const toggleBtn = bar.getByTestId("button-freshness-toggle");
    await toggleBtn.click();

    // The detail panel must surface the stale warning from the backend.
    await expect(bar).toContainText("STALE", { timeout: 5_000 });
    await expect(bar).toContainText("BUY recommendations disabled", {
      timeout: 5_000,
    });
  });
});
