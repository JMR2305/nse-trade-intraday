/**
 * Phase 23 Parts 6/7 — AI Strategy Optimization Lab + Institutional Analytics.
 *
 * ALL endpoints are read-only + advisory over the canonical stores
 * (backtest store, event store, paper ledger, candle cache). Base runs and
 * live settings are never modified.
 *
 * POST /api/lab/compare-runs        { run_ids }        — Part B table
 * POST /api/lab/what-if             { run_id, params } — Parts A/C derived sim
 * POST /api/lab/compare-configs     { run_id, configs }— Part A comparison
 * GET  /api/lab/walk-forward/:id?folds=               — Part D
 * GET  /api/lab/monte-carlo?source=&run_id=&n=        — Part E
 * GET  /api/lab/buckets?source=&run_id=               — Parts F/G/H
 * GET  /api/lab/leaderboard?source=&run_id=           — Part I
 * GET  /api/lab/calibration?source=&run_id=           — Part J
 * GET  /api/lab/dashboard?source=&run_id=             — Part K bundle
 * GET  /api/lab/recommendations?source=&run_id=       — Part L
 * GET  /api/lab/diff?a=&b=                            — Part M
 * GET  /api/lab/export?source=&run_id=&fmt=           — Part N (json/csv/md)
 * GET  /api/lab/verify?run_id=                        — Part O
 */
import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import path from "path";
import { PYTHON_BIN, PYTHON_DIR } from "../lib/python-env";

const router: IRouter = Router();

function runPython(args: string[], timeoutMs = 120_000): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], {
      cwd: PYTHON_DIR,
      env: process.env,
    });
    const timer = setTimeout(() => {
      proc.kill("SIGKILL");
      reject(new Error(`python timed out after ${timeoutMs}ms`));
    }, timeoutMs);
    let out = "";
    let err = "";
    proc.stdout.on("data", (d) => (out += d));
    proc.stderr.on("data", (d) => (err += d));
    proc.on("close", (code) => {
      clearTimeout(timer);
      if (code !== 0) return reject(new Error(err || `python exited ${code}`));
      try {
        resolve(JSON.parse(out));
      } catch {
        reject(new Error("invalid JSON from python"));
      }
    });
  });
}

function fail(res: any, err: unknown): void {
  res.status(500).json({
    success: false,
    error: err instanceof Error ? err.message : String(err),
  });
}

// ── input bounds (availability): cap payload sizes before spawning python ──
const MAX_RUN_IDS = 10;
const MAX_CONFIGS = 6;
const MAX_ID_LEN = 64;
const cleanId = (v: unknown): string => String(v ?? "").slice(0, MAX_ID_LEN);
function cleanParams(p: unknown): Record<string, unknown> {
  if (!p || typeof p !== "object") return {};
  const out: Record<string, unknown> = {};
  let n = 0;
  for (const [k, v] of Object.entries(p as Record<string, unknown>)) {
    if (++n > 20) break;
    if (typeof v === "number" && Number.isFinite(v)) out[k.slice(0, 40)] = v;
    else if (typeof v === "string") out[k.slice(0, 40)] = v.slice(0, 80);
  }
  return out;
}

// simple in-process coalescing cache for the heavy GET endpoints (Part P)
const cache = new Map<string, { at: number; p: Promise<unknown> }>();
const CACHE_MAX = 100;
function cachedPython(key: string, args: string[], timeoutMs: number,
                      ttlMs = 30_000): Promise<unknown> {
  const hit = cache.get(key);
  const now = Date.now();
  if (hit && now - hit.at < ttlMs) return hit.p;
  const p = runPython(args, timeoutMs).catch((e) => {
    cache.delete(key);
    throw e;
  });
  if (cache.size >= CACHE_MAX) {
    const oldest = [...cache.entries()].sort((a, b) => a[1].at - b[1].at)[0];
    if (oldest) cache.delete(oldest[0]);
  }
  cache.set(key, { at: now, p });
  return p;
}

