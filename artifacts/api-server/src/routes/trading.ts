import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import path from "path";

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
    } = req.body as {
      selection_date: string;
      holding_period?: number;
      num_stocks?: number;
      quantity?: number;
      method?: string;
    };

    if (!selection_date || !/^\d{4}-\d{2}-\d{2}$/.test(selection_date)) {
      res.status(400).json({ error: "selection_date is required in YYYY-MM-DD format" });
      return;
    }

    const cacheKey = `${selection_date}|${holding_period}|${num_stocks}|${quantity}|${method}`;
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
