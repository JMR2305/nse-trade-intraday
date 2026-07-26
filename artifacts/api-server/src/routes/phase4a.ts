// Phase 4A — Controlled Paper Trading Operations routes.
// PAPER TRADING / RESEARCH ONLY. No live orders anywhere in this module.
//
// Strategy: each Python script writes its result to a known JSON file under
// docs/. Routes spawn the script (fire-and-wait), then read that file and
// return it. This is more robust than parsing human-readable stdout.

import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import path from "path";
import fs from "fs";

import { PYTHON_DIR, PYTHON_BIN } from "../lib/python-env";

const router: IRouter = Router();

// ── Helpers ───────────────────────────────────────────────────────────────────

const DOCS_DIR = path.resolve(PYTHON_DIR, "..", "..", "docs");

/** Strict 8-digit date validation — prevents path traversal. */
function validateDate(raw: unknown): string | null {
  const s = String(raw ?? "").replace(/-/g, "");
  return /^\d{8}$/.test(s) ? s : null;
}

/** Today as YYYYMMDD. */
function todayCompact(): string {
  return new Date().toISOString().slice(0, 10).replace(/-/g, "");
}

/** Read a JSON file from docs/. Returns null when missing. */
function readDoc(filename: string): unknown | null {
  const p = path.join(DOCS_DIR, filename);
  try {
    return JSON.parse(fs.readFileSync(p, "utf-8"));
  } catch {
    return null;
  }
}

/**
 * Spawn a Phase 4A Python script, wait for it to finish, then return the
 * JSON file it was supposed to write. `outputFile` is relative to DOCS_DIR.
 * If the file is still missing after the run, throws with the stderr message.
 */
function runPyThenRead(
  script: string,
  args: string[],
  outputFile: string,
  timeoutMs = 120_000
): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const proc = spawn(
      PYTHON_BIN,
      [path.join(PYTHON_DIR, script), ...args],
      { cwd: PYTHON_DIR }
    );
    let stderr = "";
    let timedOut = false;

    const timer = setTimeout(() => {
      timedOut = true;
      proc.kill("SIGTERM");
      reject(new Error(`Python timed out after ${timeoutMs / 1000}s`));
    }, timeoutMs);

    proc.stderr.on("data", (d: Buffer) => { stderr += d.toString(); });
    // consume stdout so it doesn't block the pipe buffer
    proc.stdout.resume();

    proc.on("close", (code) => {
      clearTimeout(timer);
      if (timedOut) return;
      const filePath = path.join(DOCS_DIR, outputFile);
      try {
        const data = JSON.parse(fs.readFileSync(filePath, "utf-8"));
        return resolve(data);
      } catch {
        if (code !== 0) {
          return reject(new Error(stderr.slice(0, 400) || `Python exited ${code}`));
        }
        reject(new Error(`Script ran but output file not found: ${outputFile}`));
      }
    });
    proc.on("error", (err) => { clearTimeout(timer); reject(err); });
  });
}

const wrap = (fn: (req: any, res: any) => Promise<void>) =>
  async (req: any, res: any) => {
    try { await fn(req, res); }
    catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      res.status(500).json({ success: false, error: msg });
    }
  };

// ── Section 1: Pre-Market ─────────────────────────────────────────────────────

/** GET /phase4a/premarket
 *  Returns cached PreMarketReport.json, or re-runs the suite when ?run=1. */
router.get("/phase4a/premarket", wrap(async (req, res) => {
  if (req.query.run === "1") {
    const data = await runPyThenRead("phase4a_premarket.py", [], "PreMarketReport.json", 90_000);
    return res.json(data);
  }
  const cached = readDoc("PreMarketReport.json");
  if (cached) return res.json(cached);
  // No cache — run once automatically
  const data = await runPyThenRead("phase4a_premarket.py", [], "PreMarketReport.json", 90_000);
  res.json(data);
}));

// ── Section 2: Session Monitor ────────────────────────────────────────────────

/** GET /phase4a/monitor/tick — take a single monitoring snapshot.
 *  The Python script writes docs/monitor_tick_latest.json on each tick. */
router.get("/phase4a/monitor/tick", wrap(async (_req, res) => {
  await runPyThenRead(
    "phase4a_monitor.py", ["--tick"],
    "monitor_tick_latest.json", 30_000
  );
  const data = readDoc("monitor_tick_latest.json");
  res.json(data ?? { error: "No tick data written" });
}));

/** GET /phase4a/monitor/summary?date=YYYY-MM-DD */
router.get("/phase4a/monitor/summary", wrap(async (req, res) => {
  const dateCompact = validateDate(req.query.date) ?? todayCompact();
  const outFile = `monitor_summary_${dateCompact}.json`;
  const args = ["--summary"];
  if (req.query.date) args.push("--date", String(req.query.date));
  await runPyThenRead("phase4a_monitor.py", args, outFile, 20_000);
  const data = readDoc(outFile);
  res.json(data ?? { error: "No summary data" });
}));

