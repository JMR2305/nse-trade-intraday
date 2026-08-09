/**
 * phase27.ts — Phase 27C/27D: AI Explainability + Strategy Optimization.
 *
 * GET /api/explain/symbol/:symbol            — per-symbol WHY bundle (27C)
 * GET /api/strategy-optimization/report      — historical optimization report (27D)
 * GET /api/operator-analytics/report         — operator analytics report (27E)
 *
 * READ-ONLY · ADVISORY-ONLY. Aggregates canonical stores only; never
 * modifies orders, portfolio, strategies, thresholds or AI state.
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

// 30s in-process cache + single-flight for the heavy report (same pattern
// as other aggregate dashboards; avoids parallel Python spawns).
let reportCache: { at: number; data: unknown } | null = null;
let reportInFlight: Promise<unknown> | null = null;
const REPORT_TTL_MS = 30_000;

router.get("/explain/symbol/:symbol", async (req, res) => {
  try {
    res.json(await runPython(["explain_symbol", String(req.params.symbol || "")]));
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

router.get("/strategy-optimization/report", async (_req, res) => {
  try {
    if (reportCache && Date.now() - reportCache.at < REPORT_TTL_MS) {
      res.json(reportCache.data);
      return;
    }
    if (!reportInFlight) {
      reportInFlight = runPython(["strategy_optimization_report"])
        .then((data) => { reportCache = { at: Date.now(), data }; return data; })
        .finally(() => { reportInFlight = null; });
    }
    res.json(await reportInFlight);
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

// Phase 27E: operator analytics — same 30s cache + single-flight pattern.
let opanCache: { at: number; data: unknown } | null = null;
let opanInFlight: Promise<unknown> | null = null;

router.get("/operator-analytics/report", async (_req, res) => {
  try {
    if (opanCache && Date.now() - opanCache.at < REPORT_TTL_MS) {
      res.json(opanCache.data);
      return;
    }
    if (!opanInFlight) {
      opanInFlight = runPython(["operator_analytics_report"])
        .then((data) => { opanCache = { at: Date.now(), data }; return data; })
        .finally(() => { opanInFlight = null; });
    }
    res.json(await opanInFlight);
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

// Phase 27F: System Readiness — 30s cache + single-flight; ?force=true
// bypasses the cache (safe read-only re-evaluation, never a new probe).
let readyCache: { at: number; data: unknown } | null = null;
let readyInFlight: Promise<unknown> | null = null;

router.get("/system-readiness/report", async (req, res) => {
  try {
    const force = String(req.query.force ?? "") === "true";
    if (!force && readyCache && Date.now() - readyCache.at < REPORT_TTL_MS) {
      res.json(readyCache.data);
      return;
    }
    if (!readyInFlight) {
      readyInFlight = runPython(["system_readiness_report"])
        .then((data) => { readyCache = { at: Date.now(), data }; return data; })
        .finally(() => { readyInFlight = null; });
    }
    res.json(await readyInFlight);
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

router.get("/system-readiness/history", async (_req, res) => {
  try {
    res.json(await runPython(["system_readiness_history"]));
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

// Phase 27.1: Operational Intelligence — 30s cache + single-flight
let oiCache: { at: number; data: unknown } | null = null;
let oiInFlight: Promise<unknown> | null = null;

router.get("/operational-intelligence/report", async (req, res) => {
  try {
    const force = String(req.query.force ?? "") === "true";
    if (!force && oiCache && Date.now() - oiCache.at < REPORT_TTL_MS) {
      res.json(oiCache.data);
      return;
    }
    if (!oiInFlight) {
      oiInFlight = runPython(["operational_intelligence_report"])
        .then((data) => { oiCache = { at: Date.now(), data }; return data; })
        .finally(() => { oiInFlight = null; });
    }
    res.json(await oiInFlight);
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

export default router;
