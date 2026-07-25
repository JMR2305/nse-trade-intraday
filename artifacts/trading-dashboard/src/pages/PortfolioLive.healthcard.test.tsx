// @vitest-environment jsdom
/**
 * Task-80 — Component-level health-card live-update test
 *
 * Mounts the real <PortfolioLive> component inside a QueryClientProvider,
 * controls the health-endpoint response via a mocked apiJson, and uses
 * fake timers to advance by REFRESH_INTERVAL — confirming that the status
 * badge switches from HEALTHY to DEGRADED without a page reload.
 *
 * Why this matters: the pure source-analysis tests in PortfolioLive.health.test.ts
 * cannot catch a React Query upgrade that silently renames `refetchInterval`,
 * changes caching semantics, or moves the polling hook.  This test mounts the
 * real component and exercises the actual useQuery / refetchInterval integration
 * end-to-end against jsdom.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ── Module mocks ──────────────────────────────────────────────────────────────

// Intercept all API calls so no real HTTP requests are made
vi.mock("@/lib/api", () => ({
  API_BASE: "",
  apiJson: vi.fn(),
}));

// DataFreshnessBar makes its own network calls; stub it to keep focus here
vi.mock("@/components/DataFreshnessBar", () => ({
  default: () => null,
}));

// Imports must come after vi.mock declarations so hoisting works correctly
import { apiJson } from "@/lib/api";
import PortfolioLive from "./PortfolioLive";

// ── Constants ─────────────────────────────────────────────────────────────────

/** Must match the `REFRESH_INTERVAL` constant in PortfolioLive.tsx */
const REFRESH_INTERVAL = 15_000;

// ── Fixture data ──────────────────────────────────────────────────────────────

const HEALTHY_HEALTH = {
  status: "HEALTHY",
  initialized: true,
  paper_mode: true,
  auto_paper_enabled: false,
  liveness: true,
  readiness: true,
  degraded: false,
  failure_reason: null,
  unresolved_discrepancies: 0,
  limits_from_config: true,
  degraded_reasons: [],
  checked_at: new Date().toISOString(),
};

const DEGRADED_HEALTH = {
  status: "DEGRADED",
  initialized: true,
  paper_mode: true,
  auto_paper_enabled: false,
  liveness: true,
  readiness: true,
  degraded: true,
  failure_reason:
    "Exposure limits using hardcoded defaults — check PortfolioConfig import",
  unresolved_discrepancies: 0,
  limits_from_config: false,
  degraded_reasons: [
    "Exposure limits using hardcoded defaults — check PortfolioConfig import",
  ],
  checked_at: new Date().toISOString(),
};

const MINIMAL_SNAPSHOT = {
  status: "READY",
  paper_mode: true,
  snapshotted_at: new Date().toISOString(),
  equity: 100_000,
  cash: 100_000,
  buying_power: 100_000,
  invested_value: 0,
  initial_capital: 100_000,
  unrealised_pnl: 0,
  realised_pnl_today: 0,
  total_pnl: 0,
  peak_equity: 100_000,
  drawdown_amount: 0,
  drawdown_pct: 0,
  open_positions: [],
  open_position_count: 0,
  closed_positions_today: 0,
  limits_from_config: true,
  sector_exposures: [],
  exposure_warnings: [],
};

const MINIMAL_CONFIG = {
  loaded: true,
  limits_from_config: true,
  config: {},
  fetched_at: new Date().toISOString(),
  overrides: {},
  overridden_fields: [],
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
        // Keep window/network event refetching off — jsdom's focus model
        // differs from a real browser; we drive time explicitly.
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
      },
    },
  });
}

function Wrapper({ client }: { client: QueryClient }) {
  return (
    <QueryClientProvider client={client}>
      <PortfolioLive />
    </QueryClientProvider>
  );
}

/**
 * Flush the mount-triggered fetches by advancing the fake clock just
 * 50 ms — well below the 15 s refetch boundary.
 */
async function flushMount() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(50);
  });
}

/**
 * Advance the fake clock by exactly one REFRESH_INTERVAL plus a small
 * margin so React Query's internal setInterval fires and the resulting
 * fetch promise resolves before we read the DOM.
 */
