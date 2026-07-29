/**
 * market-intelligence.ts — Phase 7.1
 * Market Intelligence Hub API routes.
 *
 * GET /api/market-intelligence/summary
 * GET /api/market-intelligence/sectors
 * GET /api/market-intelligence/watchlist
 * GET /api/market-intelligence/breadth
 * GET /api/market-intelligence/overview
 * GET /api/market-intelligence/export/csv
 * GET /api/market-intelligence/export/json
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

router.get("/market-intelligence/summary", async (_req, res) => {
  try { res.json(await runPython(["market_intelligence_summary"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

router.get("/market-intelligence/sectors", async (_req, res) => {
  try { res.json(await runPython(["market_intelligence_sectors"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

router.get("/market-intelligence/watchlist", async (_req, res) => {
  try { res.json(await runPython(["market_intelligence_watchlist"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

router.get("/market-intelligence/breadth", async (_req, res) => {
  try { res.json(await runPython(["market_intelligence_breadth"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

router.get("/market-intelligence/overview", async (_req, res) => {
  try { res.json(await runPython(["market_intelligence_overview"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

router.get("/market-intelligence/export/csv", async (_req, res) => {
  try {
    const result = await runPython(["market_intelligence_export_csv"]) as Record<string, unknown>;
    if (result?.status === "DISABLED") { res.status(403).json(result); return; }
    res.setHeader("Content-Type", "text/csv");
    res.setHeader("Content-Disposition", "attachment; filename=market_intelligence.csv");
    res.send(String(result?.csv ?? ""));
  } catch (e) { res.status(500).json({ error: String(e) }); }
});

router.get("/market-intelligence/export/json", async (_req, res) => {
  try {
    const result = await runPython(["market_intelligence_export_json"]) as Record<string, unknown>;
    if (result?.status === "DISABLED") { res.status(403).json(result); return; }
    res.setHeader("Content-Type", "application/json");
    res.setHeader("Content-Disposition", "attachment; filename=market_intelligence.json");
    res.send(String(result?.json ?? "{}"));
  } catch (e) { res.status(500).json({ error: String(e) }); }
});

export default router;
