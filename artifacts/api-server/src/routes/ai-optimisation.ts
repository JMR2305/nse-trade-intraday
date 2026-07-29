/**
 * ai-optimisation.ts — Phase 6.3
 * AI Optimisation & Continuous Learning Framework API routes.
 *
 * GET /api/ai-optimisation/summary
 * GET /api/ai-optimisation/calibration
 * GET /api/ai-optimisation/drift
 * GET /api/ai-optimisation/recommendations
 * GET /api/ai-optimisation/history
 * GET /api/ai-optimisation/export/csv
 * GET /api/ai-optimisation/export/json
 *
 * READ-ONLY. ADVISORY-ONLY.
 * No AI models, trading engine, orders, portfolio, signals, risk engine,
 * or strategies are ever modified by this module.
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
    child.on("close", (code) => {
      if (code !== 0) {
        try { resolve(JSON.parse(out)); } catch { reject(new Error(err || `exit ${code}`)); }
        return;
      }
      try { resolve(JSON.parse(out)); } catch { reject(new Error(`Invalid JSON: ${out.slice(0, 200)}`)); }
    });
  });
}

router.get("/ai-optimisation/summary", async (_req, res) => {
  try { res.json(await runPython(["ai_optimisation_summary"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

router.get("/ai-optimisation/calibration", async (_req, res) => {
  try { res.json(await runPython(["ai_optimisation_calibration"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

router.get("/ai-optimisation/drift", async (_req, res) => {
  try { res.json(await runPython(["ai_optimisation_drift"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

router.get("/ai-optimisation/recommendations", async (_req, res) => {
  try { res.json(await runPython(["ai_optimisation_recommendations"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

router.get("/ai-optimisation/history", async (_req, res) => {
  try { res.json(await runPython(["ai_optimisation_history"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

router.get("/ai-optimisation/export/csv", async (_req, res) => {
  try {
    const result = await runPython(["ai_optimisation_export_csv"]) as Record<string, unknown>;
    if (result?.status === "DISABLED") { res.status(403).json(result); return; }
    res.setHeader("Content-Type", "text/csv");
    res.setHeader("Content-Disposition", "attachment; filename=ai_optimisation.csv");
    res.send(String(result?.csv ?? ""));
  } catch (e) { res.status(500).json({ error: String(e) }); }
});

router.get("/ai-optimisation/export/json", async (_req, res) => {
  try {
    const result = await runPython(["ai_optimisation_export_json"]) as Record<string, unknown>;
    if (result?.status === "DISABLED") { res.status(403).json(result); return; }
    res.setHeader("Content-Type", "application/json");
    res.setHeader("Content-Disposition", "attachment; filename=ai_optimisation.json");
    res.send(String(result?.json ?? "{}"));
  } catch (e) { res.status(500).json({ error: String(e) }); }
});

export default router;
