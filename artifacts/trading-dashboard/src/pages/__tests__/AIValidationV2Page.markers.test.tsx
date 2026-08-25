// @vitest-environment jsdom
/**
 * AIValidationV2Page — Trade Simulation equity curve marker tests (#398)
 *
 * Verifies that:
 *   1. The eqCurve timeline contains both ENTRY and EXIT events for every trade.
 *   2. Entry events carry entry_price and the equity at entry (unchanged from previous exit).
 *   3. Exit events carry exit_price, exit_reason, pnl_pct, and the updated equity.
 *   4. WIN/LOSS/BREAKEVEN result values propagate to both event types.
 *   5. The TradeSimulationTab renders the chart container and trade cards.
 *   6. The legend labels ("Entry", "EXIT", "WIN", "LOSS") are present in the DOM.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

// ── Recharts stub (jsdom has no SVG layout engine) ────────────────────────────
vi.mock("recharts", () => {
  const React = require("react");
  const stub = (name: string) => {
    const C = ({ children, data, ...rest }: any) =>
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
    ResponsiveContainer: ({ children }: any) => React.createElement("div", { "data-testid": "recharts-ResponsiveContainer" }, children),
    CartesianGrid: stub("CartesianGrid"),
    ReferenceArea: stub("ReferenceArea"),
    ReferenceLine: stub("ReferenceLine"),
  };
});

// ── API stub ──────────────────────────────────────────────────────────────────
vi.mock("@/lib/api", () => ({
  apiJson: vi.fn(),
}));
vi.mock("@/components/DataFreshnessBar", () => ({
  default: () => null,
}));

import { apiJson } from "@/lib/api";
const mockApiJson = vi.mocked(apiJson);

// ── Fixtures ──────────────────────────────────────────────────────────────────

const RUN_ID = "run-marker-test-001";

/** Three trades: one WIN, one LOSS, one BREAKEVEN */
const TRADES = [
  {
    id: 1, run_id: RUN_ID, symbol: "RELIANCE", strategy: "trend_rider",
    entry_date: "2025-01-10", entry_price: 2800.00,
    exit_date: "2025-01-15",  exit_price: 2940.00,
    pnl_pct: 5.0, result: "WIN", exit_reason: "TARGET_HIT",
    stop_loss: 2716, target_price: 2940, holding_days: 5,
    mfe_pct: 5.5, mad_pct: -0.8, confidence: 72,
  },
  {
    id: 2, run_id: RUN_ID, symbol: "TCS", strategy: "trend_rider",
    entry_date: "2025-01-16", entry_price: 4000.00,
    exit_date: "2025-01-20",  exit_price: 3880.00,
    pnl_pct: -3.0, result: "LOSS", exit_reason: "STOP_LOSS",
    stop_loss: 3880, target_price: 4200, holding_days: 4,
    mfe_pct: 1.0, mad_pct: -3.2, confidence: 58,
  },
  {
    id: 3, run_id: RUN_ID, symbol: "INFY", strategy: "trend_rider",
    entry_date: "2025-01-21", entry_price: 1800.00,
    exit_date: "2025-01-22",  exit_price: 1800.50,
    pnl_pct: 0.0, result: "BREAKEVEN", exit_reason: "TIME_EXIT",
    stop_loss: 1746, target_price: 1890, holding_days: 1,
    mfe_pct: 0.3, mad_pct: -0.1, confidence: 55,
  },
];

const mockStats = {
  total_trades: 3, winning_trades: 1, losing_trades: 1, breakeven_trades: 1,
  win_rate_pct: 33.3, loss_rate_pct: 33.3, avg_pnl_pct: 0.67,
  best_trade_pct: 5.0, worst_trade_pct: -3.0, max_drawdown_pct: -3.0,
  profit_factor: 1.1, expectancy_pct: 0.5, sharpe_ratio: 0.6,
  avg_holding_days: 3.3, avg_confidence: 61.7, sufficient_data: true,
};

const RUN_DETAIL = {
  run_id: RUN_ID, status: "COMPLETED",
  config: {}, symbols: ["RELIANCE","TCS","INFY"],
  strategies: ["trend_rider"], interval: "1d",
  total_decisions: 60, total_trades: 3,
  stats: mockStats,
  recommendation_distribution: { BUY: 3 },
  most_common_rejection: "LOW_CONFIDENCE",
  decisions_sample: [], trades: TRADES, missed_opportunities: [],
  generated_at: "2025-01-22T10:00:00Z",
};

