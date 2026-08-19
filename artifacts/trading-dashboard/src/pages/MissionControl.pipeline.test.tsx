// @vitest-environment jsdom
/**
 * MissionControl.pipeline.test.tsx
 *
 * Component-level tests for PipelinePanel auto-expand behaviour (Task #708).
 *
 * Key scenario: when `progress.stage` changes while `scanning` stays true and
 * the pipeline summary (`stages`) reference has NOT changed, the effect must
 * still fire because `progressStage` is now an explicit dependency.
 *
 * Tests use real React rendering + RTL so the useEffect runs as it would in the
 * browser.  apiJson is mocked to return deterministic summary/grid data.
 */

import React, { useState } from "react";
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, waitFor, cleanup, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { UseQueryResult } from "@tanstack/react-query";

// ── Module mocks ──────────────────────────────────────────────────────────────

vi.mock("@/lib/api", () => ({ apiJson: vi.fn(), API_BASE: "" }));

vi.mock("wouter", () => ({
  Link: ({ href, children, className }: React.AnchorHTMLAttributes<HTMLAnchorElement>) =>
    React.createElement("a", { href, className }, children),
  useLocation: vi.fn(() => ["/"]),
  useRoute:    vi.fn(() => [false, {}]),
}));

import { apiJson } from "@/lib/api";
import { EventStreamPanel, PipelinePanel } from "./MissionControl";

const mockApi = apiJson as ReturnType<typeof vi.fn>;

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeQc() {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
}

// Build a minimal UseQueryResult-like object that PipelinePanel reads via
// replayQ / scanQ props.  Only the fields the component touches are required.
function makeQuery<T>(data: T): UseQueryResult<T> {
  return {
    data,
    error:      null,
    isError:    false,
    isLoading:  false,
    isPending:  false,
    isSuccess:  true,
    isFetching: false,
    status:     "success",
  } as unknown as UseQueryResult<T>;
}

const SCAN_ID = "scan-test-001";

// Two stages: SCANNER (ts 30 s ago) and STRATEGY (ts 90 s ago — stale by timestamp).
// The test drives which stage is "active" via progressStage, not timestamps.
function makeStages() {
  const now = new Date();
  const ts30s = new Date(now.getTime() - 30_000).toISOString();
  const ts90s = new Date(now.getTime() - 90_000).toISOString();
  return [
    { stage: "SCANNER",  events: 5, completed: 5, rejected: 0, errors: 0, last_ts: ts30s, last_symbol: "RELIANCE" },
    { stage: "STRATEGY", events: 0, completed: 0, rejected: 0, errors: 0, last_ts: ts90s, last_symbol: null },
  ];
}

// Summary data returned by the internal useWidgetQuery for /pipeline/summary.
function summaryPayload(stages: ReturnType<typeof makeStages>) {
  return {
    scan_id: SCAN_ID,
    mode: "live",
    total_events: 10,
    stages,
    generated_at: new Date().toISOString(),
  };
}

// Grid events (returned by /pipeline/events?limit=400&newest_first=true).
// Providing at least one event per stage so symEntries is non-empty and the
// expand toggle label ("▲ / ▼ N symbols") is rendered.
function gridEventsPayload() {
  return {
    events: [
      { id: 1, ts: new Date().toISOString(), event_type: "SCANNER_COMPLETE", stage: "SCANNER",  symbol: "RELIANCE.NS", payload: {} },
      { id: 2, ts: new Date().toISOString(), event_type: "STRATEGY_COMPLETE", stage: "STRATEGY", symbol: "INFY.NS",     payload: {} },
    ],
  };
}

// Make a scan status for a given progress stage.
function makeScanQ(progressStage: string | null) {
  return makeQuery({
    status: "SCANNING",
    scan_id: SCAN_ID,
    progress: progressStage
      ? { stage: progressStage, symbol: null, current_symbol: null, symbols_done: 10, symbols_total: 51, scan_id: SCAN_ID }
      : null,
    latest_scan: { scan_id: SCAN_ID, symbols_total: 51, universe_size: 51, symbols_done: 10 },
  });
}

