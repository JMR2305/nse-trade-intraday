/**
 * explainable-ai.ts — Phase 7.4
 * REST routes for the Explainable AI & Decision Intelligence Hub.
 *
 * GET /api/explainable-ai/summary
 * GET /api/explainable-ai/decision?symbol=
 * GET /api/explainable-ai/contributions?symbol=
 * GET /api/explainable-ai/confidence?symbol=
 * GET /api/explainable-ai/scenarios?symbol=
 * GET /api/explainable-ai/history?symbol=
 * GET /api/explainable-ai/snapshot
 * GET /api/explainable-ai/export?format=json|csv
 *
 * READ-ONLY. ADVISORY-ONLY.
 * This module NEVER modifies orders, portfolio, strategies, AI, risk engine or signals.
 */
import { Router } from "express";
import { spawn } from "child_process";
import path from "path";
import { PYTHON_DIR, PYTHON_BIN } from "../lib/python-env";

const router = Router();
const FLAG = "EXPLAINABLE_AI_ENABLED";

function isEnabled(): boolean {
  return process.env[FLAG] === "true";
}

function disabled() {
  return { status: "DISABLED", message: `Set ${FLAG}=true to enable Explainable AI.` };
}

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

/** GET /api/explainable-ai/summary */
router.get("/explainable-ai/summary", async (_req, res) => {
  if (!isEnabled()) { res.json(disabled()); return; }
  try { res.json(await runPython(["explainable_ai_summary"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

/** GET /api/explainable-ai/decision?symbol=RELIANCE */
router.get("/explainable-ai/decision", async (req, res) => {
  if (!isEnabled()) { res.json(disabled()); return; }
  const symbol = (req.query.symbol as string) || "";
  if (!symbol) { res.status(400).json({ error: "symbol query param is required" }); return; }
  try { res.json(await runPython(["explainable_ai_decision", symbol])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

/** GET /api/explainable-ai/contributions?symbol=RELIANCE */
router.get("/explainable-ai/contributions", async (req, res) => {
  if (!isEnabled()) { res.json(disabled()); return; }
  const symbol = (req.query.symbol as string) || "";
  if (!symbol) { res.status(400).json({ error: "symbol query param is required" }); return; }
  try { res.json(await runPython(["explainable_ai_contributions", symbol])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

/** GET /api/explainable-ai/confidence?symbol=RELIANCE */
router.get("/explainable-ai/confidence", async (req, res) => {
  if (!isEnabled()) { res.json(disabled()); return; }
  const symbol = (req.query.symbol as string) || "";
  if (!symbol) { res.status(400).json({ error: "symbol query param is required" }); return; }
  try { res.json(await runPython(["explainable_ai_confidence", symbol])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

/** GET /api/explainable-ai/scenarios?symbol=RELIANCE */
router.get("/explainable-ai/scenarios", async (req, res) => {
  if (!isEnabled()) { res.json(disabled()); return; }
  const symbol = (req.query.symbol as string) || "";
  if (!symbol) { res.status(400).json({ error: "symbol query param is required" }); return; }
  try { res.json(await runPython(["explainable_ai_scenarios", symbol])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

/** GET /api/explainable-ai/history?symbol=RELIANCE */
router.get("/explainable-ai/history", async (req, res) => {
  if (!isEnabled()) { res.json(disabled()); return; }
  const symbol = (req.query.symbol as string) || "";
  if (!symbol) { res.status(400).json({ error: "symbol query param is required" }); return; }
  try { res.json(await runPython(["explainable_ai_history", symbol])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

/** GET /api/explainable-ai/snapshot */
router.get("/explainable-ai/snapshot", async (_req, res) => {
  if (!isEnabled()) { res.json(disabled()); return; }
  try { res.json(await runPython(["explainable_ai_snapshot"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

/** GET /api/explainable-ai/export?format=json|csv */
router.get("/explainable-ai/export", async (req, res) => {
  if (!isEnabled()) { res.json(disabled()); return; }
  const format = (req.query.format as string) || "json";
  try { res.json(await runPython(["explainable_ai_export", format])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

export default router;
