/**
 * phase22.ts — Phase 22: Controlled Auto Paper Trading & Evidence Accumulation.
 *
 * Routes:
 *   GET  /api/phase22/readiness          — pre-activation readiness checklist
 *   GET  /api/phase22/activation         — activation status (banner state)
 *   POST /api/phase22/enable             — enable auto paper entries (typed confirmation)
 *   POST /api/phase22/disable            — immediate disable (no confirmation)
 *   GET  /api/phase22/evidence           — evidence dataset rows + summary
 *   POST /api/phase22/evidence/update    — time-safe outcome update tick
 *   GET  /api/phase22/progress           — evidence progress + milestones
 *   GET  /api/phase22/daily-report       — daily close report (JSON)
 *   POST /api/phase22/export             — build JSON/CSV/PDF daily report
 *   GET  /api/phase22/export/:file       — download a generated report file
 *
 * PAPER TRADING / RESEARCH ONLY. Never places real Zerodha orders; all
 * live-order write paths remain disabled. Auto paper entries default OFF
 * after every deployment and require the exact typed confirmation
 * "ENABLE PAPER ONLY" plus a fully-passing readiness checklist.
 */
import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import path from "path";
import fs from "fs";

const router: IRouter = Router();
import { PYTHON_DIR, PYTHON_BIN } from "../lib/python-env";
const EXPORT_DIR = path.join(PYTHON_DIR, "exports");

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

router.get("/phase22/readiness", wrap(async (_req, res) => {
  res.json(await runPython(["phase22_readiness"], 120_000));
}));

router.get("/phase22/activation", wrap(async (_req, res) => {
  res.json(await runPython(["phase22_activation_status"]));
}));

router.post("/phase22/enable", wrap(async (req, res) => {
  const body = req.body ?? {};
  const confirmationText = typeof body.confirmation_text === "string"
    ? body.confirmation_text.slice(0, 100) : "";
  const user = typeof body.user === "string"
    ? body.user.replace(/[^\w@. -]/g, "").slice(0, 60) : undefined;
  const result = (await runPython([
    "phase22_enable",
    JSON.stringify({ confirmation_text: confirmationText, user }),
  ], 120_000)) as Record<string, unknown>;
  if (result && result["success"] === false) {
    res.status(400).json(result);
    return;
  }
  res.json(result);
}));

router.post("/phase22/disable", wrap(async (req, res) => {
  const body = req.body ?? {};
  const user = typeof body.user === "string"
    ? body.user.replace(/[^\w@. -]/g, "").slice(0, 60) : undefined;
  res.json(await runPython(["phase22_disable", JSON.stringify({ user })]));
}));

router.get("/phase22/evidence", wrap(async (req, res) => {
  const limit = Math.min(Math.max(Number(req.query["limit"]) || 100, 1), 1000);
  res.json(await runPython(["phase22_evidence", String(limit)]));
}));

router.post("/phase22/evidence/update", wrap(async (_req, res) => {
  res.json(await runPython(["phase22_evidence_update"], 120_000));
}));

router.get("/phase22/progress", wrap(async (_req, res) => {
  res.json(await runPython(["phase22_progress"]));
}));

router.get("/phase22/daily-report", wrap(async (req, res) => {
  const day = typeof req.query["day"] === "string"
    && /^\d{4}-\d{2}-\d{2}$/.test(req.query["day"] as string)
    ? (req.query["day"] as string) : null;
  res.json(await runPython(day
    ? ["phase22_daily_report", day] : ["phase22_daily_report"], 120_000));
}));

router.post("/phase22/export", wrap(async (req, res) => {
  const body = req.body ?? {};
  const day = typeof body.day === "string" && /^\d{4}-\d{2}-\d{2}$/.test(body.day)
    ? body.day : null;
  res.json(await runPython(day
    ? ["phase22_export", day] : ["phase22_export"], 120_000));
}));

router.get("/phase22/export/:file", wrap(async (req, res) => {
  const raw = String(req.params["file"] || "");
  const name = path.basename(raw);
  if (!/^Phase22_Daily_\d{4}-\d{2}-\d{2}\.(json|csv|pdf)$/.test(name)) {
    res.status(400).json({ success: false, error: "Invalid Phase 22 export file name" });
    return;
  }
  const full = path.join(EXPORT_DIR, name);
  if (!full.startsWith(EXPORT_DIR + path.sep) || !fs.existsSync(full)) {
    res.status(404).json({
      success: false,
      error: `Export file not found: ${name}. Run POST /api/phase22/export first.`,
    });
    return;
  }
  res.download(full, name);
}));

export default router;
