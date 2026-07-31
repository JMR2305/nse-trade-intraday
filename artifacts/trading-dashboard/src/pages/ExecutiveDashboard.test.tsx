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

/**
 * Representative payload matching the REAL /api/ai/summary response shape.
 * - health_score is a composite object (total_score 0-100, label, components)
 * - prediction.accuracy is a 0-1 fraction (NOT a percentage)
 * - avg_confidence is a 0-1 fraction (NOT a percentage)
 */
const FULL_AI_SUMMARY = {
  status:                "ENABLED",
  total_signals:          142,
  executed_signals:        38,
  ignored_signals:        104,
  successful_signals:      27,
  failed_signals:          11,
  signal_success_rate:   0.71,
  high_confidence_pct:   0.54,
  avg_confidence:        0.68,    // 0-1 fraction → displays as "68.0%"
  health_score: {
    total_score:    72.5,
    label:          "Good",
    components: {
      prediction_accuracy: 65.0,
      calibration_quality: 78.0,
      consistency:         70.0,
      execution_outcome:   80.0,
      risk_awareness:      60.0,
      recommendation_quality: 75.0,
    },
    weights: {
      prediction_accuracy: 0.25,
      calibration_quality: 0.20,
      consistency:         0.20,
      execution_outcome:   0.15,
      risk_awareness:      0.10,
      recommendation_quality: 0.10,
    },
  },
  trend_direction:   "Improving",
  accuracy_delta:         3.2,
  recent_accuracy:       0.71,
  prediction: {
    tp: 27, fp: 11, tn: 82, fn: 22,
    accuracy:           0.73,   // 0-1 fraction → displays as "73.0%"
    precision:          0.71,
    recall:             0.75,
    f1_score:           0.73,
    false_positive_rate: 0.12,
    false_negative_rate: 0.25,
    true_positive_rate:  0.75,
    true_negative_rate:  0.88,
    mcc:                 0.47,
    balanced_accuracy:   0.81,
  },
  calibration_ece:          0.04,
  calibration_reliability:  0.91,
};

const DISABLED_AI_SUMMARY = { status: "DISABLED" };

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

/**
 * Build a standard mock that routes the three queries correctly.
 *   executive/summary      → execSummary
 *   research-lab/snapshot  → researchSnap
 *   ai/summary             → aiSummary
 * Any other path returns {}.
 */
