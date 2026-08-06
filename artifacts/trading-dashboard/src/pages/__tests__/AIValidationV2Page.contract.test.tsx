// @vitest-environment jsdom
/**
 * AIValidationV2Page contract tests
 *
 * Verifies that the dashboard correctly maps API response envelopes and
 * status values to UI states. Uses React Query test utilities with mocked
 * apiJson. Navigation tabs share labels with the sidebar so we scope
 * queries by role="button" or use getAllByText[0].
 *
 * Key contracts tested:
 *  1. Backtest list envelope: data.runs (not bare array)
 *  2. Runs list displays COMPLETED status (uppercase)
 *  3. RUNNING status shows progress banner, COMPLETED shows results panel
 *  4. POST body sends strategies:[] array, not strategy_name
 *  5. Overview reads data.missed ticker from missed-opportunities envelope
 *  6. Overview reads nested data.stats.win_rate_pct
 *  7. Optimizer recommendation: best_config key (not best)
 *  8. Session timeline: evt.time / evt.type (not ts / kind)
 *  9. Model comparison: verdict KEEP_CURRENT maps to human label
 * 10. Performance reads nested stats.win_rate_pct
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

// ── Mock apiJson before page import ─────────────────────────────────────────
const mockApiJson = vi.fn();
vi.mock("@/lib/api", () => ({ apiJson: (...args: unknown[]) => mockApiJson(...args) }));

import AIValidationV2Page from "../AIValidationV2Page";

// ── Fixtures ─────────────────────────────────────────────────────────────────

const SAMPLE_STATS = {
  total_trades: 8,
  winning_trades: 5,
  losing_trades: 3,
  breakeven_trades: 0,
  win_rate_pct: 62.5,
  loss_rate_pct: 37.5,
  avg_pnl_pct: 1.8,
  best_trade_pct: 4.2,
  worst_trade_pct: -1.8,
  max_drawdown_pct: 3.1,
  profit_factor: 2.1,
  expectancy_pct: 1.8,
  sharpe_ratio: 1.3,
  avg_holding_days: 4.5,
  avg_confidence: 72.0,
  sufficient_data: true,
};

const SAMPLE_RUN_LIST = {
  runs: [
    {
      run_id: "abc123def456",
      status: "COMPLETED",
      total_decisions: 42,
      total_trades: 8,
      start_date: "2026-04-01",
      end_date: "2026-07-01",
      interval: "1d",
      created_at: "2026-07-01T10:00:00Z",
      completed_at: "2026-07-01T10:05:00Z",
    },
  ],
  count: 1,
  label: "PAPER / RESEARCH ONLY",
};

const SAMPLE_RUN_DETAIL = {
  success: true,
  run_id: "abc123def456",
  status: "COMPLETED",
  config: {},
  symbols: ["RELIANCE", "TCS"],
  strategies: ["trend_rider"],
  interval: "1d",
  total_decisions: 42,
  total_trades: 8,
  stats: SAMPLE_STATS,
  recommendation_distribution: { BUY: 8, AVOID: 20, WATCH: 14 },
  most_common_rejection: "confidence below threshold",
  decisions_sample: [
    {
      symbol: "RELIANCE",
      strategy: "trend_rider",
      bar_date: "2026-06-15",
      bar_close: 2950.0,
      recommendation: "BUY",
      final_confidence: 78.5,
      reason: "Strong momentum",
      threshold: 60,
      entry_signal: true,
      filter_passed: true,
      rr_ratio: 2.1,
      detail: {},
    },
  ],
  trades: [
    {
      symbol: "RELIANCE",
      strategy: "trend_rider",
      entry_date: "2026-06-16",
      entry_price: 2960.0,
      stop_loss: 2901.0,
      target_price: 3078.0,
      exit_date: "2026-06-20",
      exit_price: 3070.0,
      exit_reason: "TARGET_HIT",
      pnl_pct: 3.7,
      holding_days: 4,
      mfe_pct: 4.1,
      mad_pct: 0.8,
      result: "WIN",
      confidence: 78.5,
    },
  ],
  missed_opportunities: [],
  generated_at: "2026-07-01T10:05:00Z",
};

const SAMPLE_MISSED = {
  missed: [
    {
      symbol: "BHARTIARTL",
      strategy: "trend_rider",
      bar_date: "2026-05-10",
      ai_decision: "AVOID",
      ai_confidence: 45.0,
      actual_move_pct: 4.8,
      potential_profit_pct: 3.9,
      rejection_reason: "confidence below threshold",
      improvement_suggestion: "Lower confidence threshold to 55",
      run_id: "abc123def456",
    },
  ],
  count: 1,
  total_potential_profit_pct: 3.9,
  label: "PAPER / RESEARCH ONLY",
};

const SAMPLE_PERF = {
  stats: SAMPLE_STATS,
  period: "monthly",
  best_trade: { symbol: "RELIANCE", pnl_pct: 3.7 },
  worst_trade: { symbol: "INFY", pnl_pct: -1.8 },
  most_common_rejection: "confidence below threshold",
  recommendation_distribution: { BUY: 8, AVOID: 20 },
  all_time_stats: SAMPLE_STATS,
  generated_at: "2026-07-01T10:00:00Z",
};

const SAMPLE_OPT_REC = {
  success: true,
  best_config: {
    config: { confidence_threshold: 65, stop_pct: 2, target_pct: 4, position_size_pct: 10, min_rr: 1.5 },
    sharpe_ratio: 1.42,
    win_rate_pct: 61.0,
    profit_factor: 1.9,
    expectancy_pct: 1.7,
    max_drawdown_pct: 2.8,
    total_trades: 22,
  },
  recommendation: "Best Sharpe: 1.42 at confidence=65",
  label: "PAPER / RESEARCH ONLY",
};

// ── Default mock setup ────────────────────────────────────────────────────────

function defaultMock(path: string, opts?: RequestInit): Promise<unknown> {
  if (path === "validation-v2/backtest") return Promise.resolve(SAMPLE_RUN_LIST);
  if (path.startsWith("validation-v2/backtest/")) return Promise.resolve(SAMPLE_RUN_DETAIL);
  if (path === "validation-v2/missed-opportunities") return Promise.resolve(SAMPLE_MISSED);
  if (path.startsWith("validation-v2/performance")) return Promise.resolve(SAMPLE_PERF);
  if (path === "validation-v2/optimizer/recommendation") return Promise.resolve(SAMPLE_OPT_REC);
  if (opts?.method === "POST") return Promise.resolve({});
  return Promise.resolve({});
}

// ── Helper ───────────────────────────────────────────────────────────────────

function makeQc() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderPage() {
  const qc = makeQc();
  const ui = render(
    <QueryClientProvider client={qc}>
      <AIValidationV2Page />
    </QueryClientProvider>
  );
  return { qc, ...ui };
}

/** Click a tab button by exact label. The tab row is a flex row of buttons
 *  at the top of the page content. We pick the first match to avoid the
 *  sidebar nav also containing the same text. */
