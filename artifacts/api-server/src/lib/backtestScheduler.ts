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
 */
import { spawn } from "child_process";
import path from "path";
import { logger } from "./logger";
import { PYTHON_BIN, PYTHON_DIR } from "./python-env";

const TICK_INTERVAL_MS = 2 * 60 * 1000; // 2 minutes
const TICK_TIMEOUT_MS  = 30_000;         // 30 s max per tick (sweep is a fast DB query)

let tickInFlight = false;
let timer: NodeJS.Timeout | null = null;

async function runQueueTick(): Promise<void> {
  if (tickInFlight) return; // never stack ticks in the same process
  tickInFlight = true;
  try {
    await new Promise<void>((resolve) => {
      const proc = spawn(
        PYTHON_BIN,
        [path.join(PYTHON_DIR, "main.py"), "bt_queue_tick"],
        { cwd: PYTHON_DIR, env: process.env },
      );
      let out = "";
      const timeout = setTimeout(() => {
        proc.kill("SIGKILL");
        logger.warn("Backtest queue tick timed out after 30 s — killed");
        resolve();
      }, TICK_TIMEOUT_MS);
      proc.stdout.on("data", (d: Buffer) => { out += d.toString(); });
      // Swallow stderr — bt_queue_tick errors are non-critical background work
      proc.stderr.on("data", (_d: Buffer) => { /* intentionally empty */ });
      proc.on("error", (_err) => { clearTimeout(timeout); resolve(); });
      proc.on("close", (_code) => {
        clearTimeout(timeout);
        try {
          const r = JSON.parse(out.trim()) as Record<string, unknown>;
          const swept   = Number(r["swept"]   ?? 0);
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
          // ignore parse errors — bt_queue_tick may emit nothing when idle
        }
        resolve();
      });
    });
  } catch {
    /* swallow — queue tick is non-critical; next tick will retry */
  } finally {
    tickInFlight = false;
  }
}

export function startBacktestScheduler(): void {
  if (timer) return; // idempotent — safe to call more than once
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
}
