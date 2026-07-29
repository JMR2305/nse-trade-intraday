/**
 * readiness.ts — Phase 6.5
 * Live Readiness & Operational Validation API routes.
 *
 * GET /api/readiness/summary
 * GET /api/readiness/system
 * GET /api/readiness/data
 * GET /api/readiness/recovery
 * GET /api/readiness/security
 * GET /api/readiness/report
 * GET /api/readiness/export/csv
 * GET /api/readiness/export/json
 *
 * READ-ONLY. ADVISORY-ONLY.
 * This module NEVER enables live trading, places orders, or modifies any
 * trading engine, portfolio, strategies, signals, AI models, or risk parameters.
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

router.get("/readiness/summary", async (_req, res) => {
  try { res.json(await runPython(["readiness_summary"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

router.get("/readiness/system", async (_req, res) => {
  try { res.json(await runPython(["readiness_system"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

router.get("/readiness/data", async (_req, res) => {
  try { res.json(await runPython(["readiness_data"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

router.get("/readiness/recovery", async (_req, res) => {
  try { res.json(await runPython(["readiness_recovery"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

router.get("/readiness/security", async (_req, res) => {
  try { res.json(await runPython(["readiness_security"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

router.get("/readiness/report", async (_req, res) => {
  try { res.json(await runPython(["readiness_report"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

router.get("/readiness/export/csv", async (_req, res) => {
  try {
    const result = await runPython(["readiness_export_csv"]) as Record<string, unknown>;
    if (result?.status === "DISABLED") { res.status(403).json(result); return; }
    res.setHeader("Content-Type", "text/csv");
    res.setHeader("Content-Disposition", "attachment; filename=readiness_report.csv");
    res.send(String(result?.csv ?? ""));
  } catch (e) { res.status(500).json({ error: String(e) }); }
});

router.get("/readiness/export/json", async (_req, res) => {
  try {
    const result = await runPython(["readiness_export_json"]) as Record<string, unknown>;
    if (result?.status === "DISABLED") { res.status(403).json(result); return; }
    res.setHeader("Content-Type", "application/json");
    res.setHeader("Content-Disposition", "attachment; filename=readiness_report.json");
    res.send(String(result?.json ?? "{}"));
  } catch (e) { res.status(500).json({ error: String(e) }); }
});

export default router;