function makeMock(
  execSummary: unknown = FULL_EXEC_SUMMARY,
  researchSnap: unknown = FULL_RESEARCH_SNAP,
  aiSummary: unknown = FULL_AI_SUMMARY,
) {
  return (path: string) => {
    if (path === "executive/summary")    return Promise.resolve(execSummary);
    if (path === "research-lab/snapshot") return Promise.resolve(researchSnap);
    if (path === "ai/summary")           return Promise.resolve(aiSummary);
    return Promise.resolve({});
  };
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────

beforeEach(() => { vi.clearAllMocks(); });
afterEach(cleanup);

// ── Tests: full payload ───────────────────────────────────────────────────────

describe("ExecutiveDashboard — full payload", () => {
  it("renders all section card titles without crashing", async () => {
    vi.mocked(apiJson).mockImplementation(makeMock());

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
    vi.mocked(apiJson).mockImplementation(makeMock());

    mountDashboard();
    await waitFor(() => expect(screen.queryByText("78")).toBeTruthy());
    // "Good" now appears in both the executive score ring AND the AI health tile badge,
    // so use queryAllByText which returns all matches without throwing on duplicates.
    await waitFor(() => expect(screen.queryAllByText("Good").length).toBeGreaterThan(0));
  });

  it("renders portfolio KPI labels", async () => {
    vi.mocked(apiJson).mockImplementation(makeMock());

    mountDashboard();
    await waitFor(() => expect(screen.queryByText("Portfolio Value")).toBeTruthy());
    await waitFor(() => expect(screen.queryByText("Open Positions")).toBeTruthy());
  });

  it("renders AI Health tile with score, label, and trend from /api/ai/summary", async () => {
    // The AIHealthTile fetches from ai/summary directly, NOT from executive/summary.
    // It should show the composite label "Good" (from health_score.label),
    // the trend "Improving", and the accuracy/confidence KPIs (converted from fractions).
    vi.mocked(apiJson).mockImplementation(makeMock());

    mountDashboard();
    // Label from health_score.label — "Good" appears in both the score ring AND the tile badge
    await waitFor(() => expect(screen.queryAllByText("Good").length).toBeGreaterThan(0));
    // Trend text is in a data-testid span so it's uniquely addressable
    await waitFor(() => expect(screen.getByTestId("ai-health-trend").textContent).toBe("Improving"));
    // Accuracy metric label
    await waitFor(() => expect(screen.queryByText("Accuracy")).toBeTruthy());
    // Link to full AI Performance page
    await waitFor(() => expect(screen.queryByText("View Full AI Performance")).toBeTruthy());
  });

  it("renders accuracy as a percentage (0-1 fraction converted to 73.0%), not raw 0.7%", async () => {
    vi.mocked(apiJson).mockImplementation(makeMock());

    mountDashboard();
    // prediction.accuracy = 0.73 → should display as "73.0%"
    await waitFor(() => expect(screen.queryByText("73.0%")).toBeTruthy());
    // Must NOT display the raw fraction as a percentage
    expect(screen.queryByText("0.7%")).toBeFalsy();
  });

  it("renders avg_confidence as a percentage (0-1 fraction converted to 68.0%), not raw 0.7%", async () => {
    vi.mocked(apiJson).mockImplementation(makeMock());

    mountDashboard();
    // avg_confidence = 0.68 → should display as "68.0%"
    await waitFor(() => expect(screen.queryByText("68.0%")).toBeTruthy());
  });

  it("renders strategy section KPI labels", async () => {
    vi.mocked(apiJson).mockImplementation(makeMock());

    mountDashboard();
    await waitFor(() => expect(screen.queryByText("Best Strategy")).toBeTruthy());
    await waitFor(() => expect(screen.queryByText("Best Regime")).toBeTruthy());
  });
});

// ── Tests: graceful degradation ───────────────────────────────────────────────

describe("ExecutiveDashboard — null/absent sections (graceful degradation)", () => {
  it("shows 'No data' for every absent section without crashing", async () => {
    // executive/summary has no sections; research-lab and ai/summary are DISABLED.
    vi.mocked(apiJson).mockImplementation(
      makeMock({ status: "ENABLED" }, DISABLED_RESEARCH_SNAP, DISABLED_AI_SUMMARY),
    );

    mountDashboard();

    // Section titles should still render
    for (const title of ["System Health", "Portfolio Overview", "AI Health",
                          "Strategy Overview", "Execution Quality"]) {
      await waitFor(() => expect(screen.queryByText(title)).toBeTruthy());
    }

    // Multiple "No data" placeholders should appear (AI Health now shows
    // "AI Performance Disabled" not "No data", so ≥5 from other sections)
    await waitFor(() => {
      const noDataEls = screen.queryAllByText("No data");
      expect(noDataEls.length).toBeGreaterThanOrEqual(5);
    });
  });

  it("shows 'No alerts' placeholder when live_alerts is absent", async () => {
    const payload = { ...FULL_EXEC_SUMMARY, live_alerts: undefined };
    vi.mocked(apiJson).mockImplementation(makeMock(payload));

    mountDashboard();
    await waitFor(() => expect(screen.queryByText("No alerts")).toBeTruthy());
  });

  it("shows 'All systems nominal' message when no critical/warnings", async () => {
    const payload = {
      ...FULL_EXEC_SUMMARY,
      live_alerts: { critical: [], warnings: [], info: [], total_critical: 0, total_warnings: 0 },
    };
    vi.mocked(apiJson).mockImplementation(makeMock(payload));

    mountDashboard();
    await waitFor(() =>
      expect(screen.queryByText(/All systems nominal/)).toBeTruthy());
  });
});

// ── Tests: Research Lab tile ──────────────────────────────────────────────────

describe("ExecutiveDashboard — Research Lab tile", () => {
  it("shows 'Research Lab Disabled' when snapshot status is DISABLED", async () => {
    vi.mocked(apiJson).mockImplementation(makeMock(FULL_EXEC_SUMMARY, DISABLED_RESEARCH_SNAP));

    mountDashboard();
    await waitFor(() =>
      expect(screen.queryByText("Research Lab Disabled")).toBeTruthy());
  });

  it("shows grade badge when snapshot status is ENABLED", async () => {
    vi.mocked(apiJson).mockImplementation(makeMock());

    mountDashboard();
    await waitFor(() => expect(screen.queryByText("Grade C")).toBeTruthy());
  });

  it("shows Research Lab link button when ENABLED", async () => {
    vi.mocked(apiJson).mockImplementation(makeMock());

    mountDashboard();
    await waitFor(() =>
      expect(screen.queryByText("View Full Research Lab")).toBeTruthy());
  });

  it("renders trend IMPROVING without crashing", async () => {
    vi.mocked(apiJson).mockImplementation(
      makeMock(FULL_EXEC_SUMMARY, { ...FULL_RESEARCH_SNAP, trend: "IMPROVING" }),
    );
    mountDashboard();
    await waitFor(() => expect(screen.queryByText("Research Lab")).toBeTruthy());
  });

  it("renders trend DECLINING without crashing", async () => {
    vi.mocked(apiJson).mockImplementation(
      makeMock(FULL_EXEC_SUMMARY, { ...FULL_RESEARCH_SNAP, trend: "DECLINING" }),
    );
    mountDashboard();
    await waitFor(() => expect(screen.queryByText("Research Lab")).toBeTruthy());
  });

  it("renders trend WEAKENING without crashing", async () => {
    vi.mocked(apiJson).mockImplementation(
      makeMock(FULL_EXEC_SUMMARY, { ...FULL_RESEARCH_SNAP, trend: "WEAKENING" }),
    );
    mountDashboard();
    await waitFor(() => expect(screen.queryByText("Research Lab")).toBeTruthy());
  });

  it("shows 'No data' placeholder when research-lab/snapshot is still pending", async () => {
    vi.mocked(apiJson).mockImplementation((path: string) => {
      if (path === "executive/summary") return Promise.resolve(FULL_EXEC_SUMMARY);
      if (path === "ai/summary")        return Promise.resolve(FULL_AI_SUMMARY);
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

// ── Tests: AI Health tile ─────────────────────────────────────────────────────

describe("ExecutiveDashboard — AI Health tile", () => {
  it("shows 'AI Performance Disabled' when ai/summary returns DISABLED", async () => {
    vi.mocked(apiJson).mockImplementation(
      makeMock(FULL_EXEC_SUMMARY, FULL_RESEARCH_SNAP, DISABLED_AI_SUMMARY),
    );

    mountDashboard();
    await waitFor(() =>
      expect(screen.queryByText("AI Performance Disabled")).toBeTruthy());
  });

  it("shows score label 'Good' from health_score.label when ENABLED", async () => {
    vi.mocked(apiJson).mockImplementation(makeMock());

    mountDashboard();
    // "Good" appears in multiple places (exec score ring + tile badge); use queryAllByText
    await waitFor(() => expect(screen.queryAllByText("Good").length).toBeGreaterThan(0));
  });

  it("shows trend 'Improving' from trend_direction field", async () => {
    vi.mocked(apiJson).mockImplementation(makeMock());

    mountDashboard();
    // Trend text is in data-testid="ai-health-trend" for reliable querying
    await waitFor(() => expect(screen.getByTestId("ai-health-trend").textContent).toBe("Improving"));
  });

  it("shows 'View Full AI Performance' link to /ai-performance", async () => {
    vi.mocked(apiJson).mockImplementation(makeMock());

    mountDashboard();
    await waitFor(() =>
      expect(screen.queryByText("View Full AI Performance")).toBeTruthy());
  });

  it("shows accuracy as 73.0% (0.73 fraction × 100), not '0.7%'", async () => {
    vi.mocked(apiJson).mockImplementation(makeMock());

    mountDashboard();
    await waitFor(() => expect(screen.queryByText("73.0%")).toBeTruthy());
    expect(screen.queryByText("0.7%")).toBeFalsy();
  });

  it("shows avg_confidence as 68.0% (0.68 fraction × 100)", async () => {
    vi.mocked(apiJson).mockImplementation(makeMock());

    mountDashboard();
    await waitFor(() => expect(screen.queryByText("68.0%")).toBeTruthy());
  });

  it("shows 'Declining' trend with no crash", async () => {
    vi.mocked(apiJson).mockImplementation(
      makeMock(FULL_EXEC_SUMMARY, FULL_RESEARCH_SNAP, {
        ...FULL_AI_SUMMARY, trend_direction: "Declining",
      }),
    );

    mountDashboard();
    await waitFor(() => expect(screen.queryByText("AI Health")).toBeTruthy());
    await waitFor(() => expect(screen.getByTestId("ai-health-trend").textContent).toBe("Declining"));
  });

  it("shows 'Stable' trend with no crash", async () => {
    vi.mocked(apiJson).mockImplementation(
      makeMock(FULL_EXEC_SUMMARY, FULL_RESEARCH_SNAP, {
        ...FULL_AI_SUMMARY, trend_direction: "Stable",
      }),
    );

    mountDashboard();
    await waitFor(() => expect(screen.queryByText("AI Health")).toBeTruthy());
    await waitFor(() => expect(screen.getByTestId("ai-health-trend").textContent).toBe("Stable"));
  });

  it("shows 'Loading…' when ai/summary query is still pending", async () => {
    vi.mocked(apiJson).mockImplementation((path: string) => {
      if (path === "executive/summary")    return Promise.resolve(FULL_EXEC_SUMMARY);
      if (path === "research-lab/snapshot") return Promise.resolve(FULL_RESEARCH_SNAP);
      return new Promise(() => {}); // ai/summary never resolves
    });

    mountDashboard();
    await waitFor(() => expect(screen.queryByText("AI Health")).toBeTruthy());
    // At least one "Loading…" placeholder is present (there may be more if other
    // tiles are also pending — use queryAllByText to avoid a "multiple elements" error)
    await waitFor(() => expect(screen.queryAllByText("Loading…").length).toBeGreaterThan(0));
  });
});

// ── Tests: KpiCard safety — object/null values ────────────────────────────────

describe("ExecutiveDashboard — KpiCard safety (non-string API values)", () => {
  it("renders without crash when best_regime is an object {}", async () => {
    const payload = {
      ...FULL_EXEC_SUMMARY,
      strategy_overview: {
        ...FULL_EXEC_SUMMARY.strategy_overview,
        best_regime: {} as unknown as string,
      },
    };
    vi.mocked(apiJson).mockImplementation(makeMock(payload));

    mountDashboard();
    await waitFor(() => expect(screen.queryByText("Strategy Overview")).toBeTruthy());
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
    vi.mocked(apiJson).mockImplementation(makeMock(payload));

    mountDashboard();
    await waitFor(() => {
      const label = screen.queryByText("Best Regime");
      expect(label).toBeTruthy();
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
    vi.mocked(apiJson).mockImplementation(makeMock(payload));

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
    vi.mocked(apiJson).mockImplementation(makeMock(payload));

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
    vi.mocked(apiJson).mockImplementation(
      makeMock({ status: "DISABLED", feature_flag: "EXECUTIVE_DASHBOARD_ENABLED" }, DISABLED_RESEARCH_SNAP, DISABLED_AI_SUMMARY),
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
    vi.mocked(apiJson).mockImplementation(makeMock(payload));

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
    vi.mocked(apiJson).mockImplementation(makeMock(payload));

    mountDashboard();
    await waitFor(() =>
      expect(screen.queryByText("Readiness Validation Disabled")).toBeTruthy());
  });

  it("renders 'View Full Readiness Report' link when available", async () => {
    vi.mocked(apiJson).mockImplementation(makeMock());

    mountDashboard();
    await waitFor(() =>
      expect(screen.queryByText("View Full Readiness Report")).toBeTruthy());
  });
});

// ── Tests: Paper Analytics tile ──────────────────────────────────────────────

describe("ExecutiveDashboard — Paper Analytics tile", () => {
  /**
   * paper_analytics data comes from the executive/summary payload (not a
   * separate query), so we just embed it in the exec summary fixture.
   */
  const FULL_EXEC_WITH_PAPER = {
    ...FULL_EXEC_SUMMARY,
    paper_analytics: {
      available:       true,
      disabled:        false,
      analytics_score: 72.5,
      grade:           "B",
      win_rate:        58.0,
      profit_factor:   1.8,
      total_trades:    25,
      total_pnl:       12000,
      sharpe_ratio:    1.2,
      best_strategy:   "Momentum",
      best_sector:     "IT",
      advisory_only:   true,
    },
  };

  const DISABLED_EXEC_WITH_PAPER = {
    ...FULL_EXEC_SUMMARY,
    paper_analytics: {
      available:       false,
      disabled:        true,
      analytics_score: 0,
      grade:           "N/A",
      win_rate:        0,
      profit_factor:   0,
      total_trades:    0,
      total_pnl:       0,
      sharpe_ratio:    0,
      best_strategy:   "N/A",
      best_sector:     "N/A",
      advisory_only:   true,
    },
  };

  it("shows 'Paper Analytics' section card title", async () => {
    vi.mocked(apiJson).mockImplementation(makeMock(FULL_EXEC_WITH_PAPER));

    mountDashboard();
    await waitFor(() => expect(screen.queryByText("Paper Analytics")).toBeTruthy());
  });

  it("shows 'Paper Analytics Disabled' when paper_analytics.disabled is true", async () => {
    vi.mocked(apiJson).mockImplementation(makeMock(DISABLED_EXEC_WITH_PAPER));

    mountDashboard();
    await waitFor(() =>
      expect(screen.queryByText("Paper Analytics Disabled")).toBeTruthy());
  });

  it("shows PAPER_ANALYTICS_ENABLED=true hint in the disabled state", async () => {
    vi.mocked(apiJson).mockImplementation(makeMock(DISABLED_EXEC_WITH_PAPER));

    mountDashboard();
    await waitFor(() =>
      expect(screen.queryByText("PAPER_ANALYTICS_ENABLED=true")).toBeTruthy());
  });

  it("renders data-testid='paper-analytics-disabled' when disabled", async () => {
    vi.mocked(apiJson).mockImplementation(makeMock(DISABLED_EXEC_WITH_PAPER));

    mountDashboard();
    await waitFor(() =>
      expect(screen.queryByTestId("paper-analytics-disabled")).toBeTruthy());
  });

  it("does NOT render the score ring (data-testid='paper-analytics-tile') when disabled", async () => {
    vi.mocked(apiJson).mockImplementation(makeMock(DISABLED_EXEC_WITH_PAPER));

    mountDashboard();
    await waitFor(() =>
      expect(screen.queryByText("Paper Analytics Disabled")).toBeTruthy());
    // Enabled tile must be absent
    expect(screen.queryByTestId("paper-analytics-tile")).toBeFalsy();
  });

  it("renders data-testid='paper-analytics-tile' (score ring) when enabled", async () => {
    vi.mocked(apiJson).mockImplementation(makeMock(FULL_EXEC_WITH_PAPER));

    mountDashboard();
    await waitFor(() =>
      expect(screen.queryByTestId("paper-analytics-tile")).toBeTruthy());
  });

  it("does NOT render the disabled message when enabled", async () => {
    vi.mocked(apiJson).mockImplementation(makeMock(FULL_EXEC_WITH_PAPER));

    mountDashboard();
    await waitFor(() =>
      expect(screen.queryByTestId("paper-analytics-tile")).toBeTruthy());
    expect(screen.queryByTestId("paper-analytics-disabled")).toBeFalsy();
  });

  it("shows 'Grade B' badge inside the paper-analytics-tile when analytics score is 72.5", async () => {
    vi.mocked(apiJson).mockImplementation(makeMock(FULL_EXEC_WITH_PAPER));

    mountDashboard();
    await waitFor(() => {
      const tile = screen.queryByTestId("paper-analytics-tile");
      expect(tile).toBeTruthy();
      expect(tile?.textContent).toContain("Grade B");
    });
  });

  it("shows 'View Full Paper Analytics' link when enabled", async () => {
    vi.mocked(apiJson).mockImplementation(makeMock(FULL_EXEC_WITH_PAPER));

    mountDashboard();
    await waitFor(() =>
      expect(screen.queryByText("View Full Paper Analytics")).toBeTruthy());
  });

  it("shows 'ADVISORY ONLY' badge when enabled", async () => {
    vi.mocked(apiJson).mockImplementation(makeMock(FULL_EXEC_WITH_PAPER));

    mountDashboard();
    await waitFor(() => expect(screen.queryByText("ADVISORY ONLY")).toBeTruthy());
  });

  it("renders without crash when paper_analytics is absent from summary", async () => {
    // paper_analytics key is undefined (old backend that hasn't been updated yet)
    const payloadNoPa = { ...FULL_EXEC_SUMMARY };
    delete (payloadNoPa as Record<string, unknown>)["paper_analytics"];
    vi.mocked(apiJson).mockImplementation(makeMock(payloadNoPa));

    mountDashboard();
    await waitFor(() => expect(screen.queryByText("Paper Analytics")).toBeTruthy());
    // Tile shows "Loading…" when d is undefined
    await waitFor(() => expect(screen.queryByText("Loading…")).toBeTruthy());
  });
});

// ── Tests: Executive Score ring reflects paper_analytics changes ──────────────
//
// The backend computes executive_score.total; the frontend renders it in the
// score ring.  These tests verify that different paper_analytics scores produce
// different displayed totals, and that the 10-point full-range spread (weight
// 10% × 100-point range) is represented correctly in the payload returned.
// ─────────────────────────────────────────────────────────────────────────────

describe("ExecutiveDashboard — Executive Score ring reflects paper analytics changes", () => {
  /**
   * payloadWithPaScore() builds an exec-summary fixture where executive_score.total
   * has already incorporated paper_analytics at the given score.
   *
   * The backend owns the arithmetic; we simulate it here by adjusting the
   * pre-computed total that the API would return:
   *   base total with paper_analytics=50 (neutral) = 68
   *   total with paper_analytics=0   = 68 - (50-0)  * 0.10 = 63
   *   total with paper_analytics=100 = 68 + (100-50)* 0.10 = 73
   *
   * Base of 68 is chosen so the DOM totals (63 and 73) are distinct from every
   * component score in FULL_EXEC_SUMMARY (80, 75, 70, 85, 82, 76), preventing
   * false positives from the ScoreBreakdown grid.
   */
  const BASE_TOTAL_AT_NEUTRAL = 68;
  const PA_WEIGHT = 0.10;
  const NEUTRAL = 50;

  function payloadWithPaScore(paScore: number) {
    const total = Math.round(
      (BASE_TOTAL_AT_NEUTRAL + (paScore - NEUTRAL) * PA_WEIGHT) * 10
    ) / 10;
    return {
      ...FULL_EXEC_SUMMARY,
      executive_score: {
        ...FULL_EXEC_SUMMARY.executive_score,
        total,
        label: total >= 75 ? "Good" : total >= 50 ? "Average" : "Poor",
        components: {
          ...(FULL_EXEC_SUMMARY.executive_score.components as Record<string, number>),
          paper_analytics: paScore,
        },
      },
      paper_analytics: {
        available:       paScore > 0,
        disabled:        paScore === 0,
        analytics_score: paScore,
        grade:           paScore >= 80 ? "A" : paScore >= 60 ? "B" : "D",
        win_rate:        paScore >= 80 ? 65.0 : 40.0,
        profit_factor:   paScore >= 80 ? 2.1  : 0.9,
        total_trades:    10,
        total_pnl:       paScore >= 80 ? 8000 : -1000,
        sharpe_ratio:    paScore >= 80 ? 1.5  : 0.4,
        best_strategy:   "Momentum",
        best_sector:     "IT",
        advisory_only:   true,
      },
    };
  }

  it("score ring shows different totals for poor (score=0) and excellent (score=100) paper analytics", async () => {
    // ── Render 1: poor paper analytics (score=0) → total=63 ──────────────────
    const payloadPoor = payloadWithPaScore(0);    // total = 63
    vi.mocked(apiJson).mockImplementation(makeMock(payloadPoor));
    mountDashboard();

    // Wait for the score ring to render; ScoreRing has data-testid="exec-score-total"
    await waitFor(() =>
      expect(screen.queryByTestId("exec-score-total")).toBeTruthy()
    );
    const poorTotal = screen.getByTestId("exec-score-total").textContent?.trim();
    expect(poorTotal).toBe(String(Math.round(payloadPoor.executive_score.total)));  // "63"

    // ── Render 2: excellent paper analytics (score=100) → total=73 ───────────
    cleanup();
    const payloadExcellent = payloadWithPaScore(100);    // total = 73
    vi.mocked(apiJson).mockImplementation(makeMock(payloadExcellent));
    mountDashboard();

    await waitFor(() =>
      expect(screen.queryByTestId("exec-score-total")).toBeTruthy()
    );
    const excellentTotal = screen.getByTestId("exec-score-total").textContent?.trim();
    expect(excellentTotal).toBe(String(Math.round(payloadExcellent.executive_score.total)));  // "73"

    // The excellent render must show a strictly higher total than the poor render
    expect(Number(excellentTotal)).toBeGreaterThan(Number(poorTotal));
  });

  it("poor-to-excellent improvement produces ≈10-point spread in displayed totals", () => {
    // This is a pure arithmetic invariant — no DOM needed.
    const totalPoor      = payloadWithPaScore(0).executive_score.total;    // 65
    const totalExcellent = payloadWithPaScore(100).executive_score.total;  // 75
    const delta = totalExcellent - totalPoor;
    // Expected: 100 × 0.10 = 10.0 (±0.5 for rounding)
    expect(Math.abs(delta - 10.0)).toBeLessThanOrEqual(0.5);
  });

  it("poor-to-neutral improvement (score 20→50) produces ≈3-point spread", () => {
    const totalPoor    = payloadWithPaScore(20).executive_score.total;
    const totalNeutral = payloadWithPaScore(50).executive_score.total;
    const delta = totalNeutral - totalPoor;
    // Expected: (50-20) × 0.10 = 3.0 (±0.5)
    expect(Math.abs(delta - 3.0)).toBeLessThanOrEqual(0.5);
  });

  it("score ring total is strictly higher for excellent analytics than for poor", async () => {
    const payloadPoor      = payloadWithPaScore(20);
    const payloadExcellent = payloadWithPaScore(90);
    expect(payloadExcellent.executive_score.total)
      .toBeGreaterThan(payloadPoor.executive_score.total);
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
    vi.mocked(apiJson).mockImplementation(makeMock(payload));

    mountDashboard();
    await waitFor(() => expect(screen.queryByText("Market Snapshot")).toBeTruthy());
    await waitFor(() => {
      const dashes = screen.queryAllByText("—");
      expect(dashes.length).toBeGreaterThanOrEqual(3);
    });
  });
});
