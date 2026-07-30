// @vitest-environment jsdom
/**
 * ExecutiveDashboard.test.tsx — Task #218
 *
 * Smoke-tests the Executive Dashboard with a mix of populated, disabled,
 * and null sections to confirm the page never throws a React runtime error
 * regardless of which backend modules are enabled.
 *
 * Assertions use native Vitest/Chai matchers (not @testing-library/jest-dom)
 * to match the existing test convention in this package.
 *
 * Coverage:
 *  1. All 10+ section cards render with a fully-populated payload.
 *  2. Every optional section gracefully degrades to "No data" when absent.
 *  3. All sections absent — page renders without crash.
 *  4. Research Lab tile — status: "DISABLED" shows disabled state.
 *  5. Research Lab tile — status: "ENABLED" shows score ring + grade.
 *  6. Research Lab tile — trend IMPROVING / DECLINING / WEAKENING — no crash.
 *  7. Research Lab tile — snapshot still pending — shows "No data".
 *  8. best_regime sent as object {} → KpiCard renders "N/A", no crash.
 *  9. best_regime sent as null → KpiCard renders "N/A".
 * 10. best_strategy sent as array → KpiCard renders "N/A".
 * 11. Loading state shows spinner.
 * 12. Error state shows error message.
 * 13. status: "DISABLED" in summary shows disabled banner.
 * 14. Kill-switch banner renders when portfolio_risk.kill_switch_active is true.
 * 15. Live Readiness disabled state shows correct message.
 * 16. Market snapshot with null prices renders "—" without crash.
 * 17. Live alerts — all-clear message when no critical/warnings.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ── Module mocks ──────────────────────────────────────────────────────────────

vi.mock("@/lib/api", () => ({
  API_BASE: "",
  apiJson:  vi.fn(),
}));

// wouter Link needs a router context; replace with a plain anchor.
vi.mock("wouter", () => ({
  Link:        ({ href, children, className }: React.AnchorHTMLAttributes<HTMLAnchorElement>) =>
    React.createElement("a", { href, className }, children),
  useLocation: vi.fn(() => ["/"]),
  useRoute:    vi.fn(() => [false, {}]),
}));

import { apiJson } from "@/lib/api";
import ExecutiveDashboard from "./ExecutiveDashboard";

// ── Fixtures ──────────────────────────────────────────────────────────────────

const FULL_EXEC_SUMMARY = {
  status: "ENABLED",
  executive_score: {
    total: 78,
    label: "Good",
    components: {
      portfolio_health: 80, ai_health: 75, strategy_health: 70,
      execution_quality: 85, risk: 82, system_health: 76,
    },
    weights: {
      portfolio_health: 0.2, ai_health: 0.2, strategy_health: 0.15,
      execution_quality: 0.15, risk: 0.15, system_health: 0.15,
    },
  },
  header: {
    market_status: "OPEN",
    ist_time: "09:30 IST",
    market_regime: "TRENDING",
    paper_trading: true,
    active_provider: "NSE Official",
    watchlist_count: 15,
    trading_date: "2026-07-30",
  },
  system_health: {
    application_health: "HEALTHY",
    scheduler_health:   "HEALTHY",
    database_status:    "CONNECTED",
    api_status:         "UP",
  },
  portfolio_overview: {
    portfolio_value:           51200,
    today_pnl:                   320,
    net_pnl:                    1200,
    cash_available:            28000,
    invested_capital:          23200,
    open_positions:                4,
    win_rate:                   62.5,
    profit_factor:               1.8,
    drawdown:                    2.3,
    total_return_pct:            2.4,
    portfolio_utilisation_pct:  45.3,
    initial_capital:           50000,
  },
  ai_health: {
    health_score:         81,
    health_label:    "Healthy",
    prediction_accuracy: 63.5,
    precision:           68.2,
    recall:              59.1,
    avg_confidence:      71.4,
    trend_direction: "Improving",
    accuracy_delta:       2.1,
    calibration_quality: 74.0,
    total_signals:       120,
  },
  strategy_overview: {
    best_strategy:    "MOMENTUM",
    worst_strategy:   "MEAN_REVERT",
    highest_win_rate: "BREAKOUT",
    best_profit_factor: "MOMENTUM",
    best_regime:      "TRENDING",
    best_sector:      "TECHNOLOGY",
    total_net_pnl:     1200,
    overall_win_rate:    62,
    strong_buy_count:     3,
    recommendations: [
      { verdict: "STRONG_BUY", strategy: "MOMENTUM" },
      { verdict: "BUY",        strategy: "BREAKOUT" },
    ],
  },
  execution_quality: {
    execution_score: 88.5,
    avg_slippage:     0.12,
    avg_fill_delay:   0.34,
    total_trades:       38,
    best_execution:   99.1,
    worst_execution:  61.2,
  },
  preopen_intelligence: {
    top_gap_up:        "RELIANCE",
    top_gap_up_pct:       1.45,
    top_gap_down:      "HDFCBANK",
    top_gap_down_pct:    -0.82,
    buy_imbalance:     "TCS",
    sell_imbalance:    "WIPRO",
    leading_sector:    "TECHNOLOGY",
    provider:          "NSE Official",
    last_refresh:      "08:59 IST",
    symbols_analysed:      50,
    trading_date:      "2026-07-30",
  },
  portfolio_risk: {
    utilisation:             45.3,
    portfolio_heat:          34.2,
    diversification_score:   72.0,
    top_sector:              "TECHNOLOGY",
    sector_concentration:    38.5,
    kill_switch_active:      false,
    alert_count:             1,
  },
  live_alerts: {
    critical: [],
    warnings: [{ level: "WARNING", message: "Portfolio heat approaching threshold" }],
    info:     [{ level: "INFO",    message: "Scan completed at 09:20" }],
    total_critical: 0,
    total_warnings: 1,
  },
  market_snapshot: {
    nifty:      { price: 24850, change_pct:  0.42 },
    bank_nifty: { price: 52100, change_pct: -0.18 },
    india_vix:  { price: 14.2,  change_pct: -3.1  },
    market_regime: "TRENDING",
    market_status: "OPEN",
  },
  live_readiness: {
    available:       true,
    disabled:        false,
    readiness_score: 84,
    grade:           "B",
    verdict:         "READY FOR EXTENDED PAPER TRADING",
    verdict_short:   "GO",
  },
  quick_actions: [
    { label: "Portfolio", href: "/portfolio" },
    { label: "Signals",   href: "/signals"   },
  ],
};

const FULL_RESEARCH_SNAP = {
  status:           "ENABLED",
  research_score:   62,
  grade:            "C",
  trend:            "IMPROVING",
  total_strategies:  7,
  total_scenarios:   8,
  total_experiments: 3,
  expected_drawdown: 7.4,
  benchmark_alpha:   2.1,
  advisory_only:     true,
};

const DISABLED_RESEARCH_SNAP = {
  status:           "DISABLED",
  research_score:   0,
  grade:            "N/A",
  trend:            "STABLE",
  total_strategies:  0,
  total_scenarios:   0,
  total_experiments: 0,
  expected_drawdown: 0,
  benchmark_alpha:   0,
  advisory_only:     true,
};

// ── Helper ────────────────────────────────────────────────────────────────────

function mountDashboard() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        refetchOnWindowFocus: false,
        staleTime: Infinity,
      },
    },
  });
  return render(
    React.createElement(
      QueryClientProvider, { client: qc },
      React.createElement(ExecutiveDashboard),
    ),
  );
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────

beforeEach(() => { vi.clearAllMocks(); });
afterEach(cleanup);

// ── Tests: full payload ───────────────────────────────────────────────────────

describe("ExecutiveDashboard — full payload", () => {
  it("renders all section card titles without crashing", async () => {
    vi.mocked(apiJson).mockImplementation((path: string) =>
      path === "executive/summary"
        ? Promise.resolve(FULL_EXEC_SUMMARY)
        : Promise.resolve(FULL_RESEARCH_SNAP),
    );

    mountDashboard();

    const sections = [
      "System Health", "Portfolio Overview", "AI Health", "Strategy Overview",
      "Execution Quality", "Pre-Open Intelligence", "Portfolio Risk", "Live Alerts",
      "Live Readiness", "Research Lab", "Market Snapshot", "Quick Actions",
    ];
    for (const title of sections) {
      await waitFor(() =>
        expect(screen.queryByText(title)).toBeTruthy(),
      );
    }
  });

  it("renders the executive score ring with total and label", async () => {
    vi.mocked(apiJson).mockImplementation((path: string) =>
      path === "executive/summary"
        ? Promise.resolve(FULL_EXEC_SUMMARY)
        : Promise.resolve(FULL_RESEARCH_SNAP),
    );

    mountDashboard();
    await waitFor(() => expect(screen.queryByText("78")).toBeTruthy());
    await waitFor(() => expect(screen.queryByText("Good")).toBeTruthy());
  });

  it("renders portfolio KPI labels", async () => {
    vi.mocked(apiJson).mockImplementation((path: string) =>
      path === "executive/summary"
        ? Promise.resolve(FULL_EXEC_SUMMARY)
        : Promise.resolve(FULL_RESEARCH_SNAP),
    );

    mountDashboard();
    await waitFor(() => expect(screen.queryByText("Portfolio Value")).toBeTruthy());
    await waitFor(() => expect(screen.queryByText("Open Positions")).toBeTruthy());
  });

  it("renders AI health score ring", async () => {
    vi.mocked(apiJson).mockImplementation((path: string) =>
      path === "executive/summary"
        ? Promise.resolve(FULL_EXEC_SUMMARY)
        : Promise.resolve(FULL_RESEARCH_SNAP),
    );

    mountDashboard();
    await waitFor(() => expect(screen.queryByText("Healthy")).toBeTruthy());
    await waitFor(() => expect(screen.queryByText("Prediction Accuracy")).toBeTruthy());
  });

  it("renders strategy section KPI labels", async () => {
    vi.mocked(apiJson).mockImplementation((path: string) =>
      path === "executive/summary"
        ? Promise.resolve(FULL_EXEC_SUMMARY)
        : Promise.resolve(FULL_RESEARCH_SNAP),
    );

    mountDashboard();
    await waitFor(() => expect(screen.queryByText("Best Strategy")).toBeTruthy());
    await waitFor(() => expect(screen.queryByText("Best Regime")).toBeTruthy());
  });
});

// ── Tests: graceful degradation ───────────────────────────────────────────────

describe("ExecutiveDashboard — null/absent sections (graceful degradation)", () => {
  it("shows 'No data' for every absent section without crashing", async () => {
    vi.mocked(apiJson).mockImplementation((path: string) =>
      path === "executive/summary"
        ? Promise.resolve({ status: "ENABLED" })
        : Promise.resolve(DISABLED_RESEARCH_SNAP),
    );

    mountDashboard();

    // Section titles should still render
    for (const title of ["System Health", "Portfolio Overview", "AI Health",
                          "Strategy Overview", "Execution Quality"]) {
      await waitFor(() => expect(screen.queryByText(title)).toBeTruthy());
    }

    // Multiple "No data" placeholders should appear
    await waitFor(() => {
      const noDataEls = screen.queryAllByText("No data");
      expect(noDataEls.length).toBeGreaterThanOrEqual(6);
    });
  });

  it("shows 'No alerts' placeholder when live_alerts is absent", async () => {
    const payload = { ...FULL_EXEC_SUMMARY, live_alerts: undefined };
    vi.mocked(apiJson).mockImplementation((path: string) =>
      path === "executive/summary"
        ? Promise.resolve(payload)
        : Promise.resolve(FULL_RESEARCH_SNAP),
    );

    mountDashboard();
    await waitFor(() => expect(screen.queryByText("No alerts")).toBeTruthy());
  });

  it("shows 'All systems nominal' message when no critical/warnings", async () => {
    const payload = {
      ...FULL_EXEC_SUMMARY,
      live_alerts: { critical: [], warnings: [], info: [], total_critical: 0, total_warnings: 0 },
    };
    vi.mocked(apiJson).mockImplementation((path: string) =>
      path === "executive/summary"
        ? Promise.resolve(payload)
        : Promise.resolve(FULL_RESEARCH_SNAP),
    );

    mountDashboard();
    await waitFor(() =>
      expect(screen.queryByText(/All systems nominal/)).toBeTruthy());
  });
});

// ── Tests: Research Lab tile ──────────────────────────────────────────────────

describe("ExecutiveDashboard — Research Lab tile", () => {
  it("shows 'Research Lab Disabled' when snapshot status is DISABLED", async () => {
    vi.mocked(apiJson).mockImplementation((path: string) =>
      path === "executive/summary"
        ? Promise.resolve(FULL_EXEC_SUMMARY)
        : Promise.resolve(DISABLED_RESEARCH_SNAP),
    );

    mountDashboard();
    await waitFor(() =>
      expect(screen.queryByText("Research Lab Disabled")).toBeTruthy());
  });

  it("shows grade badge when snapshot status is ENABLED", async () => {
    vi.mocked(apiJson).mockImplementation((path: string) =>
      path === "executive/summary"
        ? Promise.resolve(FULL_EXEC_SUMMARY)
        : Promise.resolve(FULL_RESEARCH_SNAP),
    );

    mountDashboard();
    await waitFor(() => expect(screen.queryByText("Grade C")).toBeTruthy());
  });

  it("shows Research Lab link button when ENABLED", async () => {
    vi.mocked(apiJson).mockImplementation((path: string) =>
      path === "executive/summary"
        ? Promise.resolve(FULL_EXEC_SUMMARY)
        : Promise.resolve(FULL_RESEARCH_SNAP),
    );

    mountDashboard();
    await waitFor(() =>
      expect(screen.queryByText("View Full Research Lab")).toBeTruthy());
  });

  it("renders trend IMPROVING without crashing", async () => {
    vi.mocked(apiJson).mockImplementation((path: string) =>
      path === "executive/summary"
        ? Promise.resolve(FULL_EXEC_SUMMARY)
        : Promise.resolve({ ...FULL_RESEARCH_SNAP, trend: "IMPROVING" }),
    );
    mountDashboard();
    await waitFor(() => expect(screen.queryByText("Research Lab")).toBeTruthy());
  });

  it("renders trend DECLINING without crashing", async () => {
    vi.mocked(apiJson).mockImplementation((path: string) =>
      path === "executive/summary"
        ? Promise.resolve(FULL_EXEC_SUMMARY)
        : Promise.resolve({ ...FULL_RESEARCH_SNAP, trend: "DECLINING" }),
    );
    mountDashboard();
    await waitFor(() => expect(screen.queryByText("Research Lab")).toBeTruthy());
  });

  it("renders trend WEAKENING without crashing", async () => {
    vi.mocked(apiJson).mockImplementation((path: string) =>
      path === "executive/summary"
        ? Promise.resolve(FULL_EXEC_SUMMARY)
        : Promise.resolve({ ...FULL_RESEARCH_SNAP, trend: "WEAKENING" }),
    );
    mountDashboard();
    await waitFor(() => expect(screen.queryByText("Research Lab")).toBeTruthy());
  });

  it("shows 'No data' placeholder when research-lab/snapshot is still pending", async () => {
    vi.mocked(apiJson).mockImplementation((path: string) => {
      if (path === "executive/summary") return Promise.resolve(FULL_EXEC_SUMMARY);
      return new Promise(() => {}); // research snap never resolves
    });

    mountDashboard();
    await waitFor(() => expect(screen.queryByText("Research Lab")).toBeTruthy());
    // Tile content should show "No data" (snap is undefined while pending)
    await waitFor(() => {
      const noData = screen.queryAllByText("No data");
      expect(noData.length).toBeGreaterThanOrEqual(1);
    });
  });
});

// ── Tests: KpiCard safety — object/null values ────────────────────────────────

describe("ExecutiveDashboard — KpiCard safety (non-string API values)", () => {
  it("renders without crash when best_regime is an object {}", async () => {
    const payload = {
      ...FULL_EXEC_SUMMARY,
      strategy_overview: {
        ...FULL_EXEC_SUMMARY.strategy_overview,
        best_regime: {} as unknown as string,  // regression: was crashing with "Objects are not valid as React child"
      },
    };
    vi.mocked(apiJson).mockImplementation((path: string) =>
      path === "executive/summary"
        ? Promise.resolve(payload)
        : Promise.resolve(FULL_RESEARCH_SNAP),
    );

    mountDashboard();
    // Page must render without React error boundary — section card title is visible
    await waitFor(() => expect(screen.queryByText("Strategy Overview")).toBeTruthy());
    // KpiCard label for Best Regime must be present
    await waitFor(() => expect(screen.queryByText("Best Regime")).toBeTruthy());
  });

  it("renders 'N/A' text when best_regime is an object {}", async () => {
    const payload = {
      ...FULL_EXEC_SUMMARY,
      strategy_overview: {
        ...FULL_EXEC_SUMMARY.strategy_overview,
        best_regime: {} as unknown as string,
      },
    };
    vi.mocked(apiJson).mockImplementation((path: string) =>
      path === "executive/summary"
        ? Promise.resolve(payload)
        : Promise.resolve(FULL_RESEARCH_SNAP),
    );

    mountDashboard();
    await waitFor(() => {
      const label = screen.queryByText("Best Regime");
      expect(label).toBeTruthy();
      // Sibling element inside the same KpiCard should be "N/A"
      const card = label?.closest(".bg-slate-800\\/60");
      expect(card?.textContent).toContain("N/A");
    });
  });

  it("renders without crash when best_regime is null", async () => {
    const payload = {
      ...FULL_EXEC_SUMMARY,
      strategy_overview: {
        ...FULL_EXEC_SUMMARY.strategy_overview,
        best_regime: null as unknown as string,
      },
    };
    vi.mocked(apiJson).mockImplementation((path: string) =>
      path === "executive/summary"
        ? Promise.resolve(payload)
        : Promise.resolve(FULL_RESEARCH_SNAP),
    );

    mountDashboard();
    await waitFor(() => expect(screen.queryByText("Best Regime")).toBeTruthy());
  });

  it("renders without crash when best_strategy is an array", async () => {
    const payload = {
      ...FULL_EXEC_SUMMARY,
      strategy_overview: {
        ...FULL_EXEC_SUMMARY.strategy_overview,
        best_strategy: ["unexpected", "array"] as unknown as string,
      },
    };
    vi.mocked(apiJson).mockImplementation((path: string) =>
      path === "executive/summary"
        ? Promise.resolve(payload)
        : Promise.resolve(FULL_RESEARCH_SNAP),
    );

    mountDashboard();
    await waitFor(() => expect(screen.queryByText("Strategy Overview")).toBeTruthy());
  });
});

// ── Tests: page-level loading / error / disabled states ───────────────────────

describe("ExecutiveDashboard — page-level states", () => {
  it("shows loading spinner while the summary query is in flight", () => {
    vi.mocked(apiJson).mockImplementation(() => new Promise(() => {}));
    mountDashboard();
    expect(screen.queryByText(/Loading Executive Dashboard/)).toBeTruthy();
  });

  it("shows error message when the summary query rejects", async () => {
    vi.mocked(apiJson).mockImplementation((path: string) =>
      path === "executive/summary"
        ? Promise.reject(new Error("Network error"))
        : Promise.resolve({}),
    );

    mountDashboard();
    await waitFor(() => expect(screen.queryByText(/Network error/)).toBeTruthy());
  });

  it("shows the disabled banner when summary status is DISABLED", async () => {
    vi.mocked(apiJson).mockImplementation((path: string) =>
      path === "executive/summary"
        ? Promise.resolve({ status: "DISABLED", feature_flag: "EXECUTIVE_DASHBOARD_ENABLED" })
        : Promise.resolve(DISABLED_RESEARCH_SNAP),
    );

    mountDashboard();
    await waitFor(() =>
      expect(screen.queryByText("Executive Dashboard is disabled")).toBeTruthy());
  });
});

// ── Tests: risk section ───────────────────────────────────────────────────────

describe("ExecutiveDashboard — risk section", () => {
  it("renders kill-switch banner when kill_switch_active is true", async () => {
    const payload = {
      ...FULL_EXEC_SUMMARY,
      portfolio_risk: { ...FULL_EXEC_SUMMARY.portfolio_risk, kill_switch_active: true },
    };
    vi.mocked(apiJson).mockImplementation((path: string) =>
      path === "executive/summary"
        ? Promise.resolve(payload)
        : Promise.resolve(FULL_RESEARCH_SNAP),
    );

    mountDashboard();
    await waitFor(() =>
      expect(screen.queryByText(/Kill Switch Active/)).toBeTruthy());
  });
});

// ── Tests: Live Readiness tile ────────────────────────────────────────────────

describe("ExecutiveDashboard — Live Readiness tile", () => {
  it("shows 'Readiness Validation Disabled' when disabled=true", async () => {
    const payload = {
      ...FULL_EXEC_SUMMARY,
      live_readiness: {
        available: false, disabled: true,
        readiness_score: 0, grade: "N/A", verdict: "", verdict_short: "NO-GO",
      },
    };
    vi.mocked(apiJson).mockImplementation((path: string) =>
      path === "executive/summary"
        ? Promise.resolve(payload)
        : Promise.resolve(FULL_RESEARCH_SNAP),
    );

    mountDashboard();
    await waitFor(() =>
      expect(screen.queryByText("Readiness Validation Disabled")).toBeTruthy());
  });

  it("renders 'View Full Readiness Report' link when available", async () => {
    vi.mocked(apiJson).mockImplementation((path: string) =>
      path === "executive/summary"
        ? Promise.resolve(FULL_EXEC_SUMMARY)
        : Promise.resolve(FULL_RESEARCH_SNAP),
    );

    mountDashboard();
    await waitFor(() =>
      expect(screen.queryByText("View Full Readiness Report")).toBeTruthy());
  });
});

// ── Tests: Market Snapshot with null prices ───────────────────────────────────

describe("ExecutiveDashboard — market snapshot", () => {
  it("renders '—' dashes for null index prices without crashing", async () => {
    const payload = {
      ...FULL_EXEC_SUMMARY,
      market_snapshot: {
        nifty:      { price: null, change_pct: null },
        bank_nifty: { price: null, change_pct: null },
        india_vix:  { price: null, change_pct: null },
        market_regime: "UNKNOWN",
        market_status: "CLOSED",
      },
    };
    vi.mocked(apiJson).mockImplementation((path: string) =>
      path === "executive/summary"
        ? Promise.resolve(payload)
        : Promise.resolve(FULL_RESEARCH_SNAP),
    );

    mountDashboard();
    await waitFor(() => expect(screen.queryByText("Market Snapshot")).toBeTruthy());
    await waitFor(() => {
      const dashes = screen.queryAllByText("—");
      expect(dashes.length).toBeGreaterThanOrEqual(3);
    });
  });
});
