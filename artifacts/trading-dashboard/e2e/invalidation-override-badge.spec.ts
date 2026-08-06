/**
 * E2E: Invalidation-override badge on Trade Decisions page
 *
 * Task 61f5ed05 — confirms the "OVERRIDDEN BY GATE" badge:
 *   1. Appears  for a decision with fc=87 that was blocked by a gate
 *      (filter_passed=false → recommendation=AVOID despite high confidence).
 *   2. Is absent for a decision with fc=40 (confidence itself is low —
 *      the gate threshold was never reached, so no override occurred).
 *
 * A unit test can verify the Python logic; only a browser test can catch:
 *   - Wrong field name or typo in `d.invalidation_override` access
 *   - Conditional rendering guard failing silently (badge never mounts)
 *   - data-testid selector drift
 *   - Tooltip text missing the blocking condition
 *
 * Approach: intercept /api/trade-decisions before navigation so the page
 * renders with controlled mock decisions from the very first render.
 */

import { test, expect } from "@playwright/test";

// ── Constants ─────────────────────────────────────────────────────────────────

// TradeDecisions is mounted at route "/" (root) in App.tsx.
const TRADE_DECISIONS_URL = "/trading-dashboard/";

// ── Mock payloads ─────────────────────────────────────────────────────────────

/** Minimal TradeDecision shape — only fields the page actually reads. */
function makeDecision(overrides: Record<string, unknown>) {
  return {
    stock: "TEST",
    sector: "ENERGY",
    recommendation: "AVOID",
    data_status: "OK",
    low_reliability: false,
    low_evidence: false,
    total_trades: 30,
    invalidation_override: false,
    invalidation_override_conditions: [],
    final_confidence: 40,
    base_confidence: 40,
    price: 100,
    entry_price: 100,
    stop_loss: 95,
    target: 112,
    rr_ratio: 2.4,
    expected_holding_days: 3,
    expected_drawdown: 2.1,
    reason: "Low confidence",
    failed_conditions: [],
    position_open: false,
    position_quantity: 0,
    position_avg_price: 0,
    position_pnl_pct: 0,
    decision_state: "VALID",
    valid_until: null,
    validity_note: null,
    conflict_level: "NONE",
    conflict_explanation: null,
    analyst_summary: null,
    current_observation: null,
    historical_assessment: null,
    decision_reasoning: null,
    invalidation_conditions: [],
    upgrade_conditions: [],
    invalidation_met: 0,
    upgrade_met: 0,
    missing_data_fields: [],
    breakdown: [],
    similarity_evidence: null,
    similarity_adjustment: 0,
    evidence_reliability: "VERY_LOW",
    explanation_sections: null,
    model_version: 0,
    exit_reason: null,
    ...overrides,
  };
}

/** High-confidence decision blocked by a gate. */
const HIGH_CONF_BLOCKED = makeDecision({
  stock: "RELIANCE",
  final_confidence: 87,
  base_confidence: 87,
  recommendation: "AVOID",
  invalidation_override: true,
  invalidation_override_conditions: ["volume below minimum threshold"],
  reason: "Risk filter failed: volume below minimum threshold",
});

/** Normal low-confidence AVOID — no gate involved. */
const LOW_CONF_AVOID = makeDecision({
  stock: "INFY",
  final_confidence: 40,
  base_confidence: 40,
  recommendation: "AVOID",
  invalidation_override: false,
  invalidation_override_conditions: [],
  reason: "Low confidence (40 < 55)",
});

/** Minimal /api/trade-decisions response envelope. */
const MOCK_DECISIONS_RESPONSE = {
  decisions: [HIGH_CONF_BLOCKED, LOW_CONF_AVOID],
  generated_at: new Date().toISOString(),
  market_regime: "Neutral",
  model_version: 1,
  strong_buy_count: 0,
  buy_count: 0,
  exit_count: 0,
  watch_count: 0,
  avoid_count: 2,
  data_unavailable_count: 0,
  warning: "Paper trading only — research tool, not investment advice.",
};

// ── Intercept helper ──────────────────────────────────────────────────────────

/**
 * Register route intercepts before navigation.
 *
 * Pattern: catch-all registered FIRST (LIFO → lowest priority); specific
 * routes registered AFTER so they win.
 */
async function interceptTradeDecisionsApis(page: import("@playwright/test").Page) {
  // 1. Catch-all — satisfies every /api/* request the page fires on mount
  //    (strategy advisory, pre-open hints, phase13 regime, freshness bar, etc.)
  //    so none of them hang and block rendering.
  await page.route("**/api/**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "DISABLED", decisions: [], strategies: [] }),
    }),
  );

  // 2. The main trade-decisions endpoint — returns our controlled mock.
  await page.route("**/api/trade-decisions**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(MOCK_DECISIONS_RESPONSE),
    }),
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe("Trade Decisions — invalidation-override badge", () => {
  test.beforeEach(async ({ page }) => {
    await interceptTradeDecisionsApis(page);
    await page.goto(TRADE_DECISIONS_URL);
    // Wait for the table to be present before asserting individual cells.
    await page.waitForSelector('[data-testid="page-trade-decisions"]', {
      timeout: 15_000,
    });
  });

  test("badge appears for high-confidence (fc=87) gate-blocked stock", async ({
    page,
  }) => {
    const badge = page.getByTestId("badge-invalidation-override-RELIANCE");
    await expect(badge).toBeVisible({ timeout: 10_000 });
    await expect(badge).toContainText(/OVERRIDDEN BY GATE/i);
  });

  test("badge tooltip mentions the blocking condition", async ({ page }) => {
    const badge = page.getByTestId("badge-invalidation-override-RELIANCE");
    await expect(badge).toBeVisible({ timeout: 10_000 });

    // The blocking condition surfaces in the `title` attribute of the <span>.
    const title = await badge.getAttribute("title");
    expect(title).toBeTruthy();
    expect(title).toMatch(/87/);          // confidence value
    expect(title).toMatch(/volume|filter|blocked/i);  // blocking condition
  });

  test("badge is absent for normal low-confidence (fc=40) AVOID row", async ({
    page,
  }) => {
    // Confirm INFY row is rendered (so the absence is meaningful).
    const row = page.getByTestId("row-decision-INFY");
    await expect(row).toBeVisible({ timeout: 10_000 });

    // The override badge must NOT be present.
    const badge = page.getByTestId("badge-invalidation-override-INFY");
    await expect(badge).not.toBeVisible();
  });

  test("RELIANCE row shows AVOID recommendation alongside the override badge", async ({
    page,
  }) => {
    // The override badge and the AVOID rec badge must coexist in the same row.
    const row = page.getByTestId("row-decision-RELIANCE");
    await expect(row).toBeVisible({ timeout: 10_000 });

    const badge = row.getByTestId("badge-invalidation-override-RELIANCE");
    await expect(badge).toBeVisible();

    const recBadge = row.getByTestId("badge-recommendation-avoid");
    await expect(recBadge).toBeVisible();
  });
});