async function advanceOnePoll() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(REFRESH_INTERVAL + 50);
  });
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("PortfolioLive health card — HEALTHY → DEGRADED live update", () => {
  let queryClient: QueryClient;
  const mockApiJson = vi.mocked(apiJson);

  beforeEach(() => {
    // Fake timers intercept the setInterval that React Query uses for
    // refetchInterval — advancing time triggers real polling code paths.
    vi.useFakeTimers();

    queryClient = makeQueryClient();

    // Each test gets a fresh counter so poll #1 → HEALTHY, poll #2+ → DEGRADED.
    let healthCallCount = 0;

    mockApiJson.mockImplementation((path: string) => {
      if (path === "/portfolio/health") {
        healthCallCount += 1;
        return Promise.resolve(
          healthCallCount === 1 ? HEALTHY_HEALTH : DEGRADED_HEALTH,
        );
      }
      if (path === "/portfolio/snapshot") {
        return Promise.resolve(MINIMAL_SNAPSHOT);
      }
      if (path === "/portfolio/config") {
        return Promise.resolve(MINIMAL_CONFIG);
      }
      return Promise.resolve({});
    });
  });

  afterEach(async () => {
    // Unmount before restoring real timers to silence act() warnings
    await act(async () => {
      cleanup();
    });
    queryClient.clear();
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  // ── 1. Initial render ────────────────────────────────────────────────────

  it("badge shows HEALTHY on initial render", async () => {
    render(<Wrapper client={queryClient} />);

    await flushMount();

    const badge = screen.getByTestId("badge-portfolio-status");
    expect(badge.textContent).toContain("HEALTHY");
  });

  // ── 2. Core assertion: badge updates via React Query polling ─────────────

  it("badge switches to DEGRADED after REFRESH_INTERVAL elapses (timer-driven refetch)", async () => {
    render(<Wrapper client={queryClient} />);

    // ① Initial mount fetch resolves → HEALTHY
    await flushMount();
    expect(screen.getByTestId("badge-portfolio-status").textContent).toContain(
      "HEALTHY",
    );

    // ② Advance the fake clock past the refetchInterval boundary.
    //   React Query's internal setInterval fires, the mock returns DEGRADED,
    //   and the component re-renders — no page reload needed.
    await advanceOnePoll();

    // ③ Badge must reflect the new server state
    expect(screen.getByTestId("badge-portfolio-status").textContent).toContain(
      "DEGRADED",
    );
  });

  // ── 3. Alert banner appears on DEGRADED ──────────────────────────────────

  it("alert banner is absent while HEALTHY and appears once DEGRADED response is received", async () => {
    render(<Wrapper client={queryClient} />);

    await flushMount();
    // No alert while HEALTHY
    expect(screen.queryByTestId("banner-portfolio-alert")).toBeNull();

    await advanceOnePoll();
    // Banner is present after DEGRADED poll
    expect(screen.getByTestId("banner-portfolio-alert")).toBeTruthy();
  });

  // ── 4. Polling continues after transition ────────────────────────────────

  it("badge stays on DEGRADED after a second poll cycle following the transition", async () => {
    render(<Wrapper client={queryClient} />);

    await flushMount();

    // Two poll cycles: first transitions to DEGRADED, second keeps it DEGRADED
    await advanceOnePoll();
    await advanceOnePoll();

    expect(screen.getByTestId("badge-portfolio-status").textContent).toContain(
      "DEGRADED",
    );
  });

  // ── 5. staleTime invariant ────────────────────────────────────────────────

  it("staleTime is less than REFRESH_INTERVAL so cached data never blocks the next poll", () => {
    // If staleTime >= refetchInterval, React Query serves the old HEALTHY
    // response from cache when the timer fires and the badge never updates.
    // The QueryClient default must not accidentally override the per-query setting.
    const opts = queryClient.getDefaultOptions();
    const defaultStale = opts.queries?.staleTime ?? 0;
    expect(defaultStale).toBeLessThanOrEqual(REFRESH_INTERVAL / 2);
  });
});
