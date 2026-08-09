// @vitest-environment jsdom
/**
 * Phase 26D — Trading Quality page component tests.
 *
 * Mounts the real <TradingQuality> with a mocked apiJson and verifies:
 *  - Full data renders funnel counts, quality stats, performance grades,
 *    daily report sections, five-day tracker and open issues
 *  - Readiness banner styles/verdicts (READY / PENDING / NOT_READY)
 *  - Export links for the readiness report exist in all four formats
 *  - Empty stores render explicit "no data" states, never fake health
 */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/api", () => ({
  API_BASE: "",
  apiJson: vi.fn(),
}));
vi.mock("@/components/DataFreshnessBar", () => ({
  default: () => null,
}));

import { apiJson } from "@/lib/api";
import TradingQuality from "./TradingQuality";

const mockApi = apiJson as unknown as ReturnType<typeof vi.fn>;

// ── Fixtures ──────────────────────────────────────────────────────────────────

const QUALITY = {
  ok: true,
  result: {
    verdict: "PASS",
    scan_id: "scan-77",
    funnel_available: true,
    funnel: {
      scanned: 15, scan_rejected: 3, analysed: 12,
      risk_approved: 8, risk_rejected: 4,
      signals: { buy: 5, sell: 1, watch: 4, ignore: 2 },
      executed_trades: 4, missed_count: 1,
    },
    quality_stats: {
      available: true, scope: "all_time_portfolio", total_trades: 12,
      win_rate: 58.3, profit_factor: 1.42, expectancy: 91.5,
      total_pnl: 1098.4, avg_hold_seconds: 5400, min_evidence: 5,
    },
  },
};

const PERFORMANCE = {
  ok: true,
  result: {
    verdict: "WARN",
    grade_counts: { PASS: 5, WARN: 1, FAIL: 0, INSUFFICIENT: 1 },
    metrics: [
      { metric: "scan_duration_s", value: 62, grade: "PASS", detail: "62s" },
      { metric: "db_query_ms", value: 900, grade: "WARN", detail: "900ms" },
    ],
  },
};

const DAILY = {
  ok: true,
  report: {
    report_id: "dr-abc",
    report_date: "2026-08-07",
    verdict: "WARN",
    validation_score: 92.9,
    certification: { certification_pct: 87.5, verdict: "NOT_READY" },
    sections: {
      system: { status: "PASS", source: "phase26b_live_snapshot" },
      trading: { status: "PASS", source: "phase26c_quality" },
      replay: { status: "WARN", source: "certification.replay" },
    },
    acceptance: { passed: true, critical_open_issues: 0, failed_sections: [] },
    recommendations: ["Review the replay section WARN (source: certification.replay)."],
  },
};

const FIVE_DAY = {
  ok: true,
  verdict: "PENDING",
  days: [
    { date: "2026-08-03", status: "PASS" },
    { date: "2026-08-04", status: "PASS" },
    { date: "2026-08-05", status: "PENDING", detail: "no daily validation report recorded" },
    { date: "2026-08-06", status: "PASS" },
    { date: "2026-08-07", status: "FAIL", failed_sections: ["portfolio"] },
  ],
  days_passed: 3, days_failed: 1, days_pending: 1,
  policy: "PASS requires 5 consecutive completed trading days",
};

const READINESS_NOT_READY = {
  ok: true,
  verdict: "NOT_READY",
  ready: false,
  blockers: ["latest certification NOT_READY (67.5%)", "1 open CRITICAL issue(s)"],
  pending: ["five-day acceptance PENDING (3/5 days passed)"],
};

const READINESS_READY = {
  ok: true, verdict: "READY", ready: true, blockers: [], pending: [],
};

const ISSUES = {
  ok: true,
  issues: [
    { category: "CONSISTENCY", key: "replay:count", severity: "CRITICAL",
      title: "Replay count mismatch", count: 3 },
    { category: "SYSTEM", key: "scanner:stale", severity: "WARNING",
      title: "Scanner heartbeat stale", count: 1 },
  ],
};

