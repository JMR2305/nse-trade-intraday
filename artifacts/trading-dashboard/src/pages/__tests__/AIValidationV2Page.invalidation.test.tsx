// @vitest-environment jsdom
/**
 * Task #399 — Missed Opportunities cache-invalidation tests
 *
 * Confirms that when a backtest run transitions to COMPLETED the
 * BacktestRunnerTab calls `queryClient.invalidateQueries(["v2-missed"])`,
 * causing the Missed Opportunities query to re-fetch without a full page
 * reload.
 *
 * Relevant code: AIValidationV2Page.tsx — useEffect on currentRun?.status
 *   qc.invalidateQueries({ queryKey: ["v2-runs"]  });
 *   qc.invalidateQueries({ queryKey: ["v2-missed"] });
 *
 * Timing note: the mock returns COMPLETED on the first detail poll so we
 * avoid waiting 3 s for the refetchInterval. React Query's state update +
 * useEffect fire asynchronously after the first fetch, so we use waitFor
 * to detect the query invalidation / re-fetch.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

// ── Mock apiJson ──────────────────────────────────────────────────────────────
const mockApiJson = vi.fn();
vi.mock("@/lib/api", () => ({ apiJson: (...args: unknown[]) => mockApiJson(...args) }));

import AIValidationV2Page from "../AIValidationV2Page";

// ── Shared fixtures ───────────────────────────────────────────────────────────

const STATS = {
  total_trades: 5, winning_trades: 3, losing_trades: 2, breakeven_trades: 0,
  win_rate_pct: 60.0, loss_rate_pct: 40.0, avg_pnl_pct: 1.5, best_trade_pct: 3.8,
  worst_trade_pct: -1.5, max_drawdown_pct: 2.8, profit_factor: 1.9,
  expectancy_pct: 1.5, sharpe_ratio: 1.1, avg_holding_days: 3.2,
  avg_confidence: 68.0, sufficient_data: true,
};

const RUN_LIST = {
  runs: [{
    run_id: "run-before", status: "COMPLETED", total_decisions: 20,
    total_trades: 5, start_date: "2026-05-01", end_date: "2026-06-01",
    interval: "1d", created_at: "2026-06-01T10:00:00Z", completed_at: "2026-06-01T10:03:00Z",
  }],
  count: 1,
  label: "PAPER / RESEARCH ONLY",
};

const RUN_DETAIL_COMPLETED = {
  success: true, run_id: "run-new", status: "COMPLETED", config: {},
  symbols: ["RELIANCE", "TCS"], strategies: ["trend_rider"], interval: "1d",
  total_decisions: 18, total_trades: 4, stats: STATS,
  recommendation_distribution: { BUY: 6, AVOID: 12 },
  most_common_rejection: "confidence below threshold",
  decisions_sample: [], trades: [], missed_opportunities: [],
  generated_at: "2026-06-21T10:05:00Z",
};

// Stale data present before the new backtest
const BASE_MISSED = {
  missed: [{
    symbol: "WIPRO", strategy: "trend_rider", bar_date: "2026-05-01",
    ai_decision: "AVOID", ai_confidence: 48.0, actual_move_pct: 3.9,
    potential_profit_pct: 3.2, rejection_reason: "confidence below threshold",
    improvement_suggestion: "Lower threshold to 55", run_id: "run-before",
  }],
  count: 1, total_potential_profit_pct: 3.2, label: "PAPER / RESEARCH ONLY",
};

// Fresh data after the new backtest
const UPDATED_MISSED = {
  missed: [{
    symbol: "TATASTEEL", strategy: "trend_rider", bar_date: "2026-06-20",
    ai_decision: "AVOID", ai_confidence: 44.0, actual_move_pct: 5.1,
    potential_profit_pct: 4.6, rejection_reason: "entry signal missing",
    improvement_suggestion: "Tune entry signal threshold", run_id: "run-new",
  }],
  count: 1, total_potential_profit_pct: 4.6, label: "PAPER / RESEARCH ONLY",
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function buildMock(missedFetches: { count: number }) {
  return vi.fn().mockImplementation((path: string, opts?: RequestInit) => {
    if (opts?.method === "POST" && (path as string).includes("backtest/run")) {
      return Promise.resolve({ run_id: "run-new" });
    }
    if (path === "validation-v2/backtest") return Promise.resolve(RUN_LIST);
    // Always return COMPLETED on first (and only) poll — avoids 3 s refetch delay
    if ((path as string).includes("backtest/run-new")) {
      return Promise.resolve(RUN_DETAIL_COMPLETED);
    }
    if (path === "validation-v2/missed-opportunities") {
      missedFetches.count++;
      // Return stale data on the initial load; fresh data after invalidation
      return Promise.resolve(missedFetches.count <= 1 ? BASE_MISSED : UPDATED_MISSED);
    }
    if ((path as string).startsWith("validation-v2/performance")) {
      return Promise.resolve({ stats: STATS, period: "monthly", most_common_rejection: "" });
    }
    if (path === "validation-v2/optimizer/recommendation") {
      return Promise.resolve({ best_config: { sharpe_ratio: 1.2 }, recommendation: "" });
    }
    return Promise.resolve({});
  });
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("AIValidationV2Page — Missed Opportunities invalidation (Task #399)", () => {
  beforeEach(() => { mockApiJson.mockReset(); });
  afterEach(() => { vi.clearAllMocks(); cleanup(); });

  // ── Test 1: invalidateQueries is called on the right key ──────────────────
  it("calls invalidateQueries([v2-missed]) when a backtest completes", async () => {
    /**
     * A spy is placed on the real QueryClient's invalidateQueries method so
     * we can assert the exact key without relying on downstream refetch timing.
     */
    const missedFetches = { count: 0 };
    mockApiJson.mockImplementation(buildMock(missedFetches));

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(qc, "invalidateQueries");

    render(
      <QueryClientProvider client={qc}>
        <AIValidationV2Page />
      </QueryClientProvider>
    );

    // Switch to Backtest Runner tab and fire the run
    const backtestBtns = await screen.findAllByRole("button", { name: /Backtest Runner/i });
    await userEvent.click(backtestBtns[0]);
    const runBtn = await screen.findByRole("button", { name: /Run Backtest/i });
    await userEvent.click(runBtn);

    // Wait for the COMPLETED detail to trigger the useEffect
    await waitFor(
      () => {
        const calls = invalidateSpy.mock.calls;
        const missedCall = calls.find(
          (args) => JSON.stringify(args[0]) === JSON.stringify({ queryKey: ["v2-missed"] })
        );
        expect(missedCall).toBeDefined();
      },
      { timeout: 10_000 }
    );

    // Also confirm v2-runs is invalidated in the same effect
    const runsCalls = invalidateSpy.mock.calls.filter(
      (args) => JSON.stringify(args[0]) === JSON.stringify({ queryKey: ["v2-runs"] })
    );
    expect(runsCalls.length).toBeGreaterThan(0);
  }, 15_000);

  // ── Test 2: Missed Opps tab shows fresh data after a new backtest ─────────
  it("shows updated missed opportunities on the Missed Opps tab after a completed backtest", async () => {
    /**
     * End-to-end flow:
     * 1. Page loads → overview fetches v2-missed → BASE_MISSED (WIPRO)
     * 2. User navigates to Missed Opps tab → sees WIPRO
     * 3. User runs a backtest; it completes immediately
     * 4. invalidateQueries(["v2-missed"]) fires with Missed Opps tab as the
     *    active subscriber → immediate re-fetch → UPDATED_MISSED (TATASTEEL)
     * 5. Table updates to show TATASTEEL without a page reload
     */
    const missedFetches = { count: 0 };
    mockApiJson.mockImplementation(buildMock(missedFetches));

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <AIValidationV2Page />
      </QueryClientProvider>
    );

    // First, navigate to Missed Opps tab — see stale data (WIPRO)
    await waitFor(() => missedFetches.count >= 1, { timeout: 3000 });
    const missedBtns = await screen.findAllByRole("button", { name: /Missed Opps/i });
    await userEvent.click(missedBtns[0]);

    // The tab mounts → uses cached value; WIPRO is visible
    await waitFor(() => {
      const els = screen.getAllByText("WIPRO");
      expect(els.length).toBeGreaterThan(0);
    }, { timeout: 3000 });

    // Navigate to Backtest Runner and run a new backtest
    const backtestBtns = await screen.findAllByRole("button", { name: /Backtest Runner/i });
    await userEvent.click(backtestBtns[0]);
    const runBtn = await screen.findByRole("button", { name: /Run Backtest/i });
    await userEvent.click(runBtn);

    // After the run completes, navigate back to Missed Opps tab
    // invalidateQueries fires → Missed Opps refetches → TATASTEEL appears
    await waitFor(() => missedFetches.count >= 2, { timeout: 10_000 });

    // Navigate back to Missed Opps if we left it (may already be on backtest tab)
    const missedBtns2 = await screen.findAllByRole("button", { name: /Missed Opps/i });
    await userEvent.click(missedBtns2[0]);

    await waitFor(() => {
      const els = screen.getAllByText("TATASTEEL");
      expect(els.length).toBeGreaterThan(0);
    }, { timeout: 5000 });
  }, 20_000);
});
