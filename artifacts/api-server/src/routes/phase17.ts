// Phase 17 — Automated QA, Regression Testing & Release Validation routes.
// PAPER TRADING / RESEARCH ONLY. The complete validation run executes every
// Python test suite plus API/data/benchmark checks and can take several
// minutes, so it runs as a background job with a polling status endpoint
// (same pattern as the review-package generator).

import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import path from "path";
import fs from "fs";

const router: IRouter = Router();
const PYTHON_DIR = path.join(process.cwd(), "src", "python");
const REPORT_DIR = path.join(PYTHON_DIR, "phase17_reports");

function runPython(args: string[], timeoutMs = 90_000): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const proc = spawn("python3", [path.join(PYTHON_DIR, "main.py"), ...args], { cwd: PYTHON_DIR });
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

// ── quick reads ────────────────────────────────────────────────────────────
router.get("/phase17/build-info", wrap(async (_req, res) => {
  res.json(await runPython(["phase17_build_info"]));
}));
router.get("/phase17/dashboard", wrap(async (_req, res) => {
  res.json(await runPython(["phase17_dashboard"]));
}));
router.get("/phase17/history", wrap(async (_req, res) => {
  res.json(await runPython(["phase17_history"]));
}));
router.get("/phase17/last", wrap(async (_req, res) => {
  res.json(await runPython(["phase17_last"], 120_000));
}));

// ── one-click complete validation (background job) ─────────────────────────
interface ValidationJob {
  status: "idle" | "running" | "done" | "error";
  stage: string;
  startedAt: number | null;
  result: unknown | null;
  error: string | null;
}
const job: ValidationJob = { status: "idle", stage: "", startedAt: null, result: null, error: null };

router.post("/phase17/run", (req, res) => {
  if (job.status === "running") {
    res.status(409).json({ error: "A validation run is already in progress. Please wait." });
    return;
  }
  const notes = typeof req.body?.notes === "string" ? req.body.notes.slice(0, 500) : "";
  job.status = "running";
  job.stage = "Running all test suites, API checks, data integrity and benchmarks (2-10 min)";
  job.startedAt = Date.now();
  job.result = null;
  job.error = null;
  runPython(["phase17_run", notes], 15 * 60_000)
    .then(async (result) => {
      job.stage = "Generating reports (PDF / XLSX / CSV / JSON)";
      try { await runPython(["phase17_reports"], 120_000); }
      catch { /* report generation failure is surfaced via files list */ }
      job.result = result;
      job.status = "done";
      job.stage = "Complete";
    })
    .catch((err: unknown) => {
      job.status = "error";
      job.error = err instanceof Error ? err.message : String(err);
    });
  res.status(202).json({ started: true, status: "running" });
});

router.get("/phase17/run/status", (_req, res) => {
  res.json({
    status: job.status,
    stage: job.stage,
    elapsed_seconds: job.startedAt && job.status === "running"
      ? Math.round((Date.now() - job.startedAt) / 1000) : null,
    result: job.status === "done" ? job.result : null,
    error: job.error,
  });
});

// ── reports ─────────────────────────────────────────────────────────────────
router.post("/phase17/reports", wrap(async (_req, res) => {
  res.json(await runPython(["phase17_reports"], 120_000));
}));

router.get("/phase17/reports/:file", wrap(async (req, res) => {
  const name = path.basename(String(req.params.file));
  const full = path.join(REPORT_DIR, name);
  if (!full.startsWith(REPORT_DIR) || !fs.existsSync(full)) {
    res.status(404).json({ success: false, error: `Report not found: ${name}. Run a complete validation first.` });
    return;
  }
  res.download(full, name);
}));

export default router;
