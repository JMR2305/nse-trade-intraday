import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import type { ChildProcess } from "child_process";
import path from "path";
import fs from "fs";
import { eventBus } from "../lib/events";
import { clearCommandCenterCache } from "./command-center";

const router: IRouter = Router();

import { PYTHON_DIR, PYTHON_BIN } from "../lib/python-env";
import { dispatchSignalPushNotifications } from "../lib/pushNotifier";

// Timeouts by command type.  Scan commands run yf.download across 50 symbols
// and need up to ~150 s; all other commands should finish well within 90 s.
const SCAN_COMMANDS = new Set(["phase7_scan", "market_scan", "scan"]);
function cmdTimeout(args: string[]): number {
  return SCAN_COMMANDS.has(args[0] ?? "") ? 150_000 : 90_000;
}

function runPython(args: string[]): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], {
      cwd: PYTHON_DIR,
    });

    let stdout = "";
    let stderr = "";

    const timer = setTimeout(() => {
      proc.kill("SIGTERM");
      reject(new Error(`Python process timed out after ${cmdTimeout(args) / 1000}s (${args[0] ?? "unknown"})`));
    }, cmdTimeout(args));

    proc.stdout.on("data", (d: Buffer) => {
      stdout += d.toString();
    });
    proc.stderr.on("data", (d: Buffer) => {
      stderr += d.toString();
    });

    proc.on("close", (code) => {
      clearTimeout(timer);
      if (code !== 0) {
        try {
          const parsed = JSON.parse(stdout.trim());
          if (parsed.error) return reject(new Error(parsed.error));
        } catch {
          // ignore parse error
        }
        reject(new Error(stderr || `Python exited with code ${code}`));
      } else {
        // Find the last line that is valid JSON (subsystems may print
        // structured log lines to stdout before the result JSON).
        const lines = stdout.trim().split("\n");
        let _parsed: unknown;
        for (let i = lines.length - 1; i >= 0; i--) {
          const line = lines[i].trim();
          if (!line) continue;
          try { _parsed = JSON.parse(line); break; } catch { /* skip */ }
        }
        if (_parsed !== undefined) {
          resolve(_parsed);
        } else {
          reject(new Error(`Failed to parse Python output: ${stdout}`));
        }
      }
    });

    proc.on("error", (err) => {
      reject(err);
    });
  });
}

