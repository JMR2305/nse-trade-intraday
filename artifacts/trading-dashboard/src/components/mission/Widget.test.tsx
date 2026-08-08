// @vitest-environment jsdom
/**
 * Widget.test.tsx — Phase 25C widget framework tests.
 *
 * Verifies the 25A widget contract:
 *  - error isolation: a failing widget renders an inline error, siblings render data
 *  - loading state renders a skeleton
 *  - stale pill appears when data is older than 2× the refresh cadence
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Activity } from "lucide-react";
import { Widget, useWidgetQuery, fmtINR, timeAgo } from "./Widget";

vi.mock("@/lib/api", () => ({ apiJson: vi.fn() }));
import { apiJson } from "@/lib/api";
const mockApi = apiJson as ReturnType<typeof vi.fn>;

function GoodWidget() {
  const q = useWidgetQuery<{ value: string }>({
    queryKey: ["t", "good"], path: "/good", refetchInterval: 60_000, retry: false,
  });
  return (
    <Widget title="Good" icon={Activity} query={q} refreshMs={60_000} testId="w-good">
      <span>{q.data?.value}</span>
    </Widget>
  );
}
function BadWidget() {
  const q = useWidgetQuery({ queryKey: ["t", "bad"], path: "/bad", refetchInterval: 60_000, retry: false });
  return (
    <Widget title="Bad" icon={Activity} query={q} refreshMs={60_000} testId="w-bad">
      <span>never</span>
    </Widget>
  );
}

function renderWithClient(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

// NOTE: do NOT touch mockApi inside beforeEach — resetting/clearing the mock
// in a hook makes Vitest treat React Query's handled rejections as unhandled
// (observed with Vitest 4). Each test installs its own implementation instead.
afterEach(() => cleanup());

describe("Widget framework", () => {
  it("isolates errors: sibling widgets keep rendering data", async () => {
    mockApi.mockImplementation(async (path: string) => {
      if (path === "/good") return { value: "healthy-data" };
      throw new Error("endpoint exploded");
    });
    renderWithClient(<><GoodWidget /><BadWidget /></>);
    // Wait on the error surface first — asserting the happy path first lets
    // the rejection land mid-waitFor and Vitest flags it as unhandled.
    await waitFor(() => expect(screen.getByText(/endpoint exploded/)).toBeTruthy(), { timeout: 5_000 });
    await waitFor(() => expect(screen.getByText("healthy-data")).toBeTruthy());
    // Failed widget shows the inline error, not its children
    expect(screen.queryByText("never")).toBeNull();
    expect(screen.getByText("Failed to load")).toBeTruthy();
  }, 25_000);

  it("shows a skeleton while loading", () => {
    mockApi.mockReturnValue(new Promise(() => {})); // never resolves
    renderWithClient(<GoodWidget />);
    const w = screen.getByTestId("w-good");
    expect(w.querySelector(".animate-pulse")).toBeTruthy();
  });

  it("stale pill: Live when fresh, Stale past 2× cadence", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      // First fetch succeeds; every refetch hangs, so dataUpdatedAt ages.
      let first = true;
      mockApi.mockImplementation(() => {
        if (first) { first = false; return Promise.resolve({ value: "x" }); }
        return new Promise(() => {});
      });
      renderWithClient(<GoodWidget />);
      await waitFor(() => expect(screen.getByText("x")).toBeTruthy());
      expect(screen.getByText(/Live ·/)).toBeTruthy();
      // Advance past 2× refresh cadence (120 s)
      await vi.advanceTimersByTimeAsync(125_000);
      await waitFor(() => expect(screen.getByText(/Stale ·/)).toBeTruthy(), { timeout: 10_000 });
    } finally {
      vi.useRealTimers();
    }
  }, 25_000);
});

describe("formatting helpers", () => {
  it("fmtINR handles numbers and garbage", () => {
    expect(fmtINR(50000)).toBe("₹50,000");
    expect(fmtINR(null)).toBe("—");
    expect(fmtINR("nope")).toBe("—");
    expect(fmtINR(NaN)).toBe("—");
  });
  it("timeAgo handles null", () => {
    expect(timeAgo(null)).toBe("—");
    expect(timeAgo(new Date(Date.now() - 5_000).toISOString())).toMatch(/s ago/);
  });
});
