// @vitest-environment jsdom
/**
 * OperatorAnalytics.test.tsx — Phase 27E
 *
 * Smoke-tests and contract-tests for the Operator Analytics Dashboard.
 * All backend calls are mocked via vi.mock("@/lib/api").
 *
 * Coverage:
 *  1.  Page renders title "Operator Analytics"
 *  2.  Page shows loading state while apiJson is pending
 *  3.  Page shows error state when apiJson rejects
 *  4.  SourcesBanner NOT shown when all sources are available
 *  5.  SourcesBanner shown when pipeline_events source is unavailable
 *  6.  SourcesBanner shown when pipeline_events source is truncated
 *  7.  Funnel stage "scanner" renders stocks_in→stocks_out
 *  8.  Funnel stage "risk" shows INSUFFICIENT TELEMETRY badge
 *  9.  Rejection row renders reason_code DAILY_LOSS_LIMIT
 * 10.  Clicking rejection row expands drill-down showing symbols
 * 11.  EvidenceBadge for SOURCE_UNAVAILABLE renders correct text
 * 12.  EvidenceBadge for PARTIAL renders correct text
 * 13.  Decisions section renders BUY count
 * 14.  Risk interventions "risk" card renders Blocked value
 * 15.  Trends table renders at least one row
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, cleanup, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ── Module mocks ──────────────────────────────────────────────────────────────

vi.mock("@/lib/api", () => ({
  API_BASE: "",
  apiJson: vi.fn(),
}));

vi.mock("wouter", () => ({
  Link: ({ href, children, className }: React.AnchorHTMLAttributes<HTMLAnchorElement>) =>
    React.createElement("a", { href, className }, children),
  useLocation: vi.fn(() => ["/"]),
  useRoute: vi.fn(() => [false, {}]),
}));

import { apiJson } from "@/lib/api";
import OperatorAnalytics from "./OperatorAnalytics";

// ── Fixtures ──────────────────────────────────────────────────────────────────

const FULL_REPORT = {
  ok: true,
  advisory_only: true,
  read_only: true,
  generated_at: "2025-01-01T09:15:00Z",
  scan_id: "scan_abc123",
  snapshot_ts: "2025-01-01T09:10:00Z",
  event_count: 120,
  note: "Phase 27E Operator Analytics — read-only",
  sources: {
    replay: { available: true, error: null },
    pipeline_events: { available: true, error: null, truncated: false, limit: 2000 },
    snapshot: { available: true, error: null },
    sessions: { available: true, error: null, demo_excluded: 0 },
  },
  session_summary: {
    source: "replay sessions",
    available: true,
    error: null,
    sessions: [
      {
        scan_id: "scan_abc123",
        snapshot_ts: "2025-01-01T09:10:00Z",
        status: "SUCCESS",
        universe_size: 50,
        symbols_processed: 48,
        total_recommendations: 5,
        buy_signals: 2,
        paper_orders: 1,
        duration_s: 42,
      },
    ],
  },
  funnel: {
    source: "unified replay snapshot",
    stages: [
      {
        id: "scanner",
        label: "Scanner",
        order: 1,
        stocks_in: 50,
        stocks_out: 48,
        rejected: 2,
        pending: 0,
        cancelled: 0,
        conversion_pct: 96.0,
        timing: {
          insufficient_telemetry: false,
          samples: 48,
          avg_ms: 120,
          median_ms: 110,
          p95_ms: 280,
        },
      },
      {
        id: "risk",
        label: "Risk",
        order: 6,
        stocks_in: 10,
        stocks_out: 3,
        rejected: 7,
        pending: 0,
        cancelled: 0,
        conversion_pct: 30.0,
        timing: { insufficient_telemetry: true, samples: 1 },
      },
    ],
  },
  rejections: {
    source: "pipeline_events",
    rejected_events: 15,
    reason_occurrences: 18,
    evidence: "OK",
    reasons: [
      {
        event_type: "RISK_REJECTED",
        group: "Risk gates",
        reason_code: "DAILY_LOSS_LIMIT",
        count: 10,
        pct_of_occurrences: 55.6,
        symbols: ["ABC", "XYZ"],
        event_ids: [1, 2, 3],
      },
      {
        event_type: "PRECHECK_REJECTED",
        group: "Portfolio pre-check",
        reason_code: "INSUFFICIENT_CASH",
        count: 8,
        pct_of_occurrences: 44.4,
        symbols: ["DEF"],
        event_ids: [4, 5],
      },
    ],
  },
  decisions: {
    source: "pipeline_events + snapshot",
    event_decisions: {
      counts: { BUY: 3, WATCH: 12 },
      total: 15,
      evidence: "OK",
      pct: { BUY: 20, WATCH: 80 },
    },
    snapshot_distribution: {
      available: true,
      note: null,
      actions: [
        { action: "WATCH", count: 12, pct: 80 },
        { action: "BUY", count: 3, pct: 20 },
      ],
      by_sector: [{ sector: "IT", actions: { BUY: 2, WATCH: 5 } }],
      regime: "TRENDING",
    },
  },
  risk_interventions: {
    source: "pipeline_events",
    risk: {
      candidates: 10,
      approved: 3,
      blocked: 7,
      block_rate_pct: 70.0,
      evidence: "OK",
      reasons: [
        { reason_code: "DAILY_LOSS_LIMIT", count: 7, symbols: ["ABC"], event_ids: [1] },
      ],
    },
    portfolio_precheck: {
      candidates: 5,
      approved: 4,
      blocked: 1,
      block_rate_pct: 20.0,
      evidence: "OK",
      reasons: [
        { reason_code: "INSUFFICIENT_CASH", count: 1, symbols: ["DEF"], event_ids: [4] },
      ],
    },
  },
  trends: {
    window_scans: 5,
    source: "replay sessions + per-scan pipeline_events",
    note: null,
    points: [
      {
        scan_id: "scan_abc123",
        snapshot_ts: "2025-01-01T09:10:00Z",
        is_current: true,
        rejected_events: 15,
        decisions: { BUY: 3 },
        rejections_by_reason: { DAILY_LOSS_LIMIT: 10 },
        evidence: "OK",
      },
    ],
  },
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: qc }, children);
}

function renderPage() {
  return render(
    React.createElement(OperatorAnalytics),
    { wrapper: makeWrapper() }
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("OperatorAnalytics", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  // 1. Page title
  it("renders page title 'Operator Analytics'", async () => {
    vi.mocked(apiJson).mockResolvedValue(FULL_REPORT);
    renderPage();
    expect(screen.getByText("Operator Analytics")).toBeTruthy();
  });

  // 2. Loading state
  it("shows loading state while apiJson is pending", async () => {
    vi.mocked(apiJson).mockReturnValue(new Promise(() => {})); // never resolves
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/Aggregating canonical stores/i)).toBeTruthy();
    });
  });

  // 3. Error state
  it("shows error state when apiJson rejects", async () => {
    // Route mock: operator-analytics report fails; paper-analytics returns null (loading)
    vi.mocked(apiJson).mockImplementation((path: string) => {
      if (String(path).includes("operator-analytics")) {
        return Promise.reject(new Error("Network failure"));
      }
      return new Promise(() => {}); // paper-analytics never resolves (keeps loading)
    });
    // Use a fresh QueryClient with retry: false so error surfaces immediately
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
    });
    render(
      React.createElement(OperatorAnalytics),
      { wrapper: ({ children }: { children: React.ReactNode }) =>
          React.createElement(QueryClientProvider, { client: qc }, children) }
    );
    await waitFor(() => {
      expect(screen.getByText(/Failed to load operator analytics/i)).toBeTruthy();
    }, { timeout: 5000 });
  });

  // 4. SourcesBanner NOT shown when all sources available
  it("does NOT show SourcesBanner when all sources are available", async () => {
    vi.mocked(apiJson).mockResolvedValue(FULL_REPORT);
    renderPage();
    await waitFor(() => {
      expect(screen.queryByTestId("sources-banner")).toBeNull();
    });
  });

  // 5. SourcesBanner shown when pipeline_events is unavailable
  it("shows SourcesBanner when pipeline_events is unavailable", async () => {
    const report = {
      ...FULL_REPORT,
      sources: {
        ...FULL_REPORT.sources,
        pipeline_events: {
          available: false,
          error: "db timeout",
          truncated: false,
          limit: 2000,
        },
      },
    };
    vi.mocked(apiJson).mockResolvedValue(report);
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("sources-banner")).toBeTruthy();
    });
  });

  // 6. SourcesBanner shown when pipeline_events is truncated
  it("shows SourcesBanner when pipeline_events fetch is truncated", async () => {
    const report = {
      ...FULL_REPORT,
      sources: {
        ...FULL_REPORT.sources,
        pipeline_events: {
          available: true,
          error: null,
          truncated: true,
          limit: 2000,
        },
      },
    };
    vi.mocked(apiJson).mockResolvedValue(report);
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("sources-banner")).toBeTruthy();
    });
  });

  // 7. Funnel stage scanner renders stocks_in→stocks_out
  it("renders funnel stage scanner with 50→48 text", async () => {
    vi.mocked(apiJson).mockResolvedValue(FULL_REPORT);
    renderPage();
    await waitFor(() => {
      const scannerStage = screen.getByTestId("funnel-stage-scanner");
      expect(scannerStage).toBeTruthy();
      expect(scannerStage.textContent).toContain("50");
      expect(scannerStage.textContent).toContain("48");
    });
  });

  // 8. Funnel stage risk shows INSUFFICIENT TELEMETRY badge
  it("shows INSUFFICIENT TELEMETRY badge for risk stage", async () => {
    vi.mocked(apiJson).mockResolvedValue(FULL_REPORT);
    renderPage();
    await waitFor(() => {
      const riskStage = screen.getByTestId("funnel-stage-risk");
      expect(riskStage.textContent).toContain("INSUFFICIENT TELEMETRY");
    });
  });

  // 9. Rejection row renders DAILY_LOSS_LIMIT
  it("renders rejection row with reason_code DAILY_LOSS_LIMIT", async () => {
    vi.mocked(apiJson).mockResolvedValue(FULL_REPORT);
    renderPage();
    await waitFor(() => {
      const rejRow = screen.getByTestId("rejection-RISK_REJECTED");
      expect(rejRow).toBeTruthy();
      expect(rejRow.textContent).toContain("DAILY_LOSS_LIMIT");
    });
  });

  // 10. Clicking rejection row expands drill-down with symbols
  it("clicking rejection row expands drill-down showing symbols ABC, XYZ", async () => {
    vi.mocked(apiJson).mockResolvedValue(FULL_REPORT);
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("rejection-RISK_REJECTED")).toBeTruthy();
    });
    const rejBtn = screen.getByTestId("rejection-RISK_REJECTED");
    fireEvent.click(rejBtn);
    await waitFor(() => {
      // After click, drill-down should show the symbols
      expect(screen.getByText(/ABC.*XYZ|ABC, XYZ/)).toBeTruthy();
    });
  });

  // 11. EvidenceBadge for SOURCE_UNAVAILABLE
  it("EvidenceBadge renders 'SOURCE UNAVAILABLE' for SOURCE_UNAVAILABLE evidence", async () => {
    const report = {
      ...FULL_REPORT,
      rejections: {
        ...FULL_REPORT.rejections,
        reasons: [],
        evidence: "SOURCE_UNAVAILABLE",
      },
    };
    vi.mocked(apiJson).mockResolvedValue(report);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("SOURCE UNAVAILABLE")).toBeTruthy();
    });
  });

  // 12. EvidenceBadge for PARTIAL
  it("EvidenceBadge renders 'PARTIAL — FETCH TRUNCATED' for PARTIAL evidence", async () => {
    const report = {
      ...FULL_REPORT,
      rejections: {
        ...FULL_REPORT.rejections,
        evidence: "PARTIAL",
      },
    };
    vi.mocked(apiJson).mockResolvedValue(report);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("PARTIAL — FETCH TRUNCATED")).toBeTruthy();
    });
  });

  // 13. Decisions section renders BUY count
  it("decisions section renders BUY count from event_decisions", async () => {
    vi.mocked(apiJson).mockResolvedValue(FULL_REPORT);
    renderPage();
    await waitFor(() => {
      // Multiple "BUY" labels exist (event_decisions + snapshot_distribution both show BUY)
      const buyLabels = screen.getAllByText("BUY");
      expect(buyLabels.length).toBeGreaterThan(0);
      // The value "3 (20%)" appears for BUY in both sections — verify at least one exists
      const buyValues = screen.getAllByText("3 (20%)");
      expect(buyValues.length).toBeGreaterThan(0);
    });
  });

  // 14. Risk interventions "risk" card renders Blocked value 7
  it("risk interventions card renders Blocked value 7", async () => {
    vi.mocked(apiJson).mockResolvedValue(FULL_REPORT);
    renderPage();
    await waitFor(() => {
      const riskCard = screen.getByTestId("risk-risk");
      expect(riskCard).toBeTruthy();
      expect(riskCard.textContent).toContain("7");
    });
  });

  // 15. Trends table renders at least one row
  it("trends table renders at least one row", async () => {
    vi.mocked(apiJson).mockResolvedValue(FULL_REPORT);
    renderPage();
    await waitFor(() => {
      // The trend table row shows rejected_events count and BUY:3 decisions
      // Multiple elements may match scan_abc123, so check for the trend-specific content
      const allMatches = screen.getAllByText(/scan_abc123/);
      expect(allMatches.length).toBeGreaterThan(0);
      // Trends table also shows rejection count "15" for this scan
      // and "BUY:3" in the decisions column
      expect(screen.getByText("BUY:3")).toBeTruthy();
    });
  });
});
