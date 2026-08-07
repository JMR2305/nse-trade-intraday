// @vitest-environment jsdom
/**
 * TradeDecisions.lowevidence.test.tsx — Task #449
 *
 * Confirms that the Trade Decisions page renders the low-evidence badge
 * correctly in the browser when the API returns `low_evidence: true` and
 * `total_trades: 3`, and that the badge is absent when `low_evidence: false`.
 *
 * Scenarios covered:
 *  1. Badge is present and shows "LOW EVIDENCE (3 trades)" when low_evidence=true
 *  2. data-testid="badge-low-evidence-SYMBOL" is present for that stock
 *  3. Badge is absent for a stock where low_evidence=false
 *  4. Badge is absent for a stock where low_evidence=false but total_trades is high
 *  5. Badge shows "LOW EVIDENCE (0 trades)" when total_trades is missing (null/undefined)
 *  6. Multiple stocks — only the low-evidence one carries the badge
 *  7. Page renders without crash when all decisions have low_evidence=false
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ── Silence Recharts layout warnings in jsdom ─────────────────────────────────
vi.mock("recharts", () => {
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
      React.createElement("div", { "data-testid": "recharts-rc" }, children),
    CartesianGrid: stub("CartesianGrid"),
    ReferenceArea: stub("ReferenceArea"),
    ReferenceLine: stub("ReferenceLine"),
  };
});

// ── External dep mocks ────────────────────────────────────────────────────────
vi.mock("@/lib/api", () => ({ apiJson: vi.fn() }));
vi.mock("@/components/DataFreshnessBar", () => ({ default: () => null }));
vi.mock("@/components/Phase20Lifecycle", () => ({
  EntryEvaluationPanel: () => null,
}));
vi.mock("@/components/Phase21Panels", () => ({ WhyThisTrade: () => null }));
vi.mock("@/components/Phase22Panels", () => ({
  PaperEligibilityPanel: () => null,
}));
vi.mock("wouter", () => ({
  Link: ({ href, children, className }: any) =>
    React.createElement("a", { href, className }, children),
  useLocation: vi.fn(() => ["/"]),
  useRoute: vi.fn(() => [false, {}]),
}));

// ── api-client-react mock — controls useGetTradeDecisions ─────────────────────
const mockUseGetTradeDecisions = vi.fn();
vi.mock("@workspace/api-client-react", () => ({
  useGetTradeDecisions: (...args: any[]) => mockUseGetTradeDecisions(...args),
  getGetTradeDecisionsQueryKey: () => ["trade-decisions"],
}));

import { apiJson } from "@/lib/api";
const mockApiJson = vi.mocked(apiJson);

import TradeDecisions from "./TradeDecisions";

// ── Fixtures ──────────────────────────────────────────────────────────────────

/** Minimal TradeDecision shape the component reads from. */
function makeDecision(overrides: Partial<Record<string, any>>) {
  return {
    stock: "UNKNOWN",
    sector: "Technology",
    recommendation: "BUY",
    data_status: "OK",
    low_reliability: false,
    low_evidence: false,
    total_trades: 10,
    invalidation_override: false,
    invalidation_override_conditions: [],
    base_confidence: 70,
    learning_adjustment: 0,
    final_confidence: 70,
    model_version: 0,
    model_adjustment: 0,
    similarity_adjustment: 0,
    evidence_reliability: "MEDIUM",
    similarity_evidence: null,
    historical_expectancy: 2.5,
    historical_profit_factor: 1.8,
    historical_win_rate: 0.65,
    historical_sharpe: 1.2,
    historical_kelly: 0.12,
    pattern_match_pct: 75,
    historical_trades: 10,
    best_pattern: "Breakout",
    regime_match: true,
    price: 1500,
    entry_price: 1520,
    stop_loss: 1450,
    target: 1650,
    rr_ratio: 2.5,
    expected_holding_days: 10,
    expected_drawdown: 4,
    position_open: false,
    position_quantity: 0,
    position_avg_price: 0,
    position_pnl_pct: 0,
    exit_reason: "",
    reason: "Test reason",
    explanation: "",
    explanation_sections: {},
    failed_conditions: [],
    breakdown: [],
    analyst_summary: "",
    current_observation: "",
    historical_assessment: "",
    decision_reasoning: "",
    invalidation_conditions: [],
    upgrade_conditions: [],
    invalidation_met: 0,
    upgrade_met: 0,
    decision_state: "VALID",
    decision_timestamp: new Date().toISOString(),
    valid_until: null,
    validity_note: "",
    conflict_level: "NONE",
    conflict_explanation: "",
    missing_data_fields: [],
    ...overrides,
  };
}

/** Stock with low evidence (3 trades only). */
const LOW_EVIDENCE_STOCK = makeDecision({
  stock: "LOWEV_X",
  recommendation: "BUY",
  low_evidence: true,
  total_trades: 3,
  final_confidence: 65,
});

/** Stock with sufficient evidence (default 10 trades). */
const NORMAL_STOCK = makeDecision({
  stock: "NORMAL_Y",
  recommendation: "STRONG_BUY",
  low_evidence: false,
  total_trades: 25,
  final_confidence: 82,
});

