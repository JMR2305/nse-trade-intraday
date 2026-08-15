// @vitest-environment jsdom
/**
 * OperatorAnalytics.test.tsx — Phase 27E component tests.
 *
 * Mounts the real <OperatorAnalytics> with apiJson mocked via
 * vi.mock("@/lib/api") and verifies:
 *  - page renders without crash with a full mock payload
 *  - SourcesBanner shown when sources are unavailable / truncated
 *  - funnel stages render with correct data-testid attributes
 *  - rejection rows expand on click (drill-down)
 *  - EvidenceBadge renders SOURCE_UNAVAILABLE / PARTIAL correctly
 *  - loading and error states render correctly
 */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/api", () => ({
  API_BASE: "",
  apiJson: vi.fn(),
}));

import { apiJson } from "@/lib/api";
import OperatorAnalytics from "./OperatorAnalytics";

const mockApi = apiJson as unknown as ReturnType<typeof vi.fn>;

// ── Fixtures ──────────────────────────────────────────────────────────────────

const SOURCES_OK = {
  replay: { available: true, error: null },
  pipeline_events: { available: true, error: null, truncated: false, limit: 2000 },
  snapshot: { available: true, error: null },
  sessions: { available: true, error: null, demo_excluded: 0 },
};

const REPORT_FULL = {
  ok: true,
  advisory_only: true,
  read_only: true,
  generated_at: "2026-08-14T10:00:00Z",
  note: "Phase 27E Operator Analytics — read-only.",
  scan_id: "scan-20260814-01",
  snapshot_ts: "2026-08-14T09:30:00Z",
  event_count: 42,
  sources: SOURCES_OK,
  session_summary: {
    source: "replay sessions",
    available: true,
    error: null,
    sessions: [
      { scan_id: "scan-20260814-01", snapshot_ts: "2026-08-14T09:30:00Z",
        status: "COMPLETED", universe_size: 51, symbols_processed: 51,
        total_recommendations: 40, buy_signals: 5, paper_orders: 2,
        duration_s: 320 },
    ],
  },
  funnel: {
    source: "unified replay snapshot (counts) + pipeline_events (timing)",
    stages: [
      { id: "market_data", label: "Scanner", order: 1, stocks_in: 51,
        stocks_out: 40, rejected: 11, pending: 0, cancelled: 0,
        conversion_pct: 78.4,
        timing: { insufficient_telemetry: false, samples: 40,
                  avg_ms: 120.5, median_ms: 100.0, p95_ms: 300.0 } },
      { id: "risk", label: "Risk Gates", order: 2, stocks_in: 6,
        stocks_out: 5, rejected: 1, pending: 0, cancelled: 0,
        conversion_pct: 83.3,
        timing: { insufficient_telemetry: true, samples: 1 } },
    ],
  },
  rejections: {
    rejected_events: 3,
    reason_occurrences: 4,
    evidence: "OK",
    source: "pipeline_events",
    reasons: [
      { event_type: "RISK_REJECTED", group: "Risk gates",
        reason_code: "max_positions", count: 2, pct_of_occurrences: 50.0,
        symbols: ["AAA", "BBB"], event_ids: [11, 12] },
      { event_type: "SYMBOL_REJECTED", group: "Scanner / market data",
        reason_code: "no candles", count: 2, pct_of_occurrences: 50.0,
        symbols: ["CCC"], event_ids: [13] },
    ],
  },
  decisions: {
    source: "pipeline_events decision events + canonical snapshot",
    event_decisions: {
      counts: { BUY: 5, WATCH: 10 }, total: 15, evidence: "OK",
      pct: { BUY: 33.3, WATCH: 66.7 },
    },
    snapshot_distribution: {
      available: true, note: null, regime: "TRENDING",
      actions: [
        { action: "WATCH", count: 27, pct: 55.1 },
        { action: "BUY", count: 5, pct: 10.2 },
      ],
      by_sector: [{ sector: "IT", actions: { BUY: 2, WATCH: 4 } }],
    },
  },
  risk_interventions: {
    source: "pipeline_events PRECHECK_*/RISK_*",
    risk: { candidates: 6, approved: 5, blocked: 1, block_rate_pct: 16.7,
            evidence: "OK",
            reasons: [{ reason_code: "max_exposure", count: 1,
                        symbols: ["AAA"], event_ids: [9] }] },
    portfolio_precheck: { candidates: 0, approved: 0, blocked: 0,
                          block_rate_pct: null, evidence: "VERIFIED_EMPTY",
                          reasons: [] },
  },
  trends: {
    window_scans: 5, note: null,
    source: "replay sessions + per-scan pipeline_events",
    points: [
      { scan_id: "scan-20260814-01", snapshot_ts: "2026-08-14T09:30:00Z",
        is_current: true, rejected_events: 3,
        rejections_by_reason: { max_positions: 2, "no candles": 2 },
        decisions: { BUY: 5 }, evidence: "OK" },
      { scan_id: "scan-20260813-01", snapshot_ts: "2026-08-13T09:30:00Z",
        is_current: false, rejected_events: 0, rejections_by_reason: {},
        decisions: {}, evidence: "PARTIAL" },
    ],
  },
  performance_note: "served by paper-analytics endpoints",
};

