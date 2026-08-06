/**
 * Scan button regression tests — Task #391
 *
 * Confirms that the useRunLiveDataScan hook (migrated from a manually-
 * maintained block to a fully-generated orval hook in Task #388) still sends
 * the right POST request and that signals.tsx handles every possible server
 * response correctly.
 *
 * Three test layers:
 *   A. Generated hook contract  — URL + mutation key from real generated exports
 *   B. LiveDataScanRunResultStatus enum — generated const values are stable
 *   C. Production state-machine functions — applyRunResponse / applyRunError
 *      extracted from signals.tsx into lib/scanLogic.ts and tested directly
 *
 * No React renderer required; no live server required.
 */

import { describe, it, expect, vi } from "vitest";

// ─────────────────────────────────────────────────────────────────────────────
// Minimal stubs so @tanstack/react-query hooks don't need a React context.
// The pure helper functions (getRunLiveDataScanUrl, getRunLiveDataScanMutationOptions,
// LiveDataScanRunResultStatus) are NOT stubbed — we import the real implementations.
// ─────────────────────────────────────────────────────────────────────────────

vi.mock("@tanstack/react-query", () => ({
  useMutation: vi.fn(),
  useQuery: vi.fn(),
}));

// ─────────────────────────────────────────────────────────────────────────────
// A. Generated hook contract
// ─────────────────────────────────────────────────────────────────────────────

