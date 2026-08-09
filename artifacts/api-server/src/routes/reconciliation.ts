/**
 * reconciliation.ts — EOD broker reconciliation API routes.
 *
 * GET  /api/broker/reconciliation         — last run summary + open discrepancies
 * POST /api/broker/reconciliation/trigger — manually trigger a reconciliation run
 * POST /api/broker/reconciliation/resolve — mark a discrepancy as resolved
 */

import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import path from "path";

const router: IRouter = Router();
import { PYTHON_DIR, PYTHON_BIN } from "../lib/python-env";

function runPython(
  args: string[],
  timeoutMs = 60_000,
): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], {
      cwd: PYTHON_DIR,
      env: process.env,
    });
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
      res.status(500).json({
        success: false,
        error: err instanceof Error ? err.message : String(err),
      });
    }
  };

// GET /api/broker/reconciliation — last run + open discrepancies
router.get("/broker/reconciliation", wrap(async (_req, res) => {
  res.json(await runPython(["reconcil_status"], 30_000));
}));

// POST /api/broker/reconciliation/trigger — manual/forced run
router.post("/broker/reconciliation/trigger", wrap(async (req, res) => {
  const force = req.body?.force === true;
  const args = ["reconcil_trigger"];
  if (force) args.push("--force");
  res.json(await runPython(args, 120_000));
}));

// POST /api/broker/reconciliation/publish — authenticated ingestion endpoint
// for the isolated trading bot to publish its reconciliation run summary
// (including paper_fallback_count). Requires a shared-secret token so the
// bot never needs direct access to this server's database.
router.post("/broker/reconciliation/publish", wrap(async (req, res) => {
  const expected = process.env.RECON_PUBLISH_TOKEN;
  if (!expected) {
    return res.status(503).json({
      success: false,
      error: "Publishing disabled: RECON_PUBLISH_TOKEN is not configured",
    });
  }
  const provided = req.get("x-recon-publish-token") ?? "";
  if (provided !== expected) {
    return res.status(401).json({ success: false, error: "Invalid publish token" });
  }
  const body = req.body ?? {};
  if (typeof body.run_id !== "string" || !body.run_id.trim() || !body.started_at) {
    return res.status(400).json({
      success: false,
      error: "run_id and started_at are required",
    });
  }
  res.json(await runPython(["reconcil_publish", JSON.stringify(body)], 15_000));
}));

// POST /api/broker/reconciliation/resolve — mark a discrepancy resolved
router.post("/broker/reconciliation/resolve", wrap(async (req, res) => {
  const id = parseInt(String(req.body?.id ?? ""), 10);
  if (!Number.isFinite(id) || id <= 0) {
    return res.status(400).json({ success: false, error: "Valid discrepancy id required" });
  }
  const args = ["reconcil_resolve", String(id)];
  const note = req.body?.note;
  if (note && typeof note === "string" && note.trim()) {
    args.push(note.trim().slice(0, 500));
  }
  res.json(await runPython(args, 15_000));
}));

// POST /api/broker/reconciliation/reopen — reopen a previously resolved discrepancy
router.post("/broker/reconciliation/reopen", wrap(async (req, res) => {
  const id = parseInt(String(req.body?.id ?? ""), 10);
  if (!Number.isFinite(id) || id <= 0) {
    return res.status(400).json({ success: false, error: "Valid discrepancy id required" });
  }
  res.json(await runPython(["reconcil_reopen", String(id)], 15_000));
}));

export default router;
