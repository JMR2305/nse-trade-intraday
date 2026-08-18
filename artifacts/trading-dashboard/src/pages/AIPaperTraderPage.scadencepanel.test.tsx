// @vitest-environment jsdom
/**
 * AIPaperTraderPage.scadencepanel.test.tsx
 *
 * Rendered component tests for <SCadencePanel>.
 *
 * Why these complement the pure-logic tests in
 * AIPaperTraderPage.cadencebadge.test.tsx:
 *   - The logic tests confirm cadenceBadgeState() returns the right value.
 *   - These tests confirm the badge text actually reaches the DOM — a
 *     broken className gate, a missing conditional render, or a React Query
 *     wiring change would silently pass the logic tests but fail here.
 *
 * Scenarios covered:
 *   1. CLOSED market state  + poor coverage → "Market closed" badge visible
 *   2. OPEN market state    + poor coverage → "Review" badge visible
 *   3. OPEN market state    + good coverage → "On Track" badge visible
 *   4. POST_CLOSE state     + good coverage → "Market closed" (not "On Track")
 *   5. UNKNOWN health state + poor coverage → "Review" (not "Market closed")
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ── Module mocks ──────────────────────────────────────────────────────────────

// vi.mock is hoisted before imports — declare before any import that uses the
// mocked module.
vi.mock("@/lib/api", () => ({
  API_BASE: "",
  apiJson: vi.fn(),
}));

// Imports AFTER vi.mock so the mock is in place when the module is first loaded.
import { apiJson } from "@/lib/api";
import { SCadencePanel } from "./AIPaperTraderPage";

// ── Fixture factories ─────────────────────────────────────────────────────────

/**
 * Minimal /live-data/health-v2 payload.
 * Only `market.state` is used by SCadencePanel.
 */
function healthV2(state: string) {
  return {
    market: { state, is_open: state === "OPEN" },
    snapshot_ts: "2026-08-18T10:00:00.000Z",
    scan_id: "scan-001",
  };
}

/**
 * Minimal /phase20/cadence-stats payload.
 * coverageOk = completed/expected >= 70%; gapOk = avgGap <= cfgInterval * 1.3.
 */
function cadenceStats(opts: { completed?: number; expected?: number; avgGap?: number } = {}) {
  const { completed = 0, expected = 10, avgGap = 10 } = opts;
  return {
    completed_scans_today: completed,
    session_scans_today: completed,
    expected_scans_today: expected,
    skipped_scans_today: 0,
    avg_gap_minutes: avgGap,
    configured_interval_minutes: 5,
    p50_gap_minutes: avgGap,
    p95_gap_minutes: avgGap * 1.5,
    avg_duration_seconds: 30,
    last_scan_duration_seconds: 25,
    next_due: null,
    scheduler_status: "FRESH",
    market_minutes: 375,
  };
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Wire apiJson mock so that:
 *   - "/live-data/health-v2"    → healthPayload
 *   - "/phase20/cadence-stats"  → cadencePayload
 */
function wireApi(
  healthPayload: ReturnType<typeof healthV2>,
  cadencePayload: ReturnType<typeof cadenceStats>,
) {
  vi.mocked(apiJson).mockImplementation(async (url: string) => {
    if (url === "/live-data/health-v2") return healthPayload;
    if (url === "/phase20/cadence-stats") return cadencePayload;
    return {};
  });
}

function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
        // Disable window/network-focus refetches — jsdom focus model differs.
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
      },
    },
  });
}

function renderPanel(qc: QueryClient) {
  return render(
    <QueryClientProvider client={qc}>
      <SCadencePanel />
    </QueryClientProvider>,
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("SCadencePanel — badge renders in the DOM", () => {
  let qc: QueryClient;

  beforeEach(() => {
    qc = makeQueryClient();
  });

  afterEach(async () => {
    cleanup();
    // Drain any pending React Query tasks before the next test.
    await act(async () => {});
    qc.clear();
    vi.clearAllMocks();
  });

  // ── 1. CLOSED + poor coverage → "Market closed" ──────────────────────────

  it("shows 'Market closed' badge when health-v2 reports CLOSED, even with poor coverage", async () => {
    wireApi(
      healthV2("CLOSED"),
      cadenceStats({ completed: 0, expected: 10 }), // poor coverage: pct=0%
    );

    renderPanel(qc);

    // Wait for both queries to resolve and the badge to appear.
    const badge = await screen.findByText("Market closed", {}, { timeout: 3000 });
    expect(badge).toBeTruthy();

    // "Review" must NOT be shown — market is closed, not degraded mid-session.
    expect(screen.queryByText("Review")).toBeNull();
  });

  // ── 2. OPEN + poor coverage → "Review" ───────────────────────────────────

  it("shows 'Review' badge when market is OPEN but coverage is poor", async () => {
    wireApi(
      healthV2("OPEN"),
      cadenceStats({ completed: 1, expected: 10 }), // pct=10%, coverageOk=false
    );

    renderPanel(qc);

    const badge = await screen.findByText("Review", {}, { timeout: 3000 });
    expect(badge).toBeTruthy();

    // "Market closed" must NOT appear — market is open.
    expect(screen.queryByText("Market closed")).toBeNull();
  });

  // ── 3. OPEN + good coverage → "On Track" ─────────────────────────────────

  it("shows 'On Track' badge when market is OPEN with good coverage and gaps", async () => {
    wireApi(
      healthV2("OPEN"),
      cadenceStats({ completed: 8, expected: 10, avgGap: 5 }), // pct=80%, gapOk=true
    );

    renderPanel(qc);

    const badge = await screen.findByText("On Track", {}, { timeout: 3000 });
    expect(badge).toBeTruthy();

    expect(screen.queryByText("Market closed")).toBeNull();
    expect(screen.queryByText("Review")).toBeNull();
  });

  // ── 4. POST_CLOSE + good coverage → "Market closed" ──────────────────────

  it("shows 'Market closed' for POST_CLOSE regardless of good coverage", async () => {
    wireApi(
      healthV2("POST_CLOSE"),
      cadenceStats({ completed: 10, expected: 10, avgGap: 5 }), // perfect coverage
    );

    renderPanel(qc);

    const badge = await screen.findByText("Market closed", {}, { timeout: 3000 });
    expect(badge).toBeTruthy();

    // Good coverage must not promote POST_CLOSE to "On Track".
    expect(screen.queryByText("On Track")).toBeNull();
  });

  // ── 5. UNKNOWN state + poor coverage → "Review", not "Market closed" ─────

  it("shows 'Review' (not 'Market closed') when health-v2 state is UNKNOWN and coverage is poor", async () => {
    wireApi(
      healthV2("UNKNOWN"),
      cadenceStats({ completed: 0, expected: 10 }),
    );

    renderPanel(qc);

    const badge = await screen.findByText("Review", {}, { timeout: 3000 });
    expect(badge).toBeTruthy();

    // An unavailable/stale health source must never be presented as a
    // confirmed closure — operators would miss genuine in-session issues.
    expect(screen.queryByText("Market closed")).toBeNull();
  });
});
