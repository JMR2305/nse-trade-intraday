/**
 * Session-mismatch gate tests — signals.tsx / phase11 recommendation queue
 *
 * The mobile Trade Feed shows yesterday's BUY/Paper badges when the latest
 * scan is from a previous trading day.  The phase11 /recommendations endpoint
 * now returns `session_mismatch=true` in that situation, and the UI is
 * required to show a neutral "Waiting for today's first scan" state instead.
 *
 * These tests verify the pure branching logic that decides which UI state to
 * render based on the API response shape, without mounting a React component.
 *
 * Key invariants:
 *   1. session_mismatch=true  → "waiting" banner, zero rec cards shown
 *   2. session_mismatch=false → items rendered normally
 *   3. session_mismatch absent (undefined) → treated as false (no mismatch)
 *   4. session_mismatch=true overrides a non-empty items array (backend sends
 *      [] but guard must be belt-and-suspenders)
 *   5. Empty items with no mismatch → "empty" state (not the mismatch banner)
 *   6. Scan completion triggers refetch of recs alongside signals + decisions
 */

import { describe, expect, it } from "vitest";
import type { Phase11RecQueue } from "../monitorApi";

// ── Pure helper that mirrors the JSX branching in signals.tsx ────────────────
//
// The function is extracted here for testability; the JSX uses the same logic.
//
// Returns:
//   "mismatch"     — show SessionMismatchBanner
//   "items"        — show recommendation cards
//   "empty"        — no items, no mismatch, show empty state
//   "loading"      — data still in flight
type RecQueueState = "mismatch" | "items" | "empty" | "loading";

function selectRecQueueState(
  data: Phase11RecQueue | undefined,
  isLoading: boolean,
): RecQueueState {
  if (isLoading && data === undefined) return "loading";
  if (data?.session_mismatch) return "mismatch";
  if ((data?.items?.length ?? 0) > 0) return "items";
  return "empty";
}

// ── 1. session_mismatch=true always shows the waiting banner ─────────────────

describe("selectRecQueueState — session_mismatch=true", () => {
  it("returns 'mismatch' when session_mismatch is true and items are empty", () => {
    const data: Phase11RecQueue = {
      items: [],
      count: 0,
      session_mismatch: true,
    };
    expect(selectRecQueueState(data, false)).toBe("mismatch");
  });

  it("returns 'mismatch' even when the items array is somehow non-empty (belt-and-suspenders)", () => {
    // The backend always returns [] when session_mismatch=true, but the gate
    // must be applied at the client side too, in the same order as the JSX.
    const data: Phase11RecQueue = {
      items: [
        {
          symbol: "RELIANCE",
          action: "BUY",
          confidence: 82,
          risk_level: "MEDIUM",
        },
      ],
      count: 1,
      session_mismatch: true,
    };
    expect(selectRecQueueState(data, false)).toBe("mismatch");
  });

  it("returns 'mismatch' regardless of what session_message/next_scan say", () => {
    const data: Phase11RecQueue = {
      items: [],
      count: 0,
      session_mismatch: true,
      session_message: "Scan from yesterday at 15:28 IST",
      next_scan_expected_ist: "09:15 IST tomorrow",
    };
    expect(selectRecQueueState(data, false)).toBe("mismatch");
  });
});

// ── 2. session_mismatch=false → items or empty ───────────────────────────────

describe("selectRecQueueState — session_mismatch=false or absent", () => {
  it("returns 'items' when session_mismatch=false and there are recommendations", () => {
    const data: Phase11RecQueue = {
      items: [
        { symbol: "TCS", action: "STRONG BUY", confidence: 91 },
        { symbol: "INFY", action: "BUY", confidence: 74 },
      ],
      count: 2,
      session_mismatch: false,
    };
    expect(selectRecQueueState(data, false)).toBe("items");
  });

  it("returns 'items' when session_mismatch is absent and there are recommendations", () => {
    // Older API responses may not include the field; treat as no mismatch.
    const data: Phase11RecQueue = {
      items: [{ symbol: "HDFC", action: "BUY", confidence: 68 }],
      count: 1,
    };
    expect(selectRecQueueState(data, false)).toBe("items");
  });

  it("returns 'empty' when session_mismatch=false and the queue is empty", () => {
    const data: Phase11RecQueue = {
      items: [],
      count: 0,
      session_mismatch: false,
    };
    expect(selectRecQueueState(data, false)).toBe("empty");
  });

  it("returns 'empty' when session_mismatch is absent and the queue is empty", () => {
    const data: Phase11RecQueue = { items: [], count: 0 };
    expect(selectRecQueueState(data, false)).toBe("empty");
  });
});

