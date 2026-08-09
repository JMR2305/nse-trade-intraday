/**
 * Phase 26D — Reports & Readiness Dashboard API.
 *
 * POST /api/phase26d/daily-report/run      — build + persist today's report
 * GET  /api/phase26d/daily-report/latest   — newest persisted daily report
 * GET  /api/phase26d/daily-report/history  — newest-first summaries (?limit)
 * GET  /api/phase26d/five-day              — five-day acceptance tracker
 * GET  /api/phase26d/readiness             — final production readiness
 *                                            report (on-demand, cached)
 *
 * Presentation-only aggregation of persisted Phase 26 validation results —
 * READ-ONLY over all canonical stores (the only write is the append-only
 * daily-report row). PAPER TRADING / RESEARCH ONLY.
 */
import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import path from "path";
import { PYTHON_BIN, PYTHON_DIR } from "../lib/python-env";

const router: IRouter = Router();

function runPython(args: string[], timeoutMs = 120_000): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], {
      cwd: PYTHON_DIR,
      env: process.env,
    });
    const timer = setTimeout(() => {
      proc.kill("SIGKILL");
      reject(new Error(`python timed out after ${timeoutMs}ms`));
    }, timeoutMs);
    let out = "";
    let err = "";
    proc.stdout.on("data", (d) => (out += d));
    proc.stderr.on("data", (d) => (err += d));
    proc.on("close", (code) => {
      clearTimeout(timer);
      if (code !== 0) return reject(new Error(err || `python exited ${code}`));
      try {
        resolve(JSON.parse(out));
      } catch {
        reject(new Error("invalid JSON from python"));
      }
    });
  });
}

function fail(res: any, err: unknown): void {
  res.status(500).json({
    success: false,
    error: err instanceof Error ? err.message : String(err),
  });
}

// Cache + single-flight: the readiness/five-day aggregators fan out over
// several persisted stores; identical concurrent requests must never stack.
const cache = new Map<string, { at: number; value: unknown }>();
const inflight = new Map<string, Promise<unknown>>();
function cachedSingleFlight(
  key: string,
  factory: () => Promise<unknown>,
  ttlMs = 30_000,
): Promise<unknown> {
  const hit = cache.get(key);
  if (hit && Date.now() - hit.at < ttlMs) return Promise.resolve(hit.value);
  const running = inflight.get(key);
  if (running) return running;
  const p = factory()
    .then((value) => {
      cache.set(key, { at: Date.now(), value });
      return value;
    })
    .finally(() => inflight.delete(key));
  inflight.set(key, p);
  return p;
}

// POST /api/phase26d/daily-report/run — manual build + persist (append-only)
router.post("/phase26d/daily-report/run", async (req, res) => {
  try {
    const payload: Record<string, unknown> = {};
    const d = String(req.body?.report_date ?? "");
    if (/^\d{4}-\d{2}-\d{2}$/.test(d)) payload.report_date = d;
    const result = await runPython(
      ["p26d_daily_run", JSON.stringify(payload)],
      180_000,
    );
    cache.delete("daily-latest");
    cache.delete("five-day");
    cache.delete("readiness");
    res.json(result);
  } catch (err) {
    fail(res, err);
  }
});

// GET /api/phase26d/daily-report/latest
router.get("/phase26d/daily-report/latest", async (_req, res) => {
  try {
    res.json(
      await cachedSingleFlight("daily-latest", () =>
        runPython(["p26d_daily_latest"], 60_000),
      ),
    );
  } catch (err) {
    fail(res, err);
  }
});

// GET /api/phase26d/daily-report/history?limit=30
router.get("/phase26d/daily-report/history", async (req, res) => {
  try {
    const limit = Math.max(1, Math.min(Number(req.query.limit) || 30, 200));
    res.json(
      await cachedSingleFlight(`daily-history:${limit}`, () =>
        runPython(["p26d_daily_history", JSON.stringify({ limit })], 60_000),
      ),
    );
  } catch (err) {
    fail(res, err);
  }
});

// GET /api/phase26d/five-day — acceptance tracker
router.get("/phase26d/five-day", async (_req, res) => {
  try {
    res.json(
      await cachedSingleFlight("five-day", () =>
        runPython(["p26d_five_day"], 60_000),
      ),
    );
  } catch (err) {
    fail(res, err);
  }
});

// GET /api/phase26d/readiness — final production readiness report
router.get("/phase26d/readiness", async (_req, res) => {
  try {
    res.json(
      await cachedSingleFlight("readiness", () =>
        runPython(["p26d_readiness"], 120_000),
      ),
    );
  } catch (err) {
    fail(res, err);
  }
});

export default router;
