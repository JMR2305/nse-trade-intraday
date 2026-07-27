/**
 * preopen-validation.ts — Phase 5B Pre-Open Prediction Validation API routes.
 *
 * 9 endpoints under /api/preopen-validation/
 * All return {status:"DISABLED"} when PREOPEN_VALIDATION_ENABLED is off.
 * No order, execution, or trade-placement call exists in this file.
 *
 * PAPER TRADING / ADVISORY ONLY.
 */
import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import path from "path";
import { PYTHON_DIR, PYTHON_BIN } from "../lib/python-env";

const router: IRouter = Router();

// ── Python runner (same pattern as preopen.ts) ────────────────────────────────

function runPython(args: string[], timeoutMs = 60_000): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const proc = spawn(
      PYTHON_BIN,
      [path.join(PYTHON_DIR, "main.py"), ...args],
      { cwd: PYTHON_DIR },
    );
    let stdout = "";
    let stderr = "";
    let timedOut = false;

    const timer = setTimeout(() => {
      timedOut = true;
      proc.kill("SIGTERM");
      reject(new Error(`Pre-Open Validation Python timed out after ${timeoutMs / 1000}s`));
    }, timeoutMs);

    proc.stdout.on("data", (d: Buffer) => { stdout += d.toString(); });
    proc.stderr.on("data", (d: Buffer) => { stderr += d.toString(); });

    proc.on("close", (code) => {
      clearTimeout(timer);
      if (timedOut) return;
      if (code !== 0) {
        try {
          const parsed = JSON.parse(stdout.trim());
          if (parsed?.error) return reject(new Error(parsed.error));
        } catch { /* ignore */ }
        return reject(new Error(stderr || `Python exited ${code}`));
      }
      try {
        resolve(JSON.parse(stdout.trim()));
      } catch {
        reject(new Error(`Failed to parse Python output: ${stdout.slice(0, 200)}`));
      }
    });
  });
}

// ── In-memory response cache ──────────────────────────────────────────────────

interface CacheEntry { data: unknown; ts: number; ttl: number }
const _cache = new Map<string, CacheEntry>();

function cached(key: string, ttlMs: number, fn: () => Promise<unknown>): Promise<unknown> {
  const entry = _cache.get(key);
  if (entry && Date.now() - entry.ts < entry.ttl) return Promise.resolve(entry.data);
  return fn().then((data) => {
    _cache.set(key, { data, ts: Date.now(), ttl: ttlMs });
    return data;
  });
}

// ── Rate-limit for POST /run ──────────────────────────────────────────────────

let _lastRunAt = 0;
const RUN_COOLDOWN_MS = 30_000;

// ── Error wrapper ─────────────────────────────────────────────────────────────

const wrap = (fn: (req: any, res: any) => Promise<void>) =>
  (req: any, res: any) => {
    fn(req, res).catch((e: Error) => {
      const msg = e.message.replace(/DATABASE_URL=.*/g, "DATABASE_URL=***");
      res.status(500).json({ success: false, error: msg, label: "PAPER / ADVISORY ONLY" });
    });
  };

// ── GET /api/preopen-validation/status ───────────────────────────────────────

router.get("/preopen-validation/status", wrap(async (_req, res) => {
  const data = await cached("pv:status", 30_000, () =>
    runPython(["preopen_validation_status"], 20_000));
  res.json(data);
}));

// ── GET /api/preopen-validation/daily ────────────────────────────────────────

router.get("/preopen-validation/daily", wrap(async (req, res) => {
  const date = req.query.date as string | undefined;
  const key  = `pv:daily:${date || "latest"}`;
  const data = await cached(key, 60_000, () => {
    const args = ["preopen_validation_daily"];
    if (date) args.push(date);
    return runPython(args, 30_000);
  });
  res.json(data);
}));

// ── GET /api/preopen-validation/candidates ────────────────────────────────────

router.get("/preopen-validation/candidates", wrap(async (req, res) => {
  const date  = req.query.date as string | undefined;
  const limit = req.query.limit ? parseInt(req.query.limit as string, 10) : 200;
  const key   = `pv:candidates:${date || "latest"}:${limit}`;
  const data  = await cached(key, 60_000, () => {
    const args = ["preopen_validation_candidates"];
    if (date) args.push(date);
    args.push(String(limit));
    return runPython(args, 30_000);
  });
  res.json(data);
}));

// ── GET /api/preopen-validation/symbol/:symbol ────────────────────────────────

router.get("/preopen-validation/symbol/:symbol", wrap(async (req, res) => {
  const symbol = String(req.params.symbol || "").replace(/[^A-Za-z0-9&\-]/g, "").toUpperCase().slice(0, 20);
  const date   = req.query.date as string | undefined;
  const key    = `pv:symbol:${symbol}:${date || "latest"}`;
  const data   = await cached(key, 60_000, () => {
    const args = ["preopen_validation_symbol", symbol];
    if (date) args.push(date);
    return runPython(args, 20_000);
  });
  res.json(data);
}));

// ── GET /api/preopen-validation/score-bands ───────────────────────────────────

router.get("/preopen-validation/score-bands", wrap(async (req, res) => {
  const date = req.query.date as string | undefined;
  const key  = `pv:score-bands:${date || "latest"}`;
  const data = await cached(key, 120_000, () => {
    const args = ["preopen_validation_score_bands"];
    if (date) args.push(date);
    return runPython(args, 30_000);
  });
  res.json(data);
}));

// ── GET /api/preopen-validation/factors ──────────────────────────────────────

router.get("/preopen-validation/factors", wrap(async (req, res) => {
  const date = req.query.date as string | undefined;
  const key  = `pv:factors:${date || "latest"}`;
  const data = await cached(key, 120_000, () => {
    const args = ["preopen_validation_factors"];
    if (date) args.push(date);
    return runPython(args, 30_000);
  });
  res.json(data);
}));

// ── GET /api/preopen-validation/sectors ──────────────────────────────────────

router.get("/preopen-validation/sectors", wrap(async (req, res) => {
  const date = req.query.date as string | undefined;
  const key  = `pv:sectors:${date || "latest"}`;
  const data = await cached(key, 120_000, () => {
    const args = ["preopen_validation_sectors"];
    if (date) args.push(date);
    return runPython(args, 30_000);
  });
  res.json(data);
}));

// ── GET /api/preopen-validation/report ───────────────────────────────────────

router.get("/preopen-validation/report", wrap(async (req, res) => {
  const date = req.query.date as string | undefined;
  const key  = `pv:report:${date || "latest"}`;
  const data = await cached(key, 60_000, () => {
    const args = ["preopen_validation_report"];
    if (date) args.push(date);
    return runPython(args, 30_000);
  });
  res.json(data);
}));

// ── POST /api/preopen-validation/run ─────────────────────────────────────────

router.post("/preopen-validation/run", wrap(async (_req, res) => {
  const now = Date.now();
  if (now - _lastRunAt < RUN_COOLDOWN_MS) {
    const wait = Math.ceil((RUN_COOLDOWN_MS - (now - _lastRunAt)) / 1000);
    return void res.status(429).json({
      error: `Rate limited. Try again in ${wait}s.`,
      label: "PAPER / ADVISORY ONLY",
    });
  }
  _lastRunAt = now;
  _cache.clear();
  const data = await runPython(["preopen_validation_run"], 120_000);
  res.json(data);
}));

export default router;
