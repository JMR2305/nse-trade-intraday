/**
 * phase16.ts — Phase 16: Paper Trading Validation & Strategy Proving
 *
 * Routes:
 *   GET /api/phase16/overview          — overall validation score, maturity, core stats
 *   GET /api/phase16/scorecard         — per-strategy scorecard (advisory only)
 *   GET /api/phase16/confidence        — confidence band validation
 *   GET /api/phase16/regimes           — market regime validation
 *   GET /api/phase16/sectors           — sector validation
 *   GET /api/phase16/ai                — AI decision validation
 *   GET /api/phase16/trades            — trade-by-trade review
 *   GET /api/phase16/weekly            — weekly report
 *   GET /api/phase16/monthly           — monthly report
 *   GET /api/phase16/recommendations   — advisory improvement recommendations
 *   GET /api/phase16/failures          — failure analysis
 *   GET /api/phase16/successes         — success analysis
 *   GET /api/phase16/timeline          — validation timeline / production readiness
 *   GET /api/phase16/bugs              — automated bug detection health report
 *   POST /api/phase16/export           — build all export files + report md
 *   GET /api/phase16/export/:file      — download a generated export file
 *
 * PAPER TRADING / RESEARCH ONLY. Recommendations are advisory — nothing is
 * ever auto-applied.
 */
import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import path from "path";
import fs from "fs";

const router: IRouter = Router();
import { PYTHON_DIR, PYTHON_BIN } from "../lib/python-env";
const EXPORT_DIR = path.join(PYTHON_DIR, "phase16_exports");

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
    proc.on("error", (err) => { clearTimeout(timer); reject(err); });
  });
}

const wrap = (fn: (req: any, res: any) => Promise<void>) =>
  async (req: any, res: any) => {
    try { await fn(req, res); }
    catch (err: unknown) {
      res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
    }
  };

const simple = (route: string, cmd: string, timeoutMs = 90_000) =>
  router.get(`/phase16/${route}`, wrap(async (_req, res) => {
    res.json(await runPython([cmd], timeoutMs));
  }));

simple("all", "phase16_all", 120_000);
simple("overview", "phase16_overview");
simple("scorecard", "phase16_scorecard");
simple("confidence", "phase16_confidence");
simple("regimes", "phase16_regimes");
simple("sectors", "phase16_sectors");
simple("ai", "phase16_ai");
simple("trades", "phase16_trades");
simple("weekly", "phase16_weekly");
simple("monthly", "phase16_monthly");
simple("recommendations", "phase16_recommendations");
simple("failures", "phase16_failures");
simple("successes", "phase16_successes");
simple("timeline", "phase16_timeline");
simple("bugs", "phase16_bugs");

router.post("/phase16/export", wrap(async (_req, res) => {
  res.json(await runPython(["phase16_export"], 120_000));
}));

router.get("/phase16/export/:file", wrap(async (req, res) => {
  const name = path.basename(String(req.params.file));
  const full = path.join(EXPORT_DIR, name);
  if (!full.startsWith(EXPORT_DIR) || !fs.existsSync(full)) {
    res.status(404).json({ success: false, error: `Export file not found: ${name}. Run POST /api/phase16/export first.` });
    return;
  }
  res.download(full, name);
}));

export default router;
