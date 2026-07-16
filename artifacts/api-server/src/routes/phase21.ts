/**
 * phase21.ts — Phase 21: Strategy Calibration, Signal Quality & Paper-Trade
 * Optimization.
 *
 * Routes:
 *   GET  /api/phase21/baseline             — frozen baseline + integrity check
 *   POST /api/phase21/baseline/freeze      — freeze baseline (idempotent)
 *   GET  /api/phase21/baseline-report      — baseline performance report
 *   GET  /api/phase21/calibration          — confidence calibration buckets + curve
 *   GET  /api/phase21/thresholds           — threshold optimization candidates
 *   GET  /api/phase21/regime-matrix        — strategy × regime performance
 *   GET  /api/phase21/stop-target          — stop/target quality analysis
 *   GET  /api/phase21/ranking              — deterministic opportunity ranking
 *   GET  /api/phase21/explain/:symbol      — "why this trade?" summary
 *   GET  /api/phase21/explain              — explanations for all scan symbols
 *   GET  /api/phase21/registry             — champion/challenger registry
 *   POST /api/phase21/challengers/build    — (re)build advisory challengers
 *   GET  /api/phase21/promotion/:id        — promotion checklist for a challenger
 *   POST /api/phase21/review/:id           — human APPROVE/REJECT of a challenger
 *   GET  /api/phase21/scorecard            — Phase 21 quality scorecard
 *   POST /api/phase21/export               — build JSON/CSV/PDF reports
 *   GET  /api/phase21/export/:file         — download a generated report
 *
 * PAPER TRADING / RESEARCH ONLY. Everything Phase 21 produces is advisory —
 * no threshold, calibration, or challenger is ever auto-applied or
 * auto-promoted. Live order placement remains disabled.
 */
import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import path from "path";
import fs from "fs";

const router: IRouter = Router();
import { PYTHON_DIR, PYTHON_BIN } from "../lib/python-env";
const EXPORT_DIR = path.join(PYTHON_DIR, "phase21_exports");

function runPython(args: string[], timeoutMs = 90_000): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], { cwd: PYTHON_DIR });
    let stdout = "";
    let stderr = "";
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      proc.kill("SIGTERM");
      reject(new Error(`Python timed out after ${timeoutMs / 1000}s`));
    }, timeoutMs);
    proc.stdout.on("data", (d: Buffer) => { stdout += d.toString(); });
    proc.stderr.on("data", (d: Buffer) => { stderr += d.toString(); });
    proc.on("close", (code) => {
      clearTimeout(timer);
      if (timedOut) return;
      if (code !== 0) {
        try {
          const parsed = JSON.parse(stdout.trim());
          if (parsed.error) return reject(new Error(parsed.error));
        } catch { /* ignore */ }
        reject(new Error(stderr || `Python exited ${code}`));
      } else {
        try { resolve(JSON.parse(stdout.trim())); }
        catch { reject(new Error(`Failed to parse Python output: ${stdout.slice(0, 200)}`)); }
      }
    });
  });
}

const wrap = (fn: (req: any, res: any) => Promise<void>) =>
  (req: any, res: any) => {
    fn(req, res).catch((e: Error) =>
      res.status(500).json({ success: false, error: e.message }));
  };

const simple = (route: string, cmd: string, timeoutMs = 90_000) =>
  router.get(`/phase21/${route}`, wrap(async (_req, res) => {
    res.json(await runPython([cmd], timeoutMs));
  }));

simple("baseline", "phase21_baseline");
simple("baseline-report", "phase21_baseline_report");
simple("calibration", "phase21_calibration");
simple("thresholds", "phase21_thresholds");
simple("regime-matrix", "phase21_regime_matrix");
simple("stop-target", "phase21_stoptarget");
simple("ranking", "phase21_ranking", 120_000);
simple("explain", "phase21_explain_all", 120_000);
simple("registry", "phase21_registry");
simple("scorecard", "phase21_scorecard", 120_000);

router.post("/phase21/baseline/freeze", wrap(async (_req, res) => {
  res.json(await runPython(["phase21_baseline_freeze"]));
}));

router.get("/phase21/explain/:symbol", wrap(async (req, res) => {
  const sym = String(req.params.symbol || "").replace(/[^A-Za-z0-9&\-]/g, "").toUpperCase();
  res.json(await runPython(["phase21_explain", sym]));
}));

router.post("/phase21/challengers/build", wrap(async (_req, res) => {
  res.json(await runPython(["phase21_challengers_build"], 120_000));
}));

router.get("/phase21/promotion/:id", wrap(async (req, res) => {
  const id = String(req.params.id || "").replace(/[^a-z0-9_]/g, "");
  res.json(await runPython(["phase21_promotion_checklist", id]));
}));

router.post("/phase21/review/:id", wrap(async (req, res) => {
  const id = String(req.params.id || "").replace(/[^a-z0-9_]/g, "");
  const action = String(req.body?.action || "").toUpperCase();
  if (action !== "APPROVE" && action !== "REJECT") {
    res.status(400).json({ success: false, error: "action must be APPROVE or REJECT" });
    return;
  }
  const approver = String(req.body?.approver || "human").slice(0, 60);
  res.json(await runPython(["phase21_review_challenger", id, action, approver]));
}));

router.post("/phase21/export", wrap(async (_req, res) => {
  res.json(await runPython(["phase21_export"], 120_000));
}));

router.get("/phase21/export/:file", wrap(async (req, res) => {
  const name = path.basename(String(req.params.file || ""));
  const full = path.join(EXPORT_DIR, name);
  if (!fs.existsSync(full)) {
    res.status(404).json({ success: false, error: `Export file not found: ${name}. Run POST /api/phase21/export first.` });
    return;
  }
  res.download(full);
}));

export default router;
