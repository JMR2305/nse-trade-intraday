/**
 * E2E: AI Paper Trader page — empty-state smoke test
 *
 * Verifies that all 12 sections render without JS errors on a fresh
 * portfolio (no trades, no scan data).  Every API call is intercepted and
 * replaced with a minimal valid empty-state response so the test is
 * completely self-contained and fast.
 *
 * What this catches that unit tests cannot:
 *  - A section that crashes when its data is undefined / empty array
 *  - A missing null-guard that only surfaces in the browser DOM
 *  - A tab that throws on mount before any data arrives
 *  - Section headers that never mount because a parent component returned null
 */

import { test, expect } from "@playwright/test";

// ── Minimal empty-state mock payloads ────────────────────────────────────────

const EMPTY_HV2 = {
  success: true,
  market: {
    state: "CLOSED",
    is_open: false,
    now_ist: new Date().toISOString(),
    holiday_today: null,
    label: "PAPER / RESEARCH ONLY",
    session: { pre_open: "09:00", open: "09:15", close: "15:30", post_close: "16:00" },
    next_transition: { state: "OPEN", at: new Date().toISOString() },
  },
  quote_provider: "mock",
  scan_id: null,
  snapshot_ts: null,
};

const EMPTY_MI_OVERVIEW = {
  regime: {
    regime: "SIDEWAYS",
    sub_regime: "NORMAL",
    nifty_price: 0,
    nifty_change_pct: 0,
    nifty_trend: "SIDEWAYS",
    banknifty_price: 0,
    banknifty_change_pct: 0,
    banknifty_trend: "SIDEWAYS",
    vix_value: 0,
    vix_status: "MODERATE",
  },
  volatility: { vix_value: 0, vix_status: "MODERATE" },
  summary: { trend: "NEUTRAL", outlook: "No data available", health_score: 0 },
  scanned_at: null,
};

const EMPTY_PORTFOLIO = {
  starting_capital: 50_000,
  cash: 50_000,
  invested_amount: 0,
  buying_power: 50_000,
  current_value: 50_000,
  realised_pnl: 0,
  unrealised_pnl: 0,
  total_pnl: 0,
  portfolio_return: 0,
  daily_pnl: 0,
  daily_return: 0,
  drawdown_pct: 0,
  open_positions: 0,
  capital_mode: "A",
  capital_mode_label: "Mode A — Standard",
  paper_only: true,
  advisory_only: true,
  as_of: new Date().toISOString(),
};

const EMPTY_OPEN_POSITIONS = { positions: [] };
const EMPTY_CLOSED_POSITIONS = { positions: [] };

const EMPTY_RECOMMENDATIONS = { items: [], count: 0 };

const EMPTY_TIMELINE = { events: [] };

const EMPTY_AI_PERF = {
  trades_analysed: 0,
  trades_executed: 0,
  win_rate: 0,
  avg_gain: 0,
  avg_loss: 0,
  avg_holding_label: "—",
  avg_holding_mins: 0,
  profit_factor: 0,
  recommendation_accuracy: 0,
  best_strategy: null,
  worst_strategy: null,
};

const EMPTY_CALENDAR = {
  days: [],
  trading_days: 0,
  total_pnl: 0,
  total_trades: 0,
};

const EMPTY_CAPITAL_CONFIG = {
  current_capital: 50_000,
  starting_capital: 50_000,
  capital_mode: "A",
  capital_mode_label: "Mode A — Standard",
  last_reset_date: null,
};

const EMPTY_TOPUPS = { items: [] };

const EMPTY_SNAPSHOT = {
  portfolio_value: 50_000,
  cash: 50_000,
  today_pnl: 0,
  today_return: 0,
  unrealised_pnl: 0,
  realised_pnl: 0,
  open_positions: 0,
  buying_power: 50_000,
  portfolio_return: 0,
  drawdown_pct: 0,
  recommendations: 0,
  top_opportunity: null,
  win_rate: 0,
  avg_confidence: 0,
  capital_mode: "A",
  capital_mode_label: "Mode A — Standard",
  date: new Date().toISOString().slice(0, 10),
  advisory_only: true,
  paper_only: true,
};

// ── Route interceptor ─────────────────────────────────────────────────────────

