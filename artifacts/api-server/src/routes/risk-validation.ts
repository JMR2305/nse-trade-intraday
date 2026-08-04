/**
 * risk-validation.ts — Phase 8.4
 * Advanced Risk Validation Framework API routes.
 * All endpoints are READ-ONLY and ADVISORY-ONLY.
 */
import { Router } from "express";
import { spawn }  from "child_process";
import path       from "path";
import { PYTHON_BIN, PYTHON_DIR } from "../lib/python-env";

const router = Router();

function runPython(args: string[], timeoutMs = 90_000): Promise<any> {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], { cwd: PYTHON_DIR });
    let stdout = "", stderr = "";
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
        try { const p = JSON.parse(stdout.trim()); if (p.error) return reject(new Error(p.error)); } catch {}
        reject(new Error(stderr || `Python exited ${code}`));
      } else {
        try { resolve(JSON.parse(stdout.trim())); }
        catch { reject(new Error(`Failed to parse Python output: ${stdout.slice(0, 200)}`)); }
      }
    });
    proc.on("error", (err) => { clearTimeout(timer); reject(err); });
  });
}

const handle = (cmd: string) => async (_req: any, res: any) => {
  try { res.json(await runPython([cmd])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
};

router.get("/risk-validation/summary",     handle("rv_summary"));
router.get("/risk-validation/portfolio",   handle("rv_portfolio"));
router.get("/risk-validation/sector",      handle("rv_sector"));
router.get("/risk-validation/correlation", handle("rv_correlation"));
router.get("/risk-validation/stress",      handle("rv_stress"));
router.get("/risk-validation/tail",        handle("rv_tail"));
router.get("/risk-validation/execution",   handle("rv_execution"));
router.get("/risk-validation/market",      handle("rv_market"));
router.get("/risk-validation/drift",       handle("rv_drift"));
router.get("/risk-validation/alerts",      handle("rv_alerts"));
router.get("/risk-validation/snapshot",    handle("rv_snapshot"));

router.get("/risk-validation/pre-trade-log", handle("rv_pre_trade_log"));

router.get("/risk-validation/export", async (req: any, res: any) => {
  const fmt = String(req.query.format ?? "json").toLowerCase();
  try {
    const data = await runPython([fmt === "csv" ? "rv_export_csv" : "rv_export_json"]);
    if (fmt === "csv") {
      const csv = typeof data === "object" ? (data as any).csv ?? "" : data;
      res.setHeader("Content-Type", "text/csv");
      res.setHeader("Content-Disposition", `attachment; filename="risk_validation_export.csv"`);
      res.send(csv);
      return;
    }
    res.json(data);
  } catch (e: any) { res.status(500).json({ error: e.message }); }
});

export default router;
