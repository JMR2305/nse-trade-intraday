/**
 * phase26c-validation.ts — Phase 26C: Recovery, Performance & Quality
 * Validation API.
 *
 * Read-only validation over canonical stores; results persist append-only
 * (phase26c_results) and FAIL findings feed the Phase 26 issue store.
 *
 * Routes:
 *   POST /phase26c/recovery/run       — run the recovery validation suite
 *   POST /phase26c/performance/run    — run the performance validation
 *   POST /phase26c/quality/run        — run the trading-quality validation
 *   GET  /phase26c/:area/latest       — latest persisted result for one area
 *   GET  /phase26c/:area/history      — recent run summaries (?limit=)
 */

import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import path from "path";
import { PYTHON_DIR, PYTHON_BIN } from "../lib/python-env";

const router: IRouter = Router();

const AREAS = new Set(["recovery", "performance", "quality"]);
const RUN_COMMANDS: Record<string, string> = {
  recovery: "recovery_validation_run",
  performance: "performance_validation_run",
  quality: "trading_quality_run",
};

function runPython(args: string[], timeoutMs = 120_000): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], {
      cwd: PYTHON_DIR,
    });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      proc.kill("SIGTERM");
      reject(new Error(`Phase 26C Python timed out (${args[0] ?? "?"})`));
    }, timeoutMs);
    proc.stdout.on("data", (d: Buffer) => { stdout += d.toString(); });
    proc.stderr.on("data", (d: Buffer) => { stderr += d.toString(); });
    proc.on("close", (code) => {
      clearTimeout(timer);
      if (code !== 0) {
        try {
          const p = JSON.parse(stdout.trim());
          if (p.error) return reject(new Error(p.error));
        } catch { /* ignore */ }
        reject(new Error(stderr || `Python exited ${code}`));
      } else {
        try { resolve(JSON.parse(stdout.trim())); }
        catch { reject(new Error(`Bad JSON: ${stdout.slice(0, 200)}`)); }
      }
    });
    proc.on("error", reject);
  });
}

// POST /api/phase26c/:area/run
router.post("/phase26c/:area/run", async (req, res) => {
  const area = String(req.params.area || "").toLowerCase();
  if (!AREAS.has(area)) {
    res.status(400).json({ error: `unknown area '${area}' — expected recovery|performance|quality` });
    return;
  }
  try {
    res.json(await runPython([RUN_COMMANDS[area]]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/phase26c/:area/latest
router.get("/phase26c/:area/latest", async (req, res) => {
  const area = String(req.params.area || "").toLowerCase();
  if (!AREAS.has(area)) {
    res.status(400).json({ error: `unknown area '${area}' — expected recovery|performance|quality` });
    return;
  }
  try {
    res.json(await runPython(["phase26c_latest", JSON.stringify({ area })]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/phase26c/:area/history?limit=
router.get("/phase26c/:area/history", async (req, res) => {
  const area = String(req.params.area || "").toLowerCase();
  if (!AREAS.has(area)) {
    res.status(400).json({ error: `unknown area '${area}' — expected recovery|performance|quality` });
    return;
  }
  try {
    const limit = Math.max(1, Math.min(Number(req.query.limit) || 50, 500));
    res.json(await runPython(["phase26c_history", JSON.stringify({ area, limit })]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

export default router;