async function interceptAllAPIs(page: import("@playwright/test").Page) {
  // Catch-all first (lowest priority in LIFO evaluation order)
  await page.route("**/api/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
  );

  // Specific routes registered after, so they take priority over the catch-all
  const routes: Array<[string, unknown]> = [
    ["**/api/live-data/health-v2",                   EMPTY_HV2],
    ["**/api/market-intelligence/overview",          EMPTY_MI_OVERVIEW],
    ["**/api/phase11/portfolio",                     EMPTY_PORTFOLIO],
    ["**/api/phase11/portfolio/open-positions",      EMPTY_OPEN_POSITIONS],
    ["**/api/phase11/portfolio/closed-positions*",   EMPTY_CLOSED_POSITIONS],
    ["**/api/phase11/recommendations",               EMPTY_RECOMMENDATIONS],
    ["**/api/phase11/timeline*",                     EMPTY_TIMELINE],
    ["**/api/phase11/ai-performance",                EMPTY_AI_PERF],
    ["**/api/phase11/calendar*",                     EMPTY_CALENDAR],
    ["**/api/phase11/capital/config",                EMPTY_CAPITAL_CONFIG],
    ["**/api/phase11/capital/topups*",               EMPTY_TOPUPS],
    ["**/api/phase11/snapshot",                      EMPTY_SNAPSHOT],
  ];

  for (const [pattern, payload] of routes) {
    await page.route(pattern, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(payload),
      }),
    );
  }
}

// ── Test suite ────────────────────────────────────────────────────────────────

const PAGE_URL = "/trading-dashboard/ai-paper-trader";