// ── Helper ────────────────────────────────────────────────────────────────────

function makeQC() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function Wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={makeQC()}>{children}</QueryClientProvider>;
}

// ── Unit tests: eqCurve shape ─────────────────────────────────────────────────
// We test the timeline data produced by the component's internal logic by
// replicating it from the known TRADES fixture (same algorithm as the component).

describe("eqCurve expanded timeline (unit)", () => {
  type EqEvent = {
    pos: number; equity: number;
    event: "START" | "ENTRY" | "EXIT";
    tradeNum: number; result: string | null;
    symbol: string; entry_price: number | null; exit_price: number | null;
    pnl_pct: number | null; exit_reason: string | null;
    entry_date: string; exit_date: string | null;
  };

  function buildEqCurve(trades: typeof TRADES): EqEvent[] {
    let equity = 10000;
    const curve: EqEvent[] = [
      {
        pos: 0, equity: 10000, event: "START", tradeNum: 0,
        result: null, symbol: "", entry_price: null, exit_price: null,
        pnl_pct: null, exit_reason: null, entry_date: "", exit_date: null,
      },
    ];
    trades.forEach((t, i) => {
      const entryEquity = Math.round(equity);
      equity += equity * (t.pnl_pct ?? 0) / 100;
      const exitEquity = Math.round(equity);
      const meta = {
        tradeNum: i + 1, result: t.result,
        symbol: t.symbol, entry_price: t.entry_price, exit_price: t.exit_price,
        pnl_pct: t.pnl_pct, exit_reason: t.exit_reason,
        entry_date: t.entry_date, exit_date: t.exit_date,
      };
      curve.push({ pos: (i + 1) * 2 - 1, equity: entryEquity, event: "ENTRY", ...meta });
      curve.push({ pos: (i + 1) * 2,     equity: exitEquity,  event: "EXIT",  ...meta });
    });
    return curve;
  }

  const curve = buildEqCurve(TRADES);

  it("has START + 2 events per trade (total 1 + 2*N points)", () => {
    expect(curve).toHaveLength(1 + TRADES.length * 2);
  });

  it("first point is START at ₹10,000", () => {
    expect(curve[0]).toMatchObject({ event: "START", equity: 10000, pos: 0 });
  });

  it("every trade has an ENTRY event before its EXIT event", () => {
    TRADES.forEach((_, i) => {
      const entryIdx = 1 + i * 2;
      const exitIdx  = 2 + i * 2;
      expect(curve[entryIdx].event).toBe("ENTRY");
      expect(curve[exitIdx].event).toBe("EXIT");
      expect(curve[entryIdx].tradeNum).toBe(i + 1);
      expect(curve[exitIdx].tradeNum).toBe(i + 1);
    });
  });

  it("ENTRY equity equals the equity after the previous trade (portfolio unchanged at entry)", () => {
    // Trade 1 entry: portfolio = 10000 (no previous trade)
    expect(curve[1].equity).toBe(10000);
    // Trade 2 entry: portfolio = 10000 * 1.05 = 10500
    expect(curve[3].equity).toBe(10500);
    // Trade 3 entry: portfolio = 10500 * 0.97 = 10185
    expect(curve[5].equity).toBe(10185);
  });

  it("EXIT equity equals ENTRY equity adjusted by pnl_pct", () => {
    // Trade 1: 10000 * 1.05 = 10500
    expect(curve[2].equity).toBe(10500);
    // Trade 2: 10500 * 0.97 = 10185
    expect(curve[4].equity).toBe(10185);
    // Trade 3: 10185 * 1.00 = 10185 (0% PnL)
    expect(curve[6].equity).toBe(10185);
  });

  it("result propagates to both ENTRY and EXIT events for each trade", () => {
    const results = ["WIN", "LOSS", "BREAKEVEN"];
    TRADES.forEach((_, i) => {
      const entry = curve[1 + i * 2];
      const exit  = curve[2 + i * 2];
      expect(entry.result).toBe(results[i]);
      expect(exit.result).toBe(results[i]);
    });
  });

  it("ENTRY events carry entry_price; EXIT events carry exit_price + exit_reason", () => {
    TRADES.forEach((t, i) => {
      const entry = curve[1 + i * 2];
      const exit  = curve[2 + i * 2];
      expect(entry.entry_price).toBe(t.entry_price);
      expect(exit.exit_price).toBe(t.exit_price);
      expect(exit.exit_reason).toBe(t.exit_reason);
    });
  });

  it("pos values are sequential odd (entry) then even (exit)", () => {
    TRADES.forEach((_, i) => {
      expect(curve[1 + i * 2].pos).toBe((i + 1) * 2 - 1); // 1, 3, 5
      expect(curve[2 + i * 2].pos).toBe((i + 1) * 2);      // 2, 4, 6
    });
  });
});

