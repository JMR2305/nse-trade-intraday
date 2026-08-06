/**
 * Pure state-transition functions extracted from the Scan button in signals.tsx.
 *
 * Keeping these as standalone exports makes them independently testable without
 * mounting a React component or mocking React state setters.
 *
 * Both functions are intentionally side-effect free: they mutate only the
 * `state` object passed in, never touching any global or module-level state.
 */

import type { LiveDataScanRunResult } from "@workspace/api-client-react";
import { LiveDataScanRunResultStatus } from "@workspace/api-client-react";

export type ScanState = {
  scanRunning: boolean;
  scanError: boolean;
};

/**
 * Apply the server's immediate response from POST /live-data/scan/run to the
 * shared scan state.
 *
 * - RUNNING / ALREADY_RUNNING: no change — the polling effect drives completion.
 * - RATE_LIMITED: stop the spinner and surface the error banner.
 */
export function applyRunResponse(
  resp: LiveDataScanRunResult | null | undefined,
  state: ScanState,
): void {
  if (resp?.status === LiveDataScanRunResultStatus.RATE_LIMITED) {
    state.scanRunning = false;
    state.scanError = true;
  }
  // RUNNING / ALREADY_RUNNING: polling effect (useEffect in signals.tsx) detects
  // completion via scan_id change — no action needed here.
}

/**
 * Apply a thrown error from the runLiveDataScan mutation to the shared scan
 * state.  User-initiated aborts (scan cancelled via the Abort button) must
 * not surface the error banner.
 */
export function applyRunError(err: unknown, state: ScanState): void {
  state.scanRunning = false;
  const msg = err instanceof Error ? err.message : String(err);
  if (!msg.includes("aborted")) {
    state.scanError = true;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Polling helpers — extracted from the useEffect in signals.tsx so they can
// be unit-tested without mounting a React component.
// ─────────────────────────────────────────────────────────────────────────────

export type StatusResponse = { latest_scan?: { scan_id?: string } };

/**
 * One polling tick: fetch the current scan status and call `onComplete` when
 * the returned scan_id differs from `baselineScanId`.
 *
 * Rules (mirror the useEffect in signals.tsx verbatim):
 *   - currentScanId === null         → still running (baseline was null too)
 *   - currentScanId === baselineScanId → still the same scan, keep waiting
 *   - currentScanId !== baselineScanId → new scan id detected → completion
 * Transient fetch errors are swallowed so the interval keeps running.
 */
export async function runScanPollTick(
  fetchStatus: () => Promise<StatusResponse>,
  baselineScanId: string | null,
  onComplete: () => void | Promise<void>,
): Promise<void> {
  try {
    const resp = await fetchStatus();
    const currentScanId = resp?.latest_scan?.scan_id ?? null;
    if (currentScanId !== null && currentScanId !== baselineScanId) {
      await onComplete();
    }
  } catch {
    // ignore transient poll errors; keep waiting
  }
}

/**
 * Start the 5-second polling loop.  Returns a `stop` function that clears
 * the interval — call it from the useEffect cleanup or on unmount.
 *
 * The `intervalMs` parameter exists purely for tests so they can use fake
 * timers with a shorter tick; production code always passes 5_000.
 */
export function startScanPoller(
  fetchStatus: () => Promise<StatusResponse>,
  baselineScanId: string | null,
  onComplete: () => void | Promise<void>,
  intervalMs = 5_000,
): { stop: () => void } {
  const id = setInterval(() => {
    void runScanPollTick(fetchStatus, baselineScanId, onComplete);
  }, intervalMs);
  return { stop: () => clearInterval(id) };
}
