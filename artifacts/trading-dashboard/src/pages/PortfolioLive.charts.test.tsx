// @vitest-environment jsdom
/**
 * Task-24 — Equity curve & Daily P&L history charts
 *
 * Mounts the real <PortfolioLive> with a mocked apiJson and confirms that:
 *  1. The equity-curve section consumes `pnl_history` from the snapshot
 *     payload (multi-point history renders the chart, not the empty state).
 *  2. The daily P&L section consumes `daily_pnl` covering MULTIPLE sessions
 *     (the session count reflects every daily bucket in the payload).
 *  3. Missing / short history renders labelled empty states instead of
 *     crashing the page.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// jsdom has no ResizeObserver; recharts' ResponsiveContainer requires one.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(globalThis as unknown as { ResizeObserver: typeof ResizeObserverStub }).ResizeObserver =
  (globalThis as unknown as { ResizeObserver?: typeof ResizeObserverStub }).ResizeObserver ??
  ResizeObserverStub;

vi.mock("@/lib/api", () => ({
  API_BASE: "",
  apiJson: vi.fn(),
}));

vi.mock("@/components/DataFreshnessBar", () => ({
  default: () => null,
}));

import { apiJson } from "@/lib/api";
import PortfolioLive from "./PortfolioLive";

const BASE_SNAPSHOT = {
  status: "READY",
  paper_mode: true,
  snapshotted_at: new Date().toISOString(),
  equity: 50_000,
  cash: 50_000,
  buying_power: 50_000,
  invested_value: 0,
  initial_capital: 50_000,
  unrealised_pnl: 0,
  realised_pnl_today: 0,
  total_pnl: 0,
  peak_equity: 50_000,
  drawdown_amount: 0,
  drawdown_pct: 0,
  open_positions: [],
  open_position_count: 0,
  closed_positions_today: 0,
  limits_from_config: true,
  sector_exposures: [],
  exposure_warnings: [],
};

const HEALTH = {
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

const CONFIG = {
  loaded: true,
  limits_from_config: true,
  config: {},
  fetched_at: new Date().toISOString(),
  overrides: {},
  overridden_fields: [],
};

function mockApi(snapshot: Record<string, unknown>) {
  (apiJson as ReturnType<typeof vi.fn>).mockImplementation((path: string) => {
    if (path.includes("/portfolio/snapshot")) return Promise.resolve(snapshot);
    if (path.includes("/portfolio/health")) return Promise.resolve(HEALTH);
    if (path.includes("/portfolio/config")) return Promise.resolve(CONFIG);
    return Promise.resolve({});
  });
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, refetchOnWindowFocus: false, refetchOnReconnect: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <PortfolioLive />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  cleanup();
});

describe("PortfolioLive — equity curve & daily P&L charts", () => {
  it("renders both chart sections and consumes multi-session snapshot history", async () => {
    mockApi({
      ...BASE_SNAPSHOT,
      pnl_history: [
        { timestamp: "2026-08-06T10:00:00", value: 50_000 },
        { timestamp: "2026-08-07T10:00:00", value: 50_400 },
        { timestamp: "2026-08-09T10:00:00", value: 50_150 },
      ],
      daily_pnl: [
        { date: "2026-08-06", pnl: 200, trades: 1 },
        { date: "2026-08-07", pnl: -40, trades: 2 },
        { date: "2026-08-09", pnl: 150, trades: 1 },
      ],
    });
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("section-equity-curve")).toBeTruthy();
      expect(screen.getByTestId("section-daily-pnl")).toBeTruthy();
    });

    // Equity curve consumed all 3 pnl_history points (not the empty state)
    expect(screen.getByText("3 snapshots")).toBeTruthy();
    expect(screen.queryByTestId("empty-equity-curve")).toBeNull();
    expect(screen.getByTestId("chart-equity-curve")).toBeTruthy();

    // Daily P&L covers MULTIPLE sessions from the payload
    expect(screen.getByText("3 sessions")).toBeTruthy();
    expect(screen.queryByTestId("empty-daily-pnl")).toBeNull();
    expect(screen.getByTestId("chart-daily-pnl")).toBeTruthy();
  });

  it("shows labelled empty states when history fields are missing", async () => {
    mockApi(BASE_SNAPSHOT); // no pnl_history / daily_pnl at all
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("section-equity-curve")).toBeTruthy();
    });

    expect(screen.getByTestId("empty-equity-curve")).toBeTruthy();
    expect(screen.getByTestId("empty-daily-pnl")).toBeTruthy();
  });

  it("treats a single equity point as not-enough-data instead of crashing", async () => {
    mockApi({
      ...BASE_SNAPSHOT,
      pnl_history: [{ timestamp: "2026-08-09T10:00:00", value: 50_000 }],
      daily_pnl: [],
    });
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("empty-equity-curve")).toBeTruthy();
    });
    expect(screen.getByText("1 snapshot")).toBeTruthy();
  });
});
