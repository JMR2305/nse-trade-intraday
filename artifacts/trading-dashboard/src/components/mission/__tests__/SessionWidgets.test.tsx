// @vitest-environment jsdom
/**
 * SessionWidgets.test.tsx — Phase 25.1 Mission Control live-operations widgets.
 *
 * Covers MarketSessionWidget (weekend + open-phase), ThroughputWidget (replay
 * stage mapping + today-only IST ledger counting), and LivePerformanceWidget
 * (win-rate / best-strategy from today's closed rows; "—" when none).
 *
 * IST handling: the widgets derive IST via Intl (Asia/Kolkata), reading the
 * wall clock through `new Date()`. Tests pin the clock with fake timers +
 * setSystemTime to a UTC instant that maps to the desired IST moment.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor, cleanup, renderHook, waitFor as wf } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import {
  MarketSessionWidget, ThroughputWidget, LivePerformanceWidget, useLedgerToday,
  type LedgerRow,
} from "../SessionWidgets";

vi.mock("@/lib/api", () => ({ apiJson: vi.fn() }));
import { apiJson } from "@/lib/api";
const mockApi = apiJson as ReturnType<typeof vi.fn>;

// Fresh QueryClient per render with retry:false (per Vitest4 + RQ rule).
function freshClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}
function Wrap({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={freshClient()}>{children}</QueryClientProvider>;
}

// NOTE (Vitest 4 + React Query): never mockReset/mockClear in beforeEach — that
// makes RQ's handled rejections surface as unhandled. Each test installs its
// own apiJson implementation instead.
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

// IST reference instants (UTC → +5:30 IST):
//   Sat 2024-01-06 12:00 IST = 2024-01-06T06:30:00Z  → weekend
//   Wed 2024-01-10 12:00 IST = 2024-01-10T06:30:00Z  → continuous session (open)
const IST_SAT_NOON = new Date("2024-01-06T06:30:00Z");
const IST_WED_NOON = new Date("2024-01-10T06:30:00Z");

describe("MarketSessionWidget", () => {
  it("renders the weekend closed state on a Saturday (IST)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(IST_SAT_NOON);
    // clock shim query resolves so the Widget chrome renders children
    mockApi.mockResolvedValue({ ok: true });

    render(<Wrap><MarketSessionWidget /></Wrap>);

    await waitFor(() => expect(screen.getByTestId("mc-session-weekend")).toBeTruthy());
    expect(screen.getByText(/Market closed — weekend/)).toBeTruthy();
    // header badge shows WEEKEND
    expect(screen.getByText(/NSE WEEKEND/)).toBeTruthy();
    // phase strip is NOT rendered on the weekend branch
    expect(screen.queryByTestId("mc-session-phases")).toBeNull();
  });

  it("renders the open continuous phase mid-session on a weekday (IST)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(IST_WED_NOON);
    mockApi.mockResolvedValue({ ok: true });

    render(<Wrap><MarketSessionWidget /></Wrap>);

    await waitFor(() => expect(screen.getByTestId("mc-session-phases")).toBeTruthy());
    // weekend branch absent
    expect(screen.queryByTestId("mc-session-weekend")).toBeNull();
    // continuous phase highlighted (active)
    const cont = screen.getByTestId("mc-session-phase-continuous");
    expect(cont.className).toMatch(/border-teal-500/);
    // header badge reflects the active phase label
    expect(screen.getByText(/NSE CONTINUOUS/)).toBeTruthy();
    // 12:00 is inside 09:00–16:00 → progress bar advanced beyond 0
    const bar = screen.getByTestId("mc-session-progress");
    const width = parseFloat(bar.style.width);
    expect(width).toBeGreaterThan(0);
    expect(width).toBeLessThan(100);
  });

  it("authoritative market prop overrides the computed label", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(IST_WED_NOON);
    mockApi.mockResolvedValue({ ok: true });

    render(<Wrap><MarketSessionWidget market={{ is_open: true, state: "SPECIAL_SESSION" }} /></Wrap>);
    await waitFor(() => expect(screen.getByText(/NSE SPECIAL_SESSION/)).toBeTruthy());
  });
});

// ── Shared ledger query hook harness ─────────────────────────────────────────

function useLedgerHarness() {
  return useLedgerToday();
}
function renderLedgerHook() {
  const qc = freshClient();
  return renderHook(() => useLedgerHarness(), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    ),
  });
}

describe("useLedgerToday", () => {
  it("fetches /phase20/ledger and exposes ledger rows", async () => {
    const rows: LedgerRow[] = [
      { trade_id: "t1", symbol: "TCS", side: "BUY", status: "OPEN" },
    ];
    mockApi.mockResolvedValue({ success: true, ledger: rows });
    const { result } = renderLedgerHook();
    await wf(() => expect(result.current.data?.ledger?.length).toBe(1));
    expect(mockApi).toHaveBeenCalledWith("/phase20/ledger?limit=500", undefined, 30_000);
  });
});

// ── ThroughputWidget ──────────────────────────────────────────────────────────

const replaySnapshot = {
  stages: [
    { id: "supervisor", label: "Universe", stocks_out: 200 },
    { id: "market_data", label: "Scanned", stocks_out: 150 },
    { id: "research", label: "Analysed", stocks_out: 60 },
    { id: "strategy", label: "Strategy", stocks_out: 20 },
    // 3 evaluated (2 approved + 1 rejected), 17 unevaluated pass-through:
    // stocks_out = 19 but only approved_count = 2 may show as "approved".
    { id: "portfolio_precheck", label: "Portfolio Pre-Check", stocks_in: 20, stocks_out: 19, rejected: 1, approved_count: 2 },
    { id: "risk", label: "Risk", stocks_out: 8, rejected: 4 },
  ],
  decisions: [
    { symbol: "A", final_action: "BUY" },
    { symbol: "B", final_action: "buy" },
    { symbol: "C", final_action: "SELL" },
    { symbol: "D", final_action: "WATCH" },
    { symbol: "E", final_action: "HOLD" },
  ],
};

// Wraps ThroughputWidget with the shared ledger hook so `ledger` prop is real.
function ThroughputHarness({ replay }: { replay?: typeof replaySnapshot }) {
  const ledger = useLedgerToday();
  return <ThroughputWidget replay={replay} ledger={ledger} />;
}

describe("ThroughputWidget", () => {
  it("maps replay stages to the funnel and counts today-IST ledger rows only", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(IST_WED_NOON); // today IST = 2024-01-10

    const rows: LedgerRow[] = [
      // today (filled + open)
      { trade_id: "t1", symbol: "TCS", side: "BUY", status: "OPEN", fill_ts: "2024-01-10T05:00:00Z" },
      // today (filled + closed → counts as filled, closed, completed)
      { trade_id: "t2", symbol: "INFY", side: "SELL", status: "CLOSED", fill_ts: "2024-01-10T04:00:00Z" },
      // today (cancelled)
      { trade_id: "t3", symbol: "WIPRO", side: "BUY", status: "CANCELLED", created_at: "2024-01-10T03:00:00Z" },
      // YESTERDAY IST — must be excluded (2024-01-09 IST)
      { trade_id: "t4", symbol: "SBIN", side: "BUY", status: "OPEN", fill_ts: "2024-01-09T05:00:00Z" },
    ];
    mockApi.mockResolvedValue({ success: true, ledger: rows });

    render(<Wrap><ThroughputHarness replay={replaySnapshot} /></Wrap>);

    // funnel stage values from replay stocks_out
    await waitFor(() => expect(screen.getByTestId("mc-throughput-funnel")).toBeTruthy());
    const funnel = screen.getByTestId("mc-throughput-funnel");
    expect(funnel.textContent).toContain("200"); // supervisor
    expect(funnel.textContent).toContain("8");   // risk stocks_out
    expect(funnel.textContent).toContain("4");   // risk rejected

    // Pre-Check Approved must show ONLY event-derived approvals (2), never
    // the pass-through stocks_out (19) that includes unevaluated symbols.
    expect(funnel.textContent).toContain("Pre-Check Approved");
    expect(funnel.textContent).not.toContain("19");

    // signals mapped from decisions (BUY counts case-insensitively → 2)
    const signals = screen.getByTestId("mc-throughput-signals");
    expect(signals.textContent).toContain("2"); // BUY

    // orders: 3 rows today (t1,t2,t3); t4 excluded
    const orders = screen.getByTestId("mc-throughput-orders");
    // Submitted = 3
    expect(orders.textContent).toContain("3");
  });

  it("shows the no-replay notice when the snapshot is missing", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(IST_WED_NOON);
    mockApi.mockResolvedValue({ success: true, ledger: [] });

    render(<Wrap><ThroughputHarness replay={undefined} /></Wrap>);
    await waitFor(() => expect(screen.getByTestId("mc-throughput-noreplay")).toBeTruthy());
  });
});

// ── LivePerformanceWidget ─────────────────────────────────────────────────────

function LivePerfHarness({ portfolio }: { portfolio?: Record<string, unknown> }) {
  const ledger = useLedgerToday();
  return <LivePerformanceWidget portfolio={portfolio} ledger={ledger} />;
}

describe("LivePerformanceWidget", () => {
  it("computes win-rate and best strategy from today's closed rows", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(IST_WED_NOON); // today IST = 2024-01-10

    const rows: LedgerRow[] = [
      // 2 winners + 1 loser closed today → win rate 67%
      { trade_id: "w1", symbol: "TCS", side: "BUY", status: "CLOSED", realized_pnl: 500, exit_ts: "2024-01-10T05:00:00Z", strategy_name: "Momentum", sector: "IT" },
      { trade_id: "w2", symbol: "INFY", side: "BUY", status: "CLOSED", realized_pnl: 300, exit_ts: "2024-01-10T05:30:00Z", strategy_name: "Momentum", sector: "IT" },
      { trade_id: "l1", symbol: "SBIN", side: "BUY", status: "CLOSED", realized_pnl: -200, exit_ts: "2024-01-10T06:00:00Z", strategy_name: "MeanRev", sector: "Bank" },
      // closed YESTERDAY → excluded
      { trade_id: "old", symbol: "WIPRO", side: "BUY", status: "CLOSED", realized_pnl: 9999, exit_ts: "2024-01-09T05:00:00Z", strategy_name: "Old", sector: "IT" },
      // still open today → excluded from closed stats
      { trade_id: "op", symbol: "HDFC", side: "BUY", status: "OPEN", fill_ts: "2024-01-10T04:00:00Z" },
    ];
    mockApi.mockResolvedValue({ success: true, ledger: rows });

    const portfolio = { equity: 100000, invested_value: 40000, initial_capital: 100000, realised_pnl_today: 600, unrealised_pnl: 100 };
    render(<Wrap><LivePerfHarness portfolio={portfolio} /></Wrap>);

    await waitFor(() => expect(screen.getByTestId("mc-live-performance")).toBeTruthy());
    // win rate 2/3 → 67%
    await waitFor(() => expect(screen.getByText("67%")).toBeTruthy());
    // best strategy = Momentum (summed +800), yesterday's "Old" excluded
    expect(screen.getByText(/Momentum/)).toBeTruthy();
    expect(screen.queryByText(/Old/)).toBeNull();
    // "3 closed today" in header extra
    expect(screen.getByText(/3 closed today/)).toBeTruthy();
  });

  it('renders "—" for win-rate and best strategy when no closed trades today', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(IST_WED_NOON);
    mockApi.mockResolvedValue({ success: true, ledger: [] });

    render(<Wrap><LivePerfHarness portfolio={{ equity: 100000 }} /></Wrap>);
    await waitFor(() => expect(screen.getByTestId("mc-live-performance")).toBeTruthy());
    expect(screen.getByText(/0 closed today/)).toBeTruthy();
    // win rate cell shows "—"
    const dashCells = screen.getAllByText("—");
    expect(dashCells.length).toBeGreaterThan(0);
  });
});
