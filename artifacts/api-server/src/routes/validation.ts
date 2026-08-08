/**
 * validation.ts — Phase 6.1
 * Paper Trading Validation & Data Collection endpoints.
 *
 * GET /api/validation/session
 * GET /api/validation/history
 * GET /api/validation/quality
 * GET /api/validation/statistics
 * GET /api/validation/export/csv
 * GET /api/validation/export/json
 *
 * READ-ONLY. ADVISORY-ONLY.
 * Never modifies trades, portfolio, strategies, orders, or signals.
 */
import { Router } from "express";
import { spawn } from "child_process";
import path from "path";
import { PYTHON_DIR, PYTHON_BIN } from "../lib/python-env";

const router = Router();

function runPython(args: string[], timeoutMs = 90_000): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const child = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], {
      cwd: PYTHON_DIR,
      env: process.env,
    });
    let out = "";
    let err = "";
    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      reject(new Error(`python ${args[0]} timed out after ${timeoutMs / 1000}s`));
    }, timeoutMs);
    child.stdout.on("data", (d: Buffer) => { out += d.toString(); });
    child.stderr.on("data", (d: Buffer) => { err += d.toString(); });
    child.on("close", (code) => {
      clearTimeout(timer);
      if (code !== 0) {
        try { resolve(JSON.parse(out)); } catch { reject(new Error(err || `exit ${code}`)); }
        return;
      }
      try { resolve(JSON.parse(out)); } catch { reject(new Error(`Invalid JSON: ${out.slice(0, 200)}`)); }
    });
  });
}

/** GET /api/validation/dashboard — aggregated validation dashboard:
 *  session context, trading statistics, historical windows, data quality,
 *  validation pipeline checklist, AI validation (phase4a_dashboard.py). */
let vDashCache: { at: number; data: unknown } | null = null;
let vDashInflight: Promise<unknown> | null = null;

router.get("/validation/dashboard", async (_req, res) => {
  try {
    if (vDashCache && Date.now() - vDashCache.at < 30_000) {
      res.json(vDashCache.data);
      return;
    }
    if (!vDashInflight) {
      vDashInflight = runPython(["validation_dashboard"], 60_000)
        .finally(() => { vDashInflight = null; });
    }
    const data = await vDashInflight;
    vDashCache = { at: Date.now(), data };
    res.json(data);
  } catch (e) { res.status(500).json({ error: String(e) }); }
});

/** GET /api/validation/session — today's session + trades + daily metrics */
router.get("/validation/session", async (_req, res) => {
  try { res.json(await runPython(["validation_session"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

/** GET /api/validation/history — daily rows + period roll-ups + dataset growth */
router.get("/validation/history", async (_req, res) => {
  try { res.json(await runPython(["validation_history"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

/** GET /api/validation/quality — data quality report */
router.get("/validation/quality", async (_req, res) => {
  try { res.json(await runPython(["validation_quality"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

/** GET /api/validation/statistics — overall validation statistics */
router.get("/validation/statistics", async (_req, res) => {
  try { res.json(await runPython(["validation_statistics"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

/** GET /api/validation/export/csv — download all trade records as CSV */
router.get("/validation/export/csv", async (_req, res) => {
  try {
    const result = await runPython(["validation_export_csv"]) as Record<string, unknown>;
    if (result?.status === "DISABLED") {
      res.status(403).json(result);
      return;
    }
    const csv = String(result?.csv ?? "");
    res.setHeader("Content-Type", "text/csv");
    res.setHeader("Content-Disposition", "attachment; filename=validation_records.csv");
    res.send(csv);
  } catch (e) { res.status(500).json({ error: String(e) }); }
});

/** GET /api/validation/export/json — download all trade records as JSON */
router.get("/validation/export/json", async (_req, res) => {
  try {
    const result = await runPython(["validation_export_json"]) as Record<string, unknown>;
    if (result?.status === "DISABLED") {
      res.status(403).json(result);
      return;
    }
    const jsonStr = String(result?.json ?? "[]");
    res.setHeader("Content-Type", "application/json");
    res.setHeader("Content-Disposition", "attachment; filename=validation_records.json");
    res.send(jsonStr);
  } catch (e) { res.status(500).json({ error: String(e) }); }
});

export default router;
