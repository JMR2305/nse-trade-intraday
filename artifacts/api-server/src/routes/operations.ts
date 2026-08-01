/**
 * operations.ts — Phase 8.5
 * Operational Control Centre API routes.
 *
 * READ-ONLY. ADVISORY-ONLY.
 * Never places orders, modifies portfolio, strategies, AI models,
 * risk parameters, feature flags, or restarts services.
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

const handle = (cmd: string, timeout?: number) => async (_req: any, res: any) => {
  try { res.json(await runPython([cmd], timeout)); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
};

// ── GET /api/operations/* ──────────────────────────────────────────────────────

router.get("/operations/summary",      handle("ops_summary"));
router.get("/operations/market",       handle("ops_market"));
router.get("/operations/paper",        handle("ops_paper"));
router.get("/operations/risk",         handle("ops_risk"));
router.get("/operations/data-quality", handle("ops_data_quality"));
router.get("/operations/observability",handle("ops_observability"));
router.get("/operations/flags",        handle("ops_flags"));
router.get("/operations/jobs",         handle("ops_jobs"));
router.get("/operations/alerts",       handle("ops_alerts"));
router.get("/operations/checklist",    handle("ops_checklist"));
router.get("/operations/timeline",     handle("ops_timeline"));
router.get("/operations/snapshot",     handle("ops_snapshot"));

// Export — supports ?format=csv or ?format=json (default json)
router.get("/operations/export", async (req: any, res: any) => {
  const fmt = String(req.query.format ?? "json").toLowerCase();
  try {
    const data = await runPython([fmt === "csv" ? "ops_export_csv" : "ops_export_json"]);
    if (fmt === "csv") {
      const csv = typeof data === "object" ? (data as any).csv ?? "" : String(data);
      res.setHeader("Content-Type", "text/csv");
      res.setHeader("Content-Disposition", `attachment; filename="operations_export_${new Date().toISOString().slice(0,10)}.csv"`);
      res.send(csv);
      return;
    }
    res.json(data);
  } catch (e: any) { res.status(500).json({ error: e.message }); }
});

export default router;
