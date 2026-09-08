/**
 * ohlcvCache.ts — Local NIFTY 50 OHLCV cache routes.
 *
 * GET  /ohlcv-cache/status          — per-symbol cache health + overall summary
 * POST /ohlcv-cache/backfill        — backfill 6-month history for all symbols
 * POST /ohlcv-cache/postmarket-refresh — trigger post-market daily-bar append
 * GET  /ohlcv-cache/readiness       — pre-market data readiness check
 * GET  /ohlcv-cache/company-master  — list all company master entries
 * POST /ohlcv-cache/company-master/bootstrap — seed from config.SECTOR_MAP
 *
 * All routes are read-only or advisory. No order placement. PAPER TRADING ONLY.
 */

import { Router, type IRouter } from "express";
import path from "path";
import { spawn } from "child_process";
import { PYTHON_DIR, PYTHON_BIN } from "../lib/python-env";

const router: IRouter = Router();

const LIVE_STATUS_CACHE_CONTROL = "no-store, no-cache, must-revalidate, proxy-revalidate";
function setLiveStatusNoStore(res: any): void {
  res.set("Cache-Control", LIVE_STATUS_CACHE_CONTROL);
  res.set("Pragma", "no-cache");
  res.set("Expires", "0");
  res.set("Surrogate-Control", "no-store");
}

function runPython(
  args: string[],
  timeoutMs = 60_000,
): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], {
      cwd: PYTHON_DIR,
      env: process.env,
    });
    let stdout = "";
    let stderr = "";
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      proc.kill("SIGTERM");
      reject(new Error(`Python timed out after ${timeoutMs / 1000}s`));
    }, timeoutMs);
    proc.stdout.on("data", (d: Buffer) => { stdout += d.toString(); });
    proc.stderr.on("data", (d: Buffer) => { stderr += d.toString(); });
    proc.on("close", (code) => {
      clearTimeout(timer);
      if (timedOut) return;
      if (code !== 0) {
        try {
          const parsed = JSON.parse(stdout.trim());
          if (parsed?.error) return reject(new Error(parsed.error));
        } catch { /* ignore */ }
        reject(new Error(stderr || `Python exited ${code}`));
      } else {
        // Parse last JSON line (runPython convention)
        const lines = stdout.trim().split("\n");
        for (let i = lines.length - 1; i >= 0; i--) {
          try { return resolve(JSON.parse(lines[i]!)); } catch { /* skip */ }
        }
        reject(new Error(`No JSON in output: ${stdout.slice(0, 200)}`));
      }
    });
    proc.on("error", (err) => { clearTimeout(timer); reject(err); });
  });
}

const wrap = (fn: (req: any, res: any) => Promise<void>) =>
  async (req: any, res: any) => {
    try { await fn(req, res); }
    catch (err: unknown) {
      res.status(500).json({
        success: false,
        error: err instanceof Error ? err.message : String(err),
      });
    }
  };

/** GET /ohlcv-cache/status */
router.get("/ohlcv-cache/status", wrap(async (_req, res) => {
  setLiveStatusNoStore(res);
  const data = await runPython(["ohlcv_cache_status"], 30_000);
  res.json(data);
}));

/** POST /ohlcv-cache/backfill — optional ?force=true */
router.post("/ohlcv-cache/backfill", wrap(async (req, res) => {
  const force = req.query["force"] === "true" || req.body?.force === true ? "1" : "0";
  // Backfill can take up to 5 minutes for a cold start
  const data = await runPython(["ohlcv_backfill", force], 360_000);
  res.json(data);
}));

/** POST /ohlcv-cache/postmarket-refresh */
router.post("/ohlcv-cache/postmarket-refresh", wrap(async (_req, res) => {
  const data = await runPython(["ohlcv_postmarket_refresh"], 120_000);
  res.json(data);
}));

/** GET /ohlcv-cache/readiness */
router.get("/ohlcv-cache/readiness", wrap(async (_req, res) => {
  setLiveStatusNoStore(res);
  const data = await runPython(["pre_market_data_readiness"], 30_000);
  res.json(data);
}));

/** GET /ohlcv-cache/company-master */
router.get("/ohlcv-cache/company-master", wrap(async (_req, res) => {
  const data = await runPython(["company_master_list"], 15_000);
  res.json(data);
}));

/** POST /ohlcv-cache/company-master/bootstrap */
router.post("/ohlcv-cache/company-master/bootstrap", wrap(async (_req, res) => {
  const data = await runPython(["company_master_bootstrap"], 30_000);
  res.json(data);
}));

export default router;
