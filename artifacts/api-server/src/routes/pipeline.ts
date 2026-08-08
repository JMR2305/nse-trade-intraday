/**
 * Phase 23 — canonical Pipeline Event Store routes.
 *
 * GET /api/pipeline/events           — filtered event query (since_id, scan_id,
 *                                      mode, stage, event_type, symbol, limit)
 * GET /api/pipeline/summary          — per-stage counts for the latest (or
 *                                      given) scan, derived purely from events
 *
 * A lightweight tail poller bridges new events onto the existing SSE bus as
 * `pipeline.event` messages while at least one dashboard client is connected,
 * so the Live Command Center updates without per-client Python spawns.
 */
import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import path from "path";
import { PYTHON_BIN, PYTHON_DIR } from "../lib/python-env";
import { eventBus } from "../lib/events";
import { sseClientCount } from "./stream";

const router: IRouter = Router();

function runPython(args: string[]): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], {
      cwd: PYTHON_DIR,
      env: process.env,
    });
    let out = "";
    let err = "";
    proc.stdout.on("data", (d) => (out += d));
    proc.stderr.on("data", (d) => (err += d));
    proc.on("close", (code) => {
      if (code !== 0) return reject(new Error(err || `python exited ${code}`));
      try {
        resolve(JSON.parse(out));
      } catch {
        reject(new Error("invalid JSON from python"));
      }
    });
  });
}

function q(v: unknown): string | undefined {
  return typeof v === "string" && v.length > 0 ? v : undefined;
}

router.get("/pipeline/events", async (req, res) => {
  try {
    const payload = {
      scan_id: q(req.query.scan_id),
      run_id: q(req.query.run_id),
      mode: q(req.query.mode) || "LIVE",
      event_type: q(req.query.event_type),
      stage: q(req.query.stage),
      symbol: q(req.query.symbol),
      since_id: Number(req.query.since_id) || 0,
      limit: Number(req.query.limit) || 200,
      newest_first: req.query.newest_first === "true",
    };
    res.json(await runPython(["pipeline_events", JSON.stringify(payload)]));
  } catch (err) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});

// Summary is cached briefly + single-flight (same pattern as scan status) —
// it backs the always-visible pipeline visual.
const SUMMARY_CACHE_MS = 5_000;
let summaryCache: { key: string; data: unknown; ts: number } | null = null;
let summaryInFlight: Map<string, Promise<unknown>> = new Map();

router.get("/pipeline/summary", async (req, res) => {
  try {
    const payload = {
      scan_id: q(req.query.scan_id),
      run_id: q(req.query.run_id),
      mode: q(req.query.mode) || "LIVE",
    };
    const key = JSON.stringify(payload);
    if (summaryCache && summaryCache.key === key && Date.now() - summaryCache.ts < SUMMARY_CACHE_MS) {
      res.json(summaryCache.data);
      return;
    }
    let p = summaryInFlight.get(key);
    if (!p) {
      p = runPython(["pipeline_summary", key])
        .then((data) => {
          summaryCache = { key, data, ts: Date.now() };
          return data;
        })
        .finally(() => summaryInFlight.delete(key));
      summaryInFlight.set(key, p);
    }
    res.json(await p);
  } catch (err) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});

// ── SSE tail bridge ──────────────────────────────────────────────────────────
// Polls for new LIVE events every few seconds and republishes them on the
// in-process event bus (which /api/stream fans out to dashboards). Runs only
// while there are SSE listeners; interval widens when idle.
let lastSeenId = 0;
let tailTimer: NodeJS.Timeout | null = null;
let tailBusy = false;

const TAIL_ACTIVE_MS = 3_000;

async function tailOnce(): Promise<void> {
  // Poll only while at least one SSE client is connected — no clients means
  // no one to fan events out to, so skip the Python spawn entirely.
  if (tailBusy || sseClientCount() === 0) return;
  tailBusy = true;
  try {
    const resp = (await runPython([
      "pipeline_events",
      JSON.stringify({ since_id: lastSeenId, mode: "LIVE", limit: 200 }),
    ])) as { events?: Array<Record<string, unknown>> };
    const events = resp?.events ?? [];
    for (const ev of events) {
      const id = Number(ev.id) || 0;
      if (id > lastSeenId) lastSeenId = id;
      eventBus.publish("pipeline.event", ev);
    }
  } catch {
    /* tail failures are silent — dashboards fall back to REST polling */
  } finally {
    tailBusy = false;
  }
}

export function startPipelineTail(): void {
  if (tailTimer) return;
  // Initialize cursor to the newest event so we only stream fresh activity.
  runPython(["pipeline_events", JSON.stringify({ mode: "LIVE", limit: 1, newest_first: true })])
    .then((resp) => {
      const events = (resp as { events?: Array<{ id?: number }> })?.events ?? [];
      if (events[0]?.id) lastSeenId = Number(events[0].id);
    })
    .catch(() => {})
    .finally(() => {
      tailTimer = setInterval(() => {
        void tailOnce();
      }, TAIL_ACTIVE_MS);
      tailTimer.unref?.();
    });
}

export default router;
