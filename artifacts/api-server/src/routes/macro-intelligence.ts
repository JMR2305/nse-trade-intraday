/**
 * macro-intelligence.ts — Phase 7.3
 * REST routes for the Economic & Macro Intelligence Hub.
 *
 * GET /api/macro-intelligence/summary
 * GET /api/macro-intelligence/calendar
 * GET /api/macro-intelligence/global
 * GET /api/macro-intelligence/flows
 * GET /api/macro-intelligence/commodities
 * GET /api/macro-intelligence/brief
 * GET /api/macro-intelligence/export/csv
 * GET /api/macro-intelligence/export/json
 *
 * READ-ONLY. ADVISORY-ONLY.
 * This module NEVER modifies orders, portfolio, strategies, AI, risk engine or signals.
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

/** GET /api/macro-intelligence/summary */
router.get("/macro-intelligence/summary", async (_req, res) => {
  try { res.json(await runPython(["macro_intelligence_summary"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

/** GET /api/macro-intelligence/calendar */
router.get("/macro-intelligence/calendar", async (_req, res) => {
  try { res.json(await runPython(["macro_intelligence_calendar"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

/** GET /api/macro-intelligence/global */
router.get("/macro-intelligence/global", async (_req, res) => {
  try { res.json(await runPython(["macro_intelligence_global"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

/** GET /api/macro-intelligence/flows */
router.get("/macro-intelligence/flows", async (_req, res) => {
  try { res.json(await runPython(["macro_intelligence_flows"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

/** GET /api/macro-intelligence/commodities */
router.get("/macro-intelligence/commodities", async (_req, res) => {
  try { res.json(await runPython(["macro_intelligence_commodities"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

/** GET /api/macro-intelligence/brief */
router.get("/macro-intelligence/brief", async (_req, res) => {
  try { res.json(await runPython(["macro_intelligence_brief"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

/** GET /api/macro-intelligence/export/csv */
router.get("/macro-intelligence/export/csv", async (_req, res) => {
  try {
    const data = await runPython(["macro_intelligence_export_csv"]) as Record<string, unknown>;
    const csv = data.csv as string | undefined;
    if (!csv) { res.status(503).json({ error: "Feature disabled or no data" }); return; }
    res.setHeader("Content-Type", "text/csv");
    res.setHeader("Content-Disposition", "attachment; filename=macro-intelligence.csv");
    res.send(csv);
  } catch (e) { res.status(500).json({ error: String(e) }); }
});

/** GET /api/macro-intelligence/export/json */
router.get("/macro-intelligence/export/json", async (_req, res) => {
  try {
    const data = await runPython(["macro_intelligence_export_json"]) as Record<string, unknown>;
    const json = data.json as string | undefined;
    if (!json) { res.status(503).json({ error: "Feature disabled or no data" }); return; }
    res.setHeader("Content-Type", "application/json");
    res.setHeader("Content-Disposition", "attachment; filename=macro-intelligence.json");
    res.send(json);
  } catch (e) { res.status(500).json({ error: String(e) }); }
});

export default router;
