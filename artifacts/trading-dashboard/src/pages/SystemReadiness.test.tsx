// @vitest-environment jsdom
/**
 * SystemReadiness.test.tsx — Phase 27F
 *
 * Smoke-tests and contract-tests for the System Readiness Dashboard.
 * All backend calls are mocked via vi.mock("@/lib/api").
 *
 * Coverage:
 *  1.  Page renders heading "System Readiness"
 *  2.  Loading state renders "Evaluating readiness…" (data-testid="loading")
 *  3.  Error state renders when apiJson rejects
 *  4.  Overall READY banner renders data-testid="overall-banner" with READY content
 *  5.  Overall BLOCKED banner shows BLOCKED status badge (data-testid="status-BLOCKED")
 *  6.  Domain card "Safety Controls" renders correctly
 *  7.  Check row data-testid="check-execution_mode" is rendered
 *  8.  Check row expands evidence JSON on click
 *  9.  BLOCKING badge shown for blocking check (blocking: true)
 *  10. Remediation text shown when check is non-READY
 *  11. FreshnessCard shows "Canonical scan snapshot" row
 *  12. HistoryCard shows "No readiness checks recorded yet" when entries empty
 *  13. HistoryCard shows 2 history entries when data provided
 *  14. source-errors banner (data-testid="source-errors") shown when source_errors non-empty
 *  15. "Run readiness check" button renders (data-testid="button-run-check")
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
import SystemReadiness from "./SystemReadiness";

// ── Fixtures ──────────────────────────────────────────────────────────────────

const READY_REPORT = {
  ok: true,
  generated_at: "2025-01-01T09:15:00Z",
  overall: "READY",
  counts: { READY: 8, WARNING: 1, BLOCKED: 0, UNKNOWN: 0 },
  note: "Deterministic readiness fold over canonical health sources.",
  paper_trading_only: true,
  advisory_only: true,
  market: { state: "CLOSED", is_open: false, next_transition: null },
  source_errors: {},
  freshness: [
    {
      name: "Canonical scan snapshot",
      ts: "2025-01-01T09:10:00Z",
      age_seconds: 300,
      limit_seconds: 5400,
      status: "READY",
      source: "scan_state_store",
      note: "budget from phase13",
    },
  ],
  domains: [
    {
      domain: "Market & Data",
      status: "READY",
      checks: [
        {
          id: "scan_freshness",
          domain: "Market & Data",
          label: "Canonical scan freshness",
          status: "READY",
          blocking: true,
          expected: "snapshot younger than 90m",
          actual: "snapshot age 5m",
          evidence: {},
          remediation: "",
          checked_at: "2025-01-01T09:15:00Z",
        },
      ],
    },
    {
      domain: "Safety Controls",
      status: "READY",
      checks: [
        {
          id: "execution_mode",
          domain: "Safety Controls",
          label: "Execution mode (paper-only)",
          status: "READY",
          blocking: true,
          expected: "PAPER TRADING mode verified",
          actual: "PAPER TRADING verified — no live-execution flags set",
          evidence: { paper_trading_mode: true },
          remediation: "",
          checked_at: "2025-01-01T09:15:00Z",
        },
      ],
    },
  ],
};

const BLOCKED_REPORT = {
  ...READY_REPORT,
  overall: "BLOCKED",
  counts: { READY: 7, WARNING: 0, BLOCKED: 1, UNKNOWN: 0 },
  source_errors: {},
  domains: [
    {
      domain: "Safety Controls",
      status: "BLOCKED",
      checks: [
        {
          id: "execution_mode",
          domain: "Safety Controls",
          label: "Execution mode (paper-only)",
          status: "BLOCKED",
          blocking: true,
          expected: "PAPER TRADING verified",
          actual: "a live-execution flag is set",
          evidence: { LIVE_EXECUTION_ENABLED: "true" },
          remediation: "Unset LIVE_EXECUTION_ENABLED.",
          checked_at: "2025-01-01T09:15:00Z",
        },
      ],
    },
  ],
};

const HISTORY_RESPONSE = {
  ok: true,
  entries: [
    {
      at: "2025-01-01T09:15:00Z",
      overall: "READY",
      counts: { READY: 8, WARNING: 1, BLOCKED: 0, UNKNOWN: 0 },
      blocking_failures: [],
      issues: [],
    },
    {
      at: "2025-01-01T08:00:00Z",
      overall: "WARNING",
      counts: { READY: 7, WARNING: 2, BLOCKED: 0, UNKNOWN: 0 },
      blocking_failures: [],
      issues: [{ id: "scan_freshness", status: "WARNING" }],
    },
  ],
};

const EMPTY_HISTORY = { ok: true, entries: [] };

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
    },
  });
}

function mountPage(client: QueryClient) {
  render(
    <QueryClientProvider client={client}>
      <SystemReadiness />
    </QueryClientProvider>
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("SystemReadiness page", () => {
  const mock = apiJson as ReturnType<typeof vi.fn>;
  let client: QueryClient;

  beforeEach(() => {
    client = makeClient();
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  // ── Test 1: Page heading ────────────────────────────────────────────────────
  it("1. page renders heading 'System Readiness'", async () => {
    mock.mockImplementation((url: string) => {
      if (url.includes("history")) return Promise.resolve(EMPTY_HISTORY);
      return new Promise(() => {}); // report stays loading
    });
    mountPage(client);
    await waitFor(() => screen.getByText("System Readiness"));
  });

  // ── Test 2: Loading state ───────────────────────────────────────────────────
  it("2. loading state renders 'Evaluating readiness…' with data-testid='loading'", async () => {
    mock.mockImplementation((url: string) => {
      if (url.includes("history")) return Promise.resolve(EMPTY_HISTORY);
      return new Promise(() => {}); // never resolves → loading
    });
    mountPage(client);
    await waitFor(() => screen.getByTestId("loading"));
    expect(screen.getByTestId("loading").textContent).toMatch(/Evaluating readiness/);
  });

  // ── Test 3: Error state ─────────────────────────────────────────────────────
  it("3. error state renders when apiJson rejects", async () => {
    mock.mockImplementation((url: string) => {
      if (url.includes("history")) return Promise.resolve(EMPTY_HISTORY);
      return Promise.reject(new Error("Server error"));
    });
    mountPage(client);
    // Component has retry:2; allow up to 10s for all retries to exhaust
    await waitFor(() => screen.getByTestId("error"), { timeout: 10000 });
    expect(screen.getByTestId("error").textContent).toMatch(/Failed to load readiness report/);
  });

  // ── Test 4: READY banner ────────────────────────────────────────────────────
  it("4. overall READY banner renders data-testid='overall-banner' with READY content", async () => {
    mock.mockImplementation((url: string) => {
      if (url.includes("history")) return Promise.resolve(EMPTY_HISTORY);
      return Promise.resolve(READY_REPORT);
    });
    mountPage(client);
    await waitFor(() => screen.getByTestId("overall-banner"));
    expect(screen.getByTestId("overall-banner").textContent).toMatch(/READY/);
  });

  // ── Test 5: BLOCKED banner ──────────────────────────────────────────────────
  it("5. overall BLOCKED banner shows BLOCKED status badge", async () => {
    mock.mockImplementation((url: string) => {
      if (url.includes("history")) return Promise.resolve(EMPTY_HISTORY);
      return Promise.resolve(BLOCKED_REPORT);
    });
    mountPage(client);
    // Multiple status-BLOCKED badges may render (banner + domain card + check row)
    await waitFor(() => {
      const badges = screen.getAllByTestId("status-BLOCKED");
      expect(badges.length).toBeGreaterThanOrEqual(1);
    });
  });

  // ── Test 6: Domain card ─────────────────────────────────────────────────────
  it("6. domain card 'Safety Controls' renders correctly", async () => {
    mock.mockImplementation((url: string) => {
      if (url.includes("history")) return Promise.resolve(EMPTY_HISTORY);
      return Promise.resolve(READY_REPORT);
    });
    mountPage(client);
    await waitFor(() => screen.getByText("Safety Controls"));
  });

  // ── Test 7: Check row by data-testid ────────────────────────────────────────
  it("7. check row data-testid='check-execution_mode' is rendered", async () => {
    mock.mockImplementation((url: string) => {
      if (url.includes("history")) return Promise.resolve(EMPTY_HISTORY);
      return Promise.resolve(READY_REPORT);
    });
    mountPage(client);
    await waitFor(() => screen.getByTestId("check-execution_mode"));
  });

  // ── Test 8: Evidence JSON expands on click ──────────────────────────────────
  it("8. check row expands evidence JSON on click", async () => {
    const reportWithEvidence = {
      ...READY_REPORT,
      domains: [
        {
          domain: "Safety Controls",
          status: "READY",
          checks: [
            {
              id: "execution_mode",
              domain: "Safety Controls",
              label: "Execution mode (paper-only)",
              status: "READY",
              blocking: true,
              expected: "PAPER TRADING mode verified",
              actual: "PAPER TRADING verified",
              evidence: { paper_trading_mode: true },
              remediation: "",
              checked_at: "2025-01-01T09:15:00Z",
            },
          ],
        },
      ],
    };
    mock.mockImplementation((url: string) => {
      if (url.includes("history")) return Promise.resolve(EMPTY_HISTORY);
      return Promise.resolve(reportWithEvidence);
    });
    mountPage(client);
    await waitFor(() => screen.getByTestId("check-execution_mode"));
    fireEvent.click(screen.getByTestId("check-execution_mode"));
    await waitFor(() => {
      const pre = document.querySelector("pre");
      expect(pre).not.toBeNull();
      expect(pre!.textContent).toContain("paper_trading_mode");
    });
  });

  // ── Test 9: BLOCKING badge ──────────────────────────────────────────────────
  it("9. BLOCKING badge shown for blocking check", async () => {
    mock.mockImplementation((url: string) => {
      if (url.includes("history")) return Promise.resolve(EMPTY_HISTORY);
      return Promise.resolve(READY_REPORT);
    });
    mountPage(client);
    // Multiple BLOCKING badges may render (one per blocking check in each domain)
    await waitFor(() => {
      const badges = screen.getAllByText("BLOCKING");
      expect(badges.length).toBeGreaterThanOrEqual(1);
    });
  });

  // ── Test 10: Remediation text ───────────────────────────────────────────────
  it("10. remediation text shown when check is non-READY", async () => {
    mock.mockImplementation((url: string) => {
      if (url.includes("history")) return Promise.resolve(EMPTY_HISTORY);
      return Promise.resolve(BLOCKED_REPORT);
    });
    mountPage(client);
    await waitFor(() => screen.getByText(/Unset LIVE_EXECUTION_ENABLED/));
  });

  // ── Test 11: FreshnessCard ──────────────────────────────────────────────────
  it("11. FreshnessCard shows 'Canonical scan snapshot' row", async () => {
    mock.mockImplementation((url: string) => {
      if (url.includes("history")) return Promise.resolve(EMPTY_HISTORY);
      return Promise.resolve(READY_REPORT);
    });
    mountPage(client);
    await waitFor(() => screen.getByText("Canonical scan snapshot"));
  });

  // ── Test 12: HistoryCard empty ──────────────────────────────────────────────
  it("12. HistoryCard shows 'No readiness checks recorded yet' when entries empty", async () => {
    mock.mockImplementation((url: string) => {
      if (url.includes("history")) return Promise.resolve(EMPTY_HISTORY);
      return Promise.resolve(READY_REPORT);
    });
    mountPage(client);
    await waitFor(() =>
      screen.getByText("No readiness checks recorded yet.")
    );
  });

  // ── Test 13: HistoryCard with entries ───────────────────────────────────────
  it("13. HistoryCard shows 2 history entries when data provided", async () => {
    mock.mockImplementation((url: string) => {
      if (url.includes("history")) return Promise.resolve(HISTORY_RESPONSE);
      return Promise.resolve(READY_REPORT);
    });
    mountPage(client);
    await waitFor(() => {
      // Both history entries should render status badges
      const readyBadges = screen.getAllByTestId("status-READY");
      const warningBadges = screen.getAllByTestId("status-WARNING");
      expect(readyBadges.length).toBeGreaterThanOrEqual(1);
      expect(warningBadges.length).toBeGreaterThanOrEqual(1);
    });
  });

  // ── Test 14: Source errors banner ──────────────────────────────────────────
  it("14. source-errors banner shown when source_errors is non-empty", async () => {
    const reportWithErrors = {
      ...READY_REPORT,
      source_errors: { scan_meta: "ImportError: module not found" },
    };
    mock.mockImplementation((url: string) => {
      if (url.includes("history")) return Promise.resolve(EMPTY_HISTORY);
      return Promise.resolve(reportWithErrors);
    });
    mountPage(client);
    await waitFor(() => screen.getByTestId("source-errors"));
    expect(screen.getByTestId("source-errors").textContent).toMatch(/scan_meta/);
  });

  // ── Test 15: Run readiness check button ─────────────────────────────────────
  it("15. 'Run readiness check' button renders with data-testid='button-run-check'", async () => {
    mock.mockImplementation((url: string) => {
      if (url.includes("history")) return Promise.resolve(EMPTY_HISTORY);
      return Promise.resolve(READY_REPORT);
    });
    mountPage(client);
    await waitFor(() => screen.getByTestId("button-run-check"));
    expect(screen.getByTestId("button-run-check").textContent).toMatch(/Run readiness check/);
  });
});
