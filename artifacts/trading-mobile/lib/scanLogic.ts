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
