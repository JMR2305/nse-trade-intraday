/**
 * Backtest Queue Scheduler
 *
 * Runs every 2 minutes independently of browser activity.
 * Ensures QUEUED runs advance and stale RUNNING workers are detected
 * even when no operator has the Investigation Center open.
 *
 * Each tick calls the ``bt_queue_tick`` Python command which:
 *   1. Marks RUNNING/PENDING runs with no heartbeat for 30+ min → STALE
 *   2. Promotes QUEUED → PENDING when concurrency slots open
 *   3. Spawns a detached worker subprocess for each newly-promoted run
 *
 * Non-critical by design: errors are swallowed, ticks never stack,
 * and the timer is unref'd so it cannot prevent clean server shutdown.
 *
 * Health tracking:
 *   last_sweep_at      — ISO timestamp of the last *successful* tick (exit 0 + valid JSON).
 *                        Only updated when the sweep actually ran. A timeout or non-zero
 *                        exit does NOT update this field.
 *   last_attempt_at    — ISO timestamp of the most recent tick attempt (success or failure).
 *   consecutive_failures — Count of consecutive ticks that did NOT produce a successful sweep.
 *                          Resets to 0 on each success.
 *   last_error         — Human-readable description of the most recent failure, or null.
 */
import { spawn } from "child_process";
import path from "path";
import { logger } from "./logger";
import { PYTHON_BIN, PYTHON_DIR } from "./python-env";

export const TICK_INTERVAL_MS = 2 * 60 * 1000; // 2 minutes
export const TICK_TIMEOUT_MS  = 30_000;         // 30 s max per tick (sweep is a fast DB query)

let tickInFlight = false;
let timer: NodeJS.Timeout | null = null;

/** Mutable scheduler health state — updated exclusively by runQueueTick(). */
let schedulerEnabled       = false;
let lastSweepAt: string | null = null;        // set only on success
let lastAttemptAt: string | null = null;      // set on every attempt
let consecutiveFailures    = 0;
let lastError: string | null = null;

export interface SchedulerStatus {
  enabled: boolean;
  last_sweep_at: string | null;
  last_attempt_at: string | null;
  consecutive_failures: number;
  last_error: string | null;
}

/** Returns a snapshot of the scheduler's current state for the status endpoint. */
export function getSchedulerStatus(): SchedulerStatus {
  return {
    enabled: schedulerEnabled,
    last_sweep_at: lastSweepAt,
    last_attempt_at: lastAttemptAt,
    consecutive_failures: consecutiveFailures,
    last_error: lastError,
  };
}

/** Reset all mutable state — only for use in tests. */
export function _resetSchedulerStateForTests(): void {
  schedulerEnabled = false;
  lastSweepAt = null;
  lastAttemptAt = null;
  consecutiveFailures = 0;
  lastError = null;
  tickInFlight = false;
  if (timer) { clearInterval(timer); timer = null; }
}

/**
 * Run one queue tick directly — exported for unit tests only.
 * Avoids the need for fake timers to drive the 45-second stagger.
 */
export async function _runQueueTickForTests(): Promise<void> {
  return runQueueTick();
}

async function runQueueTick(): Promise<void> {
  if (tickInFlight) return; // never stack ticks in the same process
  tickInFlight = true;
  lastAttemptAt = new Date().toISOString();
  try {
    await new Promise<void>((resolve) => {
      let didTimeout = false;

      const proc = spawn(
        PYTHON_BIN,
        [path.join(PYTHON_DIR, "main.py"), "bt_queue_tick"],
        { cwd: PYTHON_DIR, env: process.env },
      );
      let out = "";
      const timeout = setTimeout(() => {
        didTimeout = true;
        proc.kill("SIGKILL");
        consecutiveFailures++;
        lastError = "bt_queue_tick timed out after 30 s";
        logger.warn("Backtest queue tick timed out after 30 s — killed");
        resolve();
      }, TICK_TIMEOUT_MS);

      proc.stdout.on("data", (d: Buffer) => { out += d.toString(); });
      // Swallow stderr — bt_queue_tick errors are non-critical background work
      proc.stderr.on("data", (_d: Buffer) => { /* intentionally empty */ });

      proc.on("error", (err) => {
        clearTimeout(timeout);
        consecutiveFailures++;
        lastError = `Failed to spawn bt_queue_tick: ${err.message}`;
        logger.warn({ err }, "Backtest queue tick spawn error");
        resolve();
      });

      proc.on("close", (code) => {
        clearTimeout(timeout);

        // Timeout already recorded a failure; the close event fires after the
        // SIGKILL but must not overwrite the failure state with a success stamp.
        if (didTimeout) { resolve(); return; }

        if (code !== 0) {
          consecutiveFailures++;
          lastError = `bt_queue_tick exited with code ${code ?? "null"}`;
          logger.warn({ code }, "Backtest queue tick exited with non-zero code");
          resolve();
          return;
        }

        // Exit code 0 — attempt to parse the result for structured logging.
        try {
          const r = JSON.parse(out.trim()) as Record<string, unknown>;
          const swept    = Number(r["swept"]    ?? 0);
          const promoted = Number(r["promoted"] ?? 0);
          // spawned_count is the scalar; spawned is the list (prefer list length)
          const spawnedArr = Array.isArray(r["spawned"]) ? r["spawned"] : [];
          const spawned = spawnedArr.length || Number(r["spawned_count"] ?? 0);
          if (swept > 0 || promoted > 0) {
            logger.info(
              { swept, promoted, spawned },
              "Backtest queue tick: swept stale runs / promoted queued / spawned workers",
            );
          }
        } catch {
          // bt_queue_tick may emit nothing when idle — that is fine and still a
          // successful sweep (the process exited 0).
        }

        // ── Mark successful only here ─────────────────────────────────────
        lastSweepAt = new Date().toISOString();
        consecutiveFailures = 0;
        lastError = null;
        resolve();
      });
    });
  } catch {
    /* swallow — queue tick is non-critical; next tick will retry */
    consecutiveFailures++;
    lastError = "Unexpected error during queue tick";
  } finally {
    tickInFlight = false;
  }
}

export function startBacktestScheduler(): void {
  if (process.env["DISABLE_BACKTEST_SCHEDULER"] === "true") {
    logger.info("Backtest queue scheduler disabled via DISABLE_BACKTEST_SCHEDULER");
    return;
  }
  if (timer) return; // idempotent — safe to call more than once
  schedulerEnabled = true;
  timer = setInterval(() => { void runQueueTick(); }, TICK_INTERVAL_MS);
  timer.unref(); // never prevent clean shutdown
  logger.info(
    { tickIntervalMs: TICK_INTERVAL_MS },
    "Backtest queue scheduler started (sweeps stale + promotes queued every 2 min)",
  );
  // Stagger the first tick 45 s after startup so all Python modules are warm
  // and the scan scheduler has already taken its initial tick.
  setTimeout(() => { void runQueueTick(); }, 45_000).unref();
}

export function stopBacktestScheduler(): void {
  if (timer) {
    clearInterval(timer);
    timer = null;
  }
  schedulerEnabled = false;
}
