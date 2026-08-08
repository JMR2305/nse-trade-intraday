// @vitest-environment jsdom
/**
 * DeepWidgets.test.tsx — Phase 25.1 Mission Control deep-operations widgets.
 *
 * Covers StockWatchWidget (cards from recommendations + empty state) and
 * SystemHealth2Widget (ok/degraded/error traffic-light mapping).
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { StockWatchWidget, SystemHealth2Widget } from "../DeepWidgets";

vi.mock("@/lib/api", () => ({ apiJson: vi.fn() }));
import { apiJson } from "@/lib/api";
const mockApi = apiJson as ReturnType<typeof vi.fn>;

function freshClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}
function Wrap({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={freshClient()}>{children}</QueryClientProvider>;
}

// NOTE (Vitest 4 + React Query): no mockReset/mockClear in beforeEach — each
// test installs its own path-keyed implementation.
afterEach(() => cleanup());

// ── StockWatchWidget ──────────────────────────────────────────────────────────

describe("StockWatchWidget", () => {
  it("renders cards from mocked recommendations (filters errored rows, cross-refs positions)", async () => {
    mockApi.mockImplementation(async (path: string) => {
      if (path === "/live-data/recommendations") {
        return {
          success: true,
          recommendations: [
            { symbol: "TCS", final_action: "BUY", entry_price: 3500, calibrated_confidence: 82, all_gates_passed: true, strategy_name: "Momentum", volume_ratio: 1.4 },
            { symbol: "INFY", final_action: "WATCH", entry_price: 1500, calibrated_confidence: 60, all_gates_passed: false, strategy_name: "MeanRev" },
            // errored row → excluded
            { symbol: "BROKEN", error: "no data" },
          ],
        };
      }
      throw new Error(`unexpected path ${path}`);
    });

    const portfolio = {
      open_positions: [
        { symbol: "TCS", last_price: 3550, unrealised_pnl: 250, unrealised_pnl_pct: 1.42 },
      ],
    };
    render(<Wrap><StockWatchWidget portfolio={portfolio} /></Wrap>);

    await waitFor(() => expect(screen.getByTestId("mc-stock-card-tcs")).toBeTruthy());
    expect(screen.getByTestId("mc-stock-card-infy")).toBeTruthy();
    // errored row excluded
    expect(screen.queryByTestId("mc-stock-card-broken")).toBeNull();
    // "2 active" count in header
    expect(screen.getByText(/2 active/)).toBeTruthy();
    // TCS card uses the open-position live price (3,550) & PnL, not the recommendation entry
    const tcs = screen.getByTestId("mc-stock-card-tcs");
    expect(tcs.textContent).toMatch(/3,550/);
    expect(tcs.textContent).toMatch(/\+1\.42%/);
  });

  it("shows the empty state when no active stocks", async () => {
    mockApi.mockImplementation(async (path: string) => {
      if (path === "/live-data/recommendations") return { success: true, recommendations: [] };
      throw new Error(`unexpected path ${path}`);
    });
    render(<Wrap><StockWatchWidget /></Wrap>);
    await waitFor(() => expect(screen.getByText(/No active stocks/)).toBeTruthy());
  });
});

// ── SystemHealth2Widget ───────────────────────────────────────────────────────

// Base happy responses for every probe path the widget calls.
function healthyResponses(): Record<string, unknown> {
  return {
    "/observability/summary": { status: "OK", db_status: "OK", api_status: "OK" },
    "/live-data/health-v2": { quote_provider: { circuit_breaker: "CLOSED" }, market: { state: "OPEN" } },
    "/kite/status": { connected: true },
    "/pipeline/summary": { status: "OK" },
    "/backtest/runs": { runs: [] },
    "/learning-layer/learning/status": { status: "OK" },
    "/optimisation/summary": { status: "OK" },
  };
}

function renderHealth(overrides: Record<string, unknown> = {}, props: Record<string, unknown> = {}) {
  const responses = { ...healthyResponses(), ...overrides };
  mockApi.mockImplementation(async (path: string) => {
    if (path in responses) {
      const v = responses[path];
      if (v instanceof Error) throw v;
      return v;
    }
    throw new Error(`unexpected path ${path}`);
  });
  return render(<Wrap><SystemHealth2Widget {...props} /></Wrap>);
}

describe("SystemHealth2Widget", () => {
  it("maps a healthy Yahoo probe (breaker CLOSED) to the ok tone", async () => {
    renderHealth({}, { portfolio: { equity: 1 }, replay: { stages: [{ id: "x" }] } });
    await waitFor(() => expect(screen.getByTestId("mc-health2-yahoo")).toBeTruthy());
    const yahoo = screen.getByTestId("mc-health2-yahoo");
    expect(yahoo.className).toMatch(/emerald/); // ok tone
    expect(yahoo.textContent).toMatch(/breaker CLOSED/);
  });

  it("maps a degraded Zerodha (not connected, paper) to the amber tone", async () => {
    renderHealth(
      { "/kite/status": { connected: false, credentials_present: false } },
      { portfolio: { equity: 1 }, replay: { stages: [] } },
    );
    await waitFor(() => expect(screen.getByTestId("mc-health2-zerodha")).toBeTruthy());
    const z = screen.getByTestId("mc-health2-zerodha");
    expect(z.className).toMatch(/amber/); // degraded tone
    expect(z.textContent).toMatch(/paper/);
  });

  it("maps a failing Yahoo breaker (OPEN) to the error tone", async () => {
    renderHealth(
      { "/live-data/health-v2": { quote_provider: { circuit_breaker: "OPEN" }, market: { state: "OPEN" } } },
      { portfolio: { equity: 1 }, replay: { stages: [] } },
    );
    await waitFor(() => expect(screen.getByTestId("mc-health2-yahoo")).toBeTruthy());
    const yahoo = screen.getByTestId("mc-health2-yahoo");
    expect(yahoo.className).toMatch(/red/); // error tone
    expect(yahoo.textContent).toMatch(/breaker OPEN/);
  });

  it("surfaces an errored engine probe as the error tone (backtest engine red)", async () => {
    // The Widget chrome is driven by obsQ, so obs stays healthy here; a failing
    // engine probe (backtest/runs) marks only its own cell error. Assert the
    // error UI (per the RQ rule the probe query resolves its rejection first).
    renderHealth(
      { "/backtest/runs": new Error("backtest offline") },
      { portfolio: { equity: 1 }, replay: { stages: [] } },
    );
    await waitFor(() => {
      const bt = screen.getByTestId("mc-health2-backtest");
      expect(bt.className).toMatch(/red/);
    });
  });
});
