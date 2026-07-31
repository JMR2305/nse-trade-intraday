// @vitest-environment jsdom
/**
 * PaperAnalytics.test.tsx — Phase 8.2
 *
 * Smoke-tests and contract-tests for the Advanced Paper Trading Analytics
 * Dashboard.  All backend calls are mocked via vi.mock("@/lib/api").
 *
 * Coverage:
 *  1.  Page header renders "Paper Analytics" and advisory badge.
 *  2.  All 12 tabs render without crash (Overview … Export).
 *  3.  Loading spinner shows while summary is pending.
 *  4.  Disabled state shows "Analytics Disabled" when status=DISABLED.
 *  5.  Overview renders KPI cards (Total Trades, Win Rate, etc.) with data.
 *  6.  Overview renders score ring with analytics_score value.
 *  7.  Overview falls back to "N/A" for missing best_strategy / best_sector.
 *  8.  No crash when summary data has null KPI fields.
 *  9.  Trades tab "available=false" shows disabled view, not crash.
 *  10. Trades tab with data renders trade KPI cards (Winning, Losing …).
 *  11. Trades tab — SparkLine with < 2 equity points shows "No data".
 *  12. Strategies tab with data renders strategy table rows.
 *  13. Strategies tab with empty strategies array shows "No data".
 *  14. Risk tab renders Sharpe / Sortino / Calmar KPI cards.
 *  15. Risk tab with no data shows disabled view.
 *  16. Portfolio tab renders capital growth KPI.
 *  17. Sectors tab renders sector rows.
 *  18. Pre-Open tab renders availability message when unavailable.
 *  19. Learning tab renders best strategy insight.
 *  20. AI Insights tab renders observations list.
 *  21. Export tab renders Download JSON and Download CSV buttons.
 *  22. "ADVISORY ONLY" badge is present on overview when data loads.
 *  23. Tab switch button activates the correct tab.
 *  24. Error state for summary query renders without crash.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, cleanup, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ── Module mocks ──────────────────────────────────────────────────────────────

vi.mock("@/lib/api", () => ({
  API_BASE: "",
  apiJson:  vi.fn(),
}));

vi.mock("wouter", () => ({
  Link:        ({ href, children, className }: React.AnchorHTMLAttributes<HTMLAnchorElement>) =>
    React.createElement("a", { href, className }, children),
  useLocation: vi.fn(() => ["/"]),
  useRoute:    vi.fn(() => [false, {}]),
}));

import { apiJson } from "@/lib/api";
import PaperAnalytics from "./PaperAnalytics";

// ── Fixtures ──────────────────────────────────────────────────────────────────

const SUMMARY_ENABLED = {
  status:              "ENABLED",
  analytics_score:     74,
  grade:               "B",
  total_trades:        42,
  win_rate:            58.3,
  profit_factor:       1.62,
  expectancy:          1250,
  total_pnl:           52500,
  sharpe_ratio:        1.34,
  max_drawdown_pct:    12.4,
  volatility_pct:      18.6,
  best_strategy:       "VWAP Pullback",
  best_sector:         "Banking",
  best_market_condition: "TRENDING",
};

const SUMMARY_DISABLED = {
  status:  "DISABLED",
  message: "Set PAPER_ANALYTICS_ENABLED=true to enable.",
};

const TRADES_DATA = {
  available:           true,
  total_trades:        42,
  winning_trades:      25,
  losing_trades:       17,
  win_rate:            59.5,
  avg_winner:          2800,
  avg_loser:           -1400,
  profit_factor:       1.62,
  expectancy:          1250,
  avg_holding_human:   "2h 30m",
  longest_win_streak:  6,
  longest_loss_streak: 3,
  total_pnl:           52500,
  max_drawdown:        -15000,
  max_drawdown_pct:    12.4,
  current_drawdown:    -3000,
  recovery_pct:        65.0,
  initial_capital:     500000,
  equity_curves:       {
    daily:   [
      { timestamp: "2026-07-01", equity: 500000 },
      { timestamp: "2026-07-08", equity: 510000 },
      { timestamp: "2026-07-15", equity: 525000 },
      { timestamp: "2026-07-22", equity: 552500 },
    ],
    weekly:  [
      { timestamp: "2026-07-01", equity: 500000 },
      { timestamp: "2026-07-22", equity: 552500 },
    ],
    monthly: [
      { timestamp: "2026-07-01", equity: 500000 },
      { timestamp: "2026-07-22", equity: 552500 },
    ],
  },
  drawdown_curve:   [
    { timestamp: "2026-07-01", equity: 500000, drawdown: 0,     drawdown_pct: 0 },
    { timestamp: "2026-07-08", equity: 487000, drawdown: 13000, drawdown_pct: 2.6 },
    { timestamp: "2026-07-15", equity: 510000, drawdown: 0,     drawdown_pct: 0 },
    { timestamp: "2026-07-22", equity: 552500, drawdown: 0,     drawdown_pct: 0 },
  ],
  rolling_returns:  [
    { date: "2026-07-08", return_pct: 2.1 },
    { date: "2026-07-15", return_pct: 3.4 },
  ],
  recovery_curve:   [],
  largest_winner:   { symbol: "RELIANCE", pnl: 8500, pnl_pct: 3.4, strategy: "VWAP Pullback", exit_ts: "2026-07-20T11:00:00" },
  largest_loser:    { symbol: "SAIL",     pnl: -4200, pnl_pct: -2.1, strategy: "ORB", exit_ts: "2026-07-14T15:00:00" },
};

const TRADES_UNAVAILABLE = { available: false, message: "No completed trades." };

const STRATEGIES_DATA = {
  available:        true,
  best_strategy:    "VWAP Pullback",
  worst_strategy:   "ORB",
  total_strategies: 3,
  strategies: [
    {
      strategy_name:    "VWAP Pullback",
      total_trades:     20,
      win_rate:         65,
      avg_return:       2000,
      profit_factor:    1.9,
      expectancy:       1500,
      max_drawdown:     -8000,
      contribution_pct: 55.0,
      confidence:       72,
    },
    {
      strategy_name:    "ORB",
      total_trades:     12,
      win_rate:         42,
      avg_return:       -300,
      profit_factor:    0.85,
      expectancy:       -200,
      max_drawdown:     -12000,
      contribution_pct: -15.0,
      confidence:       null,
    },
  ],
};

const STRATEGIES_EMPTY = {
  available:        true,
  best_strategy:    null,
  worst_strategy:   null,
  total_strategies: 0,
  strategies:       [],
};

const RISK_DATA = {
  available:       true,
  sharpe_ratio:    1.34,
  sortino_ratio:   1.87,
  calmar_ratio:    0.92,
  volatility_pct:  18.6,
  max_drawdown_pct: 12.4,
  avg_drawdown_pct: 4.1,
  recovery_time_days: 7,
  risk_reward_ratio:  1.8,
};

const RISK_UNAVAILABLE = { available: false };

const PORTFOLIO_DATA = {
  available:             true,
  total_value:           552500,
  cash:                  150000,
  invested:              402500,
  cash_utilisation_pct:  72.9,
  diversification_score: 0.68,
  capital_growth: [
    { date: "2026-07-01", value: 500000 },
    { date: "2026-07-22", value: 552500 },
  ],
  sector_allocation: [
    { sector: "Banking", weight_pct: 35.0 },
    { sector: "IT",      weight_pct: 25.0 },
  ],
  strategy_allocation: [
    { strategy: "VWAP Pullback", weight_pct: 55.0 },
  ],
};

const LEARNING_DATA = {
  available:                  true,
  has_data:                   true,
  best_strategy:              "VWAP Pullback",
  worst_strategy:             "ORB",
  most_consistent_strategy:   "VWAP Pullback",
  highest_risk_strategy:      "ORB",
  best_sector:                "Banking",
  worst_sector:               "Metal",
  best_market_condition:      "TRENDING",
  worst_market_condition:     "CHOPPY",
  winning_characteristics:    ["High-volume entry", "Pullback to VWAP"],
  losing_characteristics:     ["Low-volume breakout"],
  time_analytics:     {
    available:    true,
    best_session: "Opening",
    worst_session: "Afternoon",
    best_hour:    "09:30",
    worst_hour:   "14:00",
    avg_hold_seconds: 4500,
    sessions:     [],
    hours:        [],
  },
  sector_analytics:   {
    available:              true,
    total_sectors_traded:   2,
    best_sector:            "Banking",
    worst_sector:           "Metal",
    best_win_rate_sector:   "Banking",
    sectors: [
      { sector: "Banking", trade_count: 12, win_rate: 66.7, avg_return: 2500, total_pnl: 30000, contribution_pct: 40 },
    ],
  },
  execution_analytics: {
    available:          true,
    total_records:      42,
    completed_records:  40,
    avg_quality_score:  78,
    overall_grade:      "B",
    grade_distribution: {},
    strategy_quality:   [],
  },
  ai_insights: {
    available:                   true,
    most_profitable_window:      "09:30–10:00",
    highest_performing_regime:   "TRENDING",
    most_reliable_strategy:      "VWAP Pullback",
    most_reliable_preopen_band:  "80–100",
    confidence_score:            75,
    ai_health_score:             72,
    ai_health_label:             "Good",
    recommended_research_areas:  ["Improve ORB entries", "Reduce afternoon trades"],
    note:                        "Advisory only.",
  },
};

const PREOPEN_DATA = {
  available:           false,
  message:             "Pre-open data unavailable.",
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  });
}

type MockApiJson = ReturnType<typeof vi.fn>;

/**
 * Wire apiJson to return the given map based on the URL path.
 * Keys match the path suffix, e.g. "paper-analytics/summary".
 */
