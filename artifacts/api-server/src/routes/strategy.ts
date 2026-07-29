/**
 * strategy.ts — Phase 5D.3 Strategy Intelligence API routes.
 *
 * 6 read-only endpoints:
 *   GET /api/strategy/summary
 *   GET /api/strategy/rankings
 *   GET /api/strategy/regimes
 *   GET /api/strategy/sectors
 *   GET /api/strategy/timing
 *   GET /api/strategy/recommendations
 *
 * STRATEGY_INTELLIGENCE_ENABLED=false → every endpoint returns { "status": "DISABLED" }.
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

// GET /api/strategy/summary
router.get("/strategy/summary", async (req, res) => {
  try {
    res.json(await runPython(["strategy_summary"]));
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

// GET /api/strategy/rankings
router.get("/strategy/rankings", async (req, res) => {
  try {
    res.json(await runPython(["strategy_rankings"]));
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

// GET /api/strategy/regimes
router.get("/strategy/regimes", async (req, res) => {
  try {
    res.json(await runPython(["strategy_regimes"]));
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

// GET /api/strategy/sectors
router.get("/strategy/sectors", async (req, res) => {
  try {
    res.json(await runPython(["strategy_sectors"]));
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

// GET /api/strategy/timing
router.get("/strategy/timing", async (req, res) => {
  try {
    res.json(await runPython(["strategy_timing"]));
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

// GET /api/strategy/recommendations
router.get("/strategy/recommendations", async (req, res) => {
  try {
    res.json(await runPython(["strategy_recommendations"]));
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

export default router;
