/**
 * Phase 23.8B — Validation & Certification Engines.
 *
 * ALL endpoints are read-only + advisory over the canonical stores.
 * Certification history lives only in the dedicated append-only
 * certification_runs table — nothing in the live trading state is modified.
 *
 * GET  /api/certification/validate/:domain   — one validation engine
 *        domains: data | pipeline | portfolio | replay | ai-decisions |
 *                 performance
 * POST /api/certification/run                — full certification run
 * GET  /api/certification/history            — append-only run history
 * GET  /api/certification/long-duration      — ?window=1w|2w|1m|3m|6m|1y
 * GET  /api/certification/:certId            — one persisted report
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

// ── short result cache + single-flight so slow validation runs never stack ─
const CACHE_TTL_MS = 30_000;
const cache = new Map<string, { at: number; value: unknown }>();
const inflight = new Map<string, Promise<unknown>>();

function cachedSingleFlight(
  key: string,
  factory: () => Promise<unknown>,
  ttlMs = CACHE_TTL_MS,
): Promise<unknown> {
  const hit = cache.get(key);
  if (hit && Date.now() - hit.at < ttlMs) return Promise.resolve(hit.value);
  const running = inflight.get(key);
  if (running) return running;
  const p = factory()
    .then((value) => {
      cache.set(key, { at: Date.now(), value });
      return value;
    })
    .finally(() => inflight.delete(key));
  inflight.set(key, p);
  return p;
}

const MAX_ID_LEN = 64;
const cleanId = (v: unknown): string => String(v ?? "").slice(0, MAX_ID_LEN);

const DOMAIN_MAP: Record<string, string> = {
  data: "data",
  pipeline: "pipeline",
  portfolio: "portfolio",
  replay: "replay",
  "ai-decisions": "ai_decision",
  ai_decision: "ai_decision",
  performance: "performance",
};

// GET /api/certification/validate/:domain
router.get("/certification/validate/:domain", async (req, res) => {
  try {
    const domain = DOMAIN_MAP[String(req.params.domain || "")];
    if (!domain) {
      res.status(400).json({
        success: false,
        error: `Unknown domain '${req.params.domain}' — use one of: ${Object.keys(DOMAIN_MAP).join(", ")}`,
      });
      return;
    }
    const payload: Record<string, unknown> = {};
    if (req.query.run_id) payload.run_id = cleanId(req.query.run_id);
    if (req.query.scan_id) payload.scan_id = cleanId(req.query.scan_id);
    if (req.query.source) payload.source = cleanId(req.query.source);
    if (req.query.mode) payload.mode = cleanId(req.query.mode);
    const key = `validate:${domain}:${JSON.stringify(payload)}`;
    res.json(
      await cachedSingleFlight(key, () =>
        runPython(["cert_validate", domain, JSON.stringify(payload)], 300_000),
      ),
    );
  } catch (err) {
    fail(res, err);
  }
});

// POST /api/certification/run — full certification (slow; single-flight)
router.post("/certification/run", async (req, res) => {
  try {
    const payload: Record<string, unknown> = {};
    if (req.body?.run_id) payload.run_id = cleanId(req.body.run_id);
    if (req.body?.source) payload.source = cleanId(req.body.source);
    const key = `cert:${JSON.stringify(payload)}`;
    res.json(
      await cachedSingleFlight(
        key,
        () => runPython(["cert_run", JSON.stringify(payload)], 600_000),
        10_000,
      ),
    );
  } catch (err) {
    fail(res, err);
  }
});

// GET /api/certification/history
router.get("/certification/history", async (req, res) => {
  try {
    res.json(
      await runPython(
        ["cert_history", JSON.stringify({ limit: Number(req.query.limit) || 50 })],
        60_000,
      ),
    );
  } catch (err) {
    fail(res, err);
  }
});

// GET /api/certification/long-duration?window=1m
router.get("/certification/long-duration", async (req, res) => {
  try {
    const window = cleanId(req.query.window || "1m");
    const key = `longdur:${window}`;
    res.json(
      await cachedSingleFlight(key, () =>
        runPython(["cert_long_duration", JSON.stringify({ window })], 300_000),
      ),
    );
  } catch (err) {
    fail(res, err);
  }
});

// GET /api/certification/:certId — keep LAST so named routes win
router.get("/certification/:certId", async (req, res) => {
  try {
    res.json(await runPython(["cert_get", cleanId(req.params.certId)], 60_000));
  } catch (err) {
    fail(res, err);
  }
});

export default router;