function wireApi(
  mock: MockApiJson,
  responses: Partial<Record<string, unknown>>,
  defaultVal: unknown = null,
) {
  mock.mockImplementation((path: string) => {
    for (const [key, val] of Object.entries(responses)) {
      if (path.includes(key)) return Promise.resolve(val);
    }
    return Promise.resolve(defaultVal);
  });
}

function mountPage(client: QueryClient) {
  return render(
    <QueryClientProvider client={client}>
      <PaperAnalytics />
    </QueryClientProvider>,
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("PaperAnalytics — Phase 8.2", () => {
  let client: QueryClient;
  const mock = apiJson as MockApiJson;

  beforeEach(() => {
    client = makeClient();
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  // ── 1. Header ──────────────────────────────────────────────────────────────
  it("1. renders page heading 'Paper Analytics'", async () => {
    wireApi(mock, { summary: SUMMARY_ENABLED });
    mountPage(client);
    expect(screen.getByText("Paper Analytics")).toBeTruthy();
  });

  // ── 2. Advisory badge ──────────────────────────────────────────────────────
  it("2. renders PAPER TRADING / ADVISORY ONLY badge in header", async () => {
    wireApi(mock, { summary: SUMMARY_ENABLED });
    mountPage(client);
    expect(screen.getByText("PAPER TRADING / ADVISORY ONLY")).toBeTruthy();
  });

  // ── 3. All 12 tabs present ─────────────────────────────────────────────────
  it("3. renders all 12 tab buttons", async () => {
    wireApi(mock, { summary: SUMMARY_ENABLED });
    mountPage(client);
    const expectedLabels = [
      "Overview", "Trades", "Strategies", "Risk", "Portfolio",
      "Time", "Sectors", "Pre-Open", "Execution", "Learning",
      "AI Insights", "Export",
    ];
    for (const label of expectedLabels) {
      expect(screen.getByText(label)).toBeTruthy();
    }
  });

  // ── 4. Loading spinner ─────────────────────────────────────────────────────
  it("4. shows loading spinner while summary is pending", () => {
    mock.mockImplementation(() => new Promise(() => {})); // never resolves
    mountPage(client);
    // The spinner element uses animate-spin class
    const spinner = document.querySelector(".animate-spin");
    expect(spinner).toBeTruthy();
  });

  // ── 5. Disabled state ──────────────────────────────────────────────────────
  it("5. shows 'Analytics Disabled' when feature flag is off", async () => {
    wireApi(mock, { summary: SUMMARY_DISABLED });
    mountPage(client);
    await waitFor(() => screen.getByText("Analytics Disabled"));
    expect(screen.getByText(/PAPER_ANALYTICS_ENABLED=true/)).toBeTruthy();
  });

  // ── 6. Overview KPI cards ──────────────────────────────────────────────────
  it("6. overview renders Total Trades, Win Rate, Profit Factor, Expectancy labels", async () => {
    wireApi(mock, { summary: SUMMARY_ENABLED, trades: TRADES_DATA });
    mountPage(client);
    await waitFor(() => screen.getByText("Total Trades"));
    expect(screen.getByText("Win Rate")).toBeTruthy();
    expect(screen.getByText("Profit Factor")).toBeTruthy();
    expect(screen.getByText("Expectancy")).toBeTruthy();
  });

  // ── 7. Analytics score ring ────────────────────────────────────────────────
  it("7. overview renders the analytics score from summary", async () => {
    wireApi(mock, { summary: SUMMARY_ENABLED, trades: TRADES_DATA });
    mountPage(client);
    // Score is rendered as integer in SVG text
    await waitFor(() => screen.getByText("74"));
    expect(screen.getByText("74")).toBeTruthy();
  });

  // ── 8. Grade displayed ─────────────────────────────────────────────────────
  it("8. overview displays the grade from summary", async () => {
    wireApi(mock, { summary: SUMMARY_ENABLED, trades: TRADES_DATA });
    mountPage(client);
    await waitFor(() => {
      // "B" appears both in heading area and SVG grade label
      const matches = screen.getAllByText("B");
      expect(matches.length).toBeGreaterThan(0);
    });
  });

  // ── 9. Best strategy / sector / condition ──────────────────────────────────
  it("9. overview shows best_strategy, best_sector, best_market_condition", async () => {
    wireApi(mock, { summary: SUMMARY_ENABLED, trades: TRADES_DATA });
    mountPage(client);
    await waitFor(() => screen.getByText("VWAP Pullback"));
    expect(screen.getByText("Banking")).toBeTruthy();
    expect(screen.getByText("TRENDING")).toBeTruthy();
  });

  // ── 10. Fallback "N/A" for missing insights ────────────────────────────────
  it("10. overview shows 'N/A' when best_strategy is absent", async () => {
    const noInsights = { ...SUMMARY_ENABLED, best_strategy: null, best_sector: null, best_market_condition: null };
    wireApi(mock, { summary: noInsights, trades: TRADES_DATA });
    mountPage(client);
    await waitFor(() => {
      const naItems = screen.getAllByText("N/A");
      expect(naItems.length).toBeGreaterThanOrEqual(3);
    });
  });

  // ── 11. Overview secondary KPI row ────────────────────────────────────────
  it("11. overview renders Total PnL, Sharpe Ratio, Max Drawdown, Volatility labels", async () => {
    wireApi(mock, { summary: SUMMARY_ENABLED, trades: TRADES_DATA });
    mountPage(client);
    await waitFor(() => screen.getByText("Total PnL"));
    expect(screen.getByText("Sharpe Ratio")).toBeTruthy();
    expect(screen.getByText("Max Drawdown")).toBeTruthy();
    expect(screen.getByText("Volatility")).toBeTruthy();
  });

  // ── 12. Overview with null KPI fields — no crash ───────────────────────────
  it("12. overview renders without crash when numeric KPIs are null", async () => {
    const nullKpis = {
      ...SUMMARY_ENABLED,
      win_rate: null, profit_factor: null, expectancy: null,
      total_pnl: null, sharpe_ratio: null, max_drawdown_pct: null, volatility_pct: null,
    };
    wireApi(mock, { summary: nullKpis, trades: TRADES_DATA });
    mountPage(client);
    await waitFor(() => screen.getByText("Total Trades"));
    // Null formatters should render "—"
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThan(0);
  });

  // ── 13. Trades tab — unavailable ───────────────────────────────────────────
  it("13. Trades tab shows disabled view when available=false", async () => {
    wireApi(mock, { summary: SUMMARY_ENABLED, trades: TRADES_UNAVAILABLE });
    mountPage(client);
    // Click Trades tab
    fireEvent.click(screen.getByText("Trades"));
    await waitFor(() => screen.getByText("Analytics Disabled"));
  });

  // ── 14. Trades tab — KPI cards with data ──────────────────────────────────
  it("14. Trades tab renders trade KPI cards when data is available", async () => {
    wireApi(mock, { summary: SUMMARY_ENABLED, trades: TRADES_DATA });
    mountPage(client);
    fireEvent.click(screen.getByText("Trades"));
    await waitFor(() => screen.getByText("Winning"));
    expect(screen.getByText("Losing")).toBeTruthy();
    expect(screen.getByText("Avg Winner")).toBeTruthy();
    expect(screen.getByText("Avg Loser")).toBeTruthy();
    expect(screen.getByText("Profit Factor")).toBeTruthy();
    expect(screen.getByText("Win Streak")).toBeTruthy();
    expect(screen.getByText("Loss Streak")).toBeTruthy();
  });

  // ── 15. Trades tab — rolling returns table ────────────────────────────────
  it("15. Trades tab renders rolling returns table when data present", async () => {
    wireApi(mock, { summary: SUMMARY_ENABLED, trades: TRADES_DATA });
    mountPage(client);
    fireEvent.click(screen.getByText("Trades"));
    await waitFor(() => screen.getByText("5-Day Return"));
  });

  // ── 16. Trades tab — largest winner / loser ───────────────────────────────
  it("16. Trades tab shows largest winner and loser symbols", async () => {
    wireApi(mock, { summary: SUMMARY_ENABLED, trades: TRADES_DATA });
    mountPage(client);
    fireEvent.click(screen.getByText("Trades"));
    await waitFor(() => screen.getByText("RELIANCE"));
    expect(screen.getByText("SAIL")).toBeTruthy();
  });

  // ── 17. Strategies tab — table rows ───────────────────────────────────────
  it("17. Strategies tab renders strategy rows in table", async () => {
    wireApi(mock, { summary: SUMMARY_ENABLED, strategies: STRATEGIES_DATA });
    mountPage(client);
    fireEvent.click(screen.getByText("Strategies"));
    // "VWAP Pullback" may appear more than once (summary KPI + table row)
    await waitFor(() => {
      const matches = screen.getAllByText("VWAP Pullback");
      expect(matches.length).toBeGreaterThan(0);
    });
    expect(screen.getAllByText("ORB").length).toBeGreaterThan(0);
  });

  // ── 18. Strategies tab — empty state ──────────────────────────────────────
  it("18. Strategies tab shows 'No data' when strategies array is empty", async () => {
    wireApi(mock, { summary: SUMMARY_ENABLED, strategies: STRATEGIES_EMPTY });
    mountPage(client);
    fireEvent.click(screen.getByText("Strategies"));
    await waitFor(() => screen.getByText(/No data yet/));
  });

  // ── 19. Strategies tab — header KPIs ──────────────────────────────────────
  it("19. Strategies tab shows Best Strategy and Worst Strategy KPIs", async () => {
    wireApi(mock, { summary: SUMMARY_ENABLED, strategies: STRATEGIES_DATA });
    mountPage(client);
    fireEvent.click(screen.getByText("Strategies"));
    await waitFor(() => screen.getByText("Best Strategy"));
    expect(screen.getByText("Worst Strategy")).toBeTruthy();
    expect(screen.getByText("Total Tracked")).toBeTruthy();
  });

  // ── 20. Risk tab — KPI cards ──────────────────────────────────────────────
  it("20. Risk tab renders Sharpe, Sortino, Calmar, Volatility KPIs", async () => {
    wireApi(mock, { summary: SUMMARY_ENABLED, risk: RISK_DATA });
    mountPage(client);
    fireEvent.click(screen.getByText("Risk"));
    await waitFor(() => screen.getByText("Sharpe Ratio"));
    expect(screen.getByText("Sortino Ratio")).toBeTruthy();
    expect(screen.getByText("Calmar Ratio")).toBeTruthy();
    expect(screen.getByText("Volatility")).toBeTruthy();
  });

  // ── 21. Risk tab — unavailable ────────────────────────────────────────────
  it("21. Risk tab shows disabled view when available=false", async () => {
    wireApi(mock, { summary: SUMMARY_ENABLED, risk: RISK_UNAVAILABLE });
    mountPage(client);
    fireEvent.click(screen.getByText("Risk"));
    await waitFor(() => screen.getByText("Analytics Disabled"));
  });

  // ── 22. Portfolio tab ─────────────────────────────────────────────────────
  it("22. Portfolio tab renders capital growth and allocation section headers", async () => {
    wireApi(mock, { summary: SUMMARY_ENABLED, portfolio: PORTFOLIO_DATA });
    mountPage(client);
    fireEvent.click(screen.getByText("Portfolio"));
    await waitFor(() => screen.getByText("Portfolio Analytics"));
  });

  // ── 23. Sectors tab ───────────────────────────────────────────────────────
  it("23. Sectors tab renders 'Sector Analytics' header when data available", async () => {
    wireApi(mock, { summary: SUMMARY_ENABLED, learning: LEARNING_DATA });
    mountPage(client);
    fireEvent.click(screen.getByText("Sectors"));
    await waitFor(() => screen.getByText("Sector Analytics"));
  });

  // ── 24. Time tab ─────────────────────────────────────────────────────────
  it("24. Time tab renders 'Time Analytics' header when data available", async () => {
    wireApi(mock, { summary: SUMMARY_ENABLED, learning: LEARNING_DATA });
    mountPage(client);
    fireEvent.click(screen.getByText("Time"));
    await waitFor(() => screen.getByText("Time Analytics"));
  });

  // ── 25. Execution tab ────────────────────────────────────────────────────
  it("25. Execution tab renders 'Execution Quality' header when data available", async () => {
    wireApi(mock, { summary: SUMMARY_ENABLED, learning: LEARNING_DATA });
    mountPage(client);
    fireEvent.click(screen.getByText("Execution"));
    await waitFor(() => screen.getByText("Execution Quality"));
  });

  // ── 26. Pre-Open tab — unavailable message ────────────────────────────────
  it("26. Pre-Open tab shows disabled view when available=false", async () => {
    wireApi(mock, { summary: SUMMARY_ENABLED, preopen: PREOPEN_DATA });
    mountPage(client);
    fireEvent.click(screen.getByText("Pre-Open"));
    // PREOPEN_DATA has available=false → DisabledView is rendered
    await waitFor(() => screen.getByText("Analytics Disabled"));
  });

  // ── 27. Learning tab ─────────────────────────────────────────────────────
  it("27. Learning tab renders best/worst strategy insights", async () => {
    wireApi(mock, { summary: SUMMARY_ENABLED, learning: LEARNING_DATA });
    mountPage(client);
    fireEvent.click(screen.getByText("Learning"));
    await waitFor(() => screen.getByText("Learning Insights"));
    expect(screen.getByText("Best Strategy")).toBeTruthy();
    expect(screen.getByText("Worst Strategy")).toBeTruthy();
  });

  // ── 28. Learning — winning characteristics ────────────────────────────────
  it("28. Learning tab renders winning characteristics list", async () => {
    wireApi(mock, { summary: SUMMARY_ENABLED, learning: LEARNING_DATA });
    mountPage(client);
    fireEvent.click(screen.getByText("Learning"));
    await waitFor(() => screen.getByText("High-volume entry"));
  });

  // ── 29. AI Insights tab ───────────────────────────────────────────────────
  it("29. AI Insights tab renders advisory KPI labels", async () => {
    wireApi(mock, { summary: SUMMARY_ENABLED, learning: LEARNING_DATA });
    mountPage(client);
    fireEvent.click(screen.getByText("AI Insights"));
    // "AI Insights" already appears as the tab button, so don't wait on it.
    // Wait for a KPI label that only appears once the tab content resolves.
    await waitFor(() => screen.getByText("Advisory Confidence"), { timeout: 3000 });
    expect(screen.getByText("Best Trading Window")).toBeTruthy();
    expect(screen.getByText("Top Regime")).toBeTruthy();
    expect(screen.getByText("Most Reliable Strategy")).toBeTruthy();
  });

  // ── 30. Export tab — download buttons ─────────────────────────────────────
  it("30. Export tab renders Download JSON and Download CSV buttons", async () => {
    wireApi(mock, { summary: SUMMARY_ENABLED });
    mountPage(client);
    fireEvent.click(screen.getByText("Export"));
    await waitFor(() => screen.getByText("Download JSON"));
    expect(screen.getByText("Download CSV")).toBeTruthy();
  });

  // ── 31. Export tab — advisory note ────────────────────────────────────────
  it("31. Export tab shows advisory/paper-trading note", async () => {
    wireApi(mock, { summary: SUMMARY_ENABLED });
    mountPage(client);
    fireEvent.click(screen.getByText("Export"));
    await waitFor(() => screen.getByText(/Advisory \/ Paper Trading only/));
  });

  // ── 32. Tab switching — active tab highlight ──────────────────────────────
  it("32. clicking a tab button makes it the active tab", async () => {
    wireApi(mock, { summary: SUMMARY_ENABLED, risk: RISK_DATA });
    mountPage(client);
    const riskTab = screen.getByRole("button", { name: /Risk/ });
    fireEvent.click(riskTab);
    // Active tab has the teal styling class
    expect(riskTab.className).toContain("text-teal-400");
  });

  // ── 33. Overview tab initially active ────────────────────────────────────
  it("33. Overview tab is active by default on first render", async () => {
    wireApi(mock, { summary: SUMMARY_ENABLED, trades: TRADES_DATA });
    mountPage(client);
    const overviewTab = screen.getByRole("button", { name: /Overview/ });
    expect(overviewTab.className).toContain("text-teal-400");
  });

  // ── 34. Phase 8.2 subtitle ────────────────────────────────────────────────
  it("34. page subtitle mentions Phase 8.2 and Advisory Only", async () => {
    wireApi(mock, { summary: SUMMARY_ENABLED });
    mountPage(client);
    expect(screen.getByText(/Phase 8\.2/)).toBeTruthy();
    expect(screen.getByText(/Advisory Only/)).toBeTruthy();
  });

  // ── 35. ADVISORY ONLY badge in overview header ────────────────────────────
  it("35. overview shows 'ADVISORY ONLY' badge when data loads", async () => {
    wireApi(mock, { summary: SUMMARY_ENABLED, trades: TRADES_DATA });
    mountPage(client);
    await waitFor(() => screen.getByText("ADVISORY ONLY"));
  });

  // ── 36. SparkLine fallback when all equity data is empty ─────────────────
  it("36. Trades tab renders no-data message when both daily and drawdown curves are empty", async () => {
    wireApi(mock, {
      summary: SUMMARY_ENABLED,
      // Empty ALL equity/drawdown sources so EquityWithDrawdownChart hits its < 2 guard
      trades: {
        ...TRADES_DATA,
        equity_curves: { daily: [], weekly: [], monthly: [] },
        drawdown_curve: [],
      },
    });
    mountPage(client);
    fireEvent.click(screen.getByText("Trades"));
    // EquityWithDrawdownChart renders this message when points.length < 2
    await waitFor(() => screen.getByText(/No equity data yet/));
  });

  // ── 37. Strategies — confidence column shows "—" when null ────────────────
  it("37. Strategies table shows '—' for null confidence", async () => {
    wireApi(mock, { summary: SUMMARY_ENABLED, strategies: STRATEGIES_DATA });
    mountPage(client);
    fireEvent.click(screen.getByText("Strategies"));
    // "VWAP Pullback" may appear in multiple places (KPI card + table row)
    await waitFor(() => {
      const matches = screen.getAllByText("VWAP Pullback");
      expect(matches.length).toBeGreaterThan(0);
    });
    const dashes = screen.getAllByText("—");
    // ORB row has null confidence → renders "—"
    expect(dashes.length).toBeGreaterThan(0);
  });

  // ── 38. No crash with null summary ────────────────────────────────────────
  it("38. overview shows 'No data' when summary resolves to null", async () => {
    wireApi(mock, { summary: null });
    mountPage(client);
    await waitFor(() => screen.getByText(/No data yet/));
  });
});