// ── Section 3: Trade Journal ──────────────────────────────────────────────────

/** GET /phase4a/trade-journal?date=YYYY-MM-DD */
router.get("/phase4a/trade-journal", wrap(async (req, res) => {
  const dateCompact = validateDate(req.query.date) ?? todayCompact();
  const args: string[] = [];
  if (req.query.date) args.push("--date", String(req.query.date));
  const outFile = `trade_journal_${dateCompact}.json`;
  await runPyThenRead("phase4a_trade_journal.py", args, outFile, 30_000);
  const data = readDoc(outFile);
  res.json(data ?? { error: "No journal data" });
}));

// ── Section 4: Risk Metrics ───────────────────────────────────────────────────

/** GET /phase4a/risk-metrics?date=YYYY-MM-DD */
router.get("/phase4a/risk-metrics", wrap(async (req, res) => {
  const dateCompact = validateDate(req.query.date) ?? todayCompact();
  const args = ["--compute"];
  if (req.query.date) args.push("--date", String(req.query.date));
  const outFile = `risk_metrics_${dateCompact}.json`;
  await runPyThenRead("phase4a_risk_metrics.py", args, outFile, 30_000);
  const data = readDoc(outFile);
  res.json(data ?? { error: "No risk metrics data" });
}));

// ── Section 5: AI Metrics ─────────────────────────────────────────────────────

/** GET /phase4a/ai-metrics?date=YYYY-MM-DD */
router.get("/phase4a/ai-metrics", wrap(async (req, res) => {
  const dateCompact = validateDate(req.query.date) ?? todayCompact();
  const args: string[] = [];
  if (req.query.date) args.push("--date", String(req.query.date));
  const outFile = `ai_metrics_${dateCompact}.json`;
  await runPyThenRead("phase4a_ai_metrics.py", args, outFile, 30_000);
  const data = readDoc(outFile);
  res.json(data ?? { error: "No AI metrics data" });
}));

// ── Section 6: Session Reports ────────────────────────────────────────────────

/** POST /phase4a/reports/generate?date=YYYY-MM-DD&type=all|<type> */
router.post("/phase4a/reports/generate", wrap(async (req, res) => {
  const dateCompact = validateDate(req.query.date) ?? todayCompact();
  const type = typeof req.query.type === "string" ? req.query.type : "all";
  const args: string[] = [];
  if (req.query.date) args.push("--date", String(req.query.date));
  if (type === "all") {
    args.push("--all");
  } else {
    // Pass as two separate argv tokens — argparse requires this
    args.push("--type", type);
  }
  const manifestFile = `session_reports/${dateCompact}/manifest.json`;
  const data = await runPyThenRead("phase4a_reports.py", args, manifestFile, 180_000);
  res.json(data);
}));

/** GET /phase4a/reports/manifest?date=YYYY-MM-DD */
router.get("/phase4a/reports/manifest", wrap(async (req, res) => {
  const dateCompact = validateDate(req.query.date) ?? todayCompact();
  // dateCompact is validated to /^\d{8}$/ — safe to use in path
  const manifestPath = path.join(DOCS_DIR, "session_reports", dateCompact, "manifest.json");
  try {
    const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf-8"));
    res.json(manifest);
  } catch {
    res.status(404).json({
      error: "Manifest not found. POST to /phase4a/reports/generate first.",
    });
  }
}));

// ── Section 7: Continuous Validation ─────────────────────────────────────────

/** GET /phase4a/validate — run all 8 safety invariants.
 *  Run without --json so the script saves its output file; we read that. */
router.get("/phase4a/validate", wrap(async (_req, res) => {
  const dateCompact = todayCompact();
  const outFile = `validation_${dateCompact}.json`;
  await runPyThenRead("phase4a_validate.py", [], outFile, 60_000);
  const data = readDoc(outFile);
  res.json(data ?? { error: "No validation data" });
}));

// ── Final Report ──────────────────────────────────────────────────────────────

/** POST /phase4a/final-report?date=YYYY-MM-DD — generate and return. */
router.post("/phase4a/final-report", wrap(async (req, res) => {
  const dateCompact = validateDate(req.query.date) ?? todayCompact();
  const args: string[] = [];
  if (req.query.date) args.push("--date", String(req.query.date));
  const outFile = `Phase4A_Final_Report_${dateCompact}.json`;
  const data = await runPyThenRead("phase4a_final_report.py", args, outFile, 240_000);
  res.json(data);
}));

/** GET /phase4a/final-report?date=YYYY-MM-DD — return cached report. */
router.get("/phase4a/final-report", wrap(async (req, res) => {
  const dateCompact = validateDate(req.query.date) ?? todayCompact();
  const cached = readDoc(`Phase4A_Final_Report_${dateCompact}.json`);
  if (cached) return res.json(cached);
  res.status(404).json({
    error: `No final report for ${dateCompact}. POST to /phase4a/final-report to generate.`,
  });
}));

export default router;
