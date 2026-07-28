/**
 * executionQuality.ts — Phase 5D.1 API routes.
 *
 * 4 read-only endpoints:
 *   GET /api/execution-quality/summary
 *   GET /api/execution-quality/trades
 *   GET /api/execution-quality/slippage
 *   GET /api/execution-quality/fills
 *
 * EXECUTION_QUALITY_ENABLED=false → every endpoint returns { "status": "DISABLED" }.
 * No order submission. No strategy modification. No portfolio mutation.
 * PAPER TRADING / ADVISORY ONLY.
 */
import { Router } from "express";
import { spawn } from "child_process";
import path from "path";
import { PYTHON_DIR, PYTHON_BIN } from "../lib/python-env";

const router = Router();

function runPython(args: string[]): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const child = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], {
      cwd: PYTHON_DIR,
      env: process.env,
    });
    let out = "";
    let err = "";
    child.stdout.on("data", (d: Buffer) => { out += d.toString(); });
    child.stderr.on("data", (d: Buffer) => { err += d.toString(); });
    child.on("error", (e: Error) => reject(e));
    child.on("close", (code) => {
      try {
        resolve(JSON.parse(out));
      } catch {
        reject(new Error(code !== 0 ? err || `exit ${code}` : `Bad JSON: ${out.slice(0, 200)}`));
      }
    });
  });
}

// GET /api/execution-quality/summary
router.get("/execution-quality/summary", async (req, res) => {
  try {
    const date = typeof req.query.date === "string" ? req.query.date : undefined;
    const args = ["execution_quality_summary", ...(date ? [date] : [])];
    res.json(await runPython(args));
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

// GET /api/execution-quality/trades
router.get("/execution-quality/trades", async (req, res) => {
  try {
    const date   = typeof req.query.date   === "string" ? req.query.date   : undefined;
    const limit  = Math.min(parseInt(String(req.query.limit  ?? "200"), 10) || 200, 500);
    const offset = Math.max(parseInt(String(req.query.offset ?? "0"),   10) || 0,   0);
    const args   = ["execution_quality_trades",
      String(limit), String(offset), ...(date ? [date] : [])];
    res.json(await runPython(args));
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

// GET /api/execution-quality/slippage
router.get("/execution-quality/slippage", async (req, res) => {
  try {
    const date = typeof req.query.date === "string" ? req.query.date : undefined;
    const args = ["execution_quality_slippage", ...(date ? [date] : [])];
    res.json(await runPython(args));
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

// GET /api/execution-quality/fills
router.get("/execution-quality/fills", async (req, res) => {
  try {
    const date = typeof req.query.date === "string" ? req.query.date : undefined;
    const args = ["execution_quality_fills", ...(date ? [date] : [])];
    res.json(await runPython(args));
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

export default router;