describe("useRunLiveDataScan — URL contract (generated export)", () => {
  it("getRunLiveDataScanUrl returns the exact path the API server listens on", async () => {
    const { getRunLiveDataScanUrl } = await import("@workspace/api-client-react");
    expect(getRunLiveDataScanUrl()).toBe("/api/live-data/scan/run");
  });

  it("URL includes /api/ prefix (base-URL prefix is baked in)", async () => {
    const { getRunLiveDataScanUrl } = await import("@workspace/api-client-react");
    expect(getRunLiveDataScanUrl()).toMatch(/^\/api\//);
  });

  it("URL ends with /live-data/scan/run without a trailing slash", async () => {
    const { getRunLiveDataScanUrl } = await import("@workspace/api-client-react");
    const url = getRunLiveDataScanUrl();
    expect(url).toMatch(/\/live-data\/scan\/run$/);
    expect(url).not.toMatch(/\/$/);
  });
});

describe("useRunLiveDataScan — mutation key (generated export)", () => {
  it("mutation key is ['runLiveDataScan'] so React Query cache identity is stable", async () => {
    const { getRunLiveDataScanMutationOptions } = await import("@workspace/api-client-react");
    const opts = getRunLiveDataScanMutationOptions();
    expect(opts.mutationKey).toEqual(["runLiveDataScan"]);
  });

  it("mutation key is identical on repeated calls (no per-call divergence)", async () => {
    const { getRunLiveDataScanMutationOptions } = await import("@workspace/api-client-react");
    const a = getRunLiveDataScanMutationOptions();
    const b = getRunLiveDataScanMutationOptions();
    expect(a.mutationKey).toEqual(b.mutationKey);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// B. LiveDataScanRunResultStatus enum — generated runtime const values
//
// signals.tsx branches on resp.status; if the enum values change in the
// OpenAPI spec (e.g. RATE_LIMITED → THROTTLED), these tests catch it.
// ─────────────────────────────────────────────────────────────────────────────

describe("LiveDataScanRunResultStatus — generated runtime const", () => {
  it("RUNNING value is the string 'RUNNING'", async () => {
    const { LiveDataScanRunResultStatus } = await import("@workspace/api-client-react");
    expect(LiveDataScanRunResultStatus.RUNNING).toBe("RUNNING");
  });

  it("ALREADY_RUNNING value is the string 'ALREADY_RUNNING'", async () => {
    const { LiveDataScanRunResultStatus } = await import("@workspace/api-client-react");
    expect(LiveDataScanRunResultStatus.ALREADY_RUNNING).toBe("ALREADY_RUNNING");
  });

  it("RATE_LIMITED value is the string 'RATE_LIMITED'", async () => {
    const { LiveDataScanRunResultStatus } = await import("@workspace/api-client-react");
    expect(LiveDataScanRunResultStatus.RATE_LIMITED).toBe("RATE_LIMITED");
  });

  it("enum has exactly three members (no unexpected additions)", async () => {
    const { LiveDataScanRunResultStatus } = await import("@workspace/api-client-react");
    expect(Object.keys(LiveDataScanRunResultStatus)).toHaveLength(3);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// C. Production state-machine — lib/scanLogic.ts (real code, not replicas)
//
// applyRunResponse and applyRunError are extracted from signals.tsx so they
// can be tested without a React renderer.  Any regression in the real
// component callback is now caught here.
// ─────────────────────────────────────────────────────────────────────────────

describe("applyRunResponse — RATE_LIMITED", () => {
  it("stops the spinner and raises the error flag", async () => {
    const { applyRunResponse } = await import("../scanLogic");
    const { LiveDataScanRunResultStatus } = await import("@workspace/api-client-react");
    const state = { scanRunning: true, scanError: false };
    applyRunResponse(
      { started: false, status: LiveDataScanRunResultStatus.RATE_LIMITED, retry_in_s: 20 },
      state,
    );
    expect(state.scanRunning).toBe(false);
    expect(state.scanError).toBe(true);
  });

  it("raises error even when retry_in_s is 1", async () => {
    const { applyRunResponse } = await import("../scanLogic");
    const { LiveDataScanRunResultStatus } = await import("@workspace/api-client-react");
    const state = { scanRunning: true, scanError: false };
    applyRunResponse(
      { started: false, status: LiveDataScanRunResultStatus.RATE_LIMITED, retry_in_s: 1 },
      state,
    );
    expect(state.scanError).toBe(true);
    expect(state.scanRunning).toBe(false);
  });
});

describe("applyRunResponse — RUNNING", () => {
  it("leaves the spinner running (polling drives completion)", async () => {
    const { applyRunResponse } = await import("../scanLogic");
    const { LiveDataScanRunResultStatus } = await import("@workspace/api-client-react");
    const state = { scanRunning: true, scanError: false };
    applyRunResponse({ started: true, status: LiveDataScanRunResultStatus.RUNNING }, state);
    expect(state.scanRunning).toBe(true);
    expect(state.scanError).toBe(false);
  });
});

describe("applyRunResponse — ALREADY_RUNNING", () => {
  it("leaves the spinner running (joined an in-flight scan)", async () => {
    const { applyRunResponse } = await import("../scanLogic");
    const { LiveDataScanRunResultStatus } = await import("@workspace/api-client-react");
    const state = { scanRunning: true, scanError: false };
    applyRunResponse(
      { started: true, status: LiveDataScanRunResultStatus.ALREADY_RUNNING },
      state,
    );
    expect(state.scanRunning).toBe(true);
    expect(state.scanError).toBe(false);
  });
});

describe("applyRunResponse — null / undefined guard", () => {
  it("handles null response without throwing or changing state", async () => {
    const { applyRunResponse } = await import("../scanLogic");
    const state = { scanRunning: true, scanError: false };
    expect(() => applyRunResponse(null, state)).not.toThrow();
    expect(state.scanRunning).toBe(true);
    expect(state.scanError).toBe(false);
  });

  it("handles undefined response without throwing or changing state", async () => {
    const { applyRunResponse } = await import("../scanLogic");
    const state = { scanRunning: true, scanError: false };
    expect(() => applyRunResponse(undefined, state)).not.toThrow();
    expect(state.scanRunning).toBe(true);
    expect(state.scanError).toBe(false);
  });
});

describe("applyRunError — network / server errors", () => {
  it("stops the spinner and sets error flag on a generic network failure", async () => {
    const { applyRunError } = await import("../scanLogic");
    const state = { scanRunning: true, scanError: false };
    applyRunError(new Error("Network request failed"), state);
    expect(state.scanRunning).toBe(false);
    expect(state.scanError).toBe(true);
  });

  it("stops the spinner and sets error flag on a 500 server error", async () => {
    const { applyRunError } = await import("../scanLogic");
    const state = { scanRunning: true, scanError: false };
    applyRunError(new Error("Internal Server Error"), state);
    expect(state.scanRunning).toBe(false);
    expect(state.scanError).toBe(true);
  });

  it("stops the spinner and sets error flag on a non-Error throwable", async () => {
    const { applyRunError } = await import("../scanLogic");
    const state = { scanRunning: true, scanError: false };
    applyRunError("server timeout", state);
    expect(state.scanRunning).toBe(false);
    expect(state.scanError).toBe(true);
  });
});

describe("applyRunError — user abort", () => {
  it("stops the spinner but does NOT set the error flag ('The operation was aborted')", async () => {
    const { applyRunError } = await import("../scanLogic");
    const state = { scanRunning: true, scanError: false };
    applyRunError(new Error("The operation was aborted"), state);
    expect(state.scanRunning).toBe(false);
    expect(state.scanError).toBe(false);
  });

  it("stops the spinner but does NOT set the error flag ('Request aborted')", async () => {
    const { applyRunError } = await import("../scanLogic");
    const state = { scanRunning: true, scanError: false };
    applyRunError(new Error("Request aborted"), state);
    expect(state.scanRunning).toBe(false);
    expect(state.scanError).toBe(false);
  });
});
