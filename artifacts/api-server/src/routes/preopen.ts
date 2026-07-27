/**
 * preopen.ts — Phase 5A: Pre-Open Intelligence Module
 *
 * Routes:
 *   GET  /api/preopen/status          — module status + feature flag
 *   GET  /api/preopen/health          — provider health check
 *   GET  /api/preopen/snapshot        — full snapshot for today
 *   GET  /api/preopen/symbol/:symbol  — single-symbol snapshot
 *   GET  /api/preopen/rankings        — ranked opportunity list
 *   GET  /api/preopen/watchlist       — 8 watchlists (frozen at 09:15)
 *   GET  /api/preopen/sectors         — sector-level aggregation
 *   GET  /api/preopen/report          — full session report
 *   POST /api/preopen/refresh         — trigger manual snapshot collection
 *
 * All endpoints:
 *   - Return structured JSON with provider_status + freshness
 *   - Fail safely when provider is unavailable
 *   - Return { status: "DISABLED" } when PREOPEN_INTELLIGENCE_ENABLED=false
 *   - Enforce request timeouts
 *   - Use in-memory cache where appropriate
 *   - Never leak secrets
 *
 * PAPER TRADING / ADVISORY ONLY. Pre-open data cannot submit orders.
 */
import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import path from "path";

const router: IRouter = Router();
import { PYTHON_DIR, PYTHON_BIN } from "../lib/python-env";

// ── Simple in-memory cache ────────────────────────────────────────────────────
interface CacheEntry {
  data: unknown;
  ts: number;
}
const _cache = new Map<string, CacheEntry>();
const CACHE_TTL_MS: Record<string, number> = {
  status:   15_000,   // 15 s
  health:   30_000,   // 30 s
  snapshot: 30_000,
  rankings: 30_000,
  watchlist:60_000,   // 1 min — frozen list
  sectors:  30_000,
  report:   60_000,
};

function cached(key: string, fn: () => Promise<unknown>): Promise<unknown> {
  const ttl = CACHE_TTL_MS[key] ?? 30_000;
  const entry = _cache.get(key);
  if (entry && Date.now() - entry.ts < ttl) {
    return Promise.resolve(entry.data);
  }
  return fn().then((data) => {
    _cache.set(key, { data, ts: Date.now() });
    return data;
  });
}

function bustCache(key?: string): void {
  if (key) {
    _cache.delete(key);
  } else {
    _cache.clear();
  }
}

// ── Python runner ─────────────────────────────────────────────────────────────

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
      reject(new Error(`Pre-open Python timed out after ${timeoutMs / 1000}s`));
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

const wrap = (fn: (req: any, res: any) => Promise<void>) =>
  (req: any, res: any) => {
    fn(req, res).catch((e: Error) => {
      // Never propagate raw error text that might leak secrets
      const msg = e.message.replace(/DATABASE_URL=.*/g, "DATABASE_URL=***");
      res.status(500).json({ success: false, error: msg });
    });
  };

// ── Sanitise symbol param ─────────────────────────────────────────────────────
function sanitiseSymbol(raw: string): string {
  return String(raw || "").replace(/[^A-Za-z0-9&\-]/g, "").toUpperCase().slice(0, 20);
}

// ── Routes ────────────────────────────────────────────────────────────────────

/** GET /api/preopen/status */
router.get("/preopen/status", wrap(async (_req, res) => {
  const data = await cached("status", () => runPython(["preopen_status"]));
  res.json(data);
}));

/** GET /api/preopen/health */
router.get("/preopen/health", wrap(async (_req, res) => {
  const data = await cached("health", () => runPython(["preopen_health"], 20_000));
  res.json(data);
}));

/** GET /api/preopen/snapshot */
router.get("/preopen/snapshot", wrap(async (_req, res) => {
  const data = await cached("snapshot", () => runPython(["preopen_snapshot"], 45_000));
  res.json(data);
}));

/** GET /api/preopen/symbol/:symbol */
router.get("/preopen/symbol/:symbol", wrap(async (req, res) => {
  const sym = sanitiseSymbol(req.params.symbol || "");
  if (!sym) {
    res.status(400).json({ success: false, error: "symbol is required" });
    return;
  }
  const data = await runPython(["preopen_symbol", sym], 30_000);
  res.json(data);
}));

/** GET /api/preopen/rankings */
router.get("/preopen/rankings", wrap(async (_req, res) => {
  const data = await cached("rankings", () => runPython(["preopen_rankings"], 45_000));
  res.json(data);
}));

/** GET /api/preopen/watchlist */
router.get("/preopen/watchlist", wrap(async (_req, res) => {
  const data = await cached("watchlist", () => runPython(["preopen_watchlist"], 30_000));
  res.json(data);
}));

/** GET /api/preopen/sectors */
router.get("/preopen/sectors", wrap(async (_req, res) => {
  const data = await cached("sectors", () => runPython(["preopen_sectors"], 30_000));
  res.json(data);
}));

/** GET /api/preopen/report */
router.get("/preopen/report", wrap(async (_req, res) => {
  const data = await cached("report", () => runPython(["preopen_report"], 60_000));
  res.json(data);
}));

/**
 * POST /api/preopen/refresh
 * Manual trigger for a fresh snapshot collection.
 * Rate-limited: max 1 per 30s.
 */
let _lastRefresh = 0;
router.post("/preopen/refresh", wrap(async (_req, res) => {
  const now = Date.now();
  if (now - _lastRefresh < 30_000) {
    res.status(429).json({
      success: false,
      error: "Refresh rate-limited — wait 30 s between manual refreshes",
      retry_after_seconds: Math.ceil((30_000 - (now - _lastRefresh)) / 1000),
    });
    return;
  }
  _lastRefresh = now;
  bustCache();  // invalidate all caches after a manual refresh
  const data = await runPython(["preopen_refresh"], 60_000);
  res.json(data);
}));

export default router;
