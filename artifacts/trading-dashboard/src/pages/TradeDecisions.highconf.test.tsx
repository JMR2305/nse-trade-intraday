// @vitest-environment jsdom
/**
 * TradeDecisions.highconf.test.tsx — Task #389
 *
 * Confirms that the Trade Decisions page renders the correct badges in the
 * browser when the high-confidence avoid gate (HIGH_CONF_AVOID_GATE_MIN_FAILURES=2)
 * overrides the default AVOID behaviour.
 *
 * Scenarios covered:
 *  1. fc=87, 1 filter failure  → WATCH badge, OVERRIDDEN-BY-GATE badge present
 *  2. fc=87, 2 filter failures → AVOID badge,  no WATCH badge for that stock
 *  3. fc=70, 1 filter failure  → AVOID badge   (strict gate — below 85 threshold)
 *  4. OVERRIDDEN-BY-GATE badge absent for a normal STRONG_BUY row
 *  5. "All" filter tab shows all three stocks simultaneously
 *  6. Filter tab "WATCH" hides the two AVOID rows and shows only the WATCH row
 *  7. Filter tab "AVOID" hides the WATCH row and shows only AVOID rows
 *  8. OVERRIDDEN-BY-GATE title attribute mentions the blocking condition
 *  9. WATCH row still shows the confidence value correctly
 * 10. Page renders without crash when decisions array is empty
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
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
    recommendation: "WATCH",
    data_status: "OK",
    low_reliability: false,
    low_evidence: false,
    total_trades: 10,
    invalidation_override: false,
    invalidation_override_conditions: [],
    base_confidence: 60,
    learning_adjustment: 0,
    final_confidence: 60,
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
    historical_trades: 25,
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

/**
 * fc=87, 1 filter failure → backend returns WATCH + invalidation_override=true.
 * This is the stock the task is centred on.
 */
const WATCH_ONE_FAILURE = makeDecision({
  stock: "WATCH_ONE",
  recommendation: "WATCH",
  final_confidence: 87,
  base_confidence: 87,
  invalidation_override: true,
  invalidation_override_conditions: ["volume_ratio 0.35 < 0.5 min"],
  reason: "Risk filter caution — volume_ratio 0.35 < 0.5 min",
});

/**
 * fc=87, 2 filter failures → backend returns AVOID + invalidation_override=true.
 */
const AVOID_TWO_FAILURES = makeDecision({
  stock: "AVOID_TWO",
  recommendation: "AVOID",
  final_confidence: 87,
  base_confidence: 87,
  invalidation_override: true,
  invalidation_override_conditions: [
    "volume_ratio 0.35 < 0.5 min",
    "RSI 78 > 70 overbought threshold",
  ],
  reason: "Risk filter failed: volume_ratio 0.35 < 0.5 min",
});

/**
 * fc=70, 1 filter failure → backend returns AVOID (strict gate).
 */
const AVOID_LOW_CONF = makeDecision({
  stock: "AVOID_LOW",
  recommendation: "AVOID",
  final_confidence: 70,
  base_confidence: 70,
  invalidation_override: true,
  invalidation_override_conditions: ["volume_ratio 0.35 < 0.5 min"],
  reason: "Risk filter failed: volume_ratio 0.35 < 0.5 min",
});

/** Normal STRONG_BUY row — no gate override. */
const STRONG_BUY_NORMAL = makeDecision({
  stock: "STRONGBUY_X",
  recommendation: "STRONG_BUY",
  final_confidence: 90,
  base_confidence: 90,
  invalidation_override: false,
  invalidation_override_conditions: [],
  reason: "Confidence 90, expectancy +3.00%, PF 2.10, R:R 2.5:1",
});

const RESPONSE_PAYLOAD = {
  decisions: [WATCH_ONE_FAILURE, AVOID_TWO_FAILURES, AVOID_LOW_CONF, STRONG_BUY_NORMAL],
  strong_buy_count: 1,
  buy_count: 0,
  watch_count: 1,
  avoid_count: 2,
  exit_count: 0,
  generated_at: new Date().toISOString(),
  warning: null,
};

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

  // Default: return the full fixture payload immediately (no loading state)
  mockUseGetTradeDecisions.mockReturnValue({
    data: RESPONSE_PAYLOAD,
    isLoading: false,
    error: null,
  });

  // Sub-queries in advisory panels — return null so the panels stay hidden
  mockApiJson.mockResolvedValue(null);
});

