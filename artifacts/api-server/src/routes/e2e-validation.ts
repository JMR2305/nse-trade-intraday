/**
 * e2e-validation.ts — Phase 26A: End-to-End Validation Engine API
 *
 * Read-only validation over canonical stores. Runs are persisted
 * append-only and queryable forever.
 *
 * Routes:
 *   POST /e2e-validation/run          — run validation for a scan cycle
 *                                       (body: { scan_id? }; default latest)
 *   GET  /e2e-validation/history      — recent run summaries (?limit=)
 *   GET  /e2e-validation/runs/:runId  — full result for one run
 *   GET  /e2e-validation/summary      — latest run + history verdict counts
 */

import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import path from "path";
import { PYTHON_DIR, PYTHON_BIN } from "../lib/python-env";

const router: IRouter = Router();

function runPython(args: string[], timeoutMs = 60_000): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], {
      cwd: PYTHON_DIR,
    });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      proc.kill("SIGTERM");
      reject(new Error(`E2E validation Python timed out (${args[0] ?? "?"})`));
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

// POST /api/e2e-validation/run — validate one scan cycle (default: latest)
router.post("/e2e-validation/run", async (req, res) => {
  try {
    const scanId = req.body?.scan_id ? String(req.body.scan_id) : undefined;
    const payload = JSON.stringify(scanId ? { scan_id: scanId } : {});
    res.json(await runPython(["e2e_run", payload]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/e2e-validation/history
router.get("/e2e-validation/history", async (req, res) => {
  try {
    const limit = Math.max(1, Math.min(Number(req.query.limit) || 50, 500));
    res.json(await runPython(["e2e_history", JSON.stringify({ limit })]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/e2e-validation/summary
router.get("/e2e-validation/summary", async (_req, res) => {
  try {
    res.json(await runPython(["e2e_summary"]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/e2e-validation/runs/:runId
router.get("/e2e-validation/runs/:runId", async (req, res) => {
  try {
    res.json(await runPython(["e2e_get", String(req.params.runId || "")]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

export default router;
