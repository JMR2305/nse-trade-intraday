// @vitest-environment jsdom
/**
 * DataQuality.test.tsx — Phase 8.3
 * React unit tests for the Data Quality & Validation Framework Dashboard.
 *
 * Assertions use native Vitest/Chai matchers (not @testing-library/jest-dom).
 * Tab navigation uses fireEvent (not @testing-library/user-event).
 * Pattern: same wireApi / setQueryData approach as ExecutiveDashboard.test.tsx.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act, fireEvent, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import DataQuality from "./DataQuality";

// ── API mock ──────────────────────────────────────────────────────────────────
vi.mock("@/lib/api", () => ({
  apiJson: vi.fn(),
}));
import { apiJson } from "@/lib/api";
const mockApi = apiJson as ReturnType<typeof vi.fn>;

// ── Fixtures ──────────────────────────────────────────────────────────────────
const SUMMARY_ENABLED = {
  status: "ENABLED",
  available: true,
  advisory_only: true,
  quality_score: 82.5,
  grade: "A",
  total_issues: 3,
  critical_count: 0,
  warning_count: 3,
  score_components: {
    completeness: 90.0,
    consistency: 85.0,
    accuracy: 78.0,
    freshness: 88.0,
    integrity: 80.0,
    validity: 75.0,
  },
  domains: [
    { domain: "market",    score: 90, grade: "A+", checks_run: 20, checks_passed: 19, checks_failed: 1, critical: 0, warnings: 1 },
    { domain: "preopen",   score: 85, grade: "A",  checks_run: 12, checks_passed: 11, checks_failed: 1, critical: 0, warnings: 1 },
    { domain: "paper",     score: 80, grade: "A",  checks_run: 15, checks_passed: 13, checks_failed: 2, critical: 0, warnings: 1 },
    { domain: "portfolio", score: 88, grade: "A",  checks_run: 10, checks_passed: 9,  checks_failed: 1, critical: 0, warnings: 0 },
    { domain: "ai",        score: 75, grade: "B",  checks_run: 8,  checks_passed: 7,  checks_failed: 1, critical: 0, warnings: 1 },
    { domain: "signals",   score: 92, grade: "A+", checks_run: 10, checks_passed: 10, checks_failed: 0, critical: 0, warnings: 0 },
    { domain: "config",    score: 70, grade: "B",  checks_run: 6,  checks_passed: 5,  checks_failed: 1, critical: 0, warnings: 0 },
  ],
  generated_at: "2026-07-30T09:15:00+05:30",
};

const SUMMARY_DISABLED = {
  status: "DISABLED",
  available: false,
  advisory_only: true,
  message: "Set DATA_QUALITY_ENABLED=true",
};

const SUMMARY_CRITICAL = {
  ...SUMMARY_ENABLED,
  critical_count: 2,
  total_issues: 5,
};

function makeDomain(domain: string, score = 80, issues: object[] = []) {
  return {
    status: "ENABLED",
    available: true,
    advisory_only: true,
    domain,
    score,
    grade: score >= 80 ? "A" : "B",
    checks_run: 10,
    checks_passed: 8,
    checks_failed: 2,
    pass_rate: 80.0,
    critical_count: 0,
    warning_count: issues.length,
    issues,
    generated_at: "2026-07-30T09:15:00+05:30",
  };
}

const ALERTS_EMPTY = {
  status: "ENABLED",
  available: true,
  total: 0,
  total_critical: 0,
  total_warnings: 0,
  critical: [], warnings: [], info: [], duplicates: [], missing: [], stale: [],
};

const ALERTS_WITH_DATA = {
  ...ALERTS_EMPTY,
  total: 2,
  total_critical: 1,
  total_warnings: 1,
  critical: [{ severity: "CRITICAL", check: "OHLC_CONSISTENCY", field: "high",
               message: "High < Low detected", domain: "market" }],
  warnings: [{ severity: "WARNING",  check: "ZERO_VOLUME", field: "volume",
               message: "Zero volume", domain: "market" }],
};

// Prevent DOM pollution across tests
afterEach(cleanup);

// ── wireApi helper ────────────────────────────────────────────────────────────
function wireApi(mock: ReturnType<typeof vi.fn>, responses: Record<string, unknown>) {
  mock.mockImplementation((path: string) => {
    for (const [key, value] of Object.entries(responses)) {
      if (path.includes(key)) return Promise.resolve(value);
    }
    return Promise.resolve({ status: "DISABLED", available: false });
  });
}

// ── Render helper ─────────────────────────────────────────────────────────────
function mkQc() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
}

function renderPage(qc: QueryClient) {
  return render(
    <QueryClientProvider client={qc}>
      <DataQuality />
    </QueryClientProvider>,
  );
}

function clickTab(label: string) {
  const btns = screen.getAllByRole("button");
  const btn = btns.find(b => b.textContent?.includes(label));
  if (btn) fireEvent.click(btn);
}

// ═══════════════════════════════════════════════════════════════════════════════
// Header and navigation
// ═══════════════════════════════════════════════════════════════════════════════
describe("DataQuality page — header and navigation (Phase 8.3)", () => {
  let qc: QueryClient;
  beforeEach(() => {
    qc = mkQc();
    wireApi(mockApi, { summary: SUMMARY_ENABLED });
    renderPage(qc);
  });

  it("renders the page heading", () => {
    expect(screen.queryByText("Data Quality")).toBeTruthy();
  });

  it("renders the phase subtitle", () => {
    expect(screen.queryByText(/Phase 8\.3/)).toBeTruthy();
  });

  it("renders all 11 tab labels", () => {
    const labels = ["Overview", "Market Data", "Pre-Open", "Paper Trading",
                    "Portfolio", "AI", "Signals", "Configuration", "Alerts",
                    "History", "Export"];
    labels.forEach(l => {
      const btns = screen.getAllByRole("button");
      expect(btns.some(b => b.textContent?.includes(l))).toBe(true);
    });
  });

  it("Overview tab is active by default (teal styling)", () => {
    const btns = screen.getAllByRole("button");
    const overview = btns.find(b => b.textContent?.includes("Overview"));
    expect(overview?.className).toContain("teal");
  });

  it("shows grade badge once summary loads", async () => {
    await waitFor(() =>
      expect(screen.queryAllByText("A").length).toBeGreaterThan(0)
    );
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// Overview tab
// ═══════════════════════════════════════════════════════════════════════════════
describe("DataQuality page — Overview tab", () => {
  let qc: QueryClient;
  beforeEach(() => {
    qc = mkQc();
    wireApi(mockApi, { summary: SUMMARY_ENABLED });
    renderPage(qc);
  });

  it("shows quality score from summary (83 rounded)", async () => {
    await waitFor(() =>
      expect(screen.queryByTestId("dq-score-total")?.textContent).toBe("83")
    );
  });

  it("renders the SVG score ring arc", async () => {
    await waitFor(() =>
      expect(screen.queryByTestId("dq-score-arc")).toBeTruthy()
    );
  });

  it("shows all 6 score component dimensions", async () => {
    await waitFor(() => {
      ["Completeness", "Consistency", "Accuracy", "Freshness", "Integrity", "Validity"]
        .forEach(dim => expect(screen.queryByText(dim)).toBeTruthy());
    });
  });

  it("shows Market Data in domain table", async () => {
    await waitFor(() => expect(screen.queryByText("Market Data")).toBeTruthy());
  });

  it("shows ADVISORY ONLY badge", async () => {
    await waitFor(() => expect(screen.queryByText("ADVISORY ONLY")).toBeTruthy());
  });

  it("shows generated_at timestamp", async () => {
    await waitFor(() => expect(screen.queryByText(/Generated:/)).toBeTruthy());
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// Critical alert banner
// ═══════════════════════════════════════════════════════════════════════════════
describe("DataQuality page — critical alert banner", () => {
  it("shows critical banner when critical_count > 0", async () => {
    const qc = mkQc();
    wireApi(mockApi, { summary: SUMMARY_CRITICAL });
    renderPage(qc);
    await waitFor(() =>
      expect(screen.queryByText(/2 critical data quality issue/i)).toBeTruthy()
    );
  });

  it("no critical banner when critical_count is 0", async () => {
    const qc = mkQc();
    wireApi(mockApi, { summary: SUMMARY_ENABLED });
    renderPage(qc);
    await waitFor(() => screen.queryByTestId("dq-score-total"));
    expect(screen.queryByText(/critical data quality issue/i)).toBeFalsy();
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// Disabled state
// ═══════════════════════════════════════════════════════════════════════════════
describe("DataQuality page — disabled state", () => {
  it("shows Disabled view when summary.status=DISABLED", async () => {
    const qc = mkQc();
    wireApi(mockApi, { summary: SUMMARY_DISABLED });
    renderPage(qc);
    await waitFor(() =>
      expect(screen.queryByText("Data Quality Disabled")).toBeTruthy()
    );
  });

  it("shows DATA_QUALITY_ENABLED env var hint", async () => {
    const qc = mkQc();
    wireApi(mockApi, { summary: SUMMARY_DISABLED });
    renderPage(qc);
    await waitFor(() =>
      expect(screen.queryByText(/DATA_QUALITY_ENABLED/i)).toBeTruthy()
    );
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// Domain tabs
// ═══════════════════════════════════════════════════════════════════════════════
describe("DataQuality page — domain tabs", () => {
  const CASES: Array<[string, string, string]> = [
    ["Market Data",   "market",    "Market Data Validation"],
    ["Pre-Open",      "preopen",   "Pre-Open Data Validation"],
    ["Paper Trading", "paper",     "Paper Trading Validation"],
    ["Portfolio",     "portfolio", "Portfolio Validation"],
    ["AI",            "ai",        "AI Data Validation"],
    ["Signals",       "signals",   "Signals Validation"],
    ["Configuration", "config",    "Configuration Validation"],
  ];

  CASES.forEach(([tabLabel, domainKey, heading]) => {
    it(`clicking "${tabLabel}" shows heading "${heading}"`, async () => {
      const qc = mkQc();
      wireApi(mockApi, { summary: SUMMARY_ENABLED, [domainKey]: makeDomain(domainKey, 85) });
      renderPage(qc);
      clickTab(tabLabel);
      await waitFor(() =>
        expect(screen.queryByText(new RegExp(heading, "i"))).toBeTruthy()
      );
    });
  });

  it("shows issue check name in issues table", async () => {
    const qc = mkQc();
    wireApi(mockApi, {
      summary: SUMMARY_ENABLED,
      market: makeDomain("market", 70, [
        { severity: "WARNING", check: "ZERO_VOLUME", field: "volume",
          message: "Volume is zero", symbol: "TCS" },
      ]),
    });
    renderPage(qc);
    clickTab("Market Data");
    await waitFor(() => expect(screen.queryByText("ZERO_VOLUME")).toBeTruthy());
  });

  it("shows all-checks-passed when no issues", async () => {
    const qc = mkQc();
    wireApi(mockApi, { summary: SUMMARY_ENABLED, market: makeDomain("market", 100, []) });
    renderPage(qc);
    clickTab("Market Data");
    await waitFor(() =>
      expect(screen.queryByText(/All checks passed/i)).toBeTruthy()
    );
  });

  it("shows KPI Score card in domain tab", async () => {
    const qc = mkQc();
    wireApi(mockApi, { summary: SUMMARY_ENABLED, portfolio: makeDomain("portfolio", 88) });
    renderPage(qc);
    clickTab("Portfolio");
    await waitFor(() => expect(screen.queryByText("Quality Score")).toBeTruthy());
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// Configuration tab extras
// ═══════════════════════════════════════════════════════════════════════════════
describe("DataQuality page — Configuration tab", () => {
  it("shows feature flag states table", async () => {
    const qc = mkQc();
    wireApi(mockApi, {
      summary: SUMMARY_ENABLED,
      config: {
        ...makeDomain("config", 80),
        flag_states: {
          DATA_QUALITY_ENABLED: "ENABLED",
          RISK_OPTIMISATION_ENABLED: "DISABLED",
        },
        provider: "kite",
      },
    });
    renderPage(qc);
    clickTab("Configuration");
    await waitFor(() => {
      expect(screen.queryByText("DATA_QUALITY_ENABLED")).toBeTruthy();
      expect(screen.queryByText("RISK_OPTIMISATION_ENABLED")).toBeTruthy();
    });
  });

  it("shows market data provider name", async () => {
    const qc = mkQc();
    wireApi(mockApi, {
      summary: SUMMARY_ENABLED,
      config: { ...makeDomain("config", 80), flag_states: {}, provider: "kite" },
    });
    renderPage(qc);
    clickTab("Configuration");
    await waitFor(() => expect(screen.queryByText("kite")).toBeTruthy());
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// Alerts tab
// ═══════════════════════════════════════════════════════════════════════════════
describe("DataQuality page — Alerts tab", () => {
  it("shows no-alerts message when list is empty", async () => {
    const qc = mkQc();
    wireApi(mockApi, { summary: SUMMARY_ENABLED, alerts: ALERTS_EMPTY });
    renderPage(qc);
    clickTab("Alerts");
    await waitFor(() => expect(screen.queryByText(/No alerts/i)).toBeTruthy());
  });

  it("shows critical alert check name", async () => {
    const qc = mkQc();
    wireApi(mockApi, { summary: SUMMARY_ENABLED, alerts: ALERTS_WITH_DATA });
    renderPage(qc);
    clickTab("Alerts");
    await waitFor(() => expect(screen.queryByText("OHLC_CONSISTENCY")).toBeTruthy());
  });

  it("shows warning alert check name", async () => {
    const qc = mkQc();
    wireApi(mockApi, { summary: SUMMARY_ENABLED, alerts: ALERTS_WITH_DATA });
    renderPage(qc);
    clickTab("Alerts");
    await waitFor(() => expect(screen.queryByText("ZERO_VOLUME")).toBeTruthy());
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// History tab
// ═══════════════════════════════════════════════════════════════════════════════
describe("DataQuality page — History tab", () => {
  it("shows Phase 8.4 coming-soon placeholder", async () => {
    const qc = mkQc();
    wireApi(mockApi, { summary: SUMMARY_ENABLED });
    renderPage(qc);
    clickTab("History");
    await waitFor(() =>
      expect(screen.queryByText(/History Coming in Phase 8\.4/i)).toBeTruthy()
    );
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// Export tab
// ═══════════════════════════════════════════════════════════════════════════════
describe("DataQuality page — Export tab", () => {
  it("renders export tab heading", async () => {
    const qc = mkQc();
    wireApi(mockApi, { summary: SUMMARY_ENABLED });
    renderPage(qc);
    clickTab("Export");
    await waitFor(() =>
      expect(screen.queryByText(/Export Validation Report/i)).toBeTruthy()
    );
  });

  it("renders Download JSON button", async () => {
    const qc = mkQc();
    wireApi(mockApi, { summary: SUMMARY_ENABLED });
    renderPage(qc);
    clickTab("Export");
    await waitFor(() =>
      expect(screen.queryByTestId("download-json")).toBeTruthy()
    );
  });

  it("renders Download CSV button", async () => {
    const qc = mkQc();
    wireApi(mockApi, { summary: SUMMARY_ENABLED });
    renderPage(qc);
    clickTab("Export");
    await waitFor(() =>
      expect(screen.queryByTestId("download-csv")).toBeTruthy()
    );
  });

  it("shows advisory-only disclaimer on export tab", async () => {
    const qc = mkQc();
    wireApi(mockApi, { summary: SUMMARY_ENABLED });
    renderPage(qc);
    clickTab("Export");
    // The export tab renders an amber "⚠ Advisory Only" paragraph
    await waitFor(() =>
      expect(screen.queryAllByText(/Advisory Only/i).length).toBeGreaterThan(0)
    );
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// Score ring animation (Phase 8.3)
// ═══════════════════════════════════════════════════════════════════════════════
describe("DataQuality page — score ring animation (Phase 8.3)", () => {
  it("score ring arc is present after summary loads", async () => {
    const qc = mkQc();
    wireApi(mockApi, { summary: SUMMARY_ENABLED });
    renderPage(qc);
    await waitFor(() =>
      expect(screen.queryByTestId("dq-score-arc")).toBeTruthy()
    );
  });

  it("strokeDasharray fill is positive for score > 0", async () => {
    const qc = mkQc();
    wireApi(mockApi, { summary: SUMMARY_ENABLED });
    renderPage(qc);
    const arc = await screen.findByTestId("dq-score-arc");
    const da = arc.getAttribute("stroke-dasharray");
    expect(da).toBeTruthy();
    const fill = parseFloat(da!.split(" ")[0]);
    expect(fill).toBeGreaterThan(0);
  });

  it("arc has CSS transition for smooth animation", async () => {
    const qc = mkQc();
    wireApi(mockApi, { summary: SUMMARY_ENABLED });
    renderPage(qc);
    const arc = await screen.findByTestId("dq-score-arc");
    const el = arc as unknown as HTMLElement;
    expect(el.style.transition).toContain("stroke-dasharray");
  });

  it("score ring fill grows when quality_score increases via setQueryData", async () => {
    const qc = mkQc();
    wireApi(mockApi, { summary: SUMMARY_ENABLED });  // score = 82.5
    renderPage(qc);
    const arc = await screen.findByTestId("dq-score-arc");
    const fillBefore = parseFloat(arc.getAttribute("stroke-dasharray")!.split(" ")[0]);

    await act(async () => {
      qc.setQueryData(["dq-summary"], { ...SUMMARY_ENABLED, quality_score: 98 });
    });

    await waitFor(() => {
      const da = arc.getAttribute("stroke-dasharray")!;
      const fillAfter = parseFloat(da.split(" ")[0]);
      expect(fillAfter).toBeGreaterThan(fillBefore);
    });
  });

  it("score text updates when quality_score changes via setQueryData", async () => {
    const qc = mkQc();
    wireApi(mockApi, { summary: SUMMARY_ENABLED });  // score = 82.5 → "83"
    renderPage(qc);
    await waitFor(() =>
      expect(screen.queryByTestId("dq-score-total")?.textContent).toBe("83")
    );

    await act(async () => {
      qc.setQueryData(["dq-summary"], { ...SUMMARY_ENABLED, quality_score: 55 });
    });

    await waitFor(() =>
      expect(screen.queryByTestId("dq-score-total")?.textContent).toBe("55")
    );
  });
});
