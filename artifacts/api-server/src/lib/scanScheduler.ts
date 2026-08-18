import { spawn } from "child_process";
import path from "path";
import { logger } from "./logger";
import { PYTHON_DIR, PYTHON_BIN } from "./python-env";
import { dispatchSignalPushNotifications, processPushDeliveryQueue } from "./pushNotifier";

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

export function startScanScheduler(): void {
  if (process.env["DISABLE_SCAN_SCHEDULER"] === "true") {
    logger.info("Scan scheduler disabled via DISABLE_SCAN_SCHEDULER");
    return;
  }
  const intervalMs = TICK_INTERVAL_MIN * 60 * 1000;

  const tick = async (): Promise<void> => {
    if (tickInFlight) return; // never stack ticks in this process
    tickInFlight = true;
    try {
      const result = (await runPython([
        "scheduled_scan_tick",
      ])) as Record<string, unknown>;
      if (result?.["ran_scan"]) {
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
      }
    } catch (err) {
      // Failed scheduled scan: last successful snapshot is preserved by design.
      logger.warn({ err: err instanceof Error ? err.message : String(err) },
        "Scheduled scan tick failed (previous snapshot preserved)");
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

  timer = setInterval(() => { void tick(); }, intervalMs);
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

  // Kick one tick shortly after boot so a cold instance during market hours
  // converges quickly instead of waiting a full interval.
  setTimeout(() => { void tick(); }, 15_000).unref();
}

export function stopScanScheduler(): void {
  if (timer) {
    clearInterval(timer);
    timer = null;
  }
}
