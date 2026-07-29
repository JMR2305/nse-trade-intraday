/**
 * risk-optimisation.ts — Phase 6.4
 * Risk Optimisation & Capital Allocation Intelligence API routes.
 *
 * GET /api/risk-optimisation/summary
 * GET /api/risk-optimisation/capital
 * GET /api/risk-optimisation/drawdown
 * GET /api/risk-optimisation/stress
 * GET /api/risk-optimisation/recommendations
 * GET /api/risk-optimisation/export/csv
 * GET /api/risk-optimisation/export/json
 *
 * READ-ONLY. ADVISORY-ONLY.
 * No orders, portfolio, strategies, signals, risk engine, or position sizes
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

router.get("/risk-optimisation/summary", async (_req, res) => {
  try { res.json(await runPython(["risk_optimisation_summary"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

router.get("/risk-optimisation/capital", async (_req, res) => {
  try { res.json(await runPython(["risk_optimisation_capital"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

router.get("/risk-optimisation/drawdown", async (_req, res) => {
  try { res.json(await runPython(["risk_optimisation_drawdown"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

router.get("/risk-optimisation/stress", async (_req, res) => {
  try { res.json(await runPython(["risk_optimisation_stress"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

router.get("/risk-optimisation/recommendations", async (_req, res) => {
  try { res.json(await runPython(["risk_optimisation_recommendations"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

router.get("/risk-optimisation/export/csv", async (_req, res) => {
  try {
    const result = await runPython(["risk_optimisation_export_csv"]) as Record<string, unknown>;
    if (result?.status === "DISABLED") { res.status(403).json(result); return; }
    res.setHeader("Content-Type", "text/csv");
    res.setHeader("Content-Disposition", "attachment; filename=risk_optimisation.csv");
    res.send(String(result?.csv ?? ""));
  } catch (e) { res.status(500).json({ error: String(e) }); }
});

router.get("/risk-optimisation/export/json", async (_req, res) => {
  try {
    const result = await runPython(["risk_optimisation_export_json"]) as Record<string, unknown>;
    if (result?.status === "DISABLED") { res.status(403).json(result); return; }
    res.setHeader("Content-Type", "application/json");
    res.setHeader("Content-Disposition", "attachment; filename=risk_optimisation.json");
    res.send(String(result?.json ?? "{}"));
  } catch (e) { res.status(500).json({ error: String(e) }); }
});

export default router;