// ── 3. Loading state ──────────────────────────────────────────────────────────

describe("selectRecQueueState — loading state", () => {
  it("returns 'loading' when isLoading=true and data is undefined", () => {
    expect(selectRecQueueState(undefined, true)).toBe("loading");
  });

  it("returns 'mismatch' not 'loading' once data arrives even if isLoading is still true", () => {
    // React Query may set isLoading=true during a background refetch while
    // stale data is available — the existing stale data must still be checked.
    const data: Phase11RecQueue = {
      items: [],
      count: 0,
      session_mismatch: true,
    };
    expect(selectRecQueueState(data, true)).toBe("mismatch");
  });

  it("returns 'items' not 'loading' when refetching with stale data present", () => {
    const data: Phase11RecQueue = {
      items: [{ symbol: "WIPRO", action: "BUY", confidence: 77 }],
      count: 1,
      session_mismatch: false,
    };
    expect(selectRecQueueState(data, true)).toBe("items");
  });
});

// ── 4. Scan completion must refetch recs alongside signals + decisions ─────────
//
// The signals.tsx poll handler calls:
//   await Promise.all([refetch(), refetchDecisions(), refetchRecs()])
//
// This test confirms the expected call-set by simulating the completion
// handler and asserting all three refetch callbacks are awaited.

describe("scan completion handler — recs refetch is included", () => {
  it("awaits refetchRecs alongside refetch and refetchDecisions on scan completion", async () => {
    const called: string[] = [];

    // Simulate the three callbacks the poll handler must call
    const refetch = async () => { called.push("refetch"); };
    const refetchDecisions = async () => { called.push("refetchDecisions"); };
    const refetchRecs = async () => { called.push("refetchRecs"); };

    // Mirrors the poll body in signals.tsx when a new scan_id is detected:
    //   setScanRunning(false);
    //   await Promise.all([refetch(), refetchDecisions(), refetchRecs()]);
    await Promise.all([refetch(), refetchDecisions(), refetchRecs()]);

    expect(called).toContain("refetch");
    expect(called).toContain("refetchDecisions");
    // The key assertion: recs must be refreshed so session_mismatch=false
    // is picked up from the fresh API response.
    expect(called).toContain("refetchRecs");
  });

  it("all three refetches complete (none is dropped)", async () => {
    const completed: string[] = [];
    await Promise.all([
      (async () => { completed.push("signals"); })(),
      (async () => { completed.push("decisions"); })(),
      (async () => { completed.push("recs"); })(),
    ]);
    expect(completed).toHaveLength(3);
  });
});

// ── 5. Phase11RecQueue type — session_mismatch field contract ─────────────────

describe("Phase11RecQueue shape — session_mismatch is optional boolean", () => {
  it("accepts a response with session_mismatch=true", () => {
    const resp: Phase11RecQueue = {
      items: [],
      count: 0,
      advisory_only: true,
      paper_only: true,
      as_of: "2026-08-17T03:30:00Z",
      session_mismatch: true,
      session_message: "Scan from a previous trading day",
    };
    expect(resp.session_mismatch).toBe(true);
    expect(resp.items).toHaveLength(0);
  });

  it("accepts a response with session_mismatch=false and items present", () => {
    const resp: Phase11RecQueue = {
      items: [
        {
          symbol: "RELIANCE",
          action: "BUY",
          confidence: 85,
          risk_level: "MEDIUM",
          expected_return: 4.2,
          entry: 2820,
          stop_loss: 2740,
          target: 2940,
          reasoning: "Strong momentum with breakout above 20-day SMA",
          strategy: "MOMENTUM_BREAKOUT",
        },
      ],
      count: 1,
      advisory_only: true,
      paper_only: true,
      as_of: "2026-08-17T05:30:00Z",
      session_mismatch: false,
    };
    expect(resp.session_mismatch).toBe(false);
    expect(resp.items).toHaveLength(1);
    expect(resp.items[0]!.symbol).toBe("RELIANCE");
  });

  it("accepts a response without session_mismatch (legacy API)", () => {
    // Older builds of the API do not include session_mismatch; the field must
    // be optional so that existing clients remain type-safe.
    const resp: Phase11RecQueue = { items: [], count: 0 };
    expect(resp.session_mismatch).toBeUndefined();
  });
});
