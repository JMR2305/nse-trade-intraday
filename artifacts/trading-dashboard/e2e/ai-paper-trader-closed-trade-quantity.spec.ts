/**
 * Browser regression: canonical and legacy closed-trade quantities must be
 * displayed verbatim, while only absent historical values use the fallback.
 */
import { test, expect } from "@playwright/test";

const CLOSED_TRADES = [
  {
    symbol: "DRREDDY",
    buy_time: "2026-08-19T04:20:00Z",
    sell_time: "2026-08-19T08:30:00Z",
    entry_price: 1234.5,
    exit_price: 1250,
    quantity: 20,
    pnl: 310,
    pnl_pct: 1.26,
    holding_label: "4h 10m",
    exit_reason: "TARGET",
    ai_confidence: 80,
    strategy: "MOMENTUM",
    lesson_learned: "",
  },
  {
    symbol: "DIVISLAB",
    buy_time: "2026-08-19T04:25:00Z",
    sell_time: "2026-08-19T08:35:00Z",
    entry_price: 6000,
    exit_price: 6030,
    quantity: 1,
    pnl: 30,
    pnl_pct: 0.5,
    holding_label: "4h 10m",
    exit_reason: "TARGET",
    ai_confidence: 76,
    strategy: "BREAKOUT",
    lesson_learned: "",
  },
  {
    symbol: "HISTORICAL",
    buy_time: "2024-01-01T04:25:00Z",
    sell_time: "2024-01-01T08:35:00Z",
    entry_price: 100,
    exit_price: 101,
    quantity: null,
    pnl: 1,
    pnl_pct: 1,
    holding_label: "4h 10m",
    exit_reason: "MANUAL",
    ai_confidence: 0,
    strategy: "UNKNOWN",
    lesson_learned: "",
  },
];

test("AI Paper Trader renders stored closed-trade quantities", async ({ page }) => {
  // Catch-all first: later, more-specific handlers win in Playwright's LIFO
  // route resolution and keep unrelated page queries harmless.
  await page.route("**/api/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
  );
  await page.route("**/api/phase11/portfolio/closed-positions*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(CLOSED_TRADES),
    }),
  );

  await page.goto("/trading-dashboard/ai-paper-trader");

  await expect(page.getByTestId("closed-trade-quantity-DRREDDY")).toHaveText("20");
  await expect(page.getByTestId("closed-trade-quantity-DIVISLAB")).toHaveText("1");
  await expect(page.getByTestId("closed-trade-quantity-HISTORICAL"))
    .toHaveText("Not recorded");
});