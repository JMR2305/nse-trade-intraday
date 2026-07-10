import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import path from "path";
import fs from "fs";

const router: IRouter = Router();

const PYTHON_DIR = path.join(process.cwd(), "src", "python");
const PYTHON_BIN = "python3";

function runPython(args: string[]): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], {
      cwd: PYTHON_DIR,
    });

    let stdout = "";
    let stderr = "";

    proc.stdout.on("data", (d: Buffer) => {
      stdout += d.toString();
    });
    proc.stderr.on("data", (d: Buffer) => {
      stderr += d.toString();
    });

    proc.on("close", (code) => {
      if (code !== 0) {
        try {
          const parsed = JSON.parse(stdout.trim());
          if (parsed.error) return reject(new Error(parsed.error));
        } catch {
          // ignore parse error
        }
        reject(new Error(stderr || `Python exited with code ${code}`));
      } else {
        try {
          resolve(JSON.parse(stdout.trim()));
        } catch {
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

// GET /api/trades
router.get("/trades", async (_req, res) => {
  try {
    const data = await runPython(["trades"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/run-scan
router.post("/run-scan", async (_req, res) => {
  try {
    const result = await runPython(["scan"]) as Record<string, unknown>;
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

// POST /api/watchlist
router.post("/watchlist", async (req, res) => {
  const { symbol } = req.body as { symbol?: string };
  if (!symbol) {
    res.status(400).json({ error: "symbol is required" });
    return;
  }
  try {
    const data = await runPython(["watchlist_add", symbol]);
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
router.post("/portfolio/reset", async (_req, res) => {
  try {
    const data = await runPython(["reset"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/opportunity-scan
router.get("/opportunity-scan", async (_req, res) => {
  try {
    const data = await runPython(["opportunity_scan"]);
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

// GET /api/strategies
router.get("/strategies", async (_req, res) => {
  try {
    const data = await runPython(["strategies"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

export default router;
