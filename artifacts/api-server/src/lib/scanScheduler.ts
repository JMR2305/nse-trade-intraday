import { spawn } from "child_process";
import path from "path";
import { logger } from "./logger";
import { PYTHON_DIR, PYTHON_BIN } from "./python-env";
import { dispatchSignalPushNotifications, processPushDeliveryQueue } from "./pushNotifier";
import { eventBus } from "./events";

// Phase 20 — market-hours auto-scan scheduler.
//
// This instance ticks every minute; the Python side ("scheduled_scan_tick")
// decides whether a scan is actually due using DURABLE Phase 20 settings
// (configurable interval 1/3/5/10/15 min, auto-scan toggle):
//   1. Skips unless NSE is OPEN (Asia/Kolkata, holidays respected) via the
//      existing market-hours service.
//   2. Skips if the durable shared snapshot is already fresher than the
//      configured interval (so multiple Autoscale instances don't
//      duplicate work).
//   3. Otherwise runs the canonical scan guarded by the distributed
//      database lease (scan_lock) with stuck-lock timeout recovery, then
//      runs paper position management (exits) and — only when explicitly
//      enabled AND confirmed in settings — automatic paper entries.
// A failed scheduled scan never overwrites the last successful snapshot.
// Paper trading / research only — no live orders anywhere.

const TICK_INTERVAL_MIN = 1;

function runPython(args: string[]): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], {
      cwd: PYTHON_DIR,
    });
    let stdout = "";
    let stderr = "";
    proc.stdout.on("data", (d: Buffer) => { stdout += d.toString(); });
    proc.stderr.on("data", (d: Buffer) => { stderr += d.toString(); });
    proc.on("close", (code) => {
      if (code !== 0) {
        reject(new Error(stderr || `Python exited with code ${code}`));
        return;
      }
      // Find the last line that is valid JSON (subsystems may print
      // structured log lines before the result).
      const lines = stdout.trim().split("\n");
      let parsed: unknown = undefined;
      for (let i = lines.length - 1; i >= 0; i--) {
        const line = lines[i].trim();
        if (!line) continue;
        try { parsed = JSON.parse(line); break; } catch { /* skip */ }
      }
      if (parsed !== undefined) {
        resolve(parsed);
      } else {
        reject(new Error(`Failed to parse Python output: ${stdout.slice(0, 300)}`));
      }
    });
    proc.on("error", reject);
  });
}

let timer: NodeJS.Timeout | null = null;
let tickInFlight = false;

// ── Cold-start OHLCV readiness barrier ────────────────────────────────────────
// Prevents scheduled_scan_tick from firing while the cold-start cache check
// (or its triggered backfill) is still in progress.  Without this gate a fresh
// production server would start scanning against the still-empty cache and fall
// back to the 7–22 min live yfinance download the feature was designed to avoid.
//
// The flag starts true and is cleared (in the ohlcv_cold_start_check .finally()
// handler) once the Python process resolves or rejects — including after the
// owner instance finishes backfill and non-owner instances finish polling.
// On any Node-level error the .catch()/.finally() chain still clears the gate
// so scans are never blocked permanently.
let _ohlcvColdStartPending = true;

// Module-level reference to the tick closure so tests can invoke it directly
// without depending on fake-timer machinery.  Assigned in startScanScheduler().
let _tick: (() => Promise<void>) | null = null;

/** @internal — reset all mutable state; call before each test. */
export function _resetColdStartCheckForTests(): void {
  _ohlcvColdStartPending = false;
  tickInFlight = false;
  _tick = null;
  if (timer) { clearInterval(timer); timer = null; }
}

/** @internal — directly invoke one scheduler tick (bypasses setInterval timing). */
export async function _runTickForTests(): Promise<void> {
  if (!_tick) throw new Error("startScanScheduler() not called — _tick is null");
  return _tick();
}