afterEach(() => {
  cleanup();
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("TradeDecisions — high-confidence avoid gate badge rendering", () => {

  // ── 1 ─────────────────────────────────────────────────────────────────────
  it("shows WATCH badge for fc=87 stock with a single filter failure", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("badge-recommendation-watch")).toBeTruthy();
    });
    // Confirm it really is our stock's row
    expect(screen.getByText("WATCH_ONE")).toBeTruthy();
  });

  // ── 2 ─────────────────────────────────────────────────────────────────────
  it("shows OVERRIDDEN-BY-GATE badge on the WATCH row", async () => {
    renderPage();
    await waitFor(() => {
      const badge = screen.getByTestId("badge-invalidation-override-WATCH_ONE");
      expect(badge).toBeTruthy();
      expect(badge.textContent?.trim()).toBe("OVERRIDDEN BY GATE");
    });
  });

  // ── 3 ─────────────────────────────────────────────────────────────────────
  it("shows AVOID badge for fc=87 stock with two simultaneous filter failures", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("AVOID_TWO")).toBeTruthy();
    });
    // The stock row must have an AVOID recommendation badge
    const avoidBadges = screen.getAllByTestId("badge-recommendation-avoid");
    expect(avoidBadges.length).toBeGreaterThanOrEqual(1);
  });

  // ── 4 ─────────────────────────────────────────────────────────────────────
  it("does NOT show WATCH badge on the two-failure row (it is AVOID)", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("AVOID_TWO")).toBeTruthy();
    });
    // AVOID_TWO must not have a badge-recommendation-watch test id
    const watchBadges = screen.queryAllByTestId("badge-recommendation-watch");
    // Only WATCH_ONE should produce a WATCH badge
    expect(watchBadges.length).toBe(1);
  });

  // ── 5 ─────────────────────────────────────────────────────────────────────
  it("shows AVOID badge for fc=70 stock with one filter failure (strict gate)", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("AVOID_LOW")).toBeTruthy();
    });
    const avoidBadges = screen.getAllByTestId("badge-recommendation-avoid");
    // Both AVOID stocks should be shown
    expect(avoidBadges.length).toBeGreaterThanOrEqual(2);
  });

  // ── 6 ─────────────────────────────────────────────────────────────────────
  it("OVERRIDDEN-BY-GATE badge absent on the normal STRONG_BUY row", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("STRONGBUY_X")).toBeTruthy();
    });
    const badge = screen.queryByTestId("badge-invalidation-override-STRONGBUY_X");
    expect(badge).toBeNull();
  });

  // ── 7 ─────────────────────────────────────────────────────────────────────
  it("'All' filter shows all four stocks", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("WATCH_ONE")).toBeTruthy();
      expect(screen.getByText("AVOID_TWO")).toBeTruthy();
      expect(screen.getByText("AVOID_LOW")).toBeTruthy();
      expect(screen.getByText("STRONGBUY_X")).toBeTruthy();
    });
  });

  // ── 8 ─────────────────────────────────────────────────────────────────────
  it("WATCH filter hides AVOID rows and shows only the WATCH stock", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("WATCH_ONE")).toBeTruthy();
    });

    // Click the WATCH filter button
    const watchButton = screen.getByRole("button", { name: /^WATCH/ });
    fireEvent.click(watchButton);

    await waitFor(() => {
      expect(screen.getByText("WATCH_ONE")).toBeTruthy();
      expect(screen.queryByText("AVOID_TWO")).toBeNull();
      expect(screen.queryByText("AVOID_LOW")).toBeNull();
      expect(screen.queryByText("STRONGBUY_X")).toBeNull();
    });
  });

  // ── 9 ─────────────────────────────────────────────────────────────────────
  it("AVOID filter shows both AVOID stocks and hides the WATCH stock", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("AVOID_TWO")).toBeTruthy();
    });

    // Click the AVOID filter button
    const avoidButton = screen.getByRole("button", { name: /^AVOID/ });
    fireEvent.click(avoidButton);

    await waitFor(() => {
      expect(screen.getByText("AVOID_TWO")).toBeTruthy();
      expect(screen.getByText("AVOID_LOW")).toBeTruthy();
      expect(screen.queryByText("WATCH_ONE")).toBeNull();
    });
  });

  // ── 10 ────────────────────────────────────────────────────────────────────
  it("OVERRIDDEN-BY-GATE title attribute includes the blocking condition", async () => {
    renderPage();
    await waitFor(() => {
      const badge = screen.getByTestId("badge-invalidation-override-WATCH_ONE");
      const title = badge.getAttribute("title") ?? "";
      expect(title).toContain("volume_ratio 0.35 < 0.5 min");
    });
  });

  // ── 11 ────────────────────────────────────────────────────────────────────
  it("WATCH row confidence value is visible in the table", async () => {
    renderPage();
    await waitFor(() => {
      // final_confidence=87 → displayed as "87"
      const cells = screen.getAllByText("87");
      expect(cells.length).toBeGreaterThanOrEqual(1);
    });
  });

  // ── 12 ────────────────────────────────────────────────────────────────────
  it("page renders without crash when decisions array is empty", async () => {
    mockUseGetTradeDecisions.mockReturnValue({
      data: { ...RESPONSE_PAYLOAD, decisions: [] },
      isLoading: false,
      error: null,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("page-trade-decisions")).toBeTruthy();
    });
  });
});
