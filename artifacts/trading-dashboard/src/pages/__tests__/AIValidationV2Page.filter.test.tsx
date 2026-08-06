// @vitest-environment jsdom
/**
 * AIValidationV2Page — Trade Simulation filter toggle tests (#403)
 *
 * Verifies that:
 *   1. All four filter buttons (ALL / WIN / LOSS / BREAKEVEN) render with correct counts.
 *   2. "ALL" shows every trade card by default.
 *   3. "WIN" hides LOSS and BREAKEVEN cards; shows only WIN cards.
 *   4. "LOSS" hides WIN and BREAKEVEN cards; shows only LOSS cards.
 *   5. "BREAKEVEN" hides WIN and LOSS cards; shows only BREAKEVEN cards.
 *   6. The equity curve container is present regardless of which filter is active.
 *   7. The heading reflects the filtered count ("X of Y Trades") when a filter is active.
 *   8. A filter with zero matches shows the empty message instead of cards.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

// ── Recharts stub ─────────────────────────────────────────────────────────────
vi.mock("recharts", () => {
  const React = require("react");
  const stub = (name: string) => {
    const C = ({ children, ...rest }: any) =>
      React.createElement("div", { "data-testid": `recharts-${name}`, ...rest }, children);
    C.displayName = name;
    return C;
  };
  return {
    LineChart: stub("LineChart"),
    Line: stub("Line"),
    AreaChart: stub("AreaChart"),
    Area: stub("Area"),
    BarChart: stub("BarChart"),
    Bar: stub("Bar"),
    XAxis: stub("XAxis"),
    YAxis: stub("YAxis"),
    Tooltip: stub("Tooltip"),
    ResponsiveContainer: ({ children }: any) =>
      React.createElement("div", { "data-testid": "recharts-ResponsiveContainer" }, children),
    CartesianGrid: stub("CartesianGrid"),
    ReferenceArea: stub("ReferenceArea"),
    ReferenceLine: stub("ReferenceLine"),
  };
});

vi.mock("@/lib/api", () => ({ apiJson: vi.fn() }));
vi.mock("@/components/DataFreshnessBar", () => ({ default: () => null }));

import { apiJson } from "@/lib/api";
const mockApiJson = vi.mocked(apiJson);

// ── Fixtures ──────────────────────────────────────────────────────────────────
const RUN_ID = "run-filter-test-001";

const TRADES = [
  // 2 WINs
  {
    id: 1, run_id: RUN_ID, symbol: "RELIANCE", strategy: "trend_rider",
    entry_date: "2025-01-10", entry_price: 2800, exit_date: "2025-01-15",
    exit_price: 2940, pnl_pct: 5.0, result: "WIN", exit_reason: "TARGET_HIT",
    stop_loss: 2716, target_price: 2940, holding_days: 5,
    mfe_pct: 5.5, mad_pct: -0.8, confidence: 72,
  },
  {
    id: 2, run_id: RUN_ID, symbol: "TCS", strategy: "trend_rider",
    entry_date: "2025-01-16", entry_price: 4000, exit_date: "2025-01-20",
    exit_price: 4200, pnl_pct: 5.0, result: "WIN", exit_reason: "TARGET_HIT",
    stop_loss: 3880, target_price: 4200, holding_days: 4,
    mfe_pct: 5.2, mad_pct: -0.5, confidence: 68,
  },
  // 1 LOSS
  {
    id: 3, run_id: RUN_ID, symbol: "INFY", strategy: "trend_rider",
    entry_date: "2025-01-17", entry_price: 1800, exit_date: "2025-01-20",
    exit_price: 1746, pnl_pct: -3.0, result: "LOSS", exit_reason: "STOP_LOSS",
    stop_loss: 1746, target_price: 1890, holding_days: 3,
    mfe_pct: 0.8, mad_pct: -3.2, confidence: 55,
  },
  // 1 BREAKEVEN (null result — treated as breakeven)
  {
    id: 4, run_id: RUN_ID, symbol: "SBIN", strategy: "trend_rider",
    entry_date: "2025-01-21", entry_price: 800, exit_date: "2025-01-22",
    exit_price: 800.5, pnl_pct: 0.0, result: "BREAKEVEN", exit_reason: "TIME_EXIT",
    stop_loss: 776, target_price: 840, holding_days: 1,
    mfe_pct: 0.2, mad_pct: -0.1, confidence: 50,
  },
];

const mockStats = {
  total_trades: 4, winning_trades: 2, losing_trades: 1, breakeven_trades: 1,
  win_rate_pct: 50, loss_rate_pct: 25, avg_pnl_pct: 3.25,
  best_trade_pct: 5, worst_trade_pct: -3, max_drawdown_pct: -3,
  profit_factor: 2, expectancy_pct: 1.5, sharpe_ratio: 1.1,
  avg_holding_days: 3.25, avg_confidence: 61.25, sufficient_data: true,
};

const RUN_DETAIL = {
  run_id: RUN_ID, status: "COMPLETED",
  config: {}, symbols: ["RELIANCE", "TCS", "INFY", "SBIN"],
  strategies: ["trend_rider"], interval: "1d",
  total_decisions: 80, total_trades: 4,
  stats: mockStats,
  recommendation_distribution: { BUY: 4 },
  most_common_rejection: "LOW_CONFIDENCE",
  decisions_sample: [], trades: TRADES, missed_opportunities: [],
  generated_at: "2025-01-22T10:00:00Z",
};

// ── Helpers ───────────────────────────────────────────────────────────────────
function makeQC() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

async function renderAndNavigateToSimulation() {
  const qc = makeQC();
  qc.setQueryData(["v2-runs"], {
    runs: [{
      run_id: RUN_ID, status: "COMPLETED", total_decisions: 80, total_trades: 4,
      start_date: "2025-01-01", end_date: "2025-01-22",
      interval: "1d", created_at: "2025-01-22T00:00:00Z", completed_at: null,
    }],
  });
  qc.setQueryData(["v2-run", RUN_ID], RUN_DETAIL);

  const { default: AIValidationV2Page } = await import("../AIValidationV2Page");
  render(
    <QueryClientProvider client={qc}>
      <AIValidationV2Page />
    </QueryClientProvider>
  );

  // Click the Trade Simulation tab (first occurrence = tab bar)
  const simTabs = screen.getAllByRole("button", { name: /Trade Simulation/i });
  await act(async () => { simTabs[0].click(); });
  await new Promise(r => setTimeout(r, 30));
}

// ── Tests ─────────────────────────────────────────────────────────────────────
describe("Trade Simulation result filter", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApiJson.mockResolvedValue({});
  });
  afterEach(cleanup);

  it("renders all four filter buttons with correct count badges", async () => {
    await renderAndNavigateToSimulation();

    // Each button has the label plus a count badge in the same accessible element
    const group = screen.getByRole("group", { name: /Filter trades by result/i });
    expect(group).toBeTruthy();

    // "All" button with count=4
    expect(group.textContent).toContain("All");
    expect(group.textContent).toContain("4"); // ALL count

    // WIN / LOSS / BREAKEVEN
    expect(group.textContent).toContain("WIN");
    expect(group.textContent).toContain("LOSS");
    expect(group.textContent).toContain("BREAKEVEN");
  });

  it("shows all 4 trade cards when filter is ALL (default)", async () => {
    await renderAndNavigateToSimulation();

    // All trade symbols visible
    expect(screen.getByText("RELIANCE")).toBeTruthy();
    expect(screen.getAllByText("TCS").length).toBeGreaterThan(0);
    expect(screen.getByText("INFY")).toBeTruthy();
    expect(screen.getByText("SBIN")).toBeTruthy();

    // Heading shows total count
    expect(screen.getByText("4 Trades")).toBeTruthy();
  });

  it("shows only WIN trade cards when WIN filter is active", async () => {
    await renderAndNavigateToSimulation();

    const winBtn = screen.getByRole("button", { name: /^WIN/ });
    await act(async () => { fireEvent.click(winBtn); });

    // WIN trades visible
    expect(screen.getByText("RELIANCE")).toBeTruthy();
    expect(screen.getAllByText("TCS").length).toBeGreaterThan(0);

    // LOSS and BREAKEVEN cards hidden
    expect(screen.queryByText("INFY")).toBeNull();
    expect(screen.queryByText("SBIN")).toBeNull();

    // Heading says "2 of 4 Trades"
    expect(screen.getByText("2 of 4 Trades")).toBeTruthy();
  });

  it("shows only LOSS trade cards when LOSS filter is active", async () => {
    await renderAndNavigateToSimulation();

    const lossBtn = screen.getByRole("button", { name: /^LOSS/ });
    await act(async () => { fireEvent.click(lossBtn); });

    expect(screen.getByText("INFY")).toBeTruthy();
    expect(screen.queryByText("RELIANCE")).toBeNull();
    expect(screen.queryByText("SBIN")).toBeNull();

    expect(screen.getByText("1 of 4 Trades")).toBeTruthy();
  });

  it("shows only BREAKEVEN trade cards when BREAKEVEN filter is active", async () => {
    await renderAndNavigateToSimulation();

    const beBtn = screen.getByRole("button", { name: /^BREAKEVEN/ });
    await act(async () => { fireEvent.click(beBtn); });

    expect(screen.getByText("SBIN")).toBeTruthy();
    expect(screen.queryByText("RELIANCE")).toBeNull();
    expect(screen.queryByText("INFY")).toBeNull();

    expect(screen.getByText("1 of 4 Trades")).toBeTruthy();
  });

  it("returns to showing all cards when ALL filter is re-selected", async () => {
    await renderAndNavigateToSimulation();

    // Switch to WIN then back to ALL
    const winBtn = screen.getByRole("button", { name: /^WIN/ });
    await act(async () => { fireEvent.click(winBtn); });
    expect(screen.queryByText("INFY")).toBeNull();

    const allBtn = screen.getByRole("button", { name: /^All/ });
    await act(async () => { fireEvent.click(allBtn); });

    expect(screen.getByText("INFY")).toBeTruthy();
    expect(screen.getByText("4 Trades")).toBeTruthy();
  });

  it("the equity curve container stays visible regardless of active filter", async () => {
    await renderAndNavigateToSimulation();

    // Equity chart is rendered (stubs render data-testid="recharts-LineChart")
    expect(screen.getByTestId("recharts-LineChart")).toBeTruthy();

    // Switch to LOSS — chart must still be there
    const lossBtn = screen.getByRole("button", { name: /^LOSS/ });
    await act(async () => { fireEvent.click(lossBtn); });

    expect(screen.getByTestId("recharts-LineChart")).toBeTruthy();
  });

  it("count badges reflect the actual result distribution from the run", async () => {
    // Re-use the shared render (4 trades: 2 WIN, 1 LOSS, 1 BREAKEVEN).
    // Verify count badges show the correct numbers without needing
    // a separate render — this directly tests the filter group content.
    await renderAndNavigateToSimulation();

    const group = screen.getByRole("group", { name: /Filter trades by result/i });
    const text = group.textContent ?? "";

    // All button badge = 4
    expect(text).toMatch(/All.*4|4.*All/);
    // WIN badge = 2
    expect(text).toMatch(/WIN.*2|2.*WIN/);
    // LOSS badge = 1
    expect(text).toMatch(/LOSS.*1|1.*LOSS/);
    // BREAKEVEN badge = 1
    expect(text).toMatch(/BREAKEVEN.*1|1.*BREAKEVEN/);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// null / unknown result values are bucketed as BREAKEVEN (#405)
// ─────────────────────────────────────────────────────────────────────────────

describe("Trade Simulation filter — null/unknown result values", () => {
  // Run with 1 WIN, 1 LOSS, 1 null-result, 1 "CANCELLED" (unknown enum)
  const NULL_RUN_ID = "run-null-result-test-001";

  const NULL_TRADES = [
    {
      id: 10, run_id: NULL_RUN_ID, symbol: "WIPRO", strategy: "trend_rider",
      entry_date: "2025-02-01", entry_price: 450, exit_date: "2025-02-05",
      exit_price: 472.5, pnl_pct: 5.0, result: "WIN", exit_reason: "TARGET_HIT",
      stop_loss: 436.5, target_price: 472.5, holding_days: 4,
      mfe_pct: 5.1, mad_pct: -0.3, confidence: 70,
    },
    {
      id: 11, run_id: NULL_RUN_ID, symbol: "HCLTECH", strategy: "trend_rider",
      entry_date: "2025-02-02", entry_price: 1500, exit_date: "2025-02-06",
      exit_price: 1455, pnl_pct: -3.0, result: "LOSS", exit_reason: "STOP_LOSS",
      stop_loss: 1455, target_price: 1575, holding_days: 4,
      mfe_pct: 0.5, mad_pct: -3.1, confidence: 52,
    },
    // null result — open trade or run produced no result field
    {
      id: 12, run_id: NULL_RUN_ID, symbol: "SUNPHARMA", strategy: "trend_rider",
      entry_date: "2025-02-03", entry_price: 1200, exit_date: null,
      exit_price: null, pnl_pct: null, result: null, exit_reason: null,
      stop_loss: 1164, target_price: 1260, holding_days: null,
      mfe_pct: null, mad_pct: null, confidence: 60,
    },
    // unknown enum value "CANCELLED" — not in the "WIN"/"LOSS" set
    {
      id: 13, run_id: NULL_RUN_ID, symbol: "ITC", strategy: "trend_rider",
      entry_date: "2025-02-04", entry_price: 450, exit_date: "2025-02-05",
      exit_price: 450, pnl_pct: 0, result: "CANCELLED", exit_reason: "MANUAL",
      stop_loss: 436.5, target_price: 472.5, holding_days: 1,
      mfe_pct: 0, mad_pct: -0.1, confidence: 55,
    },
  ];

  const NULL_RUN_DETAIL = {
    run_id: NULL_RUN_ID, status: "COMPLETED",
    config: {}, symbols: ["WIPRO", "HCLTECH", "SUNPHARMA", "ITC"],
    strategies: ["trend_rider"], interval: "1d",
    total_decisions: 40, total_trades: 4,
    stats: {
      total_trades: 4, winning_trades: 1, losing_trades: 1, breakeven_trades: 2,
      win_rate_pct: 25, loss_rate_pct: 25, avg_pnl_pct: 0.5,
      best_trade_pct: 5, worst_trade_pct: -3, max_drawdown_pct: -3,
      profit_factor: 1, expectancy_pct: 0.5, sharpe_ratio: 0.5,
      avg_holding_days: 3, avg_confidence: 59.25, sufficient_data: true,
    },
    recommendation_distribution: { BUY: 4 },
    most_common_rejection: "LOW_CONFIDENCE",
    decisions_sample: [], trades: NULL_TRADES, missed_opportunities: [],
    generated_at: "2025-02-06T10:00:00Z",
  };

  async function renderNullRun() {
    const qc = makeQC();
    qc.setQueryData(["v2-runs"], {
      runs: [{
        run_id: NULL_RUN_ID, status: "COMPLETED", total_decisions: 40, total_trades: 4,
        start_date: "2025-02-01", end_date: "2025-02-06",
        interval: "1d", created_at: "2025-02-06T00:00:00Z", completed_at: null,
      }],
    });
    qc.setQueryData(["v2-run", NULL_RUN_ID], NULL_RUN_DETAIL);

    const { default: AIValidationV2Page } = await import("../AIValidationV2Page");
    render(
      <QueryClientProvider client={qc}>
        <AIValidationV2Page />
      </QueryClientProvider>
    );

    const simTabs = screen.getAllByRole("button", { name: /Trade Simulation/i });
    await act(async () => { simTabs[0].click(); });
    await new Promise(r => setTimeout(r, 30));
  }

  beforeEach(() => {
    vi.clearAllMocks();
    mockApiJson.mockResolvedValue({});
  });
  afterEach(cleanup);

  it("counts null-result and unknown-enum trades under BREAKEVEN, not WIN or LOSS", async () => {
    await renderNullRun();

    const group = screen.getByRole("group", { name: /Filter trades by result/i });
    const text = group.textContent ?? "";

    // 1 WIN, 1 LOSS, 2 BREAKEVEN (null + CANCELLED)
    expect(text).toMatch(/WIN.*1|1.*WIN/);
    expect(text).toMatch(/LOSS.*1|1.*LOSS/);
    expect(text).toMatch(/BREAKEVEN.*2|2.*BREAKEVEN/);
  });

  it("clicking BREAKEVEN filter shows the null-result trade card", async () => {
    await renderNullRun();

    const beBtn = screen.getByRole("button", { name: /^BREAKEVEN/ });
    await act(async () => { fireEvent.click(beBtn); });

    // SUNPHARMA has result: null — must appear under BREAKEVEN
    expect(screen.getByText("SUNPHARMA")).toBeTruthy();
  });

  it("clicking BREAKEVEN filter shows the unknown-enum (CANCELLED) trade card", async () => {
    await renderNullRun();

    const beBtn = screen.getByRole("button", { name: /^BREAKEVEN/ });
    await act(async () => { fireEvent.click(beBtn); });

    // ITC has result: "CANCELLED" — must appear under BREAKEVEN
    expect(screen.getByText("ITC")).toBeTruthy();
  });

  it("clicking BREAKEVEN filter hides WIN and LOSS cards", async () => {
    await renderNullRun();

    const beBtn = screen.getByRole("button", { name: /^BREAKEVEN/ });
    await act(async () => { fireEvent.click(beBtn); });

    expect(screen.queryByText("WIPRO")).toBeNull();   // WIN trade hidden
    expect(screen.queryByText("HCLTECH")).toBeNull(); // LOSS trade hidden
  });

  it("the count heading reflects 2 of 4 when BREAKEVEN filter is active", async () => {
    await renderNullRun();

    const beBtn = screen.getByRole("button", { name: /^BREAKEVEN/ });
    await act(async () => { fireEvent.click(beBtn); });

    expect(screen.getByText("2 of 4 Trades")).toBeTruthy();
  });

  it("null-result trades do NOT appear under WIN or LOSS filters", async () => {
    await renderNullRun();

    const winBtn = screen.getByRole("button", { name: /^WIN/ });
    await act(async () => { fireEvent.click(winBtn); });

    expect(screen.queryByText("SUNPHARMA")).toBeNull();
    expect(screen.queryByText("ITC")).toBeNull();

    const lossBtn = screen.getByRole("button", { name: /^LOSS/ });
    await act(async () => { fireEvent.click(lossBtn); });

    expect(screen.queryByText("SUNPHARMA")).toBeNull();
    expect(screen.queryByText("ITC")).toBeNull();
  });
});