/** Stock with low_evidence=false but still 4 trades (boundary check). */
const BOUNDARY_STOCK = makeDecision({
  stock: "BOUNDARY_Z",
  recommendation: "WATCH",
  low_evidence: false,
  total_trades: 4,
  final_confidence: 55,
});

function makePayload(decisions: any[]) {
  return {
    decisions,
    strong_buy_count: decisions.filter((d) => d.recommendation === "STRONG_BUY").length,
    buy_count: decisions.filter((d) => d.recommendation === "BUY").length,
    watch_count: decisions.filter((d) => d.recommendation === "WATCH").length,
    avoid_count: 0,
    exit_count: 0,
    generated_at: new Date().toISOString(),
    warning: null,
  };
}

// ── Test helpers ──────────────────────────────────────────────────────────────

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

function renderPage(qc = makeQueryClient()) {
  return render(
    <QueryClientProvider client={qc}>
      <TradeDecisions />
    </QueryClientProvider>
  );
}

// ── Setup / teardown ──────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks();

  mockUseGetTradeDecisions.mockReturnValue({
    data: makePayload([LOW_EVIDENCE_STOCK, NORMAL_STOCK]),
    isLoading: false,
    error: null,
  });

  // Sub-queries in advisory panels — return null so panels stay hidden
  mockApiJson.mockResolvedValue(null);
});

afterEach(() => {
  cleanup();
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("TradeDecisions — low-evidence badge rendering", () => {

  // ── 1 ─────────────────────────────────────────────────────────────────────
  it("renders the low-evidence badge with correct text when low_evidence=true and total_trades=3", async () => {
    renderPage();
    await waitFor(() => {
      const badge = screen.getByTestId("badge-low-evidence-LOWEV_X");
      expect(badge).toBeTruthy();
      expect(badge.textContent?.trim()).toBe("LOW EVIDENCE (3 trades)");
    });
  });

  // ── 2 ─────────────────────────────────────────────────────────────────────
  it("data-testid='badge-low-evidence-LOWEV_X' is present in the DOM", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("badge-low-evidence-LOWEV_X")).toBeTruthy();
    });
  });

  // ── 3 ─────────────────────────────────────────────────────────────────────
  it("badge is absent for a stock where low_evidence=false", async () => {
    renderPage();
    await waitFor(() => {
      // NORMAL_Y must be visible
      expect(screen.getByText("NORMAL_Y")).toBeTruthy();
    });
    expect(screen.queryByTestId("badge-low-evidence-NORMAL_Y")).toBeNull();
  });

  // ── 4 ─────────────────────────────────────────────────────────────────────
  it("badge is absent for BOUNDARY_Z (low_evidence=false, total_trades=4)", async () => {
    mockUseGetTradeDecisions.mockReturnValue({
      data: makePayload([LOW_EVIDENCE_STOCK, BOUNDARY_STOCK]),
      isLoading: false,
      error: null,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("BOUNDARY_Z")).toBeTruthy();
    });
    expect(screen.queryByTestId("badge-low-evidence-BOUNDARY_Z")).toBeNull();
  });

  // ── 5 ─────────────────────────────────────────────────────────────────────
  it("badge shows '0 trades' when low_evidence=true but total_trades is not set", async () => {
    const noTradesStock = makeDecision({
      stock: "NOTRADES_A",
      recommendation: "WATCH",
      low_evidence: true,
      total_trades: undefined,
      final_confidence: 50,
    });
    mockUseGetTradeDecisions.mockReturnValue({
      data: makePayload([noTradesStock]),
      isLoading: false,
      error: null,
    });
    renderPage();
    await waitFor(() => {
      const badge = screen.getByTestId("badge-low-evidence-NOTRADES_A");
      expect(badge.textContent?.trim()).toBe("LOW EVIDENCE (0 trades)");
    });
  });

  // ── 6 ─────────────────────────────────────────────────────────────────────
  it("only the low-evidence stock carries the badge when shown alongside a normal stock", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("LOWEV_X")).toBeTruthy();
      expect(screen.getByText("NORMAL_Y")).toBeTruthy();
    });
    // One badge for the low-evidence stock
    expect(screen.getByTestId("badge-low-evidence-LOWEV_X")).toBeTruthy();
    // No badge for the normal stock
    expect(screen.queryByTestId("badge-low-evidence-NORMAL_Y")).toBeNull();
  });

  // ── 7 ─────────────────────────────────────────────────────────────────────
  it("page renders without crash and no low-evidence badge when all decisions have low_evidence=false", async () => {
    mockUseGetTradeDecisions.mockReturnValue({
      data: makePayload([NORMAL_STOCK, BOUNDARY_STOCK]),
      isLoading: false,
      error: null,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("page-trade-decisions")).toBeTruthy();
    });
    // No low-evidence badges anywhere
    expect(screen.queryAllByTestId(/^badge-low-evidence-/).length).toBe(0);
  });
});
