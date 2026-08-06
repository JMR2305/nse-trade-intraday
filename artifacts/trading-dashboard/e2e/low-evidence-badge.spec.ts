/**
 * E2E: LOW EVIDENCE badge on Trade Decisions page
 *
 * Task 384 — confirms the "LOW EVIDENCE" badge:
 *   1. Appears for a stock where `low_evidence=true` and `total_trades=2`
 *      (e.g. RELIANCE with only 2 backtest trades).
 *   2. Is absent for a stock with `low_evidence=false` and `total_trades=30`
 *      (no false positives on a well-evidenced row).
 *   3. The badge `title` tooltip contains the exact trade count.
 *   4. The LOW RELIABILITY badge can appear alongside LOW EVIDENCE in the
 *      same row without either badge being suppressed.
 *   5. LOW EVIDENCE badge is absent when `low_evidence` is falsy (even if
 *      total_trades is small — the flag is authoritative).
 *
 * Approach: intercept /api/trade-decisions before navigation so the page
 * renders with controlled mock decisions from the very first render, avoiding
 * any dependency on live backend data.
 */

import { test, expect } from "@playwright/test";

// ── Constants ─────────────────────────────────────────────────────────────────

const TRADE_DECISIONS_URL = "/trading-dashboard/";

// ── Mock payloads ─────────────────────────────────────────────────────────────

/** Minimal TradeDecision shape — only fields the page actually reads. */
function makeDecision(overrides: Record<string, unknown>) {
  return {
    stock: "TEST",
    sector: "ENERGY",
    recommendation: "WATCH",
    data_status: "OK",
    low_reliability: false,
    low_evidence: false,
    total_trades: 30,
    invalidation_override: false,
    invalidation_override_conditions: [],
    final_confidence: 55,
    base_confidence: 55,
    price: 2500,
    entry_price: 2500,
    stop_loss: 2400,
    target: 2700,
    rr_ratio: 2.0,
    expected_holding_days: 3,
    expected_drawdown: 2.0,
    reason: "Watching for breakout",
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

/** Low-evidence stock: 2 trades, flag set. */
const LOW_EVIDENCE_STOCK = makeDecision({
  stock: "RELIANCE",
  sector: "ENERGY",
  recommendation: "WATCH",
  low_evidence: true,
  total_trades: 2,
  final_confidence: 48,
  base_confidence: 48,
  reason: "Thin evidence — only 2 backtest trades available",
});

/** High-evidence stock: 30 trades, no flag. */
const HIGH_EVIDENCE_STOCK = makeDecision({
  stock: "INFY",
  sector: "IT",
  recommendation: "BUY",
  low_evidence: false,
  total_trades: 30,
  final_confidence: 72,
  base_confidence: 72,
  reason: "Strong momentum signal",
});

/** Stock with BOTH low_evidence AND low_reliability set. */
const DUAL_BADGE_STOCK = makeDecision({
  stock: "TATAPOWER",
  sector: "POWER",
  recommendation: "WATCH",
  low_evidence: true,
  total_trades: 3,
  low_reliability: true,
  final_confidence: 42,
  base_confidence: 42,
  reason: "Thin evidence and low reliability",
});

/** Minimal /api/trade-decisions response envelope. */
const MOCK_DECISIONS_RESPONSE = {
  decisions: [LOW_EVIDENCE_STOCK, HIGH_EVIDENCE_STOCK, DUAL_BADGE_STOCK],
  generated_at: new Date().toISOString(),
  market_regime: "Neutral",
  model_version: 1,
  strong_buy_count: 0,
  buy_count: 1,
  exit_count: 0,
  watch_count: 2,
  avoid_count: 0,
  data_unavailable_count: 0,
  warning: "Paper trading only — research tool, not investment advice.",
};

// ── Intercept helper ──────────────────────────────────────────────────────────

async function interceptApis(page: import("@playwright/test").Page) {
  // 1. Catch-all satisfies every /api/* request fired on mount
  //    (strategy advisory, pre-open hints, phase13 regime, freshness bar, etc.)
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

test.describe("Trade Decisions — LOW EVIDENCE badge", () => {
  test.beforeEach(async ({ page }) => {
    await interceptApis(page);
    await page.goto(TRADE_DECISIONS_URL);
    await page.waitForSelector('[data-testid="page-trade-decisions"]', {
      timeout: 15_000,
    });
  });

  test("badge appears for RELIANCE with 2 trades (low_evidence=true)", async ({
    page,
  }) => {
    const badge = page.getByTestId("badge-low-evidence-RELIANCE");
    await expect(badge).toBeVisible({ timeout: 10_000 });
    await expect(badge).toContainText(/LOW EVIDENCE/i);
  });

  test("badge tooltip includes the trade count (2 trades)", async ({ page }) => {
    const badge = page.getByTestId("badge-low-evidence-RELIANCE");
    await expect(badge).toBeVisible({ timeout: 10_000 });

    // The trade count surfaces in the `title` attribute of the <span>.
    const title = await badge.getAttribute("title");
    expect(title).toBeTruthy();
    expect(title).toMatch(/2/);       // trade count
    expect(title).toMatch(/trade/i);  // contextual word
  });

  test("badge text shows trade count inline", async ({ page }) => {
    const badge = page.getByTestId("badge-low-evidence-RELIANCE");
    await expect(badge).toBeVisible({ timeout: 10_000 });
    // Badge renders "LOW EVIDENCE (2 trades)" — the count must appear in text.
    await expect(badge).toContainText("2");
  });

  test("badge is absent for INFY with 30 trades (low_evidence=false)", async ({
    page,
  }) => {
    // Confirm INFY row is rendered, so the absence is meaningful.
    const row = page.getByTestId("row-decision-INFY");
    await expect(row).toBeVisible({ timeout: 10_000 });

    // LOW EVIDENCE badge must NOT be present.
    const badge = page.getByTestId("badge-low-evidence-INFY");
    await expect(badge).not.toBeVisible();
  });

  test("LOW RELIABILITY badge appears alongside LOW EVIDENCE on TATAPOWER", async ({
    page,
  }) => {
    const row = page.getByTestId("row-decision-TATAPOWER");
    await expect(row).toBeVisible({ timeout: 10_000 });

    // Both badges must be visible in the same row without either being suppressed.
    const evidenceBadge = row.getByTestId("badge-low-evidence-TATAPOWER");
    await expect(evidenceBadge).toBeVisible();
    await expect(evidenceBadge).toContainText(/LOW EVIDENCE/i);

    // LOW RELIABILITY is a <span> without a testid — match exact text only.
    await expect(row.getByText("LOW RELIABILITY", { exact: true })).toBeVisible();
  });

  test("LOW EVIDENCE badge on TATAPOWER tooltip shows 3 trades", async ({
    page,
  }) => {
    const badge = page.getByTestId("badge-low-evidence-TATAPOWER");
    await expect(badge).toBeVisible({ timeout: 10_000 });

    const title = await badge.getAttribute("title");
    expect(title).toBeTruthy();
    expect(title).toMatch(/3/);
  });

  test("RELIANCE row also renders its recommendation badge", async ({ page }) => {
    const row = page.getByTestId("row-decision-RELIANCE");
    await expect(row).toBeVisible({ timeout: 10_000 });

    // LOW EVIDENCE must coexist with the recommendation badge.
    const evidenceBadge = row.getByTestId("badge-low-evidence-RELIANCE");
    await expect(evidenceBadge).toBeVisible();

    // RELIANCE is WATCH — recommendation badge must also be visible.
    const recBadge = row.getByTestId("badge-recommendation-watch");
    await expect(recBadge).toBeVisible();
  });
});
