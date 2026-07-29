/**
 * optimisation.ts — Phase 6.2
 * Strategy Optimisation & Adaptive Learning API routes.
 *
 * GET /api/optimisation/summary
 * GET /api/optimisation/strategies
 * GET /api/optimisation/recommendations
 * GET /api/optimisation/patterns
 * GET /api/optimisation/export/csv
 * GET /api/optimisation/export/json
 *
 * READ-ONLY. ADVISORY-ONLY.
 * No strategy parameters, orders, portfolio, signals, or risk engine
 * are ever modified by this module.
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

router.get("/optimisation/summary", async (_req, res) => {
  try { res.json(await runPython(["optimisation_summary"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

router.get("/optimisation/strategies", async (_req, res) => {
  try { res.json(await runPython(["optimisation_strategies"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

router.get("/optimisation/recommendations", async (_req, res) => {
  try { res.json(await runPython(["optimisation_recommendations"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

router.get("/optimisation/patterns", async (_req, res) => {
  try { res.json(await runPython(["optimisation_patterns"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

router.get("/optimisation/export/csv", async (_req, res) => {
  try {
    const result = await runPython(["optimisation_export_csv"]) as Record<string, unknown>;
    if (result?.status === "DISABLED") { res.status(403).json(result); return; }
    res.setHeader("Content-Type", "text/csv");
    res.setHeader("Content-Disposition", "attachment; filename=strategy_optimisation.csv");
    res.send(String(result?.csv ?? ""));
  } catch (e) { res.status(500).json({ error: String(e) }); }
});

router.get("/optimisation/export/json", async (_req, res) => {
  try {
    const result = await runPython(["optimisation_export_json"]) as Record<string, unknown>;
    if (result?.status === "DISABLED") { res.status(403).json(result); return; }
    res.setHeader("Content-Type", "application/json");
    res.setHeader("Content-Disposition", "attachment; filename=strategy_optimisation.json");
    res.send(String(result?.json ?? "{}"));
  } catch (e) { res.status(500).json({ error: String(e) }); }
});

export default router;