export function startScanScheduler(): void {
  if (process.env["DISABLE_SCAN_SCHEDULER"] === "true") {
    logger.info("Scan scheduler disabled via DISABLE_SCAN_SCHEDULER");
    return;
  }
  // Mark the OHLCV readiness gate as pending for this scheduler instance.
  // Must happen before any tick fires, so the first tick always sees the gate
  // up and defers the scan until ohlcv_cold_start_check settles.
  // (Also re-arms correctly after _resetColdStartCheckForTests() in tests.)
  _ohlcvColdStartPending = true;

  const intervalMs = TICK_INTERVAL_MIN * 60 * 1000;

  _tick = async (): Promise<void> => {
    if (tickInFlight) return; // never stack ticks in this process
    tickInFlight = true;
    try {
      // ── OHLCV readiness gate ───────────────────────────────────────────────
      // Block the market scan until the cold-start cache check (and any
      // triggered backfill) has completed.  The gate only affects the main
      // scan; per-minute advisory ticks below (pre-open intelligence, signal
      // validation, push delivery) still run normally so they don't miss
      // their IST-gated windows during a long backfill.
      if (_ohlcvColdStartPending) {
        logger.info(
          "Scheduled scan deferred — cold-start OHLCV cache check in progress",
        );
        // Skip the scan but proceed to the per-minute advisory ticks below.
      } else {
        // Clear status/history cache before this due attempt. The route layer
        // also handles the completion/busy/failure event below, making every
        // scheduler outcome visible to the next poll.
        eventBus.publish("scan.started", { source: "scheduler", ts: new Date().toISOString() });
        const result = (await runPython([
          "scheduled_scan_tick",
        ])) as Record<string, unknown>;
        if (result?.["ran_scan"]) {
          eventBus.publish("scan.completed", {
            source: "scheduler",
            scan_id: result["scan_id"],
            snapshot_ts: result["snapshot_ts"],
          });
          logger.info(
            { scan_id: result["scan_id"], snapshot_ts: result["snapshot_ts"] },
            "Scheduled market scan completed",
          );
          // Advisory push alerts for high-confidence signals; never blocks
          // or influences the scan/trading pipeline.
          dispatchSignalPushNotifications().catch((err: unknown) => {
            logger.warn({ err: err instanceof Error ? err.message : String(err) },
              "Signal push dispatch failed");
          });
        } else {
          const reason = String(result?.["reason"] ?? "");
          eventBus.publish(
            reason.toUpperCase().includes("BUSY") ? "scan.busy" : "scan.scheduled.tick",
            { source: "scheduler", reason },
          );
        }
      }
    } catch (err) {
      // Failed scheduled scan: last successful snapshot is preserved by design.
      logger.warn({ err: err instanceof Error ? err.message : String(err) },
        "Scheduled scan tick failed (previous snapshot preserved)");
      eventBus.publish("scan.failed", {
        source: "scheduler",
        error: err instanceof Error ? err.message : String(err),
      });
    } finally {
      tickInFlight = false;
    }

    // Phase 5A — Pre-Open Intelligence tick.
    // Runs on every minute; Python owns all IST time-gating for each phase:
    //   08:43 init, 08:53 readiness, 09:00–09:15 collect, 09:15 freeze, 09:18 reconcile.
    // No-ops outside phase windows and on non-trading days.
    // Provider failure is caught and returned as DEGRADED/UNAVAILABLE — never crashes.
    // Paper / advisory only — no orders.
    runPython(["preopen_intelligence_tick"]).then((r) => {
      const res = r as Record<string, unknown>;
      if (res?.["ran"]) {
        logger.info(
          { phase: res["phase"], collect_count: res["collect_count"],
            session_id: res["session_id"], trading_date: res["trading_date"],
            provider_status: res["provider_status"] },
          "Pre-Open Intelligence phase executed",
        );
      }
    }).catch((err: unknown) => {
      logger.warn({ err: err instanceof Error ? err.message : String(err) },
        "Pre-Open Intelligence tick failed (non-fatal)");
    });

    // Phase 5B — Pre-Open Validation tick.
    // Runs on every minute; the Python side owns all IST time-gating and
    // checkpoint deduplication. No-ops outside checkpoint windows and on
    // non-trading days. Paper / advisory only — no orders.
    runPython(["preopen_validation_tick"]).then((r) => {
      const res = r as Record<string, unknown>;
      if (res?.["ran"]) {
        logger.info(
          { checkpoint: res["checkpoint"], candidates: res["candidates"],
            session_id: res["session_id"], trading_date: res["trading_date"] },
          "Pre-Open Validation checkpoint collected",
        );
      }
    }).catch((err: unknown) => {
      logger.warn({ err: err instanceof Error ? err.message : String(err) },
        "Pre-Open Validation tick failed (non-fatal)");
    });

    // Phase 5C — Signal Validation tick.
    // Fires every minute; Python owns all IST window-gating and idempotency.
    // No-ops outside checkpoint windows and on non-trading days.
    // SIGNAL_VALIDATION_ENABLED=false → Python returns DISABLED immediately.
    // Paper / advisory only — no orders, no strategy modification.
    runPython(["signal_validation_tick"]).then((r) => {
      const res = r as Record<string, unknown>;
      if (res?.["ran"]) {
        logger.info(
          { phase: res["phase"], session_id: res["session_id"],
            trading_date: res["trading_date"] },
          "Signal Validation phase executed",
        );
      }
    }).catch((err: unknown) => {
      logger.warn({ err: err instanceof Error ? err.message : String(err) },
        "Signal Validation tick failed (non-fatal)");
    });

    // Priority 4 (#41): drain the durable alert delivery queue every tick
    // (retries for push + email survive restarts and provider outages).
    // Runs even when no scan is due; never blocks or fails the tick.
    processPushDeliveryQueue().catch((err: unknown) => {
      logger.warn({ err: err instanceof Error ? err.message : String(err) },
        "Push delivery queue processing failed");
    });
    runPython(["alert_queue_process"]).catch((err: unknown) => {
      logger.warn({ err: err instanceof Error ? err.message : String(err) },
        "Email alert queue processing failed");
    });
  };

  timer = setInterval(() => { void _tick!(); }, intervalMs);
  timer.unref();
  logger.info({ tickIntervalMin: TICK_INTERVAL_MIN },
    "Market-hours scan scheduler started (interval configured in Settings)");

  // Record the scheduler process start time durably so the cadence panel can
  // report SCAN_COMPLETED counts "since last restart". Non-fatal on failure.
  runPython(["phase20_scheduler_started"]).catch((err: unknown) => {
    logger.warn({ err: err instanceof Error ? err.message : String(err) },
      "Failed to record scheduler process start time (non-fatal)");
  });

  // Cold-start overnight-carry safety check.
  // Runs immediately at server startup to detect OPEN paper positions that
  // survived from a prior session because the server was down during the
  // POST_CLOSE/CLOSED window (15:30–18:00 IST).  The Python side is
  // idempotent via kv_claim_once("startup_overnight_check:<today>") so
  // multiple rapid restarts or Autoscale instances only execute once per
  // IST calendar day.  Never blocks the scheduler or raises.
  runPython(["phase20_startup_overnight_check"]).then((r) => {
    const res = r as Record<string, unknown>;
    const priorCount = res?.["prior_session_count"] as number | undefined;
    if (priorCount && priorCount > 0) {
      logger.warn(
        {
          yesterday: res["yesterday"],
          symbols: res["symbols"],
          prior_session_count: priorCount,
          eod_force_close: res["eod_force_close"],
        },
        "Overnight carry detected at cold-start — EOD force-close executed",
      );
    } else if (res?.["ran"]) {
      logger.info(
        { reason: res["reason"], yesterday: res["yesterday"] },
        "Startup overnight-carry check complete (no prior-session positions)",
      );
    }
  }).catch((err: unknown) => {
    logger.warn(
      { err: err instanceof Error ? err.message : String(err) },
      "Startup overnight-carry check failed (non-fatal)",
    );
  });

  // Cold-start OHLCV cache check — with startup readiness barrier.
  //
  // On a fresh production deployment the daily_ohlcv_cache table is empty.
  // The Python check detects this and runs backfill_all_symbols() (2–8 min).
  // _ohlcvColdStartPending stays true throughout so tick() skips the market
  // scan while the backfill is in progress.  Once the promise settles
  // (success, Python-level failure, or Node error) the flag is cleared and
  // normal scan scheduling resumes.
  //
  // On a warm server the Python check is a fast DB query (< 1 s) and the
  // flag is cleared before the 15-second initial tick fires.
  runPython(["ohlcv_cold_start_check"]).then((r) => {
    const res = r as Record<string, unknown>;
    const action = res?.["action"] as string | undefined;
    if (action === "backfill") {
      logger.warn(
        {
          was_fully_cold: res["was_fully_cold"],
          cold_symbol_count: res["cold_symbol_count"],
          total_symbols: res["total_symbols"],
          symbols_updated: res["symbols_updated"],
          symbols_failed: res["symbols_failed"],
          duration_seconds: res["duration_seconds"],
          status: res["status"],
          recovery_hint: res["recovery_hint"],
        },
        "Cold-start OHLCV backfill completed — cache was empty on this server",
      );
    } else if (action === "backfill_failed") {
      logger.error(
        {
          was_fully_cold: res["was_fully_cold"],
          cold_symbol_count: res["cold_symbol_count"],
          error: res["error"],
          recovery_hint: res["recovery_hint"],
        },
        "Cold-start OHLCV backfill failed — first scan will use live yfinance (slow)",
      );
    } else if (res?.["ran"] && action === "no_op") {
      logger.info(
        {
          cache_hit_rate_pct: res["cache_hit_rate_pct"],
          total_symbols: res["total_symbols"],
        },
        "Cold-start OHLCV cache check: cache warm, no backfill needed",
      );
    }
  }).catch((err: unknown) => {
    logger.warn(
      { err: err instanceof Error ? err.message : String(err) },
      "Cold-start OHLCV cache check failed (non-fatal — first scan may be slow)",
    );
  }).finally(() => {
    // Always clear the gate — even on error, so scans are not blocked forever.
    _ohlcvColdStartPending = false;
  });

  // Kick one tick shortly after boot so a cold instance during market hours
  // converges quickly instead of waiting a full interval.
  setTimeout(() => { void _tick!(); }, 15_000).unref();
}

export function stopScanScheduler(): void {
  if (timer) {
    clearInterval(timer);
    timer = null;
  }
}
