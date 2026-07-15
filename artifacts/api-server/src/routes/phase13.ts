/**
 * phase13.ts — Phase 13: Institutional AI & Strategy Evolution
 *
 * Routes:
 *   GET  /api/phase13/analysis               — 14-factor fused analysis (cached 10 min)
 *   GET  /api/phase13/regime                 — market regime + transition tracking
 *   GET  /api/phase13/sector-rotation        — sector ranking + momentum
 *   POST /api/phase13/bundle                 — generate diagnostic bundle
 *   GET  /api/phase13/bundle/download        — download JSON or CSV (?file=json|csv)
 *   GET  /api/phase13/evolution              — list strategy evolution proposals
 *   POST /api/phase13/evolution/generate     — generate new proposals
 *   POST /api/phase13/evolution/review/:id   — approve/reject a proposal
 *   GET  /api/phase13/audit                  — model comparison audit report
 *
 * PAPER TRADING / RESEARCH ONLY — no real broker orders.
 */
import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import path from "path";
import fs from "fs";

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

// GET /api/phase13/analysis
router.get("/phase13/analysis", wrap(async (req, res) => {
  const symbols = typeof req.query.symbols === "string" ? req.query.symbols : "";
  const force = req.query.force === "true";
  res.json(await runPython(["phase13_analysis", symbols, ...(force ? ["force"] : [])]));
}));

// GET /api/phase13/regime
router.get("/phase13/regime", wrap(async (_req, res) => {
  res.json(await runPython(["phase13_regime"]));
}));

// GET /api/phase13/sector-rotation
router.get("/phase13/sector-rotation", wrap(async (_req, res) => {
  res.json(await runPython(["phase13_sector_rotation"]));
}));

// POST /api/phase13/bundle
router.post("/phase13/bundle", wrap(async (_req, res) => {
  res.json(await runPython(["phase13_bundle"], 120_000));
}));

// GET /api/phase13/bundle/download?file=json|csv
router.get("/phase13/bundle/download", wrap(async (req, res) => {
  const kind = String(req.query.file ?? "json");
  if (!["json", "csv"].includes(kind)) {
    res.status(400).json({ success: false, error: "file must be json or csv" });
    return;
  }
  const fname = kind === "json" ? "phase13_diagnostic_bundle.json" : "phase13_summary.csv";
  const filePath = path.join(PYTHON_DIR, fname);
  await runPython(["phase13_bundle"], 120_000);
  if (!fs.existsSync(filePath)) {
    res.status(500).json({ success: false, error: "Bundle file missing after generation" });
    return;
  }
  res.setHeader("Content-Type", kind === "json" ? "application/json; charset=utf-8" : "text/csv; charset=utf-8");
  res.setHeader("Content-Disposition", `attachment; filename="${fname}"`);
  fs.createReadStream(filePath).pipe(res);
}));

// GET /api/phase13/evolution
router.get("/phase13/evolution", wrap(async (req, res) => {
  const status = typeof req.query.status === "string" ? req.query.status : "";
  res.json(await runPython(["phase13_evolution_list", status]));
}));

// POST /api/phase13/evolution/generate
router.post("/phase13/evolution/generate", wrap(async (_req, res) => {
  res.json(await runPython(["phase13_evolution", "force"], 120_000));
}));

// POST /api/phase13/evolution/review/:id
router.post("/phase13/evolution/review/:id", wrap(async (req, res) => {
  const { id } = req.params;
  const { action, notes } = req.body as { action?: string; notes?: string };
  if (!action) {
    res.status(400).json({ success: false, error: "action required (APPROVE | REJECT)" });
    return;
  }
  res.json(await runPython(["phase13_evolution_review", id, action.toUpperCase(), notes ?? ""]));
}));

// GET /api/phase13/audit
router.get("/phase13/audit", wrap(async (_req, res) => {
  res.json(await runPython(["phase13_audit"], 120_000));
}));

export default router;