test.describe("AI Paper Trader — empty-state smoke tests", () => {
  let consoleErrors: string[] = [];

  test.beforeEach(async ({ page }) => {
    consoleErrors = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });
    page.on("pageerror", (err) => consoleErrors.push(err.message));

    await interceptAllAPIs(page);
    await page.goto(PAGE_URL);
    // Wait for the page to settle past initial skeleton states
    await page.waitForLoadState("domcontentloaded");
  });

  // ── Safety banner ──────────────────────────────────────────────────────────

  test("safety banner is visible and says PAPER ONLY", async ({ page }) => {
    const banner = page.locator("text=AI Paper Trader").first();
    await expect(banner).toBeVisible({ timeout: 10_000 });

    // The sticky "PAPER ONLY" badge must always be present
    await expect(page.locator("text=PAPER ONLY").first()).toBeVisible({ timeout: 5_000 });

    // Advisory text in the header
    await expect(
      page.locator("text=No live broker orders").first(),
    ).toBeVisible({ timeout: 5_000 });
  });

  // ── S1 — Market Status ─────────────────────────────────────────────────────

  test("S1 Market Status section heading renders", async ({ page }) => {
    await expect(
      page.locator("text=MARKET STATUS").first(),
    ).toBeVisible({ timeout: 10_000 });

    // Live IST clock should always be ticking — just confirm it's present
    await expect(page.locator("text=IST Time").first()).toBeVisible({ timeout: 5_000 });
  });

  // ── S2 — Portfolio Summary ─────────────────────────────────────────────────

  test("S2 Portfolio Summary section renders with zero-value KPIs", async ({ page }) => {
    await expect(
      page.locator("text=PORTFOLIO SUMMARY").first(),
    ).toBeVisible({ timeout: 10_000 });

    // Starting capital should appear (₹50k from mock)
    await expect(page.locator("text=Starting Capital").first()).toBeVisible({ timeout: 5_000 });
    await expect(page.locator("text=Portfolio Value").first()).toBeVisible({ timeout: 5_000 });
  });

  // ── S3 — Live AI Status ────────────────────────────────────────────────────

  test("S3 Live AI Status section renders with fallback values", async ({ page }) => {
    await expect(
      page.locator("text=LIVE AI STATUS").first(),
    ).toBeVisible({ timeout: 10_000 });

    await expect(page.locator("text=Stocks Monitored").first()).toBeVisible({ timeout: 5_000 });
    // Default activity when no timeline events
    await expect(page.locator("text=Analysing").first()).toBeVisible({ timeout: 5_000 });
  });

  // ── S4 — Current Holdings ──────────────────────────────────────────────────

  test("S4 Current Holdings shows empty-state message (no crash)", async ({ page }) => {
    await expect(
      page.locator("text=CURRENT HOLDINGS").first(),
    ).toBeVisible({ timeout: 10_000 });

    // Empty state message, not a blank box
    await expect(
      page.locator("text=No open positions").first(),
    ).toBeVisible({ timeout: 5_000 });
  });

  // ── S5 — Activity Feed ─────────────────────────────────────────────────────

  test("S5 Activity Feed renders filter buttons and empty state", async ({ page }) => {
    await expect(
      page.locator("text=LIVE ACTIVITY FEED").first(),
    ).toBeVisible({ timeout: 10_000 });

    // Category filter buttons
    await expect(page.locator("text=ALL").first()).toBeVisible({ timeout: 5_000 });
    await expect(page.locator("text=TRADE").first()).toBeVisible({ timeout: 5_000 });

    // Empty state message
    await expect(
      page.locator("text=No events today").first(),
    ).toBeVisible({ timeout: 5_000 });
  });

  // ── S6 — Recommendation Queue ──────────────────────────────────────────────

  test("S6 Recommendation Queue shows empty-state message", async ({ page }) => {
    await expect(
      page.locator("text=RECOMMENDATION QUEUE").first(),
    ).toBeVisible({ timeout: 10_000 });

    await expect(
      page.locator("text=No recommendations").first(),
    ).toBeVisible({ timeout: 5_000 });
  });

  // ── S7 — Closed Trades ────────────────────────────────────────────────────

  test("S7 Closed Trades shows empty-state message", async ({ page }) => {
    await expect(
      page.locator("text=CLOSED TRADES").first(),
    ).toBeVisible({ timeout: 10_000 });

    await expect(
      page.locator("text=No closed trades today").first(),
    ).toBeVisible({ timeout: 5_000 });
  });

  // ── S8 — AI Performance ───────────────────────────────────────────────────

  test("S8 AI Performance section renders zero-value KPIs", async ({ page }) => {
    await expect(
      page.locator("text=AI PERFORMANCE").first(),
    ).toBeVisible({ timeout: 10_000 });

    await expect(page.locator("text=Win Rate").first()).toBeVisible({ timeout: 5_000 });
    await expect(page.locator("text=Profit Factor").first()).toBeVisible({ timeout: 5_000 });
  });

  // ── Bottom tabs ───────────────────────────────────────────────────────────

  test("Charts tab opens without errors", async ({ page }) => {
    const chartsTab = page.locator("button", { hasText: "Charts" });
    await expect(chartsTab).toBeVisible({ timeout: 10_000 });
    await chartsTab.click();

    // Each chart shows "no data" placeholder, not an exception
    const noData = page.locator("text=No trade data yet").first();
    await expect(noData).toBeVisible({ timeout: 5_000 });
  });

  test("Date History tab opens and shows calendar", async ({ page }) => {
    const tab = page.locator("button", { hasText: "Date History" });
    await expect(tab).toBeVisible({ timeout: 10_000 });
    await tab.click();

    // Month navigation arrows should be present
    await expect(page.locator("button >> svg").first()).toBeVisible({ timeout: 5_000 });
    // Instruction text for the drill-down panel
    await expect(
      page.locator("text=Click a trading day").first(),
    ).toBeVisible({ timeout: 5_000 });
  });

  test("Replay tab opens and shows date picker", async ({ page }) => {
    const tab = page.locator("button", { hasText: "Replay" });
    await expect(tab).toBeVisible({ timeout: 10_000 });
    await tab.click();

    // Date input always present
    const dateInput = page.locator("input[type='date']");
    await expect(dateInput).toBeVisible({ timeout: 5_000 });

    // Empty state when no snapshots
    await expect(
      page.locator("text=No replay data").first(),
    ).toBeVisible({ timeout: 5_000 });
  });

  test("Capital tab opens and shows config section", async ({ page }) => {
    const tab = page.locator("button", { hasText: "Capital" });
    await expect(tab).toBeVisible({ timeout: 10_000 });
    await tab.click();

    await expect(
      page.locator("text=CAPITAL CONFIGURATION").first(),
    ).toBeVisible({ timeout: 5_000 });

    await expect(
      page.locator("text=No capital events yet").first(),
    ).toBeVisible({ timeout: 5_000 });
  });

  // ── No console errors on the happy path ───────────────────────────────────

  test("no unhandled JS errors on page load with empty data", async ({ page }) => {
    // Allow time for all queries to settle
    await page.waitForTimeout(2_000);

    // Filter out known-benign noise:
    //  - React DevTools browser extension hint
    //  - Vite HMR "[vite]" messages
    //  - favicon 404s
    //  - EventSource MIME-type warning: the catch-all route intercepts Vite's
    //    HMR SSE endpoint (/trading-dashboard/@vite/...) and returns JSON
    //    instead of text/event-stream — harmless in the test environment.
    const realErrors = consoleErrors.filter(
      (e) =>
        !e.includes("React DevTools") &&
        !e.includes("[vite]") &&
        !e.includes("favicon") &&
        !e.includes("EventSource") &&
        !e.includes("text/event-stream"),
    );

    expect(
      realErrors,
      `Unexpected console errors: ${realErrors.join(" | ")}`,
    ).toHaveLength(0);
  });
});