function mockAll(overrides: Record<string, unknown> = {}) {
  const routes: Record<string, unknown> = {
    "phase26c/quality/latest": QUALITY,
    "phase26c/performance/latest": PERFORMANCE,
    "phase26d/daily-report/latest": DAILY,
    "phase26d/five-day": FIVE_DAY,
    "phase26d/readiness": READINESS_NOT_READY,
    "live-validation/issues?status=OPEN&limit=100": ISSUES,
    ...overrides,
  };
  mockApi.mockImplementation((path: string) => {
    const hit = routes[path];
    if (hit === undefined) return Promise.reject(new Error(`unexpected path ${path}`));
    if (hit instanceof Error) return Promise.reject(hit);
    return Promise.resolve(hit);
  });
}

function mount() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <TradingQuality />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("TradingQuality page", () => {
  it("renders funnel, quality stats and performance grades", async () => {
    mockAll();
    mount();
    await waitFor(() => {
      expect(screen.getByText("Session Funnel")).toBeTruthy();
      expect(screen.getByText("15")).toBeTruthy();          // scanned
      expect(screen.getByText("Win Rate")).toBeTruthy();
      expect(screen.getByText("58.3%")).toBeTruthy();
      expect(screen.getByText(/all time portfolio/i)).toBeTruthy(); // scope label
      expect(screen.getByText("scan duration s")).toBeTruthy();
      expect(screen.getByText("db query ms")).toBeTruthy();
    });
  });

  it("renders daily report sections, score and five-day tracker", async () => {
    mockAll();
    mount();
    await waitFor(() => {
      expect(screen.getByText("Daily Validation Report")).toBeTruthy();
      expect(screen.getByText("2026-08-07")).toBeTruthy();
      expect(screen.getByText("92.9%")).toBeTruthy();
      expect(screen.getByText("Five-Day Acceptance")).toBeTruthy();
      expect(screen.getByTestId("five-day-2026-08-05")).toBeTruthy();
      expect(screen.getByText(/1 failed/)).toBeTruthy();
      expect(screen.getByText(/1 pending/)).toBeTruthy();
    });
  });

  it("NOT_READY banner shows blockers, pending and export links", async () => {
    mockAll();
    mount();
    await waitFor(() => {
      expect(screen.getByText("NOT READY")).toBeTruthy();
      expect(screen.getByText(/latest certification NOT_READY/)).toBeTruthy();
      expect(screen.getByText(/five-day acceptance PENDING/)).toBeTruthy();
    });
    for (const fmt of ["pdf", "csv", "json", "md"]) {
      const link = screen.getByText(fmt).closest("a");
      expect(link?.getAttribute("href")).toBe(`/phase239/export/readiness/${fmt}`);
    }
  });

  it("READY banner renders green verdict", async () => {
    mockAll({ "phase26d/readiness": READINESS_READY });
    mount();
    await waitFor(() => {
      expect(screen.getByText("READY")).toBeTruthy();
    });
  });

  it("renders open issues with severity badges", async () => {
    mockAll();
    mount();
    await waitFor(() => {
      expect(screen.getByText("Replay count mismatch")).toBeTruthy();
      expect(screen.getByText("Scanner heartbeat stale")).toBeTruthy();
      expect(screen.getByText("2 open")).toBeTruthy();
    });
  });

  it("empty stores render explicit no-data states", async () => {
    mockAll({
      "phase26c/quality/latest": { ok: false },
      "phase26c/performance/latest": { ok: false },
      "phase26d/daily-report/latest": { ok: false },
      "live-validation/issues?status=OPEN&limit=100": { ok: true, issues: [] },
    });
    mount();
    await waitFor(() => {
      expect(screen.getByText(/No trading-quality run recorded yet/)).toBeTruthy();
      expect(screen.getByText(/No performance validation run recorded yet/)).toBeTruthy();
      expect(screen.getByText(/No daily validation report recorded yet/)).toBeTruthy();
      expect(screen.getByText(/No open issues/)).toBeTruthy();
    });
  });
});