// GET /api/portfolio
router.get("/portfolio", async (_req, res) => {
  try {
    const data = await runPython(["portfolio"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/signals
router.get("/signals", async (_req, res) => {
  try {
    const data = await runPython(["signals"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/signal-history
// ?limit=N (default 30, max 200) — last N snapshots, newest first
// ?from=YYYY-MM-DD&to=YYYY-MM-DD — optional inclusive date bounds
router.get("/signal-history", async (req, res) => {
  try {
    const limitRaw = parseInt(String(req.query.limit ?? ""), 10);
    const limit = Number.isFinite(limitRaw) ? Math.min(Math.max(limitRaw, 1), 200) : 30;
    const dateRe = /^\d{4}-\d{2}-\d{2}(T[\d:.+Z-]*)?$/;
    const from = typeof req.query.from === "string" && dateRe.test(req.query.from) ? req.query.from : "-";
    const toRaw = typeof req.query.to === "string" && dateRe.test(req.query.to) ? req.query.to : "-";
    // Make a bare "to" date inclusive of the whole day
    const to = toRaw !== "-" && !toRaw.includes("T") ? `${toRaw}T23:59:59.999+05:30` : toRaw;
    const data = await runPython(["signal_history", String(limit), from, to]);
    res.json({ snapshots: data ?? [] });
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/trades
// ?scope=all returns all-time history including trades archived by portfolio
// resets; default returns current-session trades only.
router.get("/trades", async (req, res) => {
  try {
    const scope = req.query.scope === "all" ? "trades_all" : "trades";
    const data = await runPython([scope]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/run-scan
// The UI's useRunScan() mutation targets this route.  We use spawnRunScan so
// the process is tracked and POST /api/live-data/scan/abort can kill it.
// Idempotent: concurrent callers join the same in-flight promise.
router.post("/run-scan", async (_req, res) => {
  try {
    if (!rsScanInFlight) {
      rsScanInFlight = spawnRunScan(["scan"])
        .finally(() => { rsScanInFlight = null; });
    }
    const result = await rsScanInFlight as Record<string, unknown>;
    res.json({
      signals: result.signals ?? [],
      ai_decisions: result.ai_decisions ?? [],
      scanned_at: result.scanned_at ?? new Date().toISOString(),
    });
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/watchlist
router.get("/watchlist", async (_req, res) => {
  try {
    const data = await runPython(["watchlist"]) as string[];
    res.json({ watchlist: data });
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/symbols — known NSE symbol universe (for watchlist autocomplete)
router.get("/symbols", async (_req, res) => {
  try {
    const data = await runPython(["symbols"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/symbols/search?q=… — Priority 9 (#34): search the approved
// research universe by ticker, company name or alias. Only approved
// instruments are returned; ambiguous input requires explicit user selection.
router.get("/symbols/search", async (req, res) => {
  try {
    const q = String(req.query.q ?? "").trim();
    if (!q) {
      res.json({ results: [], query: "" });
      return;
    }
    const data = await runPython(["symbol_search", q]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/watchlist
router.post("/watchlist", async (req, res) => {
  const { symbol } = req.body as { symbol?: string };
  if (!symbol) {
    res.status(400).json({ error: "symbol is required" });
    return;
  }
  try {
    const data = await runPython(["watchlist_add", symbol]) as Record<string, unknown>;
    if (data && typeof data.error === "string") {
      res.status(400).json({ error: data.error });
      return;
    }
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// DELETE /api/watchlist/:symbol
router.delete("/watchlist/:symbol", async (req, res) => {
  const { symbol } = req.params;
  try {
    const data = await runPython(["watchlist_remove", symbol]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/portfolio/reset
// Destructive-adjacent action (cash back to initial capital, positions
// cleared; trades are archived, never deleted). Requires an explicit
// confirmation in the request body so a stray API call or single click
// can never reset the portfolio.
export const PORTFOLIO_RESET_CONFIRMATION = "RESET PORTFOLIO";

router.post("/portfolio/reset", async (req, res) => {
  try {
    const confirmation = (req.body?.confirmation ?? "").toString();
    if (confirmation !== PORTFOLIO_RESET_CONFIRMATION) {
      res.status(400).json({
        error: "Confirmation required",
        detail:
          `Portfolio reset requires body {"confirmation": "${PORTFOLIO_RESET_CONFIRMATION}"}. ` +
          "Reset clears positions and restores initial cash; trade history is archived, not deleted.",
      });
      return;
    }
    const reason = (req.body?.reason ?? "Manual portfolio reset").toString().slice(0, 300);
    const data = await runPython(["reset", reason]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// PATCH /api/portfolio/position/:symbol/stop
// Update the stop-loss on an open paper-trading position so that Daily Risk
// and the portfolio heat heatmap reflect the operator's current thesis.
// Body: { stop_loss: number }  — must be > 0 and < current price.
router.patch("/portfolio/position/:symbol/stop", async (req, res) => {
  try {
    const symbol = req.params.symbol.toUpperCase();
    const stop_loss = Number(req.body?.stop_loss);
    if (!symbol || isNaN(stop_loss) || stop_loss <= 0) {
      res.status(400).json({ error: 'Body must contain { "stop_loss": <positive number> }' });
      return;
    }
    const data = await runPython(["update_stop", symbol, stop_loss.toString()]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// ── Priority 2 (#21): Archived session review & guarded restore ─────────────
// Restore is a two-step flow: step 1 validates the exact confirmation phrase
// and issues a one-time restore token; step 2 requires the phrase AGAIN plus
// the token. The Python layer archives the current session before applying
// and rolls back on failure. Only simulated paper state is ever touched.
export const SESSION_RESTORE_CONFIRMATION = "RESTORE PAPER SESSION";

// GET /api/session-archives — list archived sessions (read-only)
router.get("/session-archives", async (_req, res) => {
  try {
    const data = await runPython(["session_archives"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/session-archives/:id — inspect one archive (read-only)
router.get("/session-archives/:id", async (req, res) => {
  try {
    const data = await runPython(["session_archive_get", req.params.id]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/session-archives/:id/restore
// Body: { confirmation } → step 1 (issues restore_token)
// Body: { confirmation, restore_token } → step 2 (executes restore)
router.post("/session-archives/:id/restore", async (req, res) => {
  try {
    const confirmation = (req.body?.confirmation ?? "").toString();
    if (confirmation !== SESSION_RESTORE_CONFIRMATION) {
      res.status(400).json({
        error: "Confirmation required",
        detail:
          `Session restore requires body {"confirmation": "${SESSION_RESTORE_CONFIRMATION}"} ` +
          "typed exactly. This restores simulated paper state only.",
      });
      return;
    }
    const token = (req.body?.restore_token ?? "").toString();
    const data = token
      ? await runPython(["session_restore_confirm", req.params.id, confirmation, token])
      : await runPython(["session_restore_request", req.params.id, confirmation]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/opportunity-scan
// Idempotent: concurrent callers (e.g. two operators clicking Refresh at the
// same time) share a single Python spawn instead of duplicating expensive work.
let opportunityScanInFlight: Promise<unknown> | null = null;

router.get("/opportunity-scan", async (_req, res) => {
  try {
    if (!opportunityScanInFlight) {
      opportunityScanInFlight = runPython(["opportunity_scan"])
        .finally(() => { opportunityScanInFlight = null; });
    }
    const data = await opportunityScanInFlight;
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/market-scan
// Scanning the full NIFTY 50 universe takes ~20-30s, so cache the result for
// a short window to keep repeat page loads / polling fast.
const MARKET_SCAN_CACHE_MS = 2 * 60 * 1000;
let marketScanCache: { data: unknown; ts: number } | null = null;
let marketScanInFlight: Promise<unknown> | null = null;

router.get("/market-scan", async (req, res) => {
  try {
    const force = req.query.refresh === "true";
    if (!force && marketScanCache && Date.now() - marketScanCache.ts < MARKET_SCAN_CACHE_MS) {
      res.json(marketScanCache.data);
      return;
    }
    if (!marketScanInFlight) {
      marketScanInFlight = runPython(["market_scan"]).finally(() => {
        marketScanInFlight = null;
      });
    }
    const data = await marketScanInFlight;
    marketScanCache = { data, ts: Date.now() };
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/market-replay
// Historical Market Scanner / Market Replay — paper trading only, no real
// orders. Scanning ~50 stocks over a historical window takes ~15-20s, so
// cache per (scan_date, holding_period, interval) combination.
const MARKET_REPLAY_CACHE_MS = 10 * 60 * 1000;
const marketReplayCache = new Map<string, { data: unknown; ts: number }>();
const marketReplayInFlight = new Map<string, Promise<unknown>>();

router.get("/market-replay", async (req, res) => {
  try {
    const scanDate = String(req.query.scan_date || "");
    const holdingPeriod = String(req.query.holding_period || "5");
    const interval = String(req.query.interval || "daily");

    if (!/^\d{4}-\d{2}-\d{2}$/.test(scanDate)) {
      res.status(400).json({ error: "scan_date must be in YYYY-MM-DD format" });
      return;
    }

    const cacheKey = `${scanDate}|${holdingPeriod}|${interval}`;
    const cached = marketReplayCache.get(cacheKey);
    if (cached && Date.now() - cached.ts < MARKET_REPLAY_CACHE_MS) {
      res.json(cached.data);
      return;
    }

    let inFlight = marketReplayInFlight.get(cacheKey);
    if (!inFlight) {
      inFlight = runPython(["market_replay", scanDate, holdingPeriod, interval]).finally(() => {
        marketReplayInFlight.delete(cacheKey);
      });
      marketReplayInFlight.set(cacheKey, inFlight);
    }
    const data = await inFlight;
    marketReplayCache.set(cacheKey, { data, ts: Date.now() });
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/market-context
router.get("/market-context", async (_req, res) => {
  try {
    const data = await runPython(["market_context"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/ai-decisions
router.get("/ai-decisions", async (_req, res) => {
  try {
    const data = await runPython(["ai_decisions"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/trade-replay
router.get("/trade-replay", async (_req, res) => {
  try {
    const data = await runPython(["trade_replay"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/learning-summary
router.get("/learning-summary", async (_req, res) => {
  try {
    const data = await runPython(["learning_summary"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/trade-intelligence
// Trade Intelligence Database (Sprint 3) — historical completed paper trades
// with indicators at entry, AI metrics, and win/loss classification.
router.get("/trade-intelligence", async (req, res) => {
  try {
    const limit = String(parseInt(String(req.query.limit ?? "200"), 10) || 200);
    const data = await runPython(["trade_intelligence", limit]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/trade-intelligence/import
// Backfill the trade intelligence table from existing paper portfolio history.
router.post("/trade-intelligence/import", async (_req, res) => {
  try {
    const data = await runPython(["trade_intelligence_import"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/predictive-intelligence/:symbol
// Predictive Intelligence Engine (Sprint 3) — historical evidence for a
// candidate built from live indicators + cached AI metrics. Evidence layer
// only; never modifies scanner logic or places orders.
router.get("/predictive-intelligence/:symbol", async (req, res) => {
  try {
    const symbol = String(req.params.symbol || "").trim().toUpperCase();
    if (!symbol) {
      res.status(400).json({ error: "symbol is required" });
      return;
    }
    const data = await runPython(["predictive_intelligence", symbol]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/predictive-intelligence/evaluate
// Evaluate an explicit candidate setup against historical trades.
router.post("/predictive-intelligence/evaluate", async (req, res) => {
  try {
    const candidate = req.body ?? {};
    if (typeof candidate !== "object" || !candidate.symbol) {
      res.status(400).json({ error: "body must include a 'symbol' field" });
      return;
    }
    const data = await runPython(["predictive_evaluate", JSON.stringify(candidate)]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// ── Historical Knowledge Base (Sprint 3 — Module 2A) ─────────────────────────
// Builds a research dataset by simulating existing strategies on Yahoo
// Finance history. Research only — no orders. The build is long-running
// (NIFTY 50 × 6 strategies × up to 5 years), so it runs as a detached
// python process and the UI polls the summary endpoint for progress.

let hkBuildRunning = false;

const HK_STATUS_PATH = path.join(PYTHON_DIR, "historical_knowledge_status.json");

// Durable cross-process check: status file says "running" AND the recorded
// builder pid is still alive. Survives API server restarts.
function hkStatusFileRunning(): boolean {
  try {
    const status = JSON.parse(fs.readFileSync(HK_STATUS_PATH, "utf-8"));
    if (status?.status !== "running") return false;
    const pid = Number(status?.pid);
    if (!Number.isInteger(pid) || pid <= 0) return false;
    try {
      process.kill(pid, 0);
      return true; // builder process is alive
    } catch {
      return false; // stale status — builder is gone (python side reconciles it)
    }
  } catch {
    return false;
  }
}

// POST /api/historical-knowledge/build
router.post("/historical-knowledge/build", async (req, res) => {
  try {
    const years = [1, 3, 5].includes(Number(req.body?.years)) ? Number(req.body.years) : 5;

    // Check for an in-flight build (this process, or status file says running)
    if (hkBuildRunning || hkStatusFileRunning()) {
      res.status(409).json({ error: "A build is already running", status: "running" });
      return;
    }

    hkBuildRunning = true;
    const proc = spawn(
      PYTHON_BIN,
      [path.join(PYTHON_DIR, "main.py"), "historical_knowledge_build", String(years)],
      { cwd: PYTHON_DIR, detached: true, stdio: "ignore" },
    );
    proc.on("exit", () => { hkBuildRunning = false; });
    proc.on("error", () => { hkBuildRunning = false; });
    proc.unref();

    // Write an immediate "running" placeholder so the UI sees the build as
    // in-progress on its very next poll (the python process takes a few
    // seconds to boot before it writes its own status). Python overwrites
    // this file with its own progress as soon as it starts.
    try {
      fs.writeFileSync(HK_STATUS_PATH, JSON.stringify({
        status: "running",
        pid: proc.pid,
        started_at: new Date().toISOString(),
        years,
        stocks_total: 50,
        stocks_processed: 0,
        trades_generated: 0,
        new_trades_inserted: 0,
        skipped_symbols: [],
        logs: ["Starting build process…"],
      }));
    } catch { /* non-fatal — python will write status shortly */ }

    res.json({ started: true, years, status: "running" });
  } catch (err: unknown) {
    hkBuildRunning = false;
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/historical-knowledge/summary
router.get("/historical-knowledge/summary", async (_req, res) => {
  try {
    const data = await runPython(["historical_knowledge_summary"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/historical-knowledge/trades
router.get("/historical-knowledge/trades", async (req, res) => {
  try {
    const opts = {
      limit: Number(req.query.limit) || 100,
      offset: Number(req.query.offset) || 0,
      symbol: req.query.symbol ? String(req.query.symbol) : undefined,
      strategy: req.query.strategy ? String(req.query.strategy) : undefined,
    };
    const data = await runPython(["historical_knowledge_trades", JSON.stringify(opts)]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// ── Walk-Forward Validation (v2.4) ───────────────────────────────────────────
// Long-running rolling train/test validation with realistic execution costs.
// Runs as a detached python process; the UI polls the status endpoint.
// Research only — no orders.

let wfRunActive = false;

const WF_DIR = path.join(PYTHON_DIR, "validation_runs");
const WF_STATUS_PATH = path.join(WF_DIR, "wf_status.json");
const WF_RESULT_PATH = path.join(WF_DIR, "wf_result.json");
const WF_CSV_FILES: Record<string, string> = {
  report: "wf_report.csv",
  trades: "wf_trades.csv",
  windows: "wf_windows.csv",
  calibration: "wf_calibration.csv",
  costs: "wf_costs.csv",
  evidence_report: "wf_evidence_report.csv",
  evidence_trades: "wf_evidence_trades.csv",
};

function wfStatusFileRunning(): boolean {
  try {
    const status = JSON.parse(fs.readFileSync(WF_STATUS_PATH, "utf-8"));
    if (status?.status !== "running") return false;
    const pid = Number(status?.pid);
    if (!Number.isInteger(pid) || pid <= 0) return false;
    try {
      process.kill(pid, 0);
      return true;
    } catch {
      return false; // stale status — validator process is gone
    }
  } catch {
    return false;
  }
}

// POST /api/walk-forward/run
router.post("/walk-forward/run", async (req, res) => {
  try {
    if (wfRunActive || wfStatusFileRunning()) {
      res.status(409).json({ error: "A validation run is already in progress", status: "running" });
      return;
    }
    const config = typeof req.body === "object" && req.body !== null ? req.body : {};

    wfRunActive = true;
    const proc = spawn(
      PYTHON_BIN,
      [path.join(PYTHON_DIR, "main.py"), "walk_forward_run", JSON.stringify(config)],
      { cwd: PYTHON_DIR, detached: true, stdio: "ignore" },
    );
    proc.on("exit", () => { wfRunActive = false; });
    proc.on("error", () => { wfRunActive = false; });
    proc.unref();

    // Immediate placeholder so the UI's next poll sees "running" before the
    // python process boots and writes its own status.
    try {
      fs.mkdirSync(WF_DIR, { recursive: true });
      fs.writeFileSync(WF_STATUS_PATH, JSON.stringify({
        status: "running",
        pid: proc.pid,
        started_at: new Date().toISOString(),
        phase: "starting validation process…",
        progress_pct: 0,
        windows_total: 0,
        windows_done: 0,
        logs: ["Starting walk-forward validation…"],
        config,
      }));
    } catch { /* non-fatal — python writes status shortly */ }

    res.json({ started: true, status: "running" });
  } catch (err: unknown) {
    wfRunActive = false;
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/walk-forward/status
router.get("/walk-forward/status", async (_req, res) => {
  try {
    if (!fs.existsSync(WF_STATUS_PATH)) {
      res.json({ status: "idle" });
      return;
    }
    const status = JSON.parse(fs.readFileSync(WF_STATUS_PATH, "utf-8"));
    // Reconcile: file says running but the process is dead → mark failed.
    if (status?.status === "running" && !wfRunActive && !wfStatusFileRunning()) {
      status.status = "failed";
      status.error = status.error ?? "Validation process stopped unexpectedly";
    }
    res.json(status);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/walk-forward/result
router.get("/walk-forward/result", async (_req, res) => {
  try {
    if (!fs.existsSync(WF_RESULT_PATH)) {
      res.json({ available: false });
      return;
    }
    const data = JSON.parse(fs.readFileSync(WF_RESULT_PATH, "utf-8"));
    data.available = true;
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/walk-forward/export/:kind — download one of the 5 CSV exports
router.get("/walk-forward/export/:kind", async (req, res) => {
  try {
    const kind = String(req.params.kind);
    const file = WF_CSV_FILES[kind];
    if (!file) {
      res.status(400).json({ error: `Unknown export '${kind}'. Valid: ${Object.keys(WF_CSV_FILES).join(", ")}` });
      return;
    }
    const full = path.join(WF_DIR, file);
    if (!fs.existsSync(full)) {
      res.status(404).json({ error: "No export available yet — run a validation first." });
      return;
    }
    res.setHeader("Content-Type", "text/csv");
    res.setHeader("Content-Disposition", `attachment; filename="${file}"`);
    fs.createReadStream(full).pipe(res);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// ── Phase 4 Research Factory: Experiment Manager ──────────────────────────
// READ-ONLY for list/leaderboard. WRITE for submit/run/delete.
// No look-ahead bias — every experiment uses strict train/test splits.
// Paper trading and research only.

const EXPERIMENTS_DIR = path.join(PYTHON_DIR, "experiments");
let expRunActive = false;

function expRunning(): boolean {
  // Check in-process flag first (fast path)
  if (expRunActive) return true;
  // Scan experiment dirs for any status.json showing "running"
  try {
    if (!fs.existsSync(EXPERIMENTS_DIR)) return false;
    for (const id of fs.readdirSync(EXPERIMENTS_DIR)) {
      const sp = path.join(EXPERIMENTS_DIR, id, "status.json");
      if (!fs.existsSync(sp)) continue;
      const st = JSON.parse(fs.readFileSync(sp, "utf8"));
      if (st?.status !== "running") continue;
      // Verify the process is still alive (stale check)
      const pid = Number(st?.pid);
      if (Number.isInteger(pid) && pid > 0) {
        try { process.kill(pid, 0); return true; } catch { /* stale */ }
      } else if (st?.status === "running") {
        // No PID stored — trust the file (Python sets it synchronously)
        return true;
      }
    }
  } catch { /* ignore */ }
  return false;
}

// ── Phase 4.1: Batches, duplicate check, export ───────────────────────────

// GET /api/batches — list all batches (experiments grouped by batch_id)
router.get("/batches", async (_req, res) => {
  try {
    const data = await runPython(["experiment_batch_list"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/batches/:batchId — single batch
router.get("/batches/:batchId", async (req, res) => {
  try {
    const data = await runPython(["experiment_batch_get", String(req.params.batchId)]);
    if ((data as any).error) { res.status(404).json(data); return; }
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/experiments/check-duplicate — check if config matches existing experiment
router.post("/experiments/check-duplicate", async (req, res) => {
  try {
    const config = typeof req.body === "object" && req.body !== null ? req.body : {};
    const data = await runPython(["experiment_check_duplicate", JSON.stringify(config)]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/experiments/export/csv — CSV export (all experiments or ?ids=...)
router.get("/experiments/export/csv", async (req, res) => {
  try {
    const ids = req.query.ids ? JSON.stringify(String(req.query.ids).split(",")) : undefined;
    const data = await runPython(ids ? ["experiment_export_csv", ids] : ["experiment_export_csv"]) as any;
    if (data.error) { res.status(500).json(data); return; }
    res.setHeader("Content-Type", "text/csv");
    res.setHeader("Content-Disposition", `attachment; filename="experiments_${Date.now()}.csv"`);
    res.send(data.csv ?? "");
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/experiments/export/json — JSON report (all or ?ids=...)
router.get("/experiments/export/json", async (req, res) => {
  try {
    const ids = req.query.ids ? JSON.stringify(String(req.query.ids).split(",")) : undefined;
    const data = await runPython(ids ? ["experiment_export_json", ids] : ["experiment_export_json"]) as any;
    if (data.error) { res.status(500).json(data); return; }
    res.setHeader("Content-Type", "application/json");
    res.setHeader("Content-Disposition", `attachment; filename="experiment_report_${Date.now()}.json"`);
    res.json(data.report ?? {});
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/experiments — list all experiments (sorted newest first)
router.get("/experiments", async (_req, res) => {
  try {
    const data = await runPython(["experiment_list"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/experiments/leaderboard — ranked completed experiments
// NOTE: must come before /experiments/:id
router.get("/experiments/leaderboard", async (_req, res) => {
  try {
    const data = await runPython(["experiment_leaderboard"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/experiments — submit a new experiment to the queue
router.post("/experiments", async (req, res) => {
  try {
    const config = typeof req.body === "object" && req.body !== null ? req.body : {};
    const data = await runPython(["experiment_submit", JSON.stringify(config)]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/experiments/:id/run — start executing a queued experiment
router.post("/experiments/:id/run", async (req, res) => {
  const expId = String(req.params.id);
  const expDir = path.join(EXPERIMENTS_DIR, expId);
  const expStatusPath = path.join(expDir, "status.json");

  if (!fs.existsSync(expStatusPath)) {
    res.status(404).json({ error: `Experiment ${expId} not found` });
    return;
  }

  // Concurrency guard: block if walk-forward OR another experiment is running
  if (wfRunActive || wfStatusFileRunning() || expRunActive || expRunning()) {
    res.status(409).json({ error: "A validation run is already in progress. Wait for it to finish.", status: "running" });
    return;
  }

  expRunActive = true;
  // Capture runner stdout/stderr to runner.log so crashes (OOM kills, native
  // faults) leave a trace instead of vanishing with stdio: "ignore".
  const runnerLogPath = path.join(expDir, "runner.log");
  let logFd: number | null = null;
  try {
    logFd = fs.openSync(runnerLogPath, "a");
    fs.writeSync(logFd, `\n──── runner attempt ${new Date().toISOString()} ────\n`);
  } catch { logFd = null; }
  const proc = spawn(
    PYTHON_BIN,
    [path.join(PYTHON_DIR, "main.py"), "experiment_run", expId],
    {
      cwd: PYTHON_DIR,
      detached: true,
      stdio: logFd !== null ? ["ignore", logFd, logFd] : "ignore",
    },
  );
  if (logFd !== null) { try { fs.closeSync(logFd); } catch { /* noop */ } }
  const childPid = proc.pid ?? null;
  proc.on("exit", (code, signal) => {
    expRunActive = false;
    // If the runner was killed (signal / non-zero exit) before it could write
    // a final status, record the failure with the exit details.
    if (code === 0) return;
    try {
      const st = JSON.parse(fs.readFileSync(expStatusPath, "utf8"));
      if (st.status !== "running" || (childPid !== null && st.pid !== childPid)) return;
      let tail = "";
      try {
        const log = fs.readFileSync(runnerLogPath, "utf8");
        tail = log.slice(-800).trim();
      } catch { /* noop */ }
      const why = signal
        ? `Runner process killed by signal ${signal} — most likely out-of-memory (OOM). `
        : `Runner process exited with code ${code} without writing a result. `;
      fs.writeFileSync(expStatusPath, JSON.stringify({
        ...st,
        status: "failed",
        error: why + (tail ? `\nLast runner output:\n${tail}` : "No runner output captured."),
        failed_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }, null, 2));
      // Append to the execution log so the UI timeline shows the crash.
      const execLogPath = path.join(expDir, "exec_log.json");
      let execLog: Array<{ ts: string; msg: string }> = [];
      try { execLog = JSON.parse(fs.readFileSync(execLogPath, "utf8")); } catch { /* noop */ }
      execLog.push({ ts: new Date().toISOString().slice(0, 19), msg: `failed — ${why.trim()}` });
      fs.writeFileSync(execLogPath, JSON.stringify(execLog.slice(-100), null, 1));
    } catch { /* noop */ }
  });
  proc.on("error", () => { expRunActive = false; });
  proc.unref();

  // Write placeholder "running" status (with the child PID) so the UI sees
  // it immediately and stale-detection can verify the process is alive.
  try {
    const existing = JSON.parse(fs.readFileSync(expStatusPath, "utf8"));
    fs.writeFileSync(expStatusPath, JSON.stringify({
      ...existing,
      status: "running",
      pid: proc.pid ?? null,
      started_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }, null, 2));
  } catch { /* non-fatal — Python will overwrite */ }

  res.json({ ok: true, id: expId, status: "running" });
});

// Experiment ids are hex slugs — reject anything else before it reaches the
// filesystem layer (defense in depth; Python validates again).
const SAFE_EXP_ID = /^[A-Za-z0-9_-]{1,64}$/;

// ── Phase 5 — AI Research Intelligence (research only, advisory) ────────────
// Nothing here modifies live/paper trading; outputs are research suggestions.

// GET /api/research/intelligence — cross-experiment insights, learning summary,
// strategy health, recommendations, portfolio suggestions, timeline
router.get("/research/intelligence", async (_req, res) => {
  try {
    const data = await runPython(["research_intelligence"]) as any;
    if (!data?.success) { res.status(500).json(data); return; }
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});

// ── Phase 7 — Live Market Intelligence (paper/research only) ────────────────
// All Phase 7 routes serve the SAME canonical scan result (via cache).
// No real broker APIs are called. No real orders are placed.

const P7_CACHE_MS = 10 * 60 * 1000;  // 10 min — same as trade-decisions
let p7Cache: { data: unknown; ts: number } | null = null;
let p7InFlight: Promise<unknown> | null = null;

// ── Abort support ────────────────────────────────────────────────────────────
//
// Two separate scan flows can be in flight:
//   • p7*   — Phase 7 canonical scan (/live-data/scan/run via getP7Scan)
//   • rs*   — Legacy intelligence scan (/run-scan, target of useRunScan)
//
// Both are tracked with the same pattern so a single POST /live-data/scan/abort
// can kill whichever scan is running.
//
// Race-safety rules:
//   1. Only the close/error/timeout handlers clear the proc variable, and only
//      when it still holds the exact same ChildProcess instance (identity check).
//      This prevents an abort from clobbering a *subsequent* scan's tracking.
//   2. The abort handler calls the reject callback to settle the in-flight
//      promise immediately (propagating the cancellation to all awaiters), but
//      it does NOT null p7InFlight / rsInFlight — .finally() handles that
//      naturally once the promise settles.
//   3. After the reject callback fires, p7InFlightReject / rsReject is nulled
//      so that the process close handler (which may arrive a few ms later) does
//      not call reject a second time.

let p7Proc: ChildProcess | null = null;
let p7InFlightReject: ((err: Error) => void) | null = null;

/** Spawn a Phase 7 scan and track it for abort support. */
function spawnP7Scan(args: string[]): Promise<unknown> {
  return new Promise((resolve, reject) => {
    p7InFlightReject = reject;
    const proc = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], {
      cwd: PYTHON_DIR,
    });
    p7Proc = proc;

    let stdout = "";
    let stderr = "";
    const timeout = cmdTimeout(args);
    const timer = setTimeout(() => {
      try { proc.kill("SIGTERM"); } catch { /* ignore */ }
      if (p7Proc === proc) p7Proc = null;
      p7InFlightReject = null;
      reject(new Error(`Python process timed out after ${timeout / 1000}s (${args[0] ?? "unknown"})`));
    }, timeout);

    proc.stdout.on("data", (d: Buffer) => { stdout += d.toString(); });
    proc.stderr.on("data", (d: Buffer) => { stderr += d.toString(); });

    proc.on("close", (code) => {
      clearTimeout(timer);
      if (p7Proc === proc) p7Proc = null;
      p7InFlightReject = null;
      if (code !== 0) {
        try {
          const parsed = JSON.parse(stdout.trim());
          if (parsed.error) return reject(new Error(parsed.error));
        } catch { /* ignore */ }
        reject(new Error(stderr || `Python exited with code ${code}`));
      } else {
        // Find the last line that is valid JSON (subsystems may print
        // structured log lines to stdout before the result JSON).
        const lines = stdout.trim().split("\n");
        let _parsed: unknown;
        for (let i = lines.length - 1; i >= 0; i--) {
          const line = lines[i].trim();
          if (!line) continue;
          try { _parsed = JSON.parse(line); break; } catch { /* skip */ }
        }
        if (_parsed !== undefined) {
          resolve(_parsed);
        } else {
          reject(new Error(`Failed to parse Python output: ${stdout}`));
        }
      }
    });

    proc.on("error", (err) => {
      clearTimeout(timer);
      if (p7Proc === proc) p7Proc = null;
      p7InFlightReject = null;
      reject(err);
    });
  });
}

// ── Legacy intelligence scan tracking (used by POST /api/run-scan) ───────────
let rsScanProc: ChildProcess | null = null;
let rsScanReject: ((err: Error) => void) | null = null;
let rsScanInFlight: Promise<unknown> | null = null;

/** Spawn the legacy intelligence scan and track it for abort support. */
function spawnRunScan(args: string[]): Promise<unknown> {
  return new Promise((resolve, reject) => {
    rsScanReject = reject;
    const proc = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], {
      cwd: PYTHON_DIR,
    });
    rsScanProc = proc;

    let stdout = "";
    let stderr = "";
    const timeout = cmdTimeout(args);
    const timer = setTimeout(() => {
      try { proc.kill("SIGTERM"); } catch { /* ignore */ }
      if (rsScanProc === proc) rsScanProc = null;
      rsScanReject = null;
      reject(new Error(`Python process timed out after ${timeout / 1000}s (${args[0] ?? "unknown"})`));
    }, timeout);

    proc.stdout.on("data", (d: Buffer) => { stdout += d.toString(); });
    proc.stderr.on("data", (d: Buffer) => { stderr += d.toString(); });

    proc.on("close", (code) => {
      clearTimeout(timer);
      if (rsScanProc === proc) rsScanProc = null;
      rsScanReject = null;
      if (code !== 0) {
        try {
          const parsed = JSON.parse(stdout.trim());
          if (parsed.error) return reject(new Error(parsed.error));
        } catch { /* ignore */ }
        reject(new Error(stderr || `Python exited with code ${code}`));
      } else {
        // Find the last line that is valid JSON (subsystems may print
        // structured log lines to stdout before the result JSON).
        const lines = stdout.trim().split("\n");
        let _parsed: unknown;
        for (let i = lines.length - 1; i >= 0; i--) {
          const line = lines[i].trim();
          if (!line) continue;
          try { _parsed = JSON.parse(line); break; } catch { /* skip */ }
        }
        if (_parsed !== undefined) {
          resolve(_parsed);
        } else {
          reject(new Error(`Failed to parse Python output: ${stdout}`));
        }
      }
    });

    proc.on("error", (err) => {
      clearTimeout(timer);
      if (rsScanProc === proc) rsScanProc = null;
      rsScanReject = null;
      reject(err);
    });
  });
}

async function getP7Scan(force = false): Promise<unknown> {
  if (!force && p7Cache && Date.now() - p7Cache.ts < P7_CACHE_MS) return p7Cache.data;
  if (!p7InFlight) {
    p7InFlight = spawnP7Scan(["phase7_scan", ...(force ? ["force"] : [])])
      .then((data) => { p7Cache = { data, ts: Date.now() }; return data; })
      .finally(() => { p7InFlight = null; });
  }
  return p7InFlight;
}

// GET /api/live-data/health — provider health + scan audit (uses cached scan)
router.get("/live-data/health", async (req, res) => {
  try {
    const force = req.query.force === "true";
    res.json(await runPython(["phase7_health", ...(force ? ["force"] : [])]));
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/live-data/scan — full canonical scan (all pages must consume this)
// Annotates each recommendation with rr_gap: true when the symbol has an R:R
// dual-threshold conflict (Risk Agent approved at ≥1.5, execution gate blocks
// at ≥2.0).
//
// IMPORTANT — scan_id binding: the rr_gap lookup must use the concrete scan_id
// returned by the scan fetch, never resolve its own from scan_state.  Parallel
// execution would allow the two calls to land on different scans during a
// forced refresh or scan-state transition, producing stale cross-scan
// annotations.  We therefore await the scan first, extract scan_id, then
// look up rr_gap symbols bound to that exact scan.
router.get("/live-data/scan", async (req, res) => {
  try {
    const force = req.query.force === "true";
    const scanData = await getP7Scan(force);
    const scan = scanData as Record<string, unknown>;
    // Extract the concrete scan_id from the resolved scan result so the rr_gap
    // query is always scoped to the same scan we are returning.
    const resolvedScanId = String((scan?.scan_id as string | undefined) ?? "");
    const rrGapData = await runPython(
      resolvedScanId ? ["get_rr_gap_symbols", resolvedScanId] : ["get_rr_gap_symbols"],
    ).catch(() => ({ symbols: [] }));
    const rrGapSet = new Set<string>(((rrGapData as Record<string, unknown>)?.symbols as string[]) ?? []);
    const recs = Array.isArray(scan?.recommendations) ? scan.recommendations as Record<string, unknown>[] : [];
    res.json({
      ...scan,
      recommendations: recs.map((r) => ({
        ...r,
        rr_gap: rrGapSet.has(String(r.symbol ?? "")),
      })),
    });
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/live-data/coverage — canonical market-hours coverage verdict for
// the dashboard banner. All market-state / session-freshness / expected-universe
// logic lives server-side in scanner_coverage.py — the browser only renders
// ok/warning. Cached briefly; never triggers a scan.
const COVERAGE_CACHE_MS = 30_000;
let coverageCache: { data: unknown; ts: number } | null = null;
let coverageInFlight: Promise<unknown> | null = null;

router.get("/live-data/coverage", async (_req, res) => {
  try {
    if (coverageCache && Date.now() - coverageCache.ts < COVERAGE_CACHE_MS) {
      res.json(coverageCache.data);
      return;
    }
    if (!coverageInFlight) {
      coverageInFlight = runPython(["scanner_coverage"])
        .then((data) => {
          coverageCache = { data, ts: Date.now() };
          return data;
        })
        .finally(() => {
          coverageInFlight = null;
        });
    }
    res.json(await coverageInFlight);
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/live-data/scan/status — lightweight canonical scan metadata for the
// DataFreshnessBar (scan_id, snapshot_ts, provider, coverage). Reads the
// durable scan-state store only — never triggers a scan. Cached briefly to
// avoid a python spawn per page load.
const SCAN_STATUS_CACHE_MS = 15_000;
let scanStatusCache:   { data: unknown; ts: number } | null = null;
let scanStatusInFlight: Promise<unknown> | null = null;
// Generation counter — incremented every time the cache is deliberately
// invalidated (scan start or scan completion).  Each in-flight request
// captures the generation at creation; it only writes the cache / clears
// the in-flight reference when the generation still matches.  This prevents
// a pre-invalidation request that resolves late from overwriting the cache
// with stale data for the 15-second TTL window.
let scanStatusGen = 0;

/**
 * Clears the scan-status in-process cache so the next GET /live-data/scan/status
 * fetches fresh data from Python.  Exported for integration tests only — mirrors
 * the clearPlatformCache() / clearAgentsCache() helpers used by other test suites.
 */
export function clearScanStatusCache(): void {
  scanStatusGen++;
  scanStatusCache    = null;
  scanStatusInFlight = null;
}

/**
 * Resets the scan-run rate-limit timestamp so POST /live-data/scan/run is not
 * throttled in tests.  Exported for integration tests only.
 */
export function resetScanRunRateLimit(): void {
  lastScanRunTs = 0;
}

/**
 * Full scan-state reset for integration tests.  Clears the scan-status cache,
 * the rate-limit timestamp, the phase7 in-flight reference (so the next
 * POST /live-data/scan/run can start a new scan even when a previous test left
 * a long-running mock proc alive), and the phase7 cache.
 *
 * The in-flight promise from a previous test is orphaned (its mock proc never
 * emits close), but with a mocked child_process that is harmless — the Promise
 * simply never settles and is eligible for GC once the module loses its last
 * reference to it.
 *
 * Exported for integration tests only.
 */
export function resetScanStateForTest(): void {
  scanStatusGen++;
  scanStatusCache    = null;
  scanStatusInFlight = null;
  scanHistoryCache   = null;
  lastScanRunTs      = 0;
  p7InFlight         = null;  // allow a fresh scan; orphaned Promise GC'd in time
  p7Cache            = null;
}

router.get("/live-data/scan/status", async (_req, res) => {
  // This endpoint drives live rotation/count displays. Keep its short
  // in-process cache for Python-spawn coalescing, but never let a browser or
  // intermediary retain an older response after a newer scan completes.
  res.set("Cache-Control", "no-store, max-age=0");
  try {
    if (scanStatusCache && Date.now() - scanStatusCache.ts < SCAN_STATUS_CACHE_MS) {
      res.json(scanStatusCache.data);
      return;
    }
    if (!scanStatusInFlight) {
      const gen = scanStatusGen;  // capture before async work begins
      scanStatusInFlight = runPython(["scan_status"])
        .then((data) => {
          // Guard: only write cache if no invalidation happened since we started.
          if (gen === scanStatusGen) {
            scanStatusCache = { data, ts: Date.now() };
          }
          return data;
        })
        .finally(() => {
          // Guard: only clear our own in-flight reference, never a newer one.
          if (gen === scanStatusGen) {
            scanStatusInFlight = null;
          }
        });
    }
    res.json(await scanStatusInFlight);
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/live-data/scan/history — today's (IST) completed scans with
// duration and gap-from-previous so operators can spot coverage gaps.
//
// Caching strategy: always fetch the maximum (50 entries) from Python and
// store the full result in one shared cache entry.  Per-request slicing is
// applied after the cache hit so different `limit` values all share the same
// in-flight promise and cached payload, preventing N independent Python
// spawns for N concurrent callers with different limits.
//
// Cache is invalidated at scan initiation AND again on successful completion
// (see below) so the first post-scan poll always returns fresh data.
const SCAN_HISTORY_CACHE_MS      = 30_000;
const SCAN_HISTORY_CANONICAL_MAX = 50;          // always fetched; sliced per request

type ScanHistoryPayload = { success: boolean; history: unknown[]; count: number; ist_date: string };
let scanHistoryCache:    { data: ScanHistoryPayload; ts: number } | null = null;
let scanHistoryInFlight: Promise<ScanHistoryPayload> | null = null;

router.get("/live-data/scan/history", async (req, res) => {
  try {
    const limitRaw = parseInt(String(req.query.limit ?? ""), 10);
    const limit = Number.isFinite(limitRaw) ? Math.min(Math.max(limitRaw, 1), SCAN_HISTORY_CANONICAL_MAX) : 10;

    // Serve from cache when fresh; otherwise start / join one canonical fetch.
    if (!scanHistoryCache || Date.now() - scanHistoryCache.ts >= SCAN_HISTORY_CACHE_MS) {
      if (!scanHistoryInFlight) {
        scanHistoryInFlight = runPython(["scan_history", String(SCAN_HISTORY_CANONICAL_MAX)])
          .then((data) => {
            const d = data as ScanHistoryPayload;
            scanHistoryCache = { data: d, ts: Date.now() };
            return d;
          })
          .finally(() => { scanHistoryInFlight = null; });
      }
      await scanHistoryInFlight;
    }

    // Slice the canonical cache to the requested limit for this caller.
    const full    = scanHistoryCache!.data;
    const sliced  = (full.history ?? []).slice(0, limit);
    res.json({ ...full, history: sliced, count: sliced.length });
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/live-data/scan/run — trigger fresh scan explicitly
// Phase 11: idempotent under concurrency (single in-flight scan lock via
// p7InFlight), rate-limited, and publishes scan.* events with notifications.
let lastScanRunTs = 0;
const SCAN_RUN_MIN_GAP_MS = 30_000;

// POST /api/live-data/scan/run — async fire-and-forget
//
// A full 50-symbol scan takes 90–120 s. Keeping the HTTP connection open for
// that long causes client-side timeouts (120 s) to fire before the server
// responds. Fix: acknowledge immediately, run the scan in the background, and
// let the caller detect completion by polling GET /live-data/scan/status
// (snapshot_ts advances when the scan completes).
//
// Response:
//   { started: true,  status: "RUNNING"         }  — scan kicked off
//   { started: true,  status: "ALREADY_RUNNING" }  — scan already in flight
//   { started: false, status: "RATE_LIMITED",
//     retry_in_s: N }                              — 429 (30 s gap)
router.post("/live-data/scan/run", (_req, res) => {
  try {
    const now = Date.now();

    // Rate-limit: prevent flooding (30-second gap between manual triggers)
    if (now - lastScanRunTs < SCAN_RUN_MIN_GAP_MS) {
      const retryInS = Math.ceil((SCAN_RUN_MIN_GAP_MS - (now - lastScanRunTs)) / 1000);
      res.status(429).json({
        started:    false,
        status:     "RATE_LIMITED",
        retry_in_s: retryInS,
        error: `Scan rate limit — wait ${retryInS}s before running another fresh scan.`,
      });
      return;
    }

    // Idempotent: if a scan is already in flight, acknowledge without re-spawning
    if (p7InFlight) {
      res.json({ started: true, status: "ALREADY_RUNNING" });
      return;
    }

    // ── Kick off scan in background ──────────────────────────────────────────
    lastScanRunTs = now;
    p7Cache         = null;   // Phase 7 cache — must refresh
    marketScanCache = null;   // Phase 19B: Market Scanner view
    // Advance the generation so any in-flight scan/status request that was
    // started before this point cannot write stale data to the cache.
    scanStatusGen++;
    scanStatusCache   = null; // Phase 19C: freshness bar
    scanStatusInFlight = null; // abandon stale in-flight; next poll starts fresh
    scanHistoryCache  = null; // Phase 713: scan history list

    eventBus.publish("scan.started", { ts: new Date().toISOString() });
    void runPython(["system_event", "SCAN_STARTED",
      JSON.stringify({ reason: "Fresh live scan started." })]).catch(() => undefined);

    void getP7Scan(true)
      .then((result) => {
        const r = result as Record<string, unknown>;
        eventBus.publish("scan.completed", {
          scan_id:      r?.["scan_id"],
          snapshot_ts:  r?.["snapshot_ts"],
          summary:      r?.["summary"],
        });
        void runPython(["system_event", "SCAN_COMPLETED", JSON.stringify({
          reason: `Live scan completed (scan ${String(r?.["scan_id"] ?? "unknown")}).`,
        })]).catch(() => undefined);
        // Advance the generation and clear both caches on scan completion so
        // the first post-completion poll sees fresh rotation count and history.
        // Advancing the generation ensures any in-flight status request that
        // started before this point cannot write its stale result to the cache
        // even if it resolves a moment after we clear it.
        scanStatusGen++;
        scanStatusCache    = null;
        scanStatusInFlight = null; // abandon stale in-flight; next poll fetches fresh
        scanHistoryCache   = null;
        // Push advisory notifications — never blocks the scan response chain.
        void dispatchSignalPushNotifications().catch(() => undefined);
      })
      .catch((scanErr: unknown) => {
        const msg = scanErr instanceof Error ? scanErr.message : String(scanErr);
        eventBus.publish("scan.failed", { error: msg });
        void runPython(["system_event", "SCAN_FAILED",
          JSON.stringify({ reason: `Live scan failed: ${msg.slice(0, 200)}` })]).catch(() => undefined);
      });

    // Respond immediately — client polls GET /live-data/scan/status for completion
    res.json({ started: true, status: "RUNNING" });
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/live-data/scan/abort — cancel any in-flight scan
// Handles both the Phase 7 canonical scan and the legacy /run-scan flow.
// Safe to call at any time; returns { aborted: false } when idle.
//
// Safety: we do NOT null p7InFlight / rsScanInFlight here — their .finally()
// handlers clear them once the promise actually settles (after SIGTERM).
// We also do NOT null p7Proc / rsScanProc — the close-event handler does
// that via an identity check so a subsequent scan's tracking is never clobbered.
router.post("/live-data/scan/abort", (_req, res) => {
  const wasRunning = !!(p7Proc || p7InFlight || rsScanProc || rsScanInFlight);

  // Kill Phase 7 scan process (if running)
  if (p7Proc) {
    try { p7Proc.kill("SIGTERM"); } catch { /* already dead */ }
  }
  // Reject the Phase 7 in-flight promise so all awaiters see the cancellation
  // immediately (before the OS delivers the close event).
  if (p7InFlightReject) {
    p7InFlightReject(new Error("Scan aborted by operator"));
    p7InFlightReject = null;  // prevent double-rejection from close handler
  }

  // Kill legacy run-scan process (if running)
  if (rsScanProc) {
    try { rsScanProc.kill("SIGTERM"); } catch { /* already dead */ }
  }
  if (rsScanReject) {
    rsScanReject(new Error("Scan aborted by operator"));
    rsScanReject = null;
  }

  res.json({
    aborted: wasRunning,
    message: wasRunning ? "Scan process terminated" : "No scan was in flight",
  });
});

// ── Phase 11 — Live health v2 + diagnostic bundle ────────────────────────────

// GET /api/live-data/health-v2 — market state + quote provider + scan health
router.get("/live-data/health-v2", async (_req, res) => {
  try { res.json(await runPython(["live_health_v2"])); }
  catch (err: unknown) { res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) }); }
});

// POST /api/live-data/diagnostic-bundle — generate bundle, return JSON
router.post("/live-data/diagnostic-bundle", async (_req, res) => {
  try { res.json(await runPython(["diagnostic_bundle"])); }
  catch (err: unknown) { res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) }); }
});

// GET /api/live-data/diagnostic-bundle/download?file=json|csv
router.get("/live-data/diagnostic-bundle/download", async (req, res) => {
  try {
    const kind = String(req.query.file ?? "json");
    if (!["json", "csv"].includes(kind)) {
      res.status(400).json({ success: false, error: "file must be json or csv" });
      return;
    }
    const fname = kind === "json" ? "phase11_diagnostic_bundle.json" : "phase11_summary.csv";
    const filePath = path.join(PYTHON_DIR, fname);
    // Always regenerate so downloads are honest point-in-time snapshots,
    // never stale files left over from a previous run.
    await runPython(["diagnostic_bundle"]);
    if (!fs.existsSync(filePath)) {
      res.status(500).json({ success: false, error: "Diagnostic bundle file missing" });
      return;
    }
    res.setHeader("Content-Type", kind === "json" ? "application/json; charset=utf-8" : "text/csv; charset=utf-8");
    res.setHeader("Content-Disposition", `attachment; filename="${fname}"`);
    fs.createReadStream(filePath).pipe(res);
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/live-data/recommendations — ranked recommendations from canonical scan
router.get("/live-data/recommendations", async (req, res) => {
  try {
    const scan = await getP7Scan(req.query.force === "true") as any;
    res.json({
      success: true,
      scan_id: scan?.scan_id, snapshot_ts: scan?.snapshot_ts,
      recommendations: scan?.recommendations ?? [],
      summary: scan?.summary ?? {},
      label: "PAPER / LIVE DATA VALIDATION",
    });
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/live-data/report?file=json|csv|html — Phase 7 validation report download
router.get("/live-data/report", async (req, res) => {
  try {
    const kind = String(req.query.file ?? "html");
    if (!["json", "csv", "html"].includes(kind)) {
      res.status(400).json({ success: false, error: "file must be json, csv or html" }); return;
    }
    const meta = await runPython(["phase7_report"]) as any;
    if (!meta?.success) { res.status(500).json(meta ?? { success: false, error: "Report failed" }); return; }
    const filePath = String(meta[kind] ?? "");
    const expectedDir = path.join(PYTHON_DIR, "exports");
    const resolved = path.resolve(filePath);
    if (!resolved.startsWith(expectedDir + path.sep) || !fs.existsSync(resolved)) {
      res.status(500).json({ success: false, error: "Report file missing" }); return;
    }
    const ctype = kind === "json" ? "application/json; charset=utf-8"
      : kind === "csv" ? "text/csv; charset=utf-8" : "text/html; charset=utf-8";
    res.setHeader("Content-Type", ctype);
    res.setHeader("Content-Disposition", `attachment; filename="phase7_report.${kind}"`);
    fs.createReadStream(resolved).pipe(res);
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});

// ── Phase 6.5 — Meta-Learning (research only) ───────────────────────────────
const META_GETS: Record<string, string> = {
  health: "meta_health",
  failures: "meta_failures",
  eligibility: "meta_eligibility",
  improvements: "meta_improvements",
  contradictions: "meta_contradictions",
};
for (const [route, cmd] of Object.entries(META_GETS)) {
  router.get(`/meta-learning/${route}`, async (_req, res) => {
    try { res.json(await runPython([cmd])); }
    catch (err: unknown) { res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) }); }
  });
}

// GET /api/meta-learning/compare?a=<expId>&b=<expId>
router.get("/meta-learning/compare", async (req, res) => {
  try {
    const a = String(req.query.a ?? ""), b = String(req.query.b ?? "");
    if (!/^[A-Za-z0-9_-]{1,64}$/.test(a) || !/^[A-Za-z0-9_-]{1,64}$/.test(b)) {
      res.status(400).json({ success: false, error: "Query params a and b must be experiment ids" }); return;
    }
    res.json(await runPython(["meta_compare", a, b]));
  } catch (err: unknown) { res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) }); }
});

// POST /api/meta-learning/create-mutation { strategyName, parameter, value, evidence? }
// Creates a DRAFT research mutation in the evolution registry. Never activates anything.
router.post("/meta-learning/create-mutation", async (req, res) => {
  try {
    const { strategyName, parameter, value, evidence } = req.body ?? {};
    if (typeof strategyName !== "string" || !strategyName.trim() || strategyName.length > 80 ||
        typeof parameter !== "string" || !/^[A-Za-z0-9_.-]{1,64}$/.test(parameter) ||
        typeof value !== "string" || !value.trim() || value.length > 120) {
      res.status(400).json({ success: false, error: "strategyName, parameter and value are required" }); return;
    }
    res.json(await runPython(["meta_create_mutation", strategyName.trim(), parameter,
      value.trim(), String(evidence ?? "").slice(0, 400)]));
  } catch (err: unknown) { res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) }); }
});

// GET /api/meta-learning/export?file=csv|json|html — Complete Meta-Learning Report
router.get("/meta-learning/export", async (req, res) => {
  try {
    const kind = String(req.query.file ?? "csv");
    if (!["csv", "json", "html"].includes(kind)) { res.status(400).json({ success: false, error: "file must be csv, json or html" }); return; }
    const meta = await runPython(["meta_export"]) as any;
    if (!meta?.success) { res.status(500).json(meta ?? { success: false, error: "Export failed" }); return; }
    const filePath = kind === "csv" ? meta.csv_file : kind === "json" ? meta.json_file : meta.html_file;
    const expectedDir = path.join(PYTHON_DIR, "exports");
    const resolved = path.resolve(String(filePath ?? ""));
    if (!resolved.startsWith(expectedDir + path.sep) || !fs.existsSync(resolved)) {
      res.status(500).json({ success: false, error: "Export file missing after generation" });
      return;
    }
    const ctype = kind === "csv" ? "text/csv; charset=utf-8"
      : kind === "json" ? "application/json; charset=utf-8" : "text/html; charset=utf-8";
    res.setHeader("Content-Type", ctype);
    res.setHeader("Content-Disposition", `attachment; filename="${path.basename(resolved)}"`);
    fs.createReadStream(resolved).pipe(res);
  } catch (err: unknown) { res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) }); }
});

// ── Phase 6 — Strategy Evolution Laboratory (research only) ─────────────────
const EVO_ID = /^[A-Za-z0-9_-]{1,64}$/;

router.get("/evolution/registry", async (_req, res) => {
  try { res.json(await runPython(["evolution_registry"])); }
  catch (err: unknown) { res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) }); }
});

router.get("/evolution/tree", async (_req, res) => {
  try { res.json(await runPython(["evolution_tree"])); }
  catch (err: unknown) { res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) }); }
});

router.get("/evolution/leaderboard", async (_req, res) => {
  try { res.json(await runPython(["evolution_leaderboard"])); }
  catch (err: unknown) { res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) }); }
});

router.get("/evolution/knowledge", async (_req, res) => {
  try { res.json(await runPython(["evolution_knowledge"])); }
  catch (err: unknown) { res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) }); }
});

router.get("/evolution/ab-tests", async (_req, res) => {
  try { res.json(await runPython(["evolution_ab_list"])); }
  catch (err: unknown) { res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) }); }
});

router.get("/evolution/robustness/:expId", async (req, res) => {
  try {
    if (!EVO_ID.test(req.params.expId)) { res.status(400).json({ success: false, error: "Invalid experiment id" }); return; }
    res.json(await runPython(["evolution_robustness", req.params.expId]));
  } catch (err: unknown) { res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) }); }
});

// POST /api/evolution/mutate { strategyId, parameters? } — creates Draft research
// variants in the registry only. Never activates anything.
router.post("/evolution/mutate", async (req, res) => {
  try {
    const { strategyId, parameters } = req.body ?? {};
    if (typeof strategyId !== "string" || !EVO_ID.test(strategyId)) {
      res.status(400).json({ success: false, error: "Invalid strategyId" }); return;
    }
    const args = ["evolution_mutate", strategyId];
    if (Array.isArray(parameters) && parameters.length > 0) {
      args.push(JSON.stringify(parameters.filter((p: unknown) => typeof p === "string").slice(0, 20)));
    }
    res.json(await runPython(args));
  } catch (err: unknown) { res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) }); }
});

// POST /api/evolution/status { strategyId, status, note? } — explicit human action
router.post("/evolution/status", async (req, res) => {
  try {
    const { strategyId, status, note } = req.body ?? {};
    if (typeof strategyId !== "string" || !EVO_ID.test(strategyId) || typeof status !== "string") {
      res.status(400).json({ success: false, error: "strategyId and status are required" }); return;
    }
    res.json(await runPython(["evolution_set_status", strategyId, status, String(note ?? "").slice(0, 300)]));
  } catch (err: unknown) { res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) }); }
});

// POST /api/evolution/ab-test { parentId, candidateId, expParent, expCandidate }
router.post("/evolution/ab-test", async (req, res) => {
  try {
    const { parentId, candidateId, expParent, expCandidate } = req.body ?? {};
    for (const v of [parentId, candidateId, expParent, expCandidate]) {
      if (typeof v !== "string" || !EVO_ID.test(v)) {
        res.status(400).json({ success: false, error: "parentId, candidateId, expParent, expCandidate are required ids" });
        return;
      }
    }
    res.json(await runPython(["evolution_ab_test", parentId, candidateId, expParent, expCandidate]));
  } catch (err: unknown) { res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) }); }
});

// POST /api/evolution/evaluate { candidateId, expCandidate, expParent } — survival rules
router.post("/evolution/evaluate", async (req, res) => {
  try {
    const { candidateId, expCandidate, expParent } = req.body ?? {};
    for (const v of [candidateId, expCandidate, expParent]) {
      if (typeof v !== "string" || !EVO_ID.test(v)) {
        res.status(400).json({ success: false, error: "candidateId, expCandidate, expParent are required ids" });
        return;
      }
    }
    res.json(await runPython(["evolution_evaluate", candidateId, expCandidate, expParent]));
  } catch (err: unknown) { res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) }); }
});

// GET /api/evolution/export?file=csv|json|html — downloadable research package
router.get("/evolution/export", async (req, res) => {
  try {
    const kind = String(req.query.file ?? "csv");
    if (!["csv", "json", "html"].includes(kind)) { res.status(400).json({ success: false, error: "file must be csv, json or html" }); return; }
    const meta = await runPython(["evolution_export"]) as any;
    if (!meta?.success) { res.status(500).json(meta ?? { success: false, error: "Export failed" }); return; }
    const filePath = kind === "csv" ? meta.csv_file : kind === "json" ? meta.json_file : meta.html_file;
    const expectedDir = path.join(PYTHON_DIR, "exports");
    const resolved = path.resolve(String(filePath ?? ""));
    if (!resolved.startsWith(expectedDir + path.sep) || !fs.existsSync(resolved)) {
      res.status(500).json({ success: false, error: "Export file missing after generation" });
      return;
    }
    const ctype = kind === "csv" ? "text/csv; charset=utf-8"
      : kind === "json" ? "application/json; charset=utf-8" : "text/html; charset=utf-8";
    res.setHeader("Content-Type", ctype);
    res.setHeader("Content-Disposition", `attachment; filename="${path.basename(resolved)}"`);
    res.setHeader("X-Row-Count", String(meta.csv_rows ?? ""));
    res.setHeader("Access-Control-Expose-Headers", "X-Row-Count");
    fs.createReadStream(resolved).pipe(res);
  } catch (err: unknown) { res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) }); }
});

// GET /api/research/phase5-review-export?file=main|summary — Phase 5 review CSVs
// Read-only reporting: generates both CSVs (main) or serves the last generated
// summary. Never modifies trading behaviour.
router.get("/research/phase5-review-export", async (req, res) => {
  try {
    const which = String(req.query.file ?? "main") === "summary" ? "summary" : "main";
    const meta = await runPython(["phase5_export", which === "main" ? "generate" : "reuse"]) as any;
    if (!meta?.success) { res.status(500).json(meta ?? { success: false, error: "Export generation failed" }); return; }
    const filePath = which === "main" ? meta.main_file : meta.summary_file;
    const expectedDir = path.join(PYTHON_DIR, "exports");
    const resolved = path.resolve(String(filePath ?? ""));
    if (!resolved.startsWith(expectedDir + path.sep) || !fs.existsSync(resolved)) {
      res.status(500).json({ success: false, error: "Export file missing after generation" });
      return;
    }
    const filename = which === "main" ? "phase5_review_export.csv" : "phase5_review_summary.csv";
    res.setHeader("Content-Type", "text/csv; charset=utf-8");
    res.setHeader("Content-Disposition", `attachment; filename="${filename}"`);
    res.setHeader("X-Row-Count", String(which === "main" ? meta.main_rows : meta.summary_rows));
    res.setHeader("Access-Control-Expose-Headers", "X-Row-Count");
    fs.createReadStream(resolved).pipe(res);
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/experiments/compare?ids=a,b,c — side-by-side latest-report comparison
// (registered before /experiments/:id so "compare" is not treated as an id)
router.get("/experiments/compare", async (req, res) => {
  try {
    const raw = String(req.query.ids ?? "");
    const ids = raw.split(",").map(s => s.trim()).filter(s => SAFE_EXP_ID.test(s));
    if (ids.length === 0) {
      res.status(400).json({ success: false, error: "Provide ?ids=<id1>,<id2> (valid experiment ids)" });
      return;
    }
    const data = await runPython(["experiment_compare", ids.slice(0, 12).join(",")]) as any;
    if (!data?.success) { res.status(500).json(data); return; }
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/experiments/:id/trade-diagnostics — per-trade diagnosis (read-only)
router.get("/experiments/:id/trade-diagnostics", async (req, res) => {
  try {
    if (!SAFE_EXP_ID.test(String(req.params.id))) {
      res.status(400).json({ success: false, error: { code: "INVALID_ID", message: "Invalid experiment id.", details: "" } });
      return;
    }
    const data = await runPython(["trade_diagnostics", String(req.params.id)]) as any;
    if (!data?.success) {
      res.status((data?.error?.code === "NOT_FOUND") ? 404 : 500).json(data);
      return;
    }
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/experiments/:id/analysis — Phase 4.2 strategy improvement analysis
// (analysis only — reads analysis.json produced after a run)
router.get("/experiments/:id/analysis", async (req, res) => {
  try {
    if (!SAFE_EXP_ID.test(String(req.params.id))) {
      res.status(400).json({ error: "Invalid experiment id" });
      return;
    }
    const data = await runPython(["experiment_analysis_get", String(req.params.id)]);
    if ((data as any).error) { res.status(404).json(data); return; }
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/experiments/:id/analyze — (re)run the analyzer on a finished
// experiment's outputs. READ-ONLY with respect to the experiment result.
router.post("/experiments/:id/analyze", async (req, res) => {
  try {
    if (!SAFE_EXP_ID.test(String(req.params.id))) {
      res.status(400).json({ error: "Invalid experiment id" });
      return;
    }
    const data = await runPython(["experiment_analyze", String(req.params.id)]);
    if ((data as any).error) { res.status(400).json(data); return; }
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// ── Phase 4.3 — Research Report Engine (research only) ─────────────────────
// Reports never modify experiment results or live/paper trading behavior.

const reportErr = (res: any, data: any, notFound = false) => {
  const code = (data?.error?.code ?? "") as string;
  const status = notFound || code === "REPORT_NOT_FOUND" || code === "NOT_FOUND" ? 404
    : code === "INVALID_ID" ? 400
    : code === "EXPERIMENT_NOT_FINISHED" ? 409
    : 500;
  res.status(status).json(data);
};

// GET /api/experiments/:id/report — latest completed research report (or ?version=N)
router.get("/experiments/:id/report", async (req, res) => {
  try {
    if (!SAFE_EXP_ID.test(String(req.params.id))) {
      res.status(400).json({ success: false, error: { code: "INVALID_ID", message: "Invalid experiment id.", details: "" } });
      return;
    }
    const args = ["report_get", String(req.params.id)];
    if (req.query.version && /^\d+$/.test(String(req.query.version))) args.push(String(req.query.version));
    const data = await runPython(args) as any;
    if (!data?.success) { reportErr(res, data); return; }
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: { code: "REPORT_GENERATION_FAILED", message: "Failed to load research report.", details: err instanceof Error ? err.message : String(err) } });
  }
});

// GET /api/experiments/:id/report/status — lifecycle status (NONE/GENERATING/COMPLETED/FAILED/OUTDATED)
router.get("/experiments/:id/report/status", async (req, res) => {
  try {
    if (!SAFE_EXP_ID.test(String(req.params.id))) {
      res.status(400).json({ success: false, error: { code: "INVALID_ID", message: "Invalid experiment id.", details: "" } });
      return;
    }
    const data = await runPython(["report_status", String(req.params.id)]) as any;
    if (!data?.success) { reportErr(res, data); return; }
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: { code: "REPORT_STATUS_FAILED", message: "Failed to read report status.", details: err instanceof Error ? err.message : String(err) } });
  }
});

// POST /api/experiments/:id/report/generate — generate (skips if source unchanged)
// POST /api/experiments/:id/report/regenerate — force a new version
for (const [route, force] of [["generate", false], ["regenerate", true]] as const) {
  router.post(`/experiments/:id/report/${route}`, async (req, res) => {
    try {
      if (!SAFE_EXP_ID.test(String(req.params.id))) {
        res.status(400).json({ success: false, error: { code: "INVALID_ID", message: "Invalid experiment id.", details: "" } });
        return;
      }
      const args = ["report_generate", String(req.params.id)];
      if (force) args.push("force");
      const data = await runPython(args) as any;
      if (!data?.success) { reportErr(res, data); return; }
      res.json(data);
    } catch (err: unknown) {
      res.status(500).json({ success: false, error: { code: "REPORT_GENERATION_FAILED", message: "Research report generation failed.", details: err instanceof Error ? err.message : String(err) } });
    }
  });
}

// GET /api/experiments/:id/report/export/json — download report JSON
router.get("/experiments/:id/report/export/json", async (req, res) => {
  try {
    if (!SAFE_EXP_ID.test(String(req.params.id))) {
      res.status(400).json({ success: false, error: { code: "INVALID_ID", message: "Invalid experiment id.", details: "" } });
      return;
    }
    const data = await runPython(["report_get", String(req.params.id)]) as any;
    if (!data?.success) { reportErr(res, data); return; }
    res.setHeader("Content-Type", "application/json");
    res.setHeader("Content-Disposition", `attachment; filename="research_report_${req.params.id}.json"`);
    res.json(data.report);
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: { code: "EXPORT_FAILED", message: "JSON export failed.", details: err instanceof Error ? err.message : String(err) } });
  }
});

// GET /api/experiments/:id/report/export/html — printable HTML report
router.get("/experiments/:id/report/export/html", async (req, res) => {
  try {
    if (!SAFE_EXP_ID.test(String(req.params.id))) {
      res.status(400).json({ success: false, error: { code: "INVALID_ID", message: "Invalid experiment id.", details: "" } });
      return;
    }
    const data = await runPython(["report_export_html", String(req.params.id)]) as any;
    if (!data?.success || !data?.path) { reportErr(res, data); return; }
    const full = path.resolve(String(data.path));
    if (!full.startsWith(path.resolve(EXPERIMENTS_DIR)) || !fs.existsSync(full)) {
      res.status(404).json({ success: false, error: { code: "REPORT_NOT_FOUND", message: "HTML report file not found.", details: "" } });
      return;
    }
    res.setHeader("Content-Type", "text/html; charset=utf-8");
    fs.createReadStream(full).pipe(res);
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: { code: "EXPORT_FAILED", message: "HTML export failed.", details: err instanceof Error ? err.message : String(err) } });
  }
});

// GET /api/experiments/:id/report/export/csv — ZIP of CSV files
router.get("/experiments/:id/report/export/csv", async (req, res) => {
  try {
    if (!SAFE_EXP_ID.test(String(req.params.id))) {
      res.status(400).json({ success: false, error: { code: "INVALID_ID", message: "Invalid experiment id.", details: "" } });
      return;
    }
    const data = await runPython(["report_export_csv", String(req.params.id)]) as any;
    if (!data?.success || !data?.path) { reportErr(res, data); return; }
    const full = path.resolve(String(data.path));
    if (!full.startsWith(path.resolve(EXPERIMENTS_DIR)) || !fs.existsSync(full)) {
      res.status(404).json({ success: false, error: { code: "REPORT_NOT_FOUND", message: "CSV export file not found.", details: "" } });
      return;
    }
    res.setHeader("Content-Type", "application/zip");
    res.setHeader("Content-Disposition", `attachment; filename="research_report_${req.params.id}_csv.zip"`);
    fs.createReadStream(full).pipe(res);
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: { code: "EXPORT_FAILED", message: "CSV export failed.", details: err instanceof Error ? err.message : String(err) } });
  }
});

// POST /api/experiments/:id/suggested-experiments/:suggestionId/queue
// Queues a suggested next experiment. Requires explicit user confirmation in
// the UI (confirm: true in the body) — never auto-queued.
router.post("/experiments/:id/suggested-experiments/:suggestionId/queue", async (req, res) => {
  try {
    if (!SAFE_EXP_ID.test(String(req.params.id))) {
      res.status(400).json({ success: false, error: { code: "INVALID_ID", message: "Invalid experiment id.", details: "" } });
      return;
    }
    if (req.body?.confirm !== true) {
      res.status(400).json({ success: false, error: { code: "CONFIRMATION_REQUIRED", message: "Queueing a suggested experiment requires explicit confirmation.", details: "Send { confirm: true }." } });
      return;
    }
    const data = await runPython(["report_get", String(req.params.id)]) as any;
    if (!data?.success) { reportErr(res, data); return; }
    const suggestions = data.report?.next_experiments?.suggestions ?? [];
    const sug = suggestions.find((s: any) => s.id === String(req.params.suggestionId));
    if (!sug) {
      res.status(404).json({ success: false, error: { code: "SUGGESTION_NOT_FOUND", message: "Suggested experiment not found in the latest report.", details: String(req.params.suggestionId) } });
      return;
    }
    const cfg = { ...(sug.treatment_config ?? {}), name: sug.name, description: `Suggested by research report for experiment ${req.params.id}: ${sug.hypothesis}` };
    delete (cfg as any).exclude_regime; // research-only field not supported by the runner
    const submitted = await runPython(["experiment_submit", JSON.stringify(cfg)]) as any;
    res.json(submitted);
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: { code: "QUEUE_FAILED", message: "Failed to queue suggested experiment.", details: err instanceof Error ? err.message : String(err) } });
  }
});

// GET /api/experiments/:id — get status + result for one experiment
router.get("/experiments/:id", async (req, res) => {
  try {
    const expId = String(req.params.id);
    const data = await runPython(["experiment_get", expId]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// DELETE /api/experiments/:id — delete experiment and all its data
router.delete("/experiments/:id", async (req, res) => {
  try {
    const expId = String(req.params.id);
    const data = await runPython(["experiment_delete", expId]);
    if ((data as any).error) { res.status(400).json(data); return; }
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// ── Research Package & ChatGPT Report export ──────────────────────────────
// READ-ONLY — never modifies portfolio, positions, or model weights.
// Gathers existing analysis results and packages them for offline review.

const PACKAGES_DIR = path.join(PYTHON_DIR, "research_packages");
const LATEST_PACKAGE_JSON = path.join(PACKAGES_DIR, "latest_package.json");
const LATEST_CHATGPT_MD = path.join(PACKAGES_DIR, "latest_chatgpt_report.md");

// POST /api/research-package/generate — build timestamped ZIP
router.post("/research-package/generate", async (_req, res) => {
  try {
    const data = await runPython(["research_package_generate"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/research-package/download — serve the latest ZIP
router.get("/research-package/download", async (_req, res) => {
  try {
    if (!fs.existsSync(LATEST_PACKAGE_JSON)) {
      res.status(404).json({ error: "No research package generated yet. Click 'Generate & Download' first." });
      return;
    }
    const info = JSON.parse(fs.readFileSync(LATEST_PACKAGE_JSON, "utf8"));
    const zipPath: string = info.zip_path;
    if (!zipPath || !fs.existsSync(zipPath)) {
      res.status(404).json({ error: "Package file not found — please regenerate." });
      return;
    }
    const filename = path.basename(zipPath);
    res.setHeader("Content-Type", "application/zip");
    res.setHeader("Content-Disposition", `attachment; filename="${filename}"`);
    fs.createReadStream(zipPath).pipe(res);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/chatgpt-report/generate — build standalone markdown report
router.post("/chatgpt-report/generate", async (_req, res) => {
  try {
    const data = await runPython(["chatgpt_report_generate"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/chatgpt-report/download — serve latest chatgpt_report.md
router.get("/chatgpt-report/download", async (_req, res) => {
  try {
    if (!fs.existsSync(LATEST_CHATGPT_MD)) {
      res.status(404).json({ error: "No ChatGPT report generated yet. Click 'Generate & Download' first." });
      return;
    }
    res.setHeader("Content-Type", "text/markdown; charset=utf-8");
    res.setHeader("Content-Disposition", 'attachment; filename="chatgpt_report.md"');
    fs.createReadStream(LATEST_CHATGPT_MD).pipe(res);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/learning-insights
// Adaptive Learning Layer (Sprint 3 Module 3) — deterministic aggregations
// over the Historical Knowledge Base. Read-only, paper trading only.
router.get("/learning-insights", async (_req, res) => {
  try {
    const data = await runPython(["learning_insights"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/pattern-quality
// Pattern Quality dashboard (Sprint 4) — every strategy × sector × regime
// pattern with full expectancy metrics, ranked by expectancy. Read-only.
router.get("/pattern-quality", async (_req, res) => {
  try {
    const data = await runPython(["pattern_quality"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/trade-decisions
// Decision Service — combines scanner, expectancy, learning and paper
// portfolio outputs into one clear recommendation per stock. Runs a full
// universe scan (~20-30s), so cache briefly like /market-scan.
const TRADE_DECISIONS_CACHE_MS = 10 * 60 * 1000;
let tradeDecisionsCache: { data: unknown; ts: number } | null = null;
let tradeDecisionsInFlight: Promise<unknown> | null = null;

router.get("/trade-decisions", async (req, res) => {
  try {
    const force = req.query.force === "true";
    if (!force && tradeDecisionsCache && Date.now() - tradeDecisionsCache.ts < TRADE_DECISIONS_CACHE_MS) {
      res.json(tradeDecisionsCache.data);
      return;
    }
    if (!tradeDecisionsInFlight) {
      tradeDecisionsInFlight = runPython(["trade_decisions"])
        .then((data) => {
          tradeDecisionsCache = { data, ts: Date.now() };
          return data;
        })
        .finally(() => {
          tradeDecisionsInFlight = null;
        });
    }
    const data = await tradeDecisionsInFlight;
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/portfolio-manager
// v3.0 Portfolio Manager — ONE portfolio-level decision per refresh: ranks the
// full universe by risk-adjusted return, allocates capital under hard caps
// (20%/stock, 30%/sector, max 5 new positions), computes portfolio metrics and
// tracks AI allocation vs an equal-weight benchmark. Runs a full universe scan
// (~20-30s), so cache briefly like /trade-decisions. Paper trading only.
const PORTFOLIO_MANAGER_CACHE_MS = 10 * 60 * 1000;
let portfolioManagerCache: { data: unknown; ts: number } | null = null;
let portfolioManagerInFlight: Promise<unknown> | null = null;

router.get("/portfolio-manager", async (req, res) => {
  try {
    const force = req.query.refresh === "true";
    if (!force && portfolioManagerCache && Date.now() - portfolioManagerCache.ts < PORTFOLIO_MANAGER_CACHE_MS) {
      res.json(portfolioManagerCache.data);
      return;
    }
    if (!portfolioManagerInFlight) {
      portfolioManagerInFlight = runPython(["portfolio_manager"])
        .then((data) => {
          portfolioManagerCache = { data, ts: Date.now() };
          return data;
        })
        .finally(() => {
          portfolioManagerInFlight = null;
        });
    }
    const data = await portfolioManagerInFlight;
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/evidence-research
// v2.1 Evidence-Based Research Engine — for every stock, compares the current
// setup with historical knowledge-base trades using a weighted similarity
// score (0-100), returns evidence statistics, reliability tier and the
// bounded confidence adjustment. Rides on the full decision pipeline (full
// universe scan, ~20-30s), so cache briefly like /trade-decisions.
// Paper trading & research only — similarity never guarantees outcomes.
const EVIDENCE_RESEARCH_CACHE_MS = 10 * 60 * 1000;
let evidenceResearchCache: { data: unknown; ts: number } | null = null;
let evidenceResearchInFlight: Promise<unknown> | null = null;

router.get("/evidence-research", async (req, res) => {
  try {
    const force = req.query.refresh === "true";
    if (!force && evidenceResearchCache && Date.now() - evidenceResearchCache.ts < EVIDENCE_RESEARCH_CACHE_MS) {
      res.json(evidenceResearchCache.data);
      return;
    }
    if (!evidenceResearchInFlight) {
      evidenceResearchInFlight = runPython(["evidence_research"])
        .then((data) => {
          evidenceResearchCache = { data, ts: Date.now() };
          return data;
        })
        .finally(() => {
          evidenceResearchInFlight = null;
        });
    }
    const data = await evidenceResearchInFlight;
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/feature-importance
// v2.2 Root Cause Intelligence — rolling feature-importance report: which
// indicators consistently predict success, their contribution percentages,
// trends (gaining/losing importance), sample sizes and the dynamic
// similarity-weight status. Weight updates are gated (>=50 new completed
// trades) and gradual. Paper trading & research only.
const FEATURE_IMPORTANCE_CACHE_MS = 10 * 60 * 1000;
let featureImportanceCache: { data: unknown; ts: number } | null = null;
let featureImportanceInFlight: Promise<unknown> | null = null;

router.get("/feature-importance", async (req, res) => {
  try {
    const force = req.query.refresh === "true";
    if (!force && featureImportanceCache && Date.now() - featureImportanceCache.ts < FEATURE_IMPORTANCE_CACHE_MS) {
      res.json(featureImportanceCache.data);
      return;
    }
    if (!featureImportanceInFlight) {
      featureImportanceInFlight = runPython(["feature_importance"])
        .then((data) => {
          featureImportanceCache = { data, ts: Date.now() };
          return data;
        })
        .finally(() => {
          featureImportanceInFlight = null;
        });
    }
    const data = await featureImportanceInFlight;
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/paper-basket
// Paper Basket Testing Layer — paper trading only, no real orders. Selects a
// basket of stocks from the previous day's data (no lookahead bias), then
// simulates buy at next trading day's open / sell after the holding period
// at close. Full-universe scans (opportunity_score / sector_strength) take
// ~15-25s, so cache per parameter combination.
const PAPER_BASKET_CACHE_MS = 10 * 60 * 1000;
const paperBasketCache = new Map<string, { data: unknown; ts: number }>();
const paperBasketInFlight = new Map<string, Promise<unknown>>();

router.post("/paper-basket", async (req, res) => {
  try {
    const {
      selection_date,
      holding_period = 5,
      num_stocks = 10,
      quantity = 10,
      method = "opportunity_score",
      min_score = 50,
      min_confidence = 50,
      min_rr = 2.0,
      include_watch = false,
    } = req.body as {
      selection_date: string;
      holding_period?: number;
      num_stocks?: number;
      quantity?: number;
      method?: string;
      min_score?: number;
      min_confidence?: number;
      min_rr?: number;
      include_watch?: boolean;
    };

    if (!selection_date || !/^\d{4}-\d{2}-\d{2}$/.test(selection_date)) {
      res.status(400).json({ error: "selection_date is required in YYYY-MM-DD format" });
      return;
    }

    const cacheKey = `${selection_date}|${holding_period}|${num_stocks}|${quantity}|${method}|${min_score}|${min_confidence}|${min_rr}|${include_watch}`;
    const cached = paperBasketCache.get(cacheKey);
    if (cached && Date.now() - cached.ts < PAPER_BASKET_CACHE_MS) {
      res.json(cached.data);
      return;
    }

    let inFlight = paperBasketInFlight.get(cacheKey);
    if (!inFlight) {
      inFlight = runPython([
        "paper_basket", selection_date, String(holding_period),
        String(num_stocks), String(quantity), method,
        String(min_score), String(min_confidence), String(min_rr),
        include_watch ? "true" : "false",
      ]).finally(() => {
        paperBasketInFlight.delete(cacheKey);
      });
      paperBasketInFlight.set(cacheKey, inFlight);
    }
    const data = await inFlight;
    paperBasketCache.set(cacheKey, { data, ts: Date.now() });
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/strategy-performance
router.get("/strategy-performance", async (_req, res) => {
  try {
    const data = await runPython(["strategy_performance"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/market-overview
router.get("/market-overview", async (_req, res) => {
  try {
    const data = await runPython(["market_overview"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/market-data/:symbol?interval=1d&period=3mo
router.get("/market-data/:symbol", async (req, res) => {
  try {
    const { symbol } = req.params;
    const { interval = "1d", period = "3mo" } = req.query as Record<string, string>;
    const data = await runPython(["market_data", symbol, interval, period]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/indicators/:symbol?interval=1d&period=3mo
router.get("/indicators/:symbol", async (req, res) => {
  try {
    const { symbol } = req.params;
    const { interval = "1d", period = "3mo" } = req.query as Record<string, string>;
    const data = await runPython(["indicators", symbol, interval, period]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/backtest
router.post("/backtest", async (req, res) => {
  try {
    const {
      symbol,
      strategy,
      start_date,
      end_date,
      initial_capital = 5000,
      interval = "1d",
      debug = false,
    } = req.body as {
      symbol: string;
      strategy: string;
      start_date: string;
      end_date: string;
      initial_capital?: number;
      interval?: string;
      debug?: boolean;
    };
    if (!symbol || !strategy || !start_date || !end_date) {
      res.status(400).json({ error: "symbol, strategy, start_date, end_date are required" });
      return;
    }
    const data = await runPython([
      "backtest", symbol, strategy, start_date, end_date,
      String(initial_capital), interval, debug ? "true" : "false",
    ]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/optimizer
router.post("/optimizer", async (req, res) => {
  try {
    const {
      symbol, start_date, end_date,
      initial_capital = 5000,
      interval = "1d",
      top_n = 10,
    } = req.body as {
      symbol: string; start_date: string; end_date: string;
      initial_capital?: number; interval?: string; top_n?: number;
    };
    const data = await runPython([
      "optimizer", symbol, start_date, end_date,
      String(initial_capital), interval, String(top_n),
    ]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/strategy-lab
router.post("/strategy-lab", async (req, res) => {
  try {
    const {
      symbol,
      start_date,
      end_date,
      initial_capital = 5000,
      interval = "1d",
    } = req.body as {
      symbol: string;
      start_date: string;
      end_date: string;
      initial_capital?: number;
      interval?: string;
    };
    const data = await runPython([
      "strategy_lab", symbol, start_date, end_date,
      String(initial_capital), interval,
    ]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// ── v2.0 Adaptive Self-Evaluation Engine ─────────────────────────────────────
// Paper trading research only. Analysis Mode by default: proposals are never
// applied without explicit approval, and mock-data trades are never learned
// from. Learning can never change core strategy rules or create a BUY.

// GET /api/learning-review — full self-evaluation report
router.get("/learning-review", async (_req, res) => {
  try {
    const data = await runPython(["learning_review"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/learning-cycle — run a learning cycle (Analysis Mode)
router.post("/learning-cycle", async (_req, res) => {
  try {
    const data = await runPython(["learning_cycle"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/learning-adjustments/:id/approve — validate out-of-sample, then apply
router.post("/learning-adjustments/:id/approve", async (req, res) => {
  try {
    const id = parseInt(String(req.params.id), 10);
    if (!Number.isInteger(id) || id <= 0) {
      res.status(400).json({ error: "id must be a positive integer" });
      return;
    }
    const data = await runPython(["learning_approve", String(id)]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/learning-adjustments/:id/reject
router.post("/learning-adjustments/:id/reject", async (req, res) => {
  try {
    const id = parseInt(String(req.params.id), 10);
    if (!Number.isInteger(id) || id <= 0) {
      res.status(400).json({ error: "id must be a positive integer" });
      return;
    }
    const data = await runPython(["learning_reject", String(id)]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/learning-rollback/:version — roll back a model version
router.post("/learning-rollback/:version", async (req, res) => {
  try {
    const version = parseInt(String(req.params.version), 10);
    if (!Number.isInteger(version) || version <= 0) {
      res.status(400).json({ error: "version must be a positive integer" });
      return;
    }
    const data = await runPython(["learning_rollback", String(version)]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// ── v2.1 Hypothesis Engine ───────────────────────────────────────────────────
// Human-readable, statistically backed hypotheses mined from completed paper
// trades. Approval is user-gated and bounded; ineffective applied hypotheses
// are rolled back automatically by the learning cycle.

// POST /api/hypotheses/:id/approve — validate out-of-sample, then apply
router.post("/hypotheses/:id/approve", async (req, res) => {
  try {
    const id = parseInt(String(req.params.id), 10);
    if (!Number.isInteger(id) || id <= 0) {
      res.status(400).json({ error: "id must be a positive integer" });
      return;
    }
    const data = await runPython(["hypothesis_approve", String(id)]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/hypotheses/:id/reject
router.post("/hypotheses/:id/reject", async (req, res) => {
  try {
    const id = parseInt(String(req.params.id), 10);
    if (!Number.isInteger(id) || id <= 0) {
      res.status(400).json({ error: "id must be a positive integer" });
      return;
    }
    const data = await runPython(["hypothesis_reject", String(id)]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/trade-evaluations — evaluated round trips (prediction vs actual)
router.get("/trade-evaluations", async (req, res) => {
  try {
    const limit = String(parseInt(String(req.query.limit ?? "200"), 10) || 200);
    const data = await runPython(["trade_evaluations", limit]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/strategies
router.get("/strategies", async (_req, res) => {
  try {
    const data = await runPython(["strategies"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// ── Phase 8: Broker Integration & Live Execution Readiness ────────────────────

// GET /api/broker/status — full broker + mode + safety + scan status
router.get("/broker/status", async (_req, res) => {
  try {
    const data = await runPython(["phase8_status"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/broker/health — quick connection probe
router.get("/broker/health", async (_req, res) => {
  try {
    const data = await runPython(["phase8_health"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/broker/paper-summary — live paper dashboard figures from the phase20 ledger
router.get("/broker/paper-summary", async (_req, res) => {
  try {
    const data = await runPython(["phase8_paper_summary"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/broker/account — profile, margins, holdings, positions, orders
router.get("/broker/account", async (_req, res) => {
  try {
    const data = await runPython(["phase8_account"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/broker/mode
router.get("/broker/mode", async (_req, res) => {
  try {
    const data = await runPython(["phase8_mode_get"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/broker/mode  body: { mode: "RESEARCH_ONLY" | "PAPER_TRADING" | "LIVE_ASSISTED" }
router.post("/broker/mode", async (req, res) => {
  try {
    const { mode } = req.body as { mode: string };
    if (!mode) { res.status(400).json({ error: "mode required" }); return; }
    const data = await runPython(["phase8_mode_set", mode]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/broker/readiness — full readiness checklist + score
router.get("/broker/readiness", async (_req, res) => {
  try {
    const data = await runPython(["phase8_readiness"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/broker/order/preview  body: { symbol, side, quantity, entry_price?, stop_loss?, target? }
router.post("/broker/order/preview", async (req, res) => {
  try {
    const { symbol, side, quantity, entry_price = 0, stop_loss = 0, target = 0 } =
      req.body as { symbol: string; side: string; quantity: number;
                    entry_price?: number; stop_loss?: number; target?: number };
    if (!symbol || !side || !quantity) {
      res.status(400).json({ error: "symbol, side, quantity required" });
      return;
    }
    const data = await runPython([
      "phase8_preview", symbol, side, String(quantity),
      String(entry_price), String(stop_loss), String(target),
    ]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/broker/order/confirm1  body: { preview_id, token }
router.post("/broker/order/confirm1", async (req, res) => {
  try {
    const { preview_id, token } = req.body as { preview_id: string; token: string };
    if (!preview_id || !token) { res.status(400).json({ error: "preview_id and token required" }); return; }
    const data = await runPython(["phase8_confirm1", preview_id, token]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/broker/order/confirm2  body: { preview_id, token }
router.post("/broker/order/confirm2", async (req, res) => {
  try {
    const { preview_id, token } = req.body as { preview_id: string; token: string };
    if (!preview_id || !token) { res.status(400).json({ error: "preview_id and token required" }); return; }
    const data = await runPython(["phase8_confirm2", preview_id, token]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/broker/kill-switch  body: { activate: boolean }
router.post("/broker/kill-switch", async (req, res) => {
  try {
    const { activate } = req.body as { activate: boolean };
    if (typeof activate !== "boolean") { res.status(400).json({ error: "activate (boolean) required" }); return; }
    const data = await runPython(["phase8_kill_switch", activate ? "on" : "off"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/broker/audit?limit=100
router.get("/broker/audit", async (req, res) => {
  try {
    const limit = String(parseInt(String(req.query.limit ?? "100"), 10) || 100);
    const data = await runPython(["phase8_audit", limit]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/broker/export?kind=json|csv
router.get("/broker/export", async (req, res) => {
  try {
    const kind = String(req.query.kind ?? "json").toLowerCase();
    const data = await runPython(["phase8_export", kind]) as { file?: string };
    if (data?.file && fs.existsSync(data.file)) {
      const filename = `phase8_export.${kind}`;
      res.setHeader("Content-Disposition", `attachment; filename="${filename}"`);
      res.setHeader("Content-Type", kind === "csv" ? "text/csv" : "application/json");
      res.send(fs.readFileSync(data.file));
    } else {
      res.json(data);
    }
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// ── Phase 9 — AI Copilot, Alerts & Explainability ──────────────────────────

// GET /api/copilot/summary
router.get("/copilot/summary", async (_req, res) => {
  try {
    const data = await runPython(["phase9_copilot"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/copilot/alerts/generate
router.post("/copilot/alerts/generate", async (_req, res) => {
  try {
    const data = await runPython(["phase9_alerts_generate"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/copilot/alerts?limit=
router.get("/copilot/alerts", async (req, res) => {
  try {
    const limit = String(parseInt(String(req.query.limit ?? "100"), 10) || 100);
    const data = await runPython(["phase9_alerts", limit]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/copilot/alerts/read  { alert_id: "..." | "all" }
router.post("/copilot/alerts/read", async (req, res) => {
  try {
    const alertId = String(req.body?.alert_id ?? "all");
    const data = await runPython(["phase9_alerts_read", alertId]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/copilot/briefing
router.get("/copilot/briefing", async (_req, res) => {
  try {
    const data = await runPython(["phase9_briefing"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/copilot/explanations?limit=
router.get("/copilot/explanations", async (req, res) => {
  try {
    const limit = String(parseInt(String(req.query.limit ?? "20"), 10) || 20);
    const data = await runPython(["phase9_explanations", limit]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/copilot/explain/:symbol
router.get("/copilot/explain/:symbol", async (req, res) => {
  try {
    const data = await runPython(["phase9_explain", String(req.params.symbol).toUpperCase()]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/copilot/why-not/:symbol
router.get("/copilot/why-not/:symbol", async (req, res) => {
  try {
    const data = await runPython(["phase9_why_not", String(req.params.symbol).toUpperCase()]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/copilot/watchlist-insights
router.get("/copilot/watchlist-insights", async (_req, res) => {
  try {
    const data = await runPython(["phase9_watchlist_insights"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/copilot/confidence-history?symbol=
router.get("/copilot/confidence-history", async (req, res) => {
  try {
    const args = ["phase9_confidence_history"];
    if (req.query.symbol) args.push(String(req.query.symbol).toUpperCase());
    const data = await runPython(args);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/copilot/export?kind=json|csv
router.get("/copilot/export", async (req, res) => {
  try {
    const kind = String(req.query.kind ?? "json").toLowerCase();
    const data = await runPython(["phase9_export", kind]) as { file?: string };
    if (data?.file && fs.existsSync(data.file)) {
      const filename = kind === "csv" ? "phase9_alerts.csv" : "phase9_export.json";
      res.setHeader("Content-Disposition", `attachment; filename="${filename}"`);
      res.setHeader("Content-Type", kind === "csv" ? "text/csv" : "application/json");
      res.send(fs.readFileSync(data.file));
    } else {
      res.json(data);
    }
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// ── Phase 10.1 — Performance Analytics ──────────────────────────────────────

// GET /api/analytics/performance
router.get("/analytics/performance", async (_req, res) => {
  try {
    const data = await runPython(["phase10_analytics"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/analytics/export?kind=json|csv|snapshot
router.get("/analytics/export", async (req, res) => {
  try {
    const kind = String(req.query.kind ?? "json").toLowerCase();
    if (!["json", "csv", "snapshot"].includes(kind)) {
      res.status(400).json({ error: `Invalid export kind '${kind}'. Use json, csv, or snapshot.` });
      return;
    }
    const data = await runPython(["phase10_export", kind]) as { file?: string };
    if (data?.file && fs.existsSync(data.file)) {
      const filename = path.basename(data.file);
      res.setHeader("Content-Disposition", `attachment; filename="${filename}"`);
      res.setHeader("Content-Type", kind === "csv" ? "text/csv" : "application/json");
      res.send(fs.readFileSync(data.file));
    } else {
      res.json(data);
    }
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// ── Phase Review Package ─────────────────────────────────────────────────────

function runNode(scriptPath: string, args: string[]): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const proc = spawn("node", [scriptPath, ...args], { cwd: process.cwd() });
    let stdout = "";
    let stderr = "";
    proc.stdout.on("data", (d: Buffer) => { stdout += d.toString(); });
    proc.stderr.on("data", (d: Buffer) => { stderr += d.toString(); });
    proc.on("close", (code) => {
      if (code !== 0) return reject(new Error(stderr || `node exited ${code}`));
      try { resolve(JSON.parse(stdout.trim())); }
      catch { reject(new Error(`Failed to parse node output: ${stdout.slice(0, 300)}`)); }
    });
    proc.on("error", reject);
  });
}

// Generation takes ~4-5 minutes — far longer than the browser/proxy request
// timeout (~2 min). So POST /generate starts a background job and returns
// immediately; the UI polls GET /status until the job finishes.
interface ReviewJob {
  status: "idle" | "running" | "done" | "error";
  stage: string;
  startedAt: number | null;
  result: Record<string, unknown> | null;
  error: string | null;
}
const reviewJob: ReviewJob = { status: "idle", stage: "", startedAt: null, result: null, error: null };

async function runReviewPackageJob(): Promise<void> {
  const shotsDir = path.join(PYTHON_DIR, "review_screenshots");
  let shots: { captured?: unknown[]; failed?: unknown[]; error?: string } = {};
  reviewJob.stage = "Capturing full-page screenshots of every page (2-4 min)";
  try {
    shots = await runNode(
      path.join(process.cwd(), "src", "scripts", "capture_screenshots.mjs"),
      [shotsDir],
    ) as typeof shots;
  } catch (e: unknown) {
    shots = { error: e instanceof Error ? e.message : String(e) };
  }
  reviewJob.stage = "Building reports, exports, running test suites and zipping";
  const result = await runPython(["review_package", shotsDir]) as Record<string, unknown>;
  const warnings = (result.warnings as string[]) ?? [];
  if (shots.error) warnings.push(`Screenshot capture failed: ${shots.error}`);
  if (shots.failed && (shots.failed as unknown[]).length > 0) {
    warnings.push(`${(shots.failed as unknown[]).length} page(s) failed to capture`);
  }
  reviewJob.result = {
    ...result,
    generation_seconds: reviewJob.startedAt
      ? Math.round((Date.now() - reviewJob.startedAt) / 1000)
      : result.generation_seconds,
    warnings,
    screenshot_failures: shots.failed ?? [],
  };
}

// POST /api/review-package/generate — start the background job (returns at once)
router.post("/review-package/generate", (_req, res) => {
  if (reviewJob.status === "running") {
    res.status(409).json({ error: "A review package is already being generated. Please wait." });
    return;
  }
  reviewJob.status = "running";
  reviewJob.stage = "Starting";
  reviewJob.startedAt = Date.now();
  reviewJob.result = null;
  reviewJob.error = null;
  runReviewPackageJob()
    .then(() => { reviewJob.status = "done"; reviewJob.stage = "Complete"; })
    .catch((err: unknown) => {
      reviewJob.status = "error";
      reviewJob.error = err instanceof Error ? err.message : String(err);
    });
  res.status(202).json({ started: true, status: "running" });
});

// GET /api/review-package/status — poll job progress / final result
router.get("/review-package/status", (_req, res) => {
  res.json({
    status: reviewJob.status,
    stage: reviewJob.stage,
    elapsed_seconds: reviewJob.startedAt && reviewJob.status === "running"
      ? Math.round((Date.now() - reviewJob.startedAt) / 1000) : null,
    result: reviewJob.status === "done" ? reviewJob.result : null,
    error: reviewJob.error,
  });
});

// GET /api/review-package/download — stream the most recently generated ZIP
router.get("/review-package/download", (_req, res) => {
  // Find the newest Phase<N>_Review_Package.zip so this never goes stale
  // when the current phase number advances.
  const candidates = fs.readdirSync(PYTHON_DIR)
    .filter((f) => /^Phase\d+_Review_Package\.zip$/.test(f))
    .map((f) => ({ f, mtime: fs.statSync(path.join(PYTHON_DIR, f)).mtimeMs }))
    .sort((a, b) => b.mtime - a.mtime);
  const zipPath = candidates.length > 0 ? path.join(PYTHON_DIR, candidates[0].f) : "";
  if (!zipPath || !fs.existsSync(zipPath)) {
    res.status(404).json({ error: "No review package has been generated yet." });
    return;
  }
  res.setHeader("Content-Type", "application/zip");
  res.setHeader("Content-Disposition", `attachment; filename="${path.basename(zipPath)}"`);
  fs.createReadStream(zipPath).pipe(res);
});

// ── Phase 11: Institutional Risk Engine ───────────────────────────────────
// Paper trading / research only — no real-money execution anywhere.

// GET /api/risk/dashboard — portfolio risk dashboard
router.get("/risk/dashboard", async (_req, res) => {
  try {
    res.json(await runPython(["risk_dashboard"]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/risk/assess — pre-trade risk assessment (8 checks)
router.post("/risk/assess", async (req, res) => {
  try {
    const { symbol, quantity, price, stop_loss, confidence } = req.body ?? {};
    if (!symbol || !quantity || !price) {
      res.status(400).json({ error: "symbol, quantity and price are required" });
      return;
    }
    const args = ["risk_assess", String(symbol), String(quantity), String(price)];
    if (stop_loss != null || confidence != null) {
      args.push(stop_loss != null ? String(stop_loss) : "null");
      if (confidence != null) args.push(String(confidence));
    }
    res.json(await runPython(args));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/risk/position-size — dynamic position sizing
router.post("/risk/position-size", async (req, res) => {
  try {
    const { symbol, price, stop_loss, confidence } = req.body ?? {};
    if (!symbol || !price) {
      res.status(400).json({ error: "symbol and price are required" });
      return;
    }
    const args = ["risk_position_size", String(symbol), String(price)];
    if (stop_loss != null || confidence != null) {
      args.push(stop_loss != null ? String(stop_loss) : "null");
      if (confidence != null) args.push(String(confidence));
    }
    res.json(await runPython(args));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/risk/analytics — full Portfolio Risk Analytics payload
router.get("/risk/analytics", async (_req, res) => {
  try {
    res.json(await runPython(["risk_analytics"]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/risk/approval-cards — trade approval cards for scan candidates
router.get("/risk/approval-cards", async (_req, res) => {
  try {
    res.json(await runPython(["risk_approval_cards"]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/risk/alerts — evaluate + list risk alerts
router.get("/risk/alerts", async (_req, res) => {
  try {
    res.json(await runPython(["risk_alerts"]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/risk/kill-switch — kill switch status
router.get("/risk/kill-switch", async (_req, res) => {
  try {
    res.json(await runPython(["risk_kill_switch", "status"]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/risk/kill-switch/trigger — halt all paper trading (simulated)
router.post("/risk/kill-switch/trigger", async (req, res) => {
  try {
    const reason = String(req.body?.reason || "Manual trigger from dashboard");
    res.json(await runPython(["risk_kill_switch", "trigger", reason]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/risk/kill-switch/resume — resume; requires explicit acknowledge
router.post("/risk/kill-switch/resume", async (req, res) => {
  try {
    const args = ["risk_kill_switch", "resume"];
    if (req.body?.acknowledge === true) args.push("acknowledge");
    res.json(await runPython(args));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/risk/report/:kind — generate + download one of the 5 risk reports
const RISK_REPORT_KINDS = new Set(["risk_summary", "exposure", "correlation", "position_sizing", "drawdown"]);
// Supports both /api/risk/report/:kind and /api/risk/report?kind=
router.get(["/risk/report/:kind", "/risk/report"], async (req, res) => {
  try {
    const kind = String(req.params.kind ?? req.query.kind ?? "");
    if (!RISK_REPORT_KINDS.has(kind)) {
      res.status(400).json({ error: `Unknown report kind '${kind}'. Valid: ${[...RISK_REPORT_KINDS].join(", ")}` });
      return;
    }
    const result = (await runPython(["risk_report", kind])) as { success?: boolean; file?: string; error?: string };
    if (!result?.success || !result.file || !fs.existsSync(result.file)) {
      res.status(500).json({ error: result?.error || "Report generation failed" });
      return;
    }
    res.setHeader("Content-Type", "text/csv");
    res.setHeader("Content-Disposition", `attachment; filename="${path.basename(result.file)}"`);
    fs.createReadStream(result.file).pipe(res);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/risk/config — current risk limits
router.get("/risk/config", async (_req, res) => {
  try {
    res.json(await runPython(["risk_config"]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/risk/config — update risk limits (allowlisted keys only, python-side)
router.post("/risk/config", async (req, res) => {
  try {
    const changes = req.body ?? {};
    if (typeof changes !== "object" || Array.isArray(changes) || Object.keys(changes).length === 0) {
      res.status(400).json({ error: "Provide a JSON object of config keys to update" });
      return;
    }
    res.json(await runPython(["risk_config", JSON.stringify(changes)]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// ── Phase 20 — auto-scan settings, scheduler health, history, paper engine ──
// Paper trading / research only. No live orders anywhere.

// GET /api/ops-centre/platform — fast platform status (< 1 s, reads only cached KV + market hours)
// Returns platform health %, scan metadata, market state, and last-known pipeline node statuses.
// Populated from the KV cache written by /ops-centre/snapshot after each full agent collection.
//
// Node.js-level cache (10 s TTL) avoids a Python spawn (~600 ms) on every platform-bar poll.
// Coalesces concurrent misses into a single subprocess.
// Explicitly cleared when a full scan completes (scan.completed event) and when the
// /ops-centre/snapshot route returns successfully — both events mean fresh KV data was written.
const PLATFORM_CACHE_MS = 10_000;
let platformCache: { data: unknown; ts: number } | null = null;
let platformInFlight: Promise<unknown> | null = null;

/** Exported so the snapshot route and tests can invalidate the cache on demand. */
export function clearPlatformCache(): void { platformCache = null; }

// Invalidate whenever a scan completes — the scan writes new health_pct + cache_ts to KV.
// eventBus extends EventEmitter; "event" is the single channel, filter by evt.event name.
eventBus.on("event", (evt: { event: string }) => {
  if (evt.event === "scan.completed") clearPlatformCache();
});

router.get("/ops-centre/platform", async (_req, res) => {
  try {
    // Serve from Node.js cache if still fresh (skips Python spawn entirely)
    if (platformCache && Date.now() - platformCache.ts < PLATFORM_CACHE_MS) {
      res.json(platformCache.data);
      return;
    }
    // Coalesce concurrent requests into a single subprocess
    if (!platformInFlight) {
      platformInFlight = runPython(["ops_centre_platform"])
        .finally(() => { platformInFlight = null; });
    }
    const data = await platformInFlight;
    platformCache = { data, ts: Date.now() };
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/ops-centre/agents — canonical agent status for all four dashboard pages
// Same 12 parallel collectors as the full snapshot; skips V3 enrichment so it
// returns in ~5-8 s instead of 22-30 s. 10 s Node.js cache + in-flight coalescing.
// Cleared on scan.completed so all four pages get fresh data after every scan.
const AGENTS_CACHE_MS = 10_000;
let agentsCache: { data: unknown; ts: number } | null = null;
let agentsInFlight: Promise<unknown> | null = null;

export function clearAgentsCache(): void { agentsCache = null; }

eventBus.on("event", (evt: { event: string }) => {
  if (evt.event === "scan.completed") clearAgentsCache();
});

// Command Centre summary cache is cleared on scan so it picks up fresh market + portfolio data.
eventBus.on("event", (evt: { event: string }) => {
  if (evt.event === "scan.completed") clearCommandCenterCache();
});

router.get("/ops-centre/agents", async (_req, res) => {
  try {
    if (agentsCache && Date.now() - agentsCache.ts < AGENTS_CACHE_MS) {
      res.json(agentsCache.data);
      return;
    }
    if (!agentsInFlight) {
      agentsInFlight = runPython(["ops_centre_agents"])
        .finally(() => { agentsInFlight = null; });
    }
    const data = await agentsInFlight;
    agentsCache = { data, ts: Date.now() };
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/ops-centre/diagnostics — Agent Registry + Snapshot Bus + feature flags
// Read-only, no cache — always reflects live state of the running Python process.
router.get("/ops-centre/diagnostics", async (_req, res) => {
  try {
    const data = await runPython(["ops_centre_diagnostics"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/ops-centre/journey/:symbol — V3 on-demand stock journey (not polled)
router.get("/ops-centre/journey/:symbol", async (req, res) => {
  const symbol = (req.params.symbol || "").toUpperCase().trim();
  if (!symbol) { res.status(400).json({ error: "symbol required" }); return; }
  res.json(await runPython(["ops_v3_stock_journey", symbol]));
});

// GET /api/ops-centre/snapshot — AI Operations Centre full snapshot (all 12 agents, parallel)
// Clears the platform cache on success: the snapshot writes fresh health_pct + cache_ts to KV,
// so the next /ops-centre/platform hit should read the new values, not the stale 10s window.
//
// In-flight coalescing: the snapshot is expensive (10–30 s, 12 parallel agent threads).
// Concurrent callers (e.g. two browser tabs opening simultaneously) share one Python process
// instead of each spawning their own. No result cache — the 30 s React Query refetch interval
// already limits frequency; we only deduplicate simultaneous spawns.
let snapshotInFlight: Promise<unknown> | null = null;

router.get("/ops-centre/snapshot", async (_req, res) => {
  try {
    if (!snapshotInFlight) {
      snapshotInFlight = runPython(["ops_centre_snapshot"])
        .finally(() => { snapshotInFlight = null; });
    }
    const data = await snapshotInFlight;
    clearPlatformCache();   // fresh KV written — next platform poll gets new cache_ts
    res.json(data);

    // Fire-and-forget health alert push notifications (Task 316).
    // Runs after res.json() so it never delays the response.
    // dispatchHealthAlertPushNotifications() is idempotent per scan_id.
    void (async () => {
      try {
        const { dispatchHealthAlertPushNotifications } = await import("../lib/pushNotifier");
        await dispatchHealthAlertPushNotifications(
          data as import("../lib/pushNotifier").OpsHealthSnapshot,
        );
      } catch {
        // Advisory only — never surface push errors to the caller
      }
    })();
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/ops-centre/integrity-check — 9-component pipeline health check (P9)
router.get("/ops-centre/integrity-check", async (_req, res) => {
  try {
    res.json(await runPython(["ops_centre_integrity_check"]));
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/ops-centre/cycle-log — last 50 per-cycle pipeline log entries (P8)
router.get("/ops-centre/cycle-log", async (_req, res) => {
  try {
    res.json(await runPython(["ops_centre_cycle_log"]));
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/phase20/orphan-seal — last execution-seal result for the dashboard
// Shows how many BUY signals were orphaned (no execution outcome) and sealed
// at session end by seal_execution_outcomes(). Zero is the healthy state.
router.get("/phase20/orphan-seal", async (_req, res) => {
  try {
    res.json(await runPython(["phase20_orphan_seal_stats"]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/phase20/pipeline — execution pipeline funnel diagnostics
router.get("/phase20/pipeline", async (_req, res) => {
  try {
    res.json(await runPython(["pipeline_stats"]));
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/phase20/settings — durable auto-scan + paper-trade settings
router.get("/phase20/settings", async (_req, res) => {
  try {
    res.json(await runPython(["phase20_settings"]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/phase20/capital-migration/status — strict read-only readiness check.
// PostgreSQL OPEN + EXIT_PENDING rows are authoritative; unreadable state blocks.
router.get("/phase20/capital-migration/status", async (_req, res) => {
  try {
    const result = (await runPython([
      "phase20_capital_migration_status",
    ])) as Record<string, unknown>;
    res.json(result);
  } catch (err: unknown) {
    res.status(500).json({
      success: false,
      status: "BLOCKED_STATE_UNREADABLE",
      error: err instanceof Error ? err.message : String(err),
    });
  }
});

// POST /api/phase20/capital-migration — guarded paper-only ₹100,000 rebase.
// The Python boundary takes a ledger table lock, pauses entries, preserves
// closed history/P&L, and requires exact operator confirmation.
router.post("/phase20/capital-migration", async (req, res) => {
  try {
    const payload = {
      confirmation_text: String(req.body?.confirmation_text ?? ""),
      reviewed_by: String(req.body?.reviewed_by ?? "operator"),
    };
    const result = (await runPython([
      "phase20_capital_migration",
      JSON.stringify(payload),
    ])) as Record<string, unknown>;
    const status = String(result["status"] ?? "");
    if (status === "BLOCKED_STATE_UNREADABLE") {
      res.status(503).json(result);
      return;
    }
    if (status === "BLOCKED_OPEN_POSITIONS") {
      res.status(409).json(result);
      return;
    }
    if (status === "CONFIRMATION_REQUIRED") {
      res.status(400).json(result);
      return;
    }
    res.json(result);
  } catch (err: unknown) {
    res.status(500).json({
      success: false,
      status: "BLOCKED_STATE_UNREADABLE",
      error: err instanceof Error ? err.message : String(err),
    });
  }
});

// GET /api/phase20/bootstrap-status — bootstrap mode readiness summary.
// Reads from the latest cached scan snapshot + settings only; no yfinance calls.
// Returns kite_session_verified, bootstrap_eligible_count, top WATCH candidates,
// and all settings needed to render the BootstrapStatusCard without extra queries.
router.get("/phase20/bootstrap-status", async (_req, res) => {
  try {
    res.json(await runPython(["phase20_bootstrap_status"]));
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/phase20/eod-status — EOD square-off countdown & result for Mission Control.
// Returns: time_to_squareoff_sec, in_squareoff_window, show_countdown,
// force_close_results (MARKET_CLOSE_EXIT / POST_CLOSE_FORCE_EXIT today),
// blocked_events (MARKET_CLOSE_EXIT_BLOCKED today).
// Read-only; never triggers any trades.
router.get("/phase20/eod-status", async (_req, res) => {
  try {
    res.json(await runPython(["phase20_eod_status"]));
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/phase20/force-eod-close — emergency bypass: run
// eod_force_close_open_positions immediately WITHOUT the kv_claim_once guard.
// Use when today's claim was already consumed by a failed earlier attempt.
// Paper-only; never calls broker order APIs.
router.post("/phase20/force-eod-close", async (_req, res) => {
  try {
    res.json(await runPython(["phase20_force_eod_close_now"]));
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});

// PUT /api/phase20/settings — update settings; enabling auto paper entries
// requires the exact confirmation text (enforced python-side).
router.put("/phase20/settings", async (req, res) => {
  try {
    const body = req.body ?? {};
    const patch = (body as Record<string, unknown>)["patch"];
    if (typeof patch !== "object" || patch === null || Array.isArray(patch)) {
      res.status(400).json({ error: "Provide { patch: {...}, confirmation_text? }" });
      return;
    }
    const payload = {
      patch,
      confirmation_text: (body as Record<string, unknown>)["confirmation_text"] ?? null,
    };
    const result = (await runPython([
      "phase20_settings_update", JSON.stringify(payload),
    ])) as Record<string, unknown>;
    if (result && result["success"] === false) {
      res.status(400).json(result);
      return;
    }
    res.json(result);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/phase20/email/status — is an email provider configured? (no secrets)
router.get("/phase20/email/status", async (_req, res) => {
  try {
    res.json(await runPython(["phase20_email_status"]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/phase20/email/test — send a test alert email (body: { address? })
router.post("/phase20/email/test", async (req, res) => {
  try {
    const address = (req.body ?? {})["address"];
    const args = ["phase20_email_test"];
    if (typeof address === "string" && address.trim()) args.push(address.trim());
    const result = (await runPython(args)) as Record<string, unknown>;
    if (result && result["success"] === false) {
      res.status(400).json(result);
      return;
    }
    res.json(result);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/phase20/email/preview-daily-summary — compose today's summary email
// without sending it (subject + text for an in-app preview)
router.get("/phase20/email/preview-daily-summary", async (_req, res) => {
  try {
    const result = (await runPython([
      "phase20_email_preview_daily_summary",
    ])) as Record<string, unknown>;
    if (result && result["success"] === false) {
      res.status(400).json(result);
      return;
    }
    res.json(result);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/phase20/email/preview-alert — compose a sample critical-alert email
// (new formatted HTML style) without sending it, for an in-app preview
router.get("/phase20/email/preview-alert", async (_req, res) => {
  try {
    const result = (await runPython([
      "phase20_email_preview_alert",
    ])) as Record<string, unknown>;
    if (result && result["success"] === false) {
      res.status(400).json(result);
      return;
    }
    res.json(result);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/phase20/email/send-daily-summary — send today's summary email now
router.post("/phase20/email/send-daily-summary", async (_req, res) => {
  try {
    const result = (await runPython([
      "phase20_email_send_daily_summary",
    ])) as Record<string, unknown>;
    if (result && result["success"] === false) {
      res.status(400).json(result);
      return;
    }
    res.json(result);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/phase20/exit-pending-alert — EXIT_PENDING trades with age (for dashboard badge)
// Cheap: reads the ledger, no scan or yfinance call. Cache 60 s.
const _exitPendingCache: { data: unknown; ts: number } = { data: null, ts: 0 };
router.get("/phase20/exit-pending-alert", async (_req, res) => {
  try {
    if (_exitPendingCache.data && Date.now() - _exitPendingCache.ts < 60_000) {
      res.json(_exitPendingCache.data);
      return;
    }
    const data = await runPython(["phase20_exit_pending_alert"]);
    _exitPendingCache.data = data;
    _exitPendingCache.ts = Date.now();
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/phase20/cadence-stats — today's scan cadence metrics
router.get("/phase20/cadence-stats", async (_req, res) => {
  try {
    res.json(await runPython(["phase20_cadence_stats"]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/phase20/scheduler/health — last runs, next due, missed, status
router.get("/phase20/scheduler/health", async (_req, res) => {
  try {
    res.json(await runPython(["phase20_scheduler_health"]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/phase20/scan-history — durable scan-run history
router.get("/phase20/scan-history", async (req, res) => {
  try {
    const limit = Math.min(Number(req.query["limit"]) || 50, 200);
    res.json(await runPython(["phase20_scan_history", String(limit)]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/phase20/notifications — in-app notification feed
router.get("/phase20/notifications", async (req, res) => {
  try {
    const limit = Math.min(Number(req.query["limit"]) || 100, 300);
    res.json(await runPython(["phase20_notifications", String(limit)]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/phase20/notifications/read — mark notifications read
router.post("/phase20/notifications/read", async (req, res) => {
  try {
    const ids = (req.body ?? {})["ids"];
    res.json(await runPython(
      Array.isArray(ids)
        ? ["phase20_notifications_read", JSON.stringify(ids)]
        : ["phase20_notifications_read"],
    ));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/phase20/evaluation — run/refresh the entry-gate evaluation
router.get("/phase20/evaluation", async (_req, res) => {
  try {
    res.json(await runPython(["phase20_evaluate"]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/phase20/ledger — durable paper-trade ledger
router.get("/phase20/ledger", async (req, res) => {
  try {
    const limit = Math.min(Number(req.query["limit"]) || 200, 500);
    res.json(await runPython(["phase20_ledger", String(limit)]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/phase20/positions — open Phase 20 paper positions
router.get("/phase20/positions", async (_req, res) => {
  try {
    res.json(await runPython(["phase20_positions"]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/phase20/exits/tick — evaluate exits for open paper positions now
router.post("/phase20/exits/tick", async (_req, res) => {
  try {
    const result = await runPython(["phase20_exit_tick"]) as Record<string, unknown>;
    // Publish paper.trade.recorded when at least one position was closed so the
    // Live Readiness page invalidates its Data Quality score immediately.
    const closedCount = Number(result?.["exits_processed"] ?? result?.["closed_count"] ?? result?.["trades_closed"] ?? 0);
    if (closedCount > 0 || result?.["success"] === true) {
      eventBus.publish("paper.trade.recorded", {
        source: "exits_tick",
        closed_count: closedCount,
        ts: new Date().toISOString(),
      });
    }
    res.json(result);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/phase20/replay/:tradeId — deterministic decision replay
router.get("/phase20/replay/:tradeId", async (req, res) => {
  try {
    res.json(await runPython(["phase20_replay", String(req.params.tradeId)]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/phase20/circuit-breaker — entry circuit-breaker state + audit log
router.get("/phase20/circuit-breaker", async (_req, res) => {
  try {
    res.json(await runPython(["phase20_circuit_breaker"]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/phase20/circuit-breaker/resume — manual-review resume (requires
// the exact confirmation statement; paper entries only, never live orders)
router.post("/phase20/circuit-breaker/resume", async (req, res) => {
  try {
    const payload = {
      confirmation_text: String(req.body?.confirmation_text ?? ""),
      reviewed_by: String(req.body?.reviewed_by ?? "user"),
    };
    res.json(await runPython(["phase20_circuit_breaker_resume", JSON.stringify(payload)]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/phase20/validation — validation dashboard status
router.get("/phase20/validation", async (_req, res) => {
  try {
    res.json(await runPython(["phase20_validation"]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/phase20/reconciliation/probe
// Checks whether EOD reconciliation ran today. If it is past 23:00 IST on a
// weekday and the KV guard was never set, fires an in-app notification and an
// email alert so the operator is notified before the next trading session.
// Returns { status: "OK" | "NOT_DUE" | "MISSED", ... }.
router.get("/phase20/reconciliation/probe", async (_req, res) => {
  try {
    res.json(await runPython(["reconcil_probe"]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/risk/audit — V4.3 Risk Agent audit panel
// Returns the full structured rule manifest for every BUY/STRONG_BUY candidate
// in the current canonical scan, with per-gate required / actual / pass-fail
// entries so operators can see exactly which thresholds are being applied.
// READ-ONLY · ADVISORY ONLY · PAPER TRADING
router.get("/risk/audit", async (_req, res) => {
  try {
    res.json(await runPython(["risk_audit"]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// ── Paper Intraday Learning / Exploration Mode ──────────────────────────────

// GET /api/paper/exploration/status — full exploration status including budget,
// candidates, open experimental trades, and learning summary.
// Returns: enabled, budget, candidates[], open_trades[], learning_summary.
// 15s server-side cache; invalidated when scanStatusGen increments.
router.get("/paper/exploration/status", async (_req, res) => {
  try {
    res.json(await runPython(["exploration_status"]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/paper/exploration/trades?limit=N — experimental trade log (read-only).
// limit: 1–200 (default 50).
router.get("/paper/exploration/trades", async (req, res) => {
  try {
    const limit = Math.min(Number(req.query["limit"]) || 50, 200);
    res.json(await runPython(["exploration_trades", String(limit)]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/paper/exploration/report — today's learning report (on-demand).
router.get("/paper/exploration/report", async (_req, res) => {
  try {
    res.json(await runPython(["exploration_report"]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// PUT /api/paper/exploration/settings — update exploration-mode settings.
// Body: { patch: { paper_exploration_mode: true, ... } }
router.put("/paper/exploration/settings", async (req, res) => {
  try {
    const body = req.body ?? {};
    const patch = (body as Record<string, unknown>)["patch"];
    if (typeof patch !== "object" || patch === null || Array.isArray(patch)) {
      res.status(400).json({ error: "Provide { patch: { ... } }" });
      return;
    }
    const result = (await runPython([
      "exploration_settings_update",
      JSON.stringify({ patch }),
    ])) as Record<string, unknown>;
    if (result && result["success"] === false) {
      res.status(400).json(result);
      return;
    }
    res.json(result);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/auto-paper/buy-audit?limit=10
// Read-only diagnostic: the most recent BUY_GENERATED pipeline events with
// market-hours verification, auto-entry cross-reference, and execution outcome.
// Each record shows: scan_id, symbol, generated_at_ist, market_open,
// auto_entry_attempted, execution_outcome, failed_gates, fill_price, qty, status.
// limit: 1–50 (default 10).  READ-ONLY · PAPER TRADING ONLY.
router.get("/auto-paper/buy-audit", async (req, res) => {
  try {
    const raw = Number(req.query["limit"]);
    const limit = Math.min(Math.max(isNaN(raw) ? 10 : raw, 1), 50);
    res.json(await runPython(["buy_audit", String(limit)]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

export default router;
