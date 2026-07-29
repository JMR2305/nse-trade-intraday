/**
 * event-intelligence.ts — Phase 7.2
 * REST routes for the Event & Corporate Intelligence Hub.
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

/** GET /api/event-intelligence/summary */
router.get("/event-intelligence/summary", async (_req, res) => {
  try { res.json(await runPython(["event_intelligence_summary"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

/** GET /api/event-intelligence/corporate */
router.get("/event-intelligence/corporate", async (_req, res) => {
  try { res.json(await runPython(["event_intelligence_corporate"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

/** GET /api/event-intelligence/regulatory */
router.get("/event-intelligence/regulatory", async (_req, res) => {
  try { res.json(await runPython(["event_intelligence_regulatory"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

/** GET /api/event-intelligence/news */
router.get("/event-intelligence/news", async (_req, res) => {
  try { res.json(await runPython(["event_intelligence_news"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

/** GET /api/event-intelligence/timeline */
router.get("/event-intelligence/timeline", async (_req, res) => {
  try { res.json(await runPython(["event_intelligence_timeline"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

/** GET /api/event-intelligence/brief */
router.get("/event-intelligence/brief", async (_req, res) => {
  try { res.json(await runPython(["event_intelligence_brief"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

/** GET /api/event-intelligence/export/csv */
router.get("/event-intelligence/export/csv", async (_req, res) => {
  try {
    const data = await runPython(["event_intelligence_export_csv"]) as Record<string, unknown>;
    const csv = data.csv as string | undefined;
    if (!csv) { res.status(503).json({ error: "Feature disabled or no data" }); return; }
    res.setHeader("Content-Type", "text/csv");
    res.setHeader("Content-Disposition", "attachment; filename=event-intelligence.csv");
    res.send(csv);
  } catch (e) { res.status(500).json({ error: String(e) }); }
});

/** GET /api/event-intelligence/export/json */
router.get("/event-intelligence/export/json", async (_req, res) => {
  try {
    const data = await runPython(["event_intelligence_export_json"]) as Record<string, unknown>;
    const json = data.json as string | undefined;
    if (!json) { res.status(503).json({ error: "Feature disabled or no data" }); return; }
    res.setHeader("Content-Type", "application/json");
    res.setHeader("Content-Disposition", "attachment; filename=event-intelligence.json");
    res.send(json);
  } catch (e) { res.status(500).json({ error: String(e) }); }
});

export default router;