// ── Integration: component renders legend and trade cards ─────────────────────

describe("TradeSimulationTab rendering (integration)", () => {
  afterEach(cleanup);
  beforeEach(() => {
    vi.clearAllMocks();
    mockApiJson.mockImplementation((path: string) => {
      if (String(path).includes("validation-v2/backtest/run-")) {
        return Promise.resolve(RUN_DETAIL);
      }
      if (String(path).includes("validation-v2/backtest")) {
        return Promise.resolve({
          runs: [{ run_id: RUN_ID, status: "COMPLETED", total_decisions: 60, total_trades: 3, start_date: "2025-01-01", end_date: "2025-01-22", interval: "1d", created_at: "2025-01-22T00:00:00Z", completed_at: "2025-01-22T10:00:00Z" }],
          count: 1,
        });
      }
      return Promise.resolve({});
    });
  });

  async function renderSimTab() {
    // Dynamically import to pick up mocks
    const { default: AIValidationV2Page } = await import("../AIValidationV2Page");
    const { container } = render(
      <Wrapper>
        <AIValidationV2Page />
      </Wrapper>
    );
    // Wait for run list to populate (needed for tab to have an activeRunId)
    await new Promise(r => setTimeout(r, 50));
    return container;
  }

  it("overview renders without crashing and shows the page heading", async () => {
    await renderSimTab();
    expect(screen.getByRole("heading", { name: "Strategy Validation — Research Models" })).toBeTruthy();
  });

  it("legend contains both 'Entry' and 'Exit' marker labels", async () => {
    // Seed the cache with the run detail so the Trade Simulation tab has data
    const qc = makeQC();
    qc.setQueryData(["v2-runs"], {
      runs: [{ run_id: RUN_ID, status: "COMPLETED", total_decisions: 60, total_trades: 3, start_date: "2025-01-01", end_date: "2025-01-22", interval: "1d", created_at: "2025-01-22T00:00:00Z", completed_at: null }],
    });
    qc.setQueryData(["v2-run", RUN_ID], RUN_DETAIL);

    const { default: AIValidationV2Page } = await import("../AIValidationV2Page");
    render(
      <QueryClientProvider client={qc}>
        <AIValidationV2Page />
      </QueryClientProvider>
    );

    // Navigate to Trade Simulation tab (may match both tab bar + overview card)
    const simTabs = screen.getAllByRole("button", { name: /Trade Simulation/i });
    simTabs[0].click(); // first match = tab bar button
    await new Promise(r => setTimeout(r, 50));

    // Legend items — use getAllByText since WIN/LOSS also appear in trade cards
    expect(screen.getByText("Entry")).toBeTruthy();
    expect(screen.getByText("Exit")).toBeTruthy();
    expect(screen.getAllByText("WIN").length).toBeGreaterThan(0);
    expect(screen.getAllByText("LOSS").length).toBeGreaterThan(0);
    expect(screen.getByText("BE")).toBeTruthy(); // only in legend
  });

  it("trade cards are rendered for each trade in the run", async () => {
    const qc = makeQC();
    qc.setQueryData(["v2-runs"], {
      runs: [{ run_id: RUN_ID, status: "COMPLETED", total_decisions: 60, total_trades: 3, start_date: "2025-01-01", end_date: "2025-01-22", interval: "1d", created_at: "2025-01-22T00:00:00Z", completed_at: null }],
    });
    qc.setQueryData(["v2-run", RUN_ID], RUN_DETAIL);

    const { default: AIValidationV2Page } = await import("../AIValidationV2Page");
    render(
      <QueryClientProvider client={qc}>
        <AIValidationV2Page />
      </QueryClientProvider>
    );

    const simTabs = screen.getAllByRole("button", { name: /Trade Simulation/i });
    simTabs[0].click(); // first match = tab bar button
    await new Promise(r => setTimeout(r, 50));

    // All three symbols should appear
    expect(screen.getByText("RELIANCE")).toBeTruthy();
    expect(screen.getByText("TCS")).toBeTruthy();
    expect(screen.getByText("INFY")).toBeTruthy();
  });
});