const src = (req: any) =>
  String(req.query.source || "backtest") === "paper" ? "paper" : "backtest";
const rid = (req: any) =>
  req.query.run_id ? cleanId(req.query.run_id) : undefined;

router.post("/lab/compare-runs", async (req, res) => {
  try {
    const run_ids = (Array.isArray(req.body?.run_ids) ? req.body.run_ids : [])
      .slice(0, MAX_RUN_IDS).map(cleanId);
    res.json(await runPython(["lab_compare_runs",
      JSON.stringify({ run_ids })], 120_000));
  } catch (err) { fail(res, err); }
});

router.post("/lab/what-if", async (req, res) => {
  try {
    res.json(await runPython(["lab_what_if", JSON.stringify({
      run_id: cleanId(req.body?.run_id),
      params: cleanParams(req.body?.params),
    })], 180_000));
  } catch (err) { fail(res, err); }
});

router.post("/lab/compare-configs", async (req, res) => {
  try {
    const configs = (Array.isArray(req.body?.configs) ? req.body.configs : [])
      .slice(0, MAX_CONFIGS)
      .map((c: any) => ({
        label: String(c?.label ?? "").slice(0, 40),
        params: cleanParams(c?.params),
      }));
    res.json(await runPython(["lab_compare_configs", JSON.stringify({
      run_id: cleanId(req.body?.run_id),
      configs,
    })], 300_000));
  } catch (err) { fail(res, err); }
});

router.get("/lab/walk-forward/:id", async (req, res) => {
  try {
    res.json(await cachedPython(`wf:${req.params.id}:${req.query.folds || 4}`,
      ["lab_walk_forward", JSON.stringify({
        run_id: req.params.id, folds: Number(req.query.folds) || 4,
      })], 120_000));
  } catch (err) { fail(res, err); }
});

router.get("/lab/monte-carlo", async (req, res) => {
  try {
    res.json(await cachedPython(
      `mc:${src(req)}:${rid(req)}:${req.query.n || 500}`,
      ["lab_monte_carlo", JSON.stringify({
        source: src(req), run_id: rid(req),
        simulations: Number(req.query.n) || 500,
      })], 180_000));
  } catch (err) { fail(res, err); }
});

for (const [name, cmd, timeout] of [
  ["buckets", "lab_buckets", 120_000],
  ["leaderboard", "lab_leaderboard", 120_000],
  ["calibration", "lab_calibration", 120_000],
  ["dashboard", "lab_dashboard", 180_000],
  ["recommendations", "lab_recommendations", 300_000],
] as const) {
  router.get(`/lab/${name}`, async (req, res) => {
    try {
      res.json(await cachedPython(`${name}:${src(req)}:${rid(req)}`,
        [cmd, JSON.stringify({ source: src(req), run_id: rid(req) })],
        timeout));
    } catch (err) { fail(res, err); }
  });
}

router.get("/lab/diff", async (req, res) => {
  try {
    res.json(await runPython(["lab_run_diff", JSON.stringify({
      run_a: cleanId(req.query.a), run_b: cleanId(req.query.b),
    })], 120_000));
  } catch (err) { fail(res, err); }
});

router.get("/lab/export", async (req, res) => {
  try {
    const out = (await runPython(["lab_export", JSON.stringify({
      source: src(req), run_id: rid(req),
      fmt: String(req.query.fmt || "markdown"),
    })], 180_000)) as {
      ok: boolean; filename?: string; content_type?: string; content?: string;
    };
    if (!out?.ok || !out.content) {
      res.json(out);
      return;
    }
    res.setHeader("Content-Type", out.content_type || "text/plain");
    res.setHeader("Content-Disposition",
      `attachment; filename="${out.filename}"`);
    res.send(out.content);
  } catch (err) { fail(res, err); }
});

router.get("/lab/verify", async (req, res) => {
  try {
    res.json(await runPython(["lab_verify",
      JSON.stringify({ run_id: rid(req) })], 300_000));
  } catch (err) { fail(res, err); }
});

export default router;
