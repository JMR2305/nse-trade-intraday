import { spawn } from "child_process";
import path from "path";
import { logger } from "./logger";
import { PYTHON_DIR, PYTHON_BIN } from "./python-env";

// Phase 19B — market-hours auto-scan scheduler.
//
// Every SCAN_INTERVAL_MINUTES (default 5) this instance runs a
// "scheduled_scan_tick", which on the Python side:
//   1. Skips unless NSE is OPEN (Asia/Kolkata, holidays respected) via the
//      existing market-hours service.
//   2. Skips if the durable shared snapshot is already fresher than the
//      interval (so multiple Autoscale instances don't duplicate work).
//   3. Otherwise runs the canonical scan guarded by the distributed
//      database lease (scan_lock) with stuck-lock timeout recovery.
// A failed scheduled scan never overwrites the last successful snapshot.
// Paper trading / research only — no live orders anywhere.

const DEFAULT_INTERVAL_MIN = 5;

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
      try {
        resolve(JSON.parse(stdout.trim()));
      } catch {
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
  const raw = Number(process.env["SCAN_INTERVAL_MINUTES"]);
  const intervalMin = Number.isFinite(raw) && raw >= 1 ? raw : DEFAULT_INTERVAL_MIN;
  const intervalMs = intervalMin * 60 * 1000;

  const tick = async (): Promise<void> => {
    if (tickInFlight) return; // never stack ticks in this process
    tickInFlight = true;
    try {
      const result = (await runPython([
        "scheduled_scan_tick", String(intervalMin),
      ])) as Record<string, unknown>;
      if (result?.["ran_scan"]) {
        logger.info(
          { scan_id: result["scan_id"], snapshot_ts: result["snapshot_ts"] },
          "Scheduled market scan completed",
        );
      }
    } catch (err) {
      // Failed scheduled scan: last successful snapshot is preserved by design.
      logger.warn({ err: err instanceof Error ? err.message : String(err) },
        "Scheduled scan tick failed (previous snapshot preserved)");
    } finally {
      tickInFlight = false;
    }
  };

  timer = setInterval(() => { void tick(); }, intervalMs);
  timer.unref();
  logger.info({ intervalMin }, "Market-hours scan scheduler started");
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
