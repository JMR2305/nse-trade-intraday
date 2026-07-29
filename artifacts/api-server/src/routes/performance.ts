/**
 * performance.ts — Phase 5D.2 Portfolio Performance Intelligence API routes.
 *
 * 5 read-only endpoints:
 *   GET /api/performance/summary
 *   GET /api/performance/equity
 *   GET /api/performance/drawdown
 *   GET /api/performance/statistics
 *   GET /api/performance/portfolio
 *
 * PORTFOLIO_PERFORMANCE_ENABLED=false → every endpoint returns { "status": "DISABLED" }.
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

// GET /api/performance/summary
router.get("/performance/summary", async (req, res) => {
  try {
    res.json(await runPython(["performance_summary"]));
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

// GET /api/performance/equity?period=daily|weekly|monthly
router.get("/performance/equity", async (req, res) => {
  try {
    const period = typeof req.query.period === "string" ? req.query.period : "daily";
    res.json(await runPython(["performance_equity", period]));
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

// GET /api/performance/drawdown
router.get("/performance/drawdown", async (req, res) => {
  try {
    res.json(await runPython(["performance_drawdown"]));
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

// GET /api/performance/statistics
router.get("/performance/statistics", async (req, res) => {
  try {
    res.json(await runPython(["performance_statistics"]));
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

// GET /api/performance/portfolio
router.get("/performance/portfolio", async (req, res) => {
  try {
    res.json(await runPython(["performance_portfolio"]));
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

export default router;
