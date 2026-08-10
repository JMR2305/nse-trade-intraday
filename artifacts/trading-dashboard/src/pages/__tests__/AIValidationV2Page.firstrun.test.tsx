// @vitest-environment jsdom
/**
 * First-run / empty-state UX tests for AI Validation Centre V2.
 *
 * With a fresh empty database (no backtest runs) the page must:
 *  - show the first-run banner + "Run First Validation Backtest" CTA
 *  - auto-open the Backtest Runner tab
 *  - disable all run-dependent tabs
 *  - show "No runs yet" in the dataset status (no fabricated data)
 * Once runs exist:
 *  - run-dependent tabs are enabled
 *  - the dataset status shows the last run timestamp + sample size
 *  - the latest run is auto-selected for run-dependent tabs
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

// jsdom lacks ResizeObserver (needed by chart components on some tabs)
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(globalThis as any).ResizeObserver = (globalThis as any).ResizeObserver ?? ResizeObserverStub;

const mockApiJson = vi.fn();
vi.mock("@/lib/api", () => ({ apiJson: (...args: unknown[]) => mockApiJson(...args) }));

import AIValidationV2Page from "../AIValidationV2Page";

const EMPTY_RUNS = { runs: [], count: 0, label: "PAPER / RESEARCH ONLY" };
const EMPTY_PERF = { performance: {}, period: "monthly", note: "No backtest trades found." };
const EMPTY_MISSED = { missed: [], count: 0 };

const RUN_LIST = {
  runs: [{
    run_id: "run-latest", status: "COMPLETED", total_decisions: 42,
    total_trades: 9, start_date: "2026-02-01", end_date: "2026-08-01",
    interval: "1d", created_at: "2026-08-01T10:00:00Z", completed_at: "2026-08-01T10:04:00Z",
  }, {
    run_id: "run-older", status: "COMPLETED", total_decisions: 30,
    total_trades: 6, start_date: "2026-01-01", end_date: "2026-06-01",
    interval: "1d", created_at: "2026-06-01T10:00:00Z", completed_at: "2026-06-01T10:03:00Z",
  }],
  count: 2, label: "PAPER / RESEARCH ONLY",
};

const RUN_DETAIL = {
  success: true, run_id: "run-latest", status: "COMPLETED", config: {},
  symbols: ["RELIANCE"], strategies: ["trend_rider"], interval: "1d",
  total_decisions: 42, total_trades: 9, stats: null,
  recommendation_distribution: {}, decisions_sample: [],
  trades: [{
    trade_id: 1, symbol: "RELIANCE", strategy: "trend_rider",
    entry_date: "2026-07-01", entry_price: 2900, exit_date: "2026-07-04",
    exit_price: 2960, quantity: 10, pnl_amount: 600, pnl_pct: 2.07,
    holding_days: 3, exit_reason: "TARGET", result: "WIN",
    stop_price: 2840, target_price: 2960, confidence: 71,
    mfe_pct: 2.5, mad_pct: -0.4, agent_scores: {},
  }],
  missed_opportunities: [],
};

function mockEmpty() {
  mockApiJson.mockImplementation((path: string) => {
    if (path === "validation-v2/backtest") return Promise.resolve(EMPTY_RUNS);
    if ((path as string).startsWith("validation-v2/performance")) return Promise.resolve(EMPTY_PERF);
    if (path === "validation-v2/missed-opportunities") return Promise.resolve(EMPTY_MISSED);
    return Promise.resolve({});
  });
}

function mockWithRuns() {
  mockApiJson.mockImplementation((path: string) => {
    if (path === "validation-v2/backtest") return Promise.resolve(RUN_LIST);
    if ((path as string).includes("backtest/run-latest")) return Promise.resolve(RUN_DETAIL);
    if ((path as string).startsWith("validation-v2/performance")) return Promise.resolve(EMPTY_PERF);
    if (path === "validation-v2/missed-opportunities") return Promise.resolve(EMPTY_MISSED);
    return Promise.resolve({});
  });
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AIValidationV2Page />
    </QueryClientProvider>
  );
}

describe("AIValidationV2Page — first-run empty state", () => {
  beforeEach(() => { mockApiJson.mockReset(); });
  afterEach(() => { vi.clearAllMocks(); cleanup(); });

  it("renders the first-run banner and CTA when no runs exist", async () => {
    mockEmpty();
    renderPage();
    expect(await screen.findByTestId("v2-first-run-banner")).toBeTruthy();
    expect(screen.getByTestId("v2-first-run-cta")).toBeTruthy();
    expect(screen.getByText(/No validation backtest run exists yet/i)).toBeTruthy();
  });

  it("auto-opens the Backtest Runner tab when no runs exist", async () => {
    mockEmpty();
    renderPage();
    await screen.findByTestId("v2-first-run-banner");
    // The big first-run submit button only renders inside the Backtest Runner tab
    await waitFor(() => {
      const btns = screen.getAllByRole("button", { name: /Run First Validation Backtest/i });
      // banner CTA + the runner's submit button
      expect(btns.length).toBeGreaterThanOrEqual(2);
    });
  });

  it("disables all run-dependent tabs when no runs exist", async () => {
    mockEmpty();
    renderPage();
    await screen.findByTestId("v2-first-run-banner");
    for (const label of ["Trade Simulation", "Missed Opps", "AI vs Market", "Param Optimizer",
                         "Explainability", "Session Playback", "Performance", "Model Comparison"]) {
      const tab = screen.getByRole("button", { name: new RegExp(`^${label}$`, "i") });
      expect((tab as HTMLButtonElement).disabled).toBe(true);
    }
    // Overview and Backtest Runner stay enabled
    expect((screen.getByRole("button", { name: /^Overview$/i }) as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByRole("button", { name: /^Backtest Runner$/i }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("shows 'No runs yet' in the dataset status and no fabricated data", async () => {
    mockEmpty();
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("v2-dataset-status").textContent).toContain("No runs yet");
    });
    // No fabricated stats anywhere: nothing should render a win-rate percentage
    expect(screen.queryByText(/\d+\.\d%/)).toBeNull();
  });

  it("enables run-dependent tabs and shows last-run status once runs exist", async () => {
    mockWithRuns();
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("v2-dataset-status").textContent).toContain("Last run:");
      expect(screen.getByTestId("v2-dataset-status").textContent).toContain("9 trades / 42 decisions");
    });
    expect(screen.queryByTestId("v2-first-run-banner")).toBeNull();
    const simTab = screen.getByRole("button", { name: /^Trade Simulation$/i });
    expect((simTab as HTMLButtonElement).disabled).toBe(false);
  });

  it("clears the banner and unlocks tabs immediately when the first backtest completes", async () => {
    // Start with an empty DB; POST kicks off a run whose first detail poll is COMPLETED.
    let completed = false;
    mockApiJson.mockImplementation((path: string, opts?: RequestInit) => {
      if (opts?.method === "POST" && String(path).includes("backtest/run")) {
        return Promise.resolve({ run_id: "run-latest" });
      }
      if (path === "validation-v2/backtest") {
        return Promise.resolve(completed ? RUN_LIST : EMPTY_RUNS);
      }
      if (String(path).includes("backtest/run-latest")) {
        completed = true;
        return Promise.resolve(RUN_DETAIL);
      }
      if (String(path).startsWith("validation-v2/performance")) return Promise.resolve(EMPTY_PERF);
      if (path === "validation-v2/missed-opportunities") return Promise.resolve(EMPTY_MISSED);
      return Promise.resolve({});
    });
    renderPage();
    await screen.findByTestId("v2-first-run-banner");
    // Backtest Runner auto-opened; click the runner's submit button (not the banner CTA)
    const submitBtns = await screen.findAllByRole("button", { name: /Run First Validation Backtest/i });
    await userEvent.click(submitBtns[submitBtns.length - 1]);
    // On completion the banner must clear and run-dependent tabs unlock at once
    await waitFor(() => {
      expect(screen.queryByTestId("v2-first-run-banner")).toBeNull();
    }, { timeout: 10_000 });
    const simTab = screen.getByRole("button", { name: /^Trade Simulation$/i });
    expect((simTab as HTMLButtonElement).disabled).toBe(false);
  });

  it("auto-selects the latest run for run-dependent tabs", async () => {
    mockWithRuns();
    renderPage();
    await screen.findByText(/Last run:/);
    await userEvent.click(screen.getByRole("button", { name: /^Trade Simulation$/i }));
    // Latest run (run-latest) detail is fetched and its trade renders
    await waitFor(() => {
      expect(mockApiJson.mock.calls.some(c => String(c[0]).includes("backtest/run-latest"))).toBe(true);
    });
    expect(await screen.findByText("RELIANCE")).toBeTruthy();
  });
});