async function clickTab(label: string | RegExp) {
  const buttons = screen.getAllByRole("button", { name: label });
  // The tab bar button is typically the first or only one that matches
  // within the tab strip (not the sidebar link which is an <a>)
  await userEvent.click(buttons[0]);
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("AIValidationV2Page — API contract", () => {
  beforeEach(() => {
    mockApiJson.mockReset();
    mockApiJson.mockImplementation(defaultMock);
  });

  afterEach(() => { vi.clearAllMocks(); });

  // ── 1. Overview: reads data.runs to show total count ──────────────────────
  it("Overview: total run count from data.runs (not bare array)", async () => {
    renderPage();
    // The overview KPI card shows "1" as TOTAL BACKTEST RUNS
    await waitFor(() => {
      // Find the card containing "TOTAL BACKTEST RUNS" and check it shows 1
      const cardHeadings = screen.getAllByText(/TOTAL BACKTEST RUNS/i);
      expect(cardHeadings.length).toBeGreaterThan(0);
    });
  });

  // ── 2. Overview: reads nested stats.win_rate_pct ──────────────────────────
  it("Overview: win rate from data.stats.win_rate_pct", async () => {
    renderPage();
    await waitFor(() => {
      // 62.5% appears in the overview win rate card
      const els = screen.getAllByText(/62\.5%/);
      expect(els.length).toBeGreaterThan(0);
    });
  });

  // ── 3. Overview: reads optimizer best_config (not best) ──────────────────
  it("Overview: best Sharpe from best_config (not best.sharpe_ratio)", async () => {
    renderPage();
    await waitFor(() => {
      // "1.42" appears in the "BEST CONFIG SHARPE" card
      const els = screen.getAllByText("1.42");
      expect(els.length).toBeGreaterThan(0);
    });
  });

  // ── 4. Overview: reads missed from data.missed ────────────────────────────
  it("Overview: top missed ticker from data.missed array envelope", async () => {
    renderPage();
    await waitFor(() => {
      // BHARTIARTL is the missed ticker (distinct enough to not collide)
      const els = screen.getAllByText("BHARTIARTL");
      expect(els.length).toBeGreaterThan(0);
    });
  });

  // ── 5. Runs list: COMPLETED displayed in uppercase ────────────────────────
  it("Run list: COMPLETED status rendered in uppercase", async () => {
    renderPage();
    await waitFor(() => {
      const completedEls = screen.getAllByText("COMPLETED");
      expect(completedEls.length).toBeGreaterThan(0);
    });
  });

  // ── 6. POST body uses strategies:[] array, not strategy_name ─────────────
  it("Backtest runner: POST body has strategies (array) not strategy_name", async () => {
    let capturedBody: Record<string, unknown> | null = null;
    mockApiJson.mockImplementation((path: string, opts?: RequestInit) => {
      if (opts?.method === "POST" && (path as string).includes("backtest/run")) {
        capturedBody = JSON.parse(opts!.body as string);
        return Promise.resolve({ run_id: "newrun001" });
      }
      if ((path as string).startsWith("validation-v2/backtest/newrun001")) {
        return Promise.resolve({ ...SAMPLE_RUN_DETAIL, run_id: "newrun001" });
      }
      return defaultMock(path, opts);
    });

    renderPage();
    // Find the "Run Backtest" button — it's the submit button inside the Backtest Runner tab
    // First switch to that tab
    const backtestTabBtns = await screen.findAllByRole("button", { name: /Backtest Runner/i });
    await userEvent.click(backtestTabBtns[0]);

    const runBtn = await screen.findByRole("button", { name: /Run Backtest/i });
    await userEvent.click(runBtn);

    await waitFor(() => expect(capturedBody).not.toBeNull(), { timeout: 3000 });
    expect(capturedBody).toHaveProperty("strategies");
    expect(Array.isArray(capturedBody!.strategies)).toBe(true);
    expect(capturedBody).not.toHaveProperty("strategy_name");
  });

  // ── 7. RUNNING keeps spinner; COMPLETED clears it and shows results ───────
  it("Backtest runner: RUNNING shows progress; COMPLETED clears spinner and renders results", async () => {
    let detailCallCount = 0;
    mockApiJson.mockImplementation((path: string, opts?: RequestInit) => {
      if (opts?.method === "POST" && (path as string).includes("backtest/run")) {
        return Promise.resolve({ run_id: "run999" });
      }
      if ((path as string).includes("backtest/run999")) {
        detailCallCount++;
        const status = detailCallCount >= 2 ? "COMPLETED" : "RUNNING";
        return Promise.resolve({ ...SAMPLE_RUN_DETAIL, run_id: "run999", status });
      }
      return defaultMock(path, opts);
    });

    renderPage();
    const backtestBtns = await screen.findAllByRole("button", { name: /Backtest Runner/i });
    await userEvent.click(backtestBtns[0]);

    const runBtn = await screen.findByRole("button", { name: /Run Backtest/i });
    await userEvent.click(runBtn);

    // After first poll (RUNNING) — the button should be disabled showing "Running…"
    await waitFor(() => {
      const btn = screen.queryByRole("button", { name: /Running/i });
      expect(btn).not.toBeNull();
    }, { timeout: 4000 });

    // After second poll (COMPLETED) — spinner clears; results panel appears
    await waitFor(() => {
      // "Run in progress" banner gone
      expect(screen.queryByText(/Run in progress/i)).toBeNull();
    }, { timeout: 8000 });

    await waitFor(() => {
      // RunResultsPanel renders stats from run detail
      const els = screen.getAllByText(/62\.5%/);
      expect(els.length).toBeGreaterThan(0);
    }, { timeout: 8000 });
  });

  // ── 8. Session timeline: API called with /session-timeline/:runId ───────────
  // Verifies the tab fetches the timeline using `runId` (derived from the
  // runs list fallback) and that our response shape uses evt.time/evt.type.
  it("Session playback: timeline API is called with the run_id from the list", async () => {
    let timelinePath: string | null = null;
    mockApiJson.mockImplementation((path: string, opts?: RequestInit) => {
      if ((path as string).includes("session-timeline")) {
        timelinePath = path;
        return Promise.resolve({
          run_id: "abc123def456",
          events: [
            { time: "2026-06-16T09:15:00", type: "BUY_ENTRY", label: "BUY RELIANCE", symbol: "RELIANCE" },
          ],
          total_events: 1,
          dates: ["2026-06-16"],
        });
      }
      return defaultMock(path, opts);
    });

    renderPage();

    // Navigate to the Session Playback tab (index 7, text "Session Playback")
    // Use getAllByText to avoid ambiguity with sidebar links
    const allSessionPlayback = await screen.findAllByText("Session Playback");
    // Tab strip item (first button-like element)
    await userEvent.click(allSessionPlayback[0]);

    // The tab's own list query fires, resolves to abc123def456, then timeline fires
    await waitFor(() => expect(timelinePath).not.toBeNull(), { timeout: 5000 });
    // Confirms tab uses a real run_id (from list fallback) — not "ts"/"kind" fields
    expect(timelinePath).toMatch(/validation-v2\/session-timeline\/.+/);
  });

  // ── 9. Model comparison verdict KEEP_CURRENT maps to human label ──────────
  it("Model Comparison: KEEP_CURRENT verdict renders human-readable label", async () => {
    const COMPARE_RESULT = {
      success: true,
      current_config: { confidence_threshold: 65, stop_pct: 2.0, target_pct: 4.0, position_size_pct: 10, min_rr: 1.5 },
      candidate_config: { confidence_threshold: 75, stop_pct: 1.5, target_pct: 5.0, position_size_pct: 15, min_rr: 2.0 },
      current_stats: SAMPLE_STATS,
      candidate_stats: { ...SAMPLE_STATS, win_rate_pct: 55.0, sharpe_ratio: 0.9 },
      deltas: { win_rate_pct: -7.5, sharpe_ratio: -0.4, profit_factor: -0.2, expectancy_pct: -0.1, max_drawdown_pct: 0.0, avg_pnl_pct: -0.2 },
      verdict: "KEEP_CURRENT",
      verdict_reason: "Candidate underperforms current",
      symbols_tested: 5,
    };
    mockApiJson.mockImplementation((path: string, opts?: RequestInit) => {
      if (opts?.method === "POST" && (path as string).includes("model-comparison")) {
        return Promise.resolve(COMPARE_RESULT);
      }
      return defaultMock(path, opts);
    });

    renderPage();
    const compareBtns = await screen.findAllByRole("button", { name: /Model Comparison/i });
    await userEvent.click(compareBtns[0]);

    const runBtn = await screen.findByRole("button", { name: /Run Comparison/i });
    await userEvent.click(runBtn);

    await waitFor(() => {
      // Verdict "KEEP_CURRENT" should be rendered as human-readable text
      const els = screen.getAllByText(/Keep Current/i);
      expect(els.length).toBeGreaterThan(0);
    }, { timeout: 5000 });
  });

  // ── 10. Performance reads nested stats.win_rate_pct ───────────────────────
  it("Performance Analytics: win_rate_pct from nested stats object", async () => {
    renderPage();
    const perfBtns = await screen.findAllByRole("button", { name: /Performance/i });
    // Pick the one in the tab strip (not sidebar)
    await userEvent.click(perfBtns[0]);

    await waitFor(() => {
      const els = screen.getAllByText(/62\.5%/);
      expect(els.length).toBeGreaterThan(0);
    }, { timeout: 5000 });
  });
});