const PAPER_SUMMARY = { available: false };
const PAPER_SNAPSHOT = {};

function wire(report: unknown | Promise<unknown>) {
  mockApi.mockImplementation((path: string) => {
    if (path.includes("operator-analytics/report")) {
      return report instanceof Promise ? report : Promise.resolve(report);
    }
    if (path.includes("paper-analytics/summary")) return Promise.resolve(PAPER_SUMMARY);
    if (path.includes("paper-analytics/snapshot")) return Promise.resolve(PAPER_SNAPSHOT);
    return Promise.resolve(null);
  });
}

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <OperatorAnalytics />
    </QueryClientProvider>,
  );
}

// NOTE: never mockReset an API mock in beforeEach — in-flight React Query
// retries from the previous test would reject unhandled (Vitest 4).
afterEach(() => cleanup());

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("OperatorAnalytics — Phase 27E", () => {
  it("renders the page with the full payload without crash", async () => {
    wire(REPORT_FULL);
    mount();
    expect(screen.getByTestId("operator-analytics-page")).toBeTruthy();
    await waitFor(() =>
      expect(screen.getByText("Pipeline Funnel & Stage Timing")).toBeTruthy());
    expect(screen.getByText("Operator Analytics")).toBeTruthy();
    expect(screen.getByText(/READ-ONLY/)).toBeTruthy();
    expect(screen.getByText("Rejection Breakdown")).toBeTruthy();
    expect(screen.getByText("Decision Distribution")).toBeTruthy();
    expect(screen.getByText("Risk Interventions")).toBeTruthy();
    expect(screen.getByText("Cross-Scan Trends")).toBeTruthy();
    expect(screen.getByText("Session Summary")).toBeTruthy();
    // no sources banner when all sources are OK
    expect(screen.queryByTestId("sources-banner")).toBeNull();
  });

  it("renders funnel stages with the correct data-testid attributes", async () => {
    wire(REPORT_FULL);
    mount();
    await waitFor(() =>
      expect(screen.getByTestId("funnel-stage-market_data")).toBeTruthy());
    expect(screen.getByTestId("funnel-stage-risk")).toBeTruthy();
    expect(screen.getByText(/51→40/)).toBeTruthy();
    // stage with < MIN samples shows insufficient telemetry, never fabricated
    expect(screen.getByText("INSUFFICIENT TELEMETRY")).toBeTruthy();
  });

  it("shows the SourcesBanner when a source is unavailable or truncated", async () => {
    wire({
      ...REPORT_FULL,
      sources: {
        ...SOURCES_OK,
        pipeline_events: { available: false, error: "db down",
                           truncated: false, limit: 2000 },
        snapshot: { available: true, truncated: true, limit: 2000 },
      },
    });
    mount();
    await waitFor(() =>
      expect(screen.getByTestId("sources-banner")).toBeTruthy());
    expect(screen.getByText(/pipeline_events: unavailable \(db down\)/)).toBeTruthy();
    expect(screen.getByText(/snapshot: fetch truncated at 2000 events/)).toBeTruthy();
  });

  it("expands a rejection row on click (drill-down)", async () => {
    wire(REPORT_FULL);
    mount();
    await waitFor(() =>
      expect(screen.getByTestId("rejection-RISK_REJECTED")).toBeTruthy());
    // details hidden before click
    expect(screen.queryByText(/symbols: AAA, BBB/)).toBeNull();
    fireEvent.click(screen.getByTestId("rejection-RISK_REJECTED"));
    expect(screen.getByText(/symbols: AAA, BBB/)).toBeTruthy();
    expect(screen.getByText(/event ids: 11, 12/)).toBeTruthy();
    // click again collapses
    fireEvent.click(screen.getByTestId("rejection-RISK_REJECTED"));
    expect(screen.queryByText(/symbols: AAA, BBB/)).toBeNull();
  });

  it("renders SOURCE_UNAVAILABLE evidence badges correctly", async () => {
    wire({
      ...REPORT_FULL,
      rejections: { rejected_events: 0, reason_occurrences: 0, reasons: [],
                    evidence: "SOURCE_UNAVAILABLE", source: "pipeline_events" },
      decisions: {
        ...REPORT_FULL.decisions,
        event_decisions: { counts: {}, total: 0, pct: {},
                           evidence: "SOURCE_UNAVAILABLE" },
      },
    });
    mount();
    await waitFor(() =>
      expect(screen.getAllByText("SOURCE UNAVAILABLE").length)
        .toBeGreaterThanOrEqual(2));
  });

  it("renders the PARTIAL evidence badge when the fetch was truncated", async () => {
    wire({
      ...REPORT_FULL,
      rejections: { ...REPORT_FULL.rejections, evidence: "PARTIAL" },
    });
    mount();
    await waitFor(() =>
      expect(screen.getByText("PARTIAL — FETCH TRUNCATED")).toBeTruthy());
  });

  it("renders risk intervention blocks with counts and reasons", async () => {
    wire(REPORT_FULL);
    mount();
    await waitFor(() => expect(screen.getByTestId("risk-risk")).toBeTruthy());
    expect(screen.getByTestId("risk-portfolio_precheck")).toBeTruthy();
    expect(screen.getByText("max_exposure")).toBeTruthy();
    expect(screen.getByText(/block rate: 16.7%/)).toBeTruthy();
    // empty precheck shows VERIFIED EMPTY, never fabricated z 0-rate
    expect(screen.getByText("VERIFIED EMPTY")).toBeTruthy();
  });

  it("renders trend rows including partial-evidence flag", async () => {
    wire(REPORT_FULL);
    mount();
    await waitFor(() =>
      expect(screen.getByText(/max_positions \(2\)/)).toBeTruthy());
    expect(screen.getByText("partial")).toBeTruthy();
  });

  it("shows the loading state while the report is pending", () => {
    wire(new Promise(() => {})); // never resolves
    mount();
    expect(screen.getByText(/Aggregating canonical stores/)).toBeTruthy();
  });

  it("shows the error state with a Retry button when the report fails", async () => {
    mockApi.mockImplementation((path: string) =>
      path.includes("operator-analytics/report")
        ? Promise.reject(new Error("boom 500"))
        : Promise.resolve(null));
    mount();
    // the page sets retry: 2 internally → error surfaces after ~3s of retries
    await waitFor(
      () => expect(screen.getByText(/Failed to load operator analytics/)).toBeTruthy(),
      { timeout: 10_000 });
    expect(screen.getByText(/boom 500/)).toBeTruthy();
    expect(screen.getByText("Retry")).toBeTruthy();
  });
});
