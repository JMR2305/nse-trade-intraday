/**
 * Scan-poller regression tests — polling effect in signals.tsx
 *
 * The useEffect in signals.tsx (lines 200–216) polls GET /live-data/scan/status
 * every 5 s and stops the spinner when the returned scan_id changes.  That path
 * had no automated test coverage.  These three tests pin the behaviour that
 * matters most for operators:
 *
 *   1. Spinner clears when the status endpoint returns a NEW scan_id.
 *   2. Spinner does NOT clear when the returned scan_id equals the baseline
 *      (scan still in flight).
 *   3. The poll interval is cleared when the component unmounts — no memory
 *      leak / stale state update after the screen is navigated away.
 *
 * Strategy: the polling logic is extracted into `runScanPollTick` and
 * `startScanPoller` in lib/scanLogic.ts so it can be tested as plain async
 * functions without mounting a React component.  No React renderer is needed.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { runScanPollTick, startScanPoller } from "../scanLogic";

// ─────────────────────────────────────────────────────────────────────────────
// 1. Spinner clears when the status endpoint returns a NEW scan_id
// ─────────────────────────────────────────────────────────────────────────────

describe("runScanPollTick — new scan_id detected", () => {
  it("calls onComplete when the returned scan_id differs from the baseline", async () => {
    const fetchStatus = vi.fn().mockResolvedValue({
      latest_scan: { scan_id: "scan-xyz-002" },
    });
    const onComplete = vi.fn().mockResolvedValue(undefined);

    await runScanPollTick(fetchStatus, "scan-xyz-001", onComplete);

    expect(onComplete).toHaveBeenCalledOnce();
  });

  it("calls onComplete when baseline was null and a scan_id now exists", async () => {
    // No scan had ever run before (baseline = null); the first completion is
    // detected as soon as any scan_id appears.
    const fetchStatus = vi.fn().mockResolvedValue({
      latest_scan: { scan_id: "scan-first-ever" },
    });
    const onComplete = vi.fn().mockResolvedValue(undefined);

    await runScanPollTick(fetchStatus, null, onComplete);

    expect(onComplete).toHaveBeenCalledOnce();
  });

  it("awaits onComplete before returning", async () => {
    const order: string[] = [];
    const fetchStatus = vi.fn().mockResolvedValue({
      latest_scan: { scan_id: "scan-new" },
    });
    const onComplete = vi.fn().mockImplementation(async () => {
      order.push("onComplete");
    });

    await runScanPollTick(fetchStatus, "scan-old", onComplete);
    order.push("after-tick");

    expect(order).toEqual(["onComplete", "after-tick"]);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 2. Spinner does NOT clear when the returned scan_id equals the baseline
// ─────────────────────────────────────────────────────────────────────────────

describe("runScanPollTick — scan still in flight", () => {
  it("does NOT call onComplete when scan_id equals the baseline", async () => {
    const fetchStatus = vi.fn().mockResolvedValue({
      latest_scan: { scan_id: "scan-xyz-001" },
    });
    const onComplete = vi.fn();

    await runScanPollTick(fetchStatus, "scan-xyz-001", onComplete);

    expect(onComplete).not.toHaveBeenCalled();
  });

  it("does NOT call onComplete when the returned scan_id is null (server still processing)", async () => {
    const fetchStatus = vi.fn().mockResolvedValue({
      latest_scan: { scan_id: undefined }, // server omitted the field
    });
    const onComplete = vi.fn();

    await runScanPollTick(fetchStatus, "scan-xyz-001", onComplete);

    expect(onComplete).not.toHaveBeenCalled();
  });

  it("does NOT call onComplete when latest_scan is absent from the response", async () => {
    const fetchStatus = vi.fn().mockResolvedValue({});
    const onComplete = vi.fn();

    await runScanPollTick(fetchStatus, "scan-xyz-001", onComplete);

    expect(onComplete).not.toHaveBeenCalled();
  });

  it("does NOT call onComplete when both baseline and current are null", async () => {
    // currentScanId === null → guard `currentScanId !== null` blocks completion.
    const fetchStatus = vi.fn().mockResolvedValue({ latest_scan: {} });
    const onComplete = vi.fn();

    await runScanPollTick(fetchStatus, null, onComplete);

    expect(onComplete).not.toHaveBeenCalled();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 3. Poll interval is cleared when the component unmounts (no memory leak)
// ─────────────────────────────────────────────────────────────────────────────

describe("startScanPoller — interval lifecycle", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("stop() prevents further fetchStatus calls after unmount", async () => {
    const fetchStatus = vi.fn().mockResolvedValue({ latest_scan: { scan_id: "scan-001" } });
    const onComplete = vi.fn();

    const { stop } = startScanPoller(fetchStatus, "scan-000", onComplete, 100);

    // Advance to just before the first tick — no calls yet.
    vi.advanceTimersByTime(50);
    expect(fetchStatus).not.toHaveBeenCalled();

    // First tick fires, fetchStatus and onComplete are called.
    await vi.advanceTimersByTimeAsync(100);
    expect(fetchStatus).toHaveBeenCalledOnce();

    // Unmount: stop the poller.
    stop();

    const callCountAfterStop = fetchStatus.mock.calls.length;

    // Additional time passes — the interval must NOT fire again.
    await vi.advanceTimersByTimeAsync(1_000);
    expect(fetchStatus).toHaveBeenCalledTimes(callCountAfterStop);
  });

  it("calling stop() before the first tick fires suppresses all ticks", async () => {
    const fetchStatus = vi.fn().mockResolvedValue({ latest_scan: { scan_id: "scan-new" } });
    const onComplete = vi.fn();

    const { stop } = startScanPoller(fetchStatus, null, onComplete, 5_000);

    // Immediately unmount (navigated away before any tick).
    stop();

    await vi.advanceTimersByTimeAsync(20_000);

    expect(fetchStatus).not.toHaveBeenCalled();
    expect(onComplete).not.toHaveBeenCalled();
  });

  it("transient fetchStatus error does not stop the poller (interval keeps running)", async () => {
    let callCount = 0;
    const fetchStatus = vi.fn().mockImplementation(async () => {
      callCount += 1;
      if (callCount === 1) throw new Error("Network failure");
      return { latest_scan: { scan_id: "scan-same" } };
    });
    const onComplete = vi.fn();

    const { stop } = startScanPoller(fetchStatus, "scan-same", onComplete, 100);

    // First tick throws — poller must survive.
    await vi.advanceTimersByTimeAsync(100);
    expect(fetchStatus).toHaveBeenCalledOnce();

    // Second tick succeeds (same scan_id → no completion).
    await vi.advanceTimersByTimeAsync(100);
    expect(fetchStatus).toHaveBeenCalledTimes(2);
    expect(onComplete).not.toHaveBeenCalled();

    stop();
  });
});
