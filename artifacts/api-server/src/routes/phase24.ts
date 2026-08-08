/**
 * phase24.ts — Phase 24: AI Learning & Continuous Improvement Engine.
 *
 * Routes (all advisory-only; nothing here mutates trading configuration):
 *   GET  /api/phase24/overview               — full AI Learning Center payload (cached)
 *   GET  /api/phase24/trades                 — permanent Trade Intelligence records
 *   POST /api/phase24/capture                — capture closed trades (idempotent)
 *   GET  /api/phase24/missed                 — stored missed-opportunity records
 *   POST /api/phase24/missed/run             — analyse latest scan rejections
 *   GET  /api/phase24/risk-learning          — per-rule effectiveness
 *   GET  /api/phase24/strategy-ranking
 *   GET  /api/phase24/sector-ranking
 *   GET  /api/phase24/time-analysis
 *   GET  /api/phase24/calibration
 *   GET  /api/phase24/scorecard
 *   GET  /api/phase24/recommendations        — ?status=PROPOSED|APPROVED|DISMISSED
 *   POST /api/phase24/recommendations/generate
 *   POST /api/phase24/recommendations/:id/decide  { decision, note? }
 *   GET  /api/phase24/reports                — ?period=daily|weekly|monthly|quarterly
 *   POST /api/phase24/reports/generate       { period }
 *
 * PAPER / RESEARCH ONLY. Approving a recommendation records intent only —
 * the engine has NO write path into trading rules, thresholds, or strategies.
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
  });
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const wrap = (fn: (req: any, res: any) => Promise<void>) =>
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (req: any, res: any) => {
    fn(req, res).catch((e: Error) =>
      res.status(500).json({ success: false, error: e.message }));
  };

// Overview is a slow aggregate — 30 s route-side cache + single-flight.
const OVERVIEW_CACHE_MS = 30_000;
let overviewCache: { data: unknown; ts: number } | null = null;
let overviewInFlight: Promise<unknown> | null = null;

router.get("/phase24/overview", wrap(async (req, res) => {
  const force = req.query.refresh === "true";
  if (!force && overviewCache && Date.now() - overviewCache.ts < OVERVIEW_CACHE_MS) {
    res.json(overviewCache.data);
    return;
  }
  if (!overviewInFlight) {
    overviewInFlight = runPython(["p24_overview"], 120_000)
      .finally(() => { overviewInFlight = null; });
  }
  const data = await overviewInFlight;
  overviewCache = { data, ts: Date.now() };
  res.json(data);
}));

const simple = (route: string, cmd: string, timeoutMs = 90_000) =>
  router.get(`/phase24/${route}`, wrap(async (_req, res) => {
    res.json(await runPython([cmd], timeoutMs));
  }));

simple("risk-learning", "p24_risk_learning");
simple("strategy-ranking", "p24_strategy_ranking");
simple("sector-ranking", "p24_sector_ranking");
simple("time-analysis", "p24_time_analysis");
simple("calibration", "p24_calibration");
simple("scorecard", "p24_scorecard", 120_000);
simple("missed", "p24_missed");

router.get("/phase24/trades", wrap(async (req, res) => {
  const limit = String(parseInt(String(req.query.limit ?? "500"), 10) || 500);
  res.json(await runPython(["p24_trades", limit]));
}));

router.post("/phase24/capture", wrap(async (_req, res) => {
  res.json(await runPython(["p24_capture"], 150_000));
}));

router.post("/phase24/missed/run", wrap(async (_req, res) => {
  res.json(await runPython(["p24_missed_run"], 150_000));
}));

router.get("/phase24/recommendations", wrap(async (req, res) => {
  const status = String(req.query.status ?? "");
  const args = status ? ["p24_recommendations", status] : ["p24_recommendations"];
  res.json(await runPython(args));
}));

router.post("/phase24/recommendations/generate", wrap(async (_req, res) => {
  res.json(await runPython(["p24_recommendations_generate"], 150_000));
}));

router.post("/phase24/recommendations/:id/decide", wrap(async (req, res) => {
  const decision = String(req.body?.decision ?? "").toLowerCase();
  if (decision !== "approve" && decision !== "dismiss") {
    res.status(400).json({ error: 'Body must contain { "decision": "approve" | "dismiss" }' });
    return;
  }
  const note = String(req.body?.note ?? "").slice(0, 500);
  res.json(await runPython(["p24_rec_decide", req.params.id, decision, note]));
}));

router.get("/phase24/reports", wrap(async (req, res) => {
  const period = String(req.query.period ?? "");
  const args = period ? ["p24_reports", period] : ["p24_reports"];
  res.json(await runPython(args));
}));

router.post("/phase24/reports/generate", wrap(async (req, res) => {
  const period = String(req.body?.period ?? "daily");
  if (!["daily", "weekly", "monthly", "quarterly"].includes(period)) {
    res.status(400).json({ error: "period must be daily|weekly|monthly|quarterly" });
    return;
  }
  const args = ["p24_report_generate", period];
  if (req.body?.force === true) args.push("--force");
  res.json(await runPython(args, 150_000));
}));

export default router;
