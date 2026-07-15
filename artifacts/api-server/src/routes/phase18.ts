// Phase 18 — Research Notebook, Daily Validation Workflow & Evidence
// Accumulation routes. PAPER TRADING / RESEARCH ONLY.
// Read/write is limited to journal data (entries, notes, decisions, issues,
// targets). No route can place trades or change trading logic.

import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import path from "path";
import fs from "fs";

const router: IRouter = Router();
import { PYTHON_DIR, PYTHON_BIN } from "../lib/python-env";
const EXPORT_DIR = path.join(PYTHON_DIR, "phase18_exports");

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

// ── entries ─────────────────────────────────────────────────────────────────
router.post("/phase18/ensure", wrap(async (_req, res) => {
  res.json(await runPython(["phase18_ensure"], 120_000));
}));
router.get("/phase18/entry", wrap(async (req, res) => {
  const args = ["phase18_entry"];
  if (typeof req.query.date === "string") args.push(req.query.date);
  res.json(await runPython(args));
}));
router.get("/phase18/entries", wrap(async (_req, res) => {
  res.json(await runPython(["phase18_list"]));
}));
router.post("/phase18/finalize", wrap(async (req, res) => {
  const args = ["phase18_finalize"];
  if (typeof req.body?.date === "string") args.push(req.body.date);
  res.json(await runPython(args, 120_000));
}));
router.post("/phase18/reopen", wrap(async (req, res) => {
  res.json(await runPython(["phase18_reopen", String(req.body?.date ?? "")]));
}));

// ── notes & decisions ───────────────────────────────────────────────────────
router.post("/phase18/notes", wrap(async (req, res) => {
  res.json(await runPython(["phase18_notes", JSON.stringify(req.body ?? {})]));
}));
router.post("/phase18/decision", wrap(async (req, res) => {
  res.json(await runPython(["phase18_decision", JSON.stringify(req.body ?? {})]));
}));
router.post("/phase18/search", wrap(async (req, res) => {
  res.json(await runPython(["phase18_search", JSON.stringify(req.body ?? {})]));
}));

// ── issues ──────────────────────────────────────────────────────────────────
router.get("/phase18/issues", wrap(async (req, res) => {
  const filters: Record<string, string> = {};
  if (typeof req.query.status === "string") filters.status = req.query.status;
  if (typeof req.query.severity === "string") filters.severity = req.query.severity;
  res.json(await runPython(["phase18_issues", JSON.stringify(filters)]));
}));
router.post("/phase18/issues", wrap(async (req, res) => {
  res.json(await runPython(["phase18_issue_add", JSON.stringify(req.body ?? {})]));
}));
router.patch("/phase18/issues", wrap(async (req, res) => {
  res.json(await runPython(["phase18_issue_update", JSON.stringify(req.body ?? {})]));
}));

// ── targets ─────────────────────────────────────────────────────────────────
router.get("/phase18/targets", wrap(async (_req, res) => {
  res.json(await runPython(["phase18_targets"]));
}));
router.post("/phase18/targets", wrap(async (req, res) => {
  res.json(await runPython(["phase18_targets_update", JSON.stringify(req.body ?? {})]));
}));

// ── reviews & evidence ──────────────────────────────────────────────────────
router.get("/phase18/review/daily", wrap(async (req, res) => {
  const args = ["phase18_daily_review"];
  if (typeof req.query.date === "string") args.push(req.query.date);
  res.json(await runPython(args));
}));
router.get("/phase18/review/weekly", wrap(async (req, res) => {
  const args = ["phase18_weekly_review"];
  if (typeof req.query.date === "string") args.push(req.query.date);
  res.json(await runPython(args, 120_000));
}));
router.get("/phase18/review/monthly", wrap(async (req, res) => {
  const args = ["phase18_monthly_review"];
  if (typeof req.query.month === "string") args.push(req.query.month);
  res.json(await runPython(args, 120_000));
}));
router.get("/phase18/evidence", wrap(async (_req, res) => {
  res.json(await runPython(["phase18_evidence"], 120_000));
}));

// ── exports ─────────────────────────────────────────────────────────────────
router.post("/phase18/exports", wrap(async (req, res) => {
  if (req.body?.scope === "daily") {
    const args = ["phase18_export_daily"];
    if (typeof req.body?.date === "string") args.push(req.body.date);
    res.json(await runPython(args, 120_000));
  } else if (req.body?.scope === "archive") {
    res.json(await runPython(["phase18_archive"], 180_000));
  } else {
    res.json(await runPython(["phase18_export_all"], 180_000));
  }
}));
router.get("/phase18/exports/:file", wrap(async (req, res) => {
  const name = path.basename(String(req.params.file));
  const full = path.join(EXPORT_DIR, name);
  if (!full.startsWith(EXPORT_DIR) || !fs.existsSync(full)) {
    res.status(404).json({ success: false, error: `Export not found: ${name}. Generate exports first.` });
    return;
  }
  res.download(full, name);
}));

export default router;
