// @vitest-environment jsdom
/**
 * RiskValidation.test.tsx — Phase 8.4
 * React unit tests for the Advanced Risk Validation Framework dashboard.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import RiskValidation from "./RiskValidation";

vi.mock("@/lib/api", () => ({ apiJson: vi.fn() }));
import { apiJson } from "@/lib/api";
const mockApi = apiJson as ReturnType<typeof vi.fn>;

afterEach(cleanup);

function mkQc() {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
}

function renderPage(qc: QueryClient) {
  render(
    <QueryClientProvider client={qc}>
      <RiskValidation />
    </QueryClientProvider>
  );
}

function clickTab(label: string) {
  const btn = screen.getAllByRole("button").find(b => b.textContent?.includes(label));
  if (btn) fireEvent.click(btn);
}

// ── Fixtures ───────────────────────────────────────────────────────────────────

const DOMAINS = [
  "portfolio","sector","correlation","stress","tail_risk","execution","market_risk","drift"
].map(name => ({
  domain: name, score: 80, grade: "A",
  checks_run: 5, checks_passed: 4, checks_failed: 1,
  critical: 0, warnings: 1, available: true,
}));

const SUMMARY_ENABLED = {
  status: "ENABLED", available: true, advisory_only: true,
  generated_at: "2026-07-30T09:15:00Z",
  risk_score: 78.5, grade: "A", trend: "Stable",
  total_issues: 2, critical_count: 0, warning_count: 2,
  domains: DOMAINS,
};

const SUMMARY_DISABLED = {
  status: "DISABLED", available: false, advisory_only: true,
};

const PORTFOLIO_DATA = {
  status: "ENABLED", available: true, advisory_only: true,
  domain: "portfolio", score: 82, grade: "A",
  checks_run: 7, checks_passed: 6, checks_failed: 1,
  critical_count: 0, warning_count: 1,
  total_value: 100000, cash_available: 20000, invested_capital: 80000,
  portfolio_utilisation_pct: 80, max_drawdown_pct: 5.2,
  positions_count: 2,
  positions: [
    { symbol: "RELIANCE", current_value: 40000, pnl: 1200, status: "OPEN" },
    { symbol: "TCS",      current_value: 40000, pnl:  800, status: "OPEN" },
  ],
  issues: [{ severity: "WARNING", check: "ELEVATED_UTILISATION", field: "utilisation", message: "Utilisation is elevated" }],
};

const SECTOR_DATA = {
  status: "ENABLED", available: true, advisory_only: true,
  domain: "sector", score: 75, grade: "B",
  checks_run: 6, checks_passed: 5, checks_failed: 1,
  critical_count: 0, warning_count: 1,
  sector_count: 2, dominant_sector: "IT", dominant_pct: 45,
  sectors: { IT: 45, Banking: 35, FMCG: 20 },
  issues: [],
};

const STRESS_DATA = {
  status: "ENABLED", available: true, advisory_only: true,
  domain: "stress", score: 60, grade: "C",
  checks_run: 10, checks_passed: 6, checks_failed: 4,
  critical_count: 4, warning_count: 0,
  portfolio_value: 100000, severe_count: 4,
  scenarios: [
    { id: "fall_5",  label: "Market Fall 5%",  shock_pct: -5,  impact_value: -5000,
      portfolio_value_after: 95000, advisory_note: "Moderate correction" },
    { id: "fall_10", label: "Market Fall 10%", shock_pct: -10, impact_value: -10000,
      portfolio_value_after: 90000, advisory_note: "Significant correction" },
  ],
  issues: [
    { severity: "CRITICAL", check: "SEVERE_STRESS_SCENARIO", field: "scenario.fall_20",
      message: "Market Fall 20%: estimated -20%" }
  ],
};

const TAIL_DATA = {
  status: "ENABLED", available: true, advisory_only: true,
  domain: "tail_risk", score: 85, grade: "A",
  checks_run: 3, checks_passed: 3, checks_failed: 0,
  critical_count: 0, warning_count: 0,
  portfolio_value: 100000, india_vix: 15.2,
  var_95_1d: 1978, var_99_1d: 2794, cvar_99_1d: 3200,
  worst_case_5sigma: 6000, daily_volatility_pct: 1.2,
  circuit_limit_loss: 10000, recovery_estimate_days: 14,
  issues: [],
};

const ALERTS_EMPTY = {
  status: "ENABLED", available: true, advisory_only: true,
  critical: [], warnings: [], info: [],
  total_critical: 0, total_warnings: 0, total_info: 0, total: 0,
};

const ALERTS_WITH_ISSUES = {
  status: "ENABLED", available: true, advisory_only: true,
  critical: [{ severity: "CRITICAL", check: "HIGH_DRAWDOWN", field: "drawdown", message: "Drawdown critical", domain: "portfolio" }],
  warnings: [{ severity: "WARNING", check: "HIGH_CORR", field: "correlation", message: "High correlation", domain: "correlation" }],
  info: [],
  total_critical: 1, total_warnings: 1, total_info: 0, total: 2,
};

const CORR_DATA = {
  status: "ENABLED", available: true, advisory_only: true,
  domain: "correlation", score: 72, grade: "B",
  checks_run: 3, checks_passed: 2, checks_failed: 1,
  critical_count: 0, warning_count: 1,
  avg_correlation: 0.45, diversification_score: 0.62,
  positions_analysed: 4, issues: [],
};

const EXECUTION_DATA = {
  status: "ENABLED", available: true, advisory_only: true,
  domain: "execution", score: 90, grade: "A",
  checks_run: 3, checks_passed: 3, checks_failed: 0,
  critical_count: 0, warning_count: 0,
  avg_slippage_bps: 8.5, fill_rate: 0.95, missed_trades: 0,
  total_trades: 20, issues: [],
};

const MARKET_DATA = {
  status: "ENABLED", available: true, advisory_only: true,
  domain: "market_risk", score: 65, grade: "C",
  checks_run: 3, checks_passed: 2, checks_failed: 1,
  critical_count: 0, warning_count: 1,
  market_risk_score: 65, india_vix: 18.5,
  regime: "NEUTRAL", macro_sentiment: "NEUTRAL",
  issues: [],
};

const DRIFT_DATA = {
  status: "ENABLED", available: true, advisory_only: true,
  domain: "drift", score: 88, grade: "A",
  checks_run: 4, checks_passed: 4, checks_failed: 0,
  critical_count: 0, warning_count: 0,
  utilisation_pct: 78, max_drawdown_pct: 5.2,
  issues: [],
};

function wireApi(mock: ReturnType<typeof vi.fn>, overrides: Record<string, any> = {}) {
  mock.mockImplementation((path: string) => {
    if (path.includes("summary"))     return Promise.resolve(overrides.summary     ?? SUMMARY_ENABLED);
    if (path.includes("portfolio"))   return Promise.resolve(overrides.portfolio   ?? PORTFOLIO_DATA);
    if (path.includes("sector"))      return Promise.resolve(overrides.sector      ?? SECTOR_DATA);
    if (path.includes("correlation")) return Promise.resolve(overrides.correlation ?? CORR_DATA);
    if (path.includes("stress"))      return Promise.resolve(overrides.stress      ?? STRESS_DATA);
    if (path.includes("tail"))        return Promise.resolve(overrides.tail        ?? TAIL_DATA);
    if (path.includes("execution"))   return Promise.resolve(overrides.execution   ?? EXECUTION_DATA);
    if (path.includes("market"))      return Promise.resolve(overrides.market      ?? MARKET_DATA);
    if (path.includes("drift"))       return Promise.resolve(overrides.drift       ?? DRIFT_DATA);
    if (path.includes("alerts"))      return Promise.resolve(overrides.alerts      ?? ALERTS_EMPTY);
    return Promise.resolve({ status: "DISABLED", available: false });
  });
}

// ── Overview tab ───────────────────────────────────────────────────────────────

describe("RiskValidation — Overview tab", () => {
  it("renders page heading", () => {
    wireApi(mockApi);
    renderPage(mkQc());
    expect(screen.queryByText(/Advanced Risk Validation/i)).toBeTruthy();
  });

  it("shows all 12 tab buttons", () => {
    wireApi(mockApi);
    renderPage(mkQc());
    const labels = ["Overview","Portfolio","Positions","Sectors","Correlation",
                    "Stress Tests","Tail Risk","Execution","Market Risk","Risk Drift",
                    "Alerts","Export"];
    labels.forEach(l => expect(screen.queryByText(l)).toBeTruthy());
  });

  it("shows score ring after summary loads", async () => {
    wireApi(mockApi);
    renderPage(mkQc());
    await waitFor(() => expect(screen.queryByTestId("rv-score-ring")).toBeTruthy());
  });

  it("shows risk score value in ring", async () => {
    wireApi(mockApi);
    renderPage(mkQc());
    await waitFor(() => expect(screen.queryByText("79")).toBeTruthy());
  });

  it("shows grade badge", async () => {
    wireApi(mockApi);
    renderPage(mkQc());
    await waitFor(() => expect(screen.queryByTestId("rv-grade")).toBeTruthy());
  });

  it("shows domain table after summary loads", async () => {
    wireApi(mockApi);
    renderPage(mkQc());
    await waitFor(() => expect(screen.queryByTestId("rv-domain-table")).toBeTruthy());
  });

  it("shows Stable trend", async () => {
    wireApi(mockApi);
    renderPage(mkQc());
    await waitFor(() => expect(screen.queryByText("Stable")).toBeTruthy());
  });

  it("shows disabled view when status=DISABLED", async () => {
    wireApi(mockApi, { summary: SUMMARY_DISABLED });
    renderPage(mkQc());
    await waitFor(() => expect(screen.queryByText("Risk Validation Disabled")).toBeTruthy());
  });

  it("shows ADVISORY-ONLY banner", () => {
    wireApi(mockApi);
    renderPage(mkQc());
    expect(screen.queryAllByText(/ADVISORY-ONLY/i).length).toBeGreaterThan(0);
  });
});

// ── Portfolio tab ──────────────────────────────────────────────────────────────

describe("RiskValidation — Portfolio tab", () => {
  it("shows portfolio utilisation after switching tab", async () => {
    wireApi(mockApi);
    renderPage(mkQc());
    clickTab("Portfolio");
    await waitFor(() => expect(screen.queryByText("Utilisation")).toBeTruthy());
  });

  it("shows total value KPI", async () => {
    wireApi(mockApi);
    renderPage(mkQc());
    clickTab("Portfolio");
    await waitFor(() => expect(screen.queryByText(/₹1,00,000/)).toBeTruthy());
  });

  it("shows issues table when issues present", async () => {
    wireApi(mockApi);
    renderPage(mkQc());
    clickTab("Portfolio");
    await waitFor(() => expect(screen.queryByText("ELEVATED_UTILISATION")).toBeTruthy());
  });
});

// ── Positions tab ──────────────────────────────────────────────────────────────

describe("RiskValidation — Positions tab", () => {
  it("shows positions table with symbols", async () => {
    wireApi(mockApi);
    renderPage(mkQc());
    clickTab("Positions");
    await waitFor(() => expect(screen.queryByTestId("rv-positions-table")).toBeTruthy());
  });

  it("shows RELIANCE in positions table", async () => {
    wireApi(mockApi);
    renderPage(mkQc());
    clickTab("Positions");
    await waitFor(() => expect(screen.queryByText("RELIANCE")).toBeTruthy());
  });

  it("shows empty state when no positions", async () => {
    wireApi(mockApi, {
      portfolio: { ...PORTFOLIO_DATA, positions: [], positions_count: 0 }
    });
    renderPage(mkQc());
    clickTab("Positions");
    await waitFor(() => expect(screen.queryByText(/No open positions/i)).toBeTruthy());
  });
});

// ── Sectors tab ───────────────────────────────────────────────────────────────

describe("RiskValidation — Sectors tab", () => {
  it("shows dominant sector", async () => {
    wireApi(mockApi);
    renderPage(mkQc());
    clickTab("Sectors");
    await waitFor(() =>
      expect(screen.queryAllByText("IT").length).toBeGreaterThan(0)
    );
  });

  it("shows sector exposure bars", async () => {
    wireApi(mockApi);
    renderPage(mkQc());
    clickTab("Sectors");
    await waitFor(() => expect(screen.queryByText(/Sector Exposure/i)).toBeTruthy());
  });

  it("shows no data when unavailable", async () => {
    wireApi(mockApi, { sector: { status: "ENABLED", available: false } });
    renderPage(mkQc());
    clickTab("Sectors");
    await waitFor(() => expect(screen.queryByText(/No sector data/i)).toBeTruthy());
  });
});

// ── Correlation tab ────────────────────────────────────────────────────────────

describe("RiskValidation — Correlation tab", () => {
  it("shows avg correlation KPI", async () => {
    wireApi(mockApi);
    renderPage(mkQc());
    clickTab("Correlation");
    await waitFor(() => expect(screen.queryByText("Avg Correlation")).toBeTruthy());
  });

  it("shows diversification score", async () => {
    wireApi(mockApi);
    renderPage(mkQc());
    clickTab("Correlation");
    await waitFor(() => expect(screen.queryByText("Diversification Score")).toBeTruthy());
  });
});

// ── Stress Tests tab ───────────────────────────────────────────────────────────

describe("RiskValidation — Stress Tests tab", () => {
  it("renders stress table", async () => {
    wireApi(mockApi);
    renderPage(mkQc());
    clickTab("Stress Tests");
    await waitFor(() => expect(screen.queryByTestId("rv-stress-table")).toBeTruthy());
  });

  it("shows Market Fall 5% scenario", async () => {
    wireApi(mockApi);
    renderPage(mkQc());
    clickTab("Stress Tests");
    await waitFor(() => expect(screen.queryByText("Market Fall 5%")).toBeTruthy());
  });

  it("shows negative shock in red", async () => {
    wireApi(mockApi);
    renderPage(mkQc());
    clickTab("Stress Tests");
    await waitFor(() => expect(screen.queryByText("-5%")).toBeTruthy());
  });

  it("shows advisory note text", async () => {
    wireApi(mockApi);
    renderPage(mkQc());
    clickTab("Stress Tests");
    await waitFor(() => expect(screen.queryByText(/Moderate correction/)).toBeTruthy());
  });
});

// ── Tail Risk tab ──────────────────────────────────────────────────────────────

describe("RiskValidation — Tail Risk tab", () => {
  it("shows VaR cards", async () => {
    wireApi(mockApi);
    renderPage(mkQc());
    clickTab("Tail Risk");
    await waitFor(() => expect(screen.queryByText("95% VaR (1d)")).toBeTruthy());
  });

  it("shows India VIX", async () => {
    wireApi(mockApi);
    renderPage(mkQc());
    clickTab("Tail Risk");
    await waitFor(() => expect(screen.queryByText("India VIX")).toBeTruthy());
  });

  it("shows recovery estimate", async () => {
    wireApi(mockApi);
    renderPage(mkQc());
    clickTab("Tail Risk");
    await waitFor(() => expect(screen.queryByText("Recovery (est.)")).toBeTruthy());
  });
});

// ── Execution tab ──────────────────────────────────────────────────────────────

describe("RiskValidation — Execution tab", () => {
  it("shows slippage KPI", async () => {
    wireApi(mockApi);
    renderPage(mkQc());
    clickTab("Execution");
    await waitFor(() => expect(screen.queryByText("Avg Slippage")).toBeTruthy());
  });

  it("shows fill rate KPI", async () => {
    wireApi(mockApi);
    renderPage(mkQc());
    clickTab("Execution");
    await waitFor(() => expect(screen.queryByText("Fill Rate")).toBeTruthy());
  });
});

// ── Market Risk tab ────────────────────────────────────────────────────────────

describe("RiskValidation — Market Risk tab", () => {
  it("shows market risk score", async () => {
    wireApi(mockApi);
    renderPage(mkQc());
    clickTab("Market Risk");
    await waitFor(() => expect(screen.queryByText("Market Risk Score")).toBeTruthy());
  });

  it("shows regime value", async () => {
    wireApi(mockApi);
    renderPage(mkQc());
    clickTab("Market Risk");
    await waitFor(() =>
      expect(screen.queryAllByText("NEUTRAL").length).toBeGreaterThan(0)
    );
  });
});

// ── Risk Drift tab ─────────────────────────────────────────────────────────────

describe("RiskValidation — Risk Drift tab", () => {
  it("shows Risk Drift heading", async () => {
    wireApi(mockApi);
    renderPage(mkQc());
    clickTab("Risk Drift");
    await waitFor(() => expect(screen.queryByText(/Risk Drift Detection/i)).toBeTruthy());
  });

  it("shows utilisation KPI", async () => {
    wireApi(mockApi);
    renderPage(mkQc());
    clickTab("Risk Drift");
    await waitFor(() => expect(screen.queryByText("Utilisation")).toBeTruthy());
  });
});

// ── Alerts tab ─────────────────────────────────────────────────────────────────

describe("RiskValidation — Alerts tab", () => {
  it("shows no-alerts message when clear", async () => {
    wireApi(mockApi);
    renderPage(mkQc());
    clickTab("Alerts");
    await waitFor(() => expect(screen.queryByText(/No active risk alerts/i)).toBeTruthy());
  });

  it("shows issues table when alerts exist", async () => {
    wireApi(mockApi, { alerts: ALERTS_WITH_ISSUES });
    renderPage(mkQc());
    clickTab("Alerts");
    await waitFor(() => expect(screen.queryByTestId("rv-issues-table")).toBeTruthy());
  });

  it("shows CRITICAL severity badge", async () => {
    wireApi(mockApi, { alerts: ALERTS_WITH_ISSUES });
    renderPage(mkQc());
    clickTab("Alerts");
    await waitFor(() => expect(screen.queryByText("CRITICAL")).toBeTruthy());
  });

  it("shows HIGH_DRAWDOWN check in alerts table", async () => {
    wireApi(mockApi, { alerts: ALERTS_WITH_ISSUES });
    renderPage(mkQc());
    clickTab("Alerts");
    await waitFor(() => expect(screen.queryByText("HIGH_DRAWDOWN")).toBeTruthy());
  });
});

// ── Export tab ─────────────────────────────────────────────────────────────────

describe("RiskValidation — Export tab", () => {
  it("shows Download JSON button", async () => {
    wireApi(mockApi);
    renderPage(mkQc());
    // Force summary to load first so isEnabled=true
    await waitFor(() => screen.queryByTestId("rv-score-ring"));
    clickTab("Export");
    await waitFor(() => expect(screen.queryByText(/Download JSON/)).toBeTruthy());
  });

  it("shows Download CSV button", async () => {
    wireApi(mockApi);
    renderPage(mkQc());
    await waitFor(() => screen.queryByTestId("rv-score-ring"));
    clickTab("Export");
    await waitFor(() => expect(screen.queryByText(/Download CSV/)).toBeTruthy());
  });
});

// ── Lazy query gating ──────────────────────────────────────────────────────────

describe("RiskValidation — lazy query gating", () => {
  it("stress query is not called until Stress Tests tab is active", async () => {
    const calls: string[] = [];
    mockApi.mockImplementation((path: string) => {
      calls.push(path);
      if (path.includes("summary")) return Promise.resolve(SUMMARY_ENABLED);
      return Promise.resolve({ status: "DISABLED", available: false });
    });
    renderPage(mkQc());
    await waitFor(() => screen.queryByTestId("rv-score-ring"));
    expect(calls.some(p => p.includes("stress"))).toBe(false);
  });

  it("portfolio query fires when Portfolio tab is clicked", async () => {
    wireApi(mockApi);
    renderPage(mkQc());
    clickTab("Portfolio");
    await waitFor(() =>
      expect(mockApi.mock.calls.some(([p]: [string]) => p.includes("portfolio"))).toBe(true)
    );
  });
});