const replayQ = makeQuery({ stages: [], scan_id: SCAN_ID });

// Wrapper that allows the test to change scanQ props after initial render.
function Harness({ initialStage }: { initialStage: string }) {
  const [progressStage, setProgressStage] = useState(initialStage);
  const qc = makeQc();
  return (
    <QueryClientProvider client={qc}>
      <PipelinePanel
        scanning={true}
        replayQ={replayQ as never}
        scanQ={makeScanQ(progressStage) as never}
      />
      {/* Expose a setter so tests can drive stage transitions */}
      <button
        data-testid="set-strategy"
        onClick={() => setProgressStage("STRATEGY")}
      >
        switch stage
      </button>
    </QueryClientProvider>
  );
}

// ── Setup / teardown ──────────────────────────────────────────────────────────

beforeEach(() => {
  const stages = makeStages();
  mockApi.mockImplementation((path: string) => {
    if (path.startsWith("/pipeline/summary"))              return Promise.resolve(summaryPayload(stages));
    if (path.startsWith("/pipeline/events"))               return Promise.resolve(gridEventsPayload());
    return Promise.resolve({});
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("PipelinePanel auto-expand", () => {
  it("expands the initial progress stage when scanning starts", async () => {
    render(<Harness initialStage="SCANNER" />);

    // Wait for summaryQ data to load so stage rows appear.
    await waitFor(() => {
      expect(screen.getByTestId("mc-stage-toggle-scanner")).toBeTruthy();
    });

    const scannerToggle = screen.getByTestId("mc-stage-toggle-scanner");
    expect(scannerToggle.getAttribute("aria-expanded")).toBe("true");
  });

  it("keeps other stages collapsed on initial render", async () => {
    render(<Harness initialStage="SCANNER" />);

    await waitFor(() => {
      expect(screen.getByTestId("mc-stage-toggle-strategy")).toBeTruthy();
    });

    const strategyToggle = screen.getByTestId("mc-stage-toggle-strategy");
    expect(strategyToggle.getAttribute("aria-expanded")).toBe("false");
  });

  it("collapses SCANNER and expands STRATEGY when progress.stage changes to STRATEGY (stages unchanged)", async () => {
    render(<Harness initialStage="SCANNER" />);

    await waitFor(() => {
      expect(screen.getByTestId("mc-stage-toggle-scanner")).toBeTruthy();
    });
    // SCANNER should be expanded initially.
    expect(screen.getByTestId("mc-stage-toggle-scanner").getAttribute("aria-expanded")).toBe("true");

    // Transition: only progress.stage changes — stages summary stays the same.
    await act(async () => {
      screen.getByTestId("set-strategy").click();
    });

    await waitFor(() => {
      expect(screen.getByTestId("mc-stage-toggle-strategy").getAttribute("aria-expanded")).toBe("true");
    });

    // Old stage must be collapsed now.
    expect(screen.getByTestId("mc-stage-toggle-scanner").getAttribute("aria-expanded")).toBe("false");
  });
});

describe("EventStreamPanel allocation audit visibility", () => {
  it("shows canonical allocation-event payload fields", async () => {
    render(
      <QueryClientProvider client={makeQc()}>
        <EventStreamPanel streamEvents={[{
          id: "alloc-1",
          ts: new Date().toISOString(),
          event_type: "ALLOCATION_OVERRIDE_APPROVED_3X",
          stage: "EXECUTION",
          symbol: "TCS",
          payload: {
            tier: "EXCEPTIONAL_QUALITY_3X",
            requested_multiplier: 3,
            effective_multiplier: 2.5,
            final_notional: 20_000,
            limiting_caps: ["per_stock"],
            reason: "EXCEPTIONAL_QUALITY_3X_APPROVED",
          },
        }] as never} />
      </QueryClientProvider>,
    );

    expect((await screen.findByTestId("mc-allocation-tier-alloc-1")).textContent)
      .toBe("3X");
    expect(screen.getByText("2.5x/3x req")).toBeTruthy();
    expect(screen.getByText("₹20.0k")).toBeTruthy();
    expect(screen.getByText("[cap: per_stock]")).toBeTruthy();
  });
});
