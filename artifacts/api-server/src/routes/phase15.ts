/**
 * phase15.ts — Phase 15: Production Hardening & Stabilization
 *
 * Routes:
 *   GET /api/phase15/scan-context           — unified scan context (single source of truth)
 *   GET /api/phase15/scan-context/:symbol   — canonical values for one symbol
 *   GET /api/phase15/quality                — data quality scores for all stocks
 *   GET /api/phase15/staleness              — stale-data detection status
 *   GET /api/phase15/consistency            — run cross-page consistency validation
 *   GET /api/phase15/explain/:symbol        — structured AI explanation (why buy/watch/ignore)
 *   GET /api/phase15/explain                — headlines for all symbols
 *   GET /api/phase15/risk-gate/:symbol      — full pre-trade risk checklist
 *   POST /api/phase15/audit/record          — record audit entry for current scan
 *   GET /api/phase15/audit                  — list scan audit records
 *   GET /api/phase15/diagnostics            — expanded production diagnostics
 *   GET /api/phase15/readiness              — automated Production Readiness Report
 *
 * PAPER TRADING / RESEARCH ONLY.
 */
import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import path from "path";

const router: IRouter = Router();
import { PYTHON_DIR, PYTHON_BIN } from "../lib/python-env";

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

router.get("/phase15/scan-context", wrap(async (_req, res) => {
  res.json(await runPython(["phase15_context"]));
}));

router.get("/phase15/scan-context/:symbol", wrap(async (req, res) => {
  res.json(await runPython(["phase15_symbol", req.params.symbol]));
}));

router.get("/phase15/quality", wrap(async (_req, res) => {
  res.json(await runPython(["phase15_quality"]));
}));

router.get("/phase15/staleness", wrap(async (_req, res) => {
  res.json(await runPython(["phase15_staleness"]));
}));

router.get("/phase15/consistency", wrap(async (_req, res) => {
  res.json(await runPython(["phase15_consistency"], 120_000));
}));

router.get("/phase15/explain", wrap(async (_req, res) => {
  res.json(await runPython(["phase15_explain_all"], 120_000));
}));

router.get("/phase15/explain/:symbol", wrap(async (req, res) => {
  res.json(await runPython(["phase15_explain", req.params.symbol]));
}));

router.get("/phase15/risk-gate/:symbol", wrap(async (req, res) => {
  res.json(await runPython(["phase15_risk_gate", req.params.symbol]));
}));

router.post("/phase15/audit/record", wrap(async (_req, res) => {
  res.json(await runPython(["phase15_audit_record"]));
}));

router.get("/phase15/audit", wrap(async (req, res) => {
  const limit = String(parseInt(String(req.query.limit ?? "20"), 10) || 20);
  res.json(await runPython(["phase15_audit_list", limit]));
}));

router.get("/phase15/diagnostics", wrap(async (_req, res) => {
  res.json(await runPython(["phase15_diagnostics"], 120_000));
}));

router.get("/phase15/readiness", wrap(async (_req, res) => {
  res.json(await runPython(["phase15_readiness"], 180_000));
}));

export default router;
