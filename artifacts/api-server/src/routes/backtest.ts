/**
 * Phase 23 Parts 2/3 — Historical Backtest Engine + Investigation Center API.
 *
 * POST /api/backtest/run                 — create + launch a run (detached)
 * GET  /api/backtest/runs                — list runs
 * GET  /api/backtest/run/:id             — run status/config/progress/metrics
 * GET  /api/backtest/run/:id/portfolio   — isolated backtest portfolio
 * GET  /api/backtest/run/:id/trades      — backtest trade ledger
 * GET  /api/backtest/run/:id/missed      — missed-opportunity analysis
 * GET  /api/backtest/run/:id/validate    — replay ≡ pipeline validation
 * GET  /api/backtest/run/:id/decision/:symbol — full decision tree
 * GET  /api/backtest/candles             — cached candles (chart/replay)
 * GET  /api/backtest/cache               — candle cache stats
 *
 * Phase 23 Parts 4/5 (read-only over the canonical event store):
 * GET  /api/backtest/run/:id/replay      — synchronized replay bundle
 * GET  /api/backtest/run/:id/story/:tradeId — trade story timeline
 * GET  /api/backtest/run/:id/explain/:symbol — why BUY / why REJECT
 * GET  /api/backtest/run/:id/search?q=   — global search (trades + events)
 * GET  /api/backtest/run/:id/replay-verify — replay integrity verification
 *
 * Backtest events are served by the existing /api/pipeline/events with
 * mode=BACKTEST&run_id=... — one canonical event store for both modes.
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

router.post("/backtest/run", async (req, res) => {
  try {
    const b = req.body ?? {};
    const payload = {
      interval: String(b.interval || "1d"),
      start: String(b.start || ""),
      end: String(b.end || ""),
      capital: Number(b.capital) || 100000,
      symbols: Array.isArray(b.symbols) && b.symbols.length ? b.symbols : undefined,
      universe: b.universe || "configured",
    };
    res.json(await runPython(["backtest_start", JSON.stringify(payload)]));
  } catch (err) {
    fail(res, err);
  }
});

router.get("/backtest/runs", async (_req, res) => {
  try {
    res.json(await runPython(["backtest_runs", "{}"]));
  } catch (err) {
    fail(res, err);
  }
});

router.get("/backtest/run/:id", async (req, res) => {
  try {
    res.json(await runPython(["backtest_status", JSON.stringify({ run_id: req.params.id })]));
  } catch (err) {
    fail(res, err);
  }
});

router.get("/backtest/run/:id/portfolio", async (req, res) => {
  try {
    res.json(await runPython(["backtest_portfolio", JSON.stringify({ run_id: req.params.id })]));
  } catch (err) {
    fail(res, err);
  }
});

router.get("/backtest/run/:id/trades", async (req, res) => {
  try {
    res.json(await runPython(["backtest_trades", JSON.stringify({ run_id: req.params.id })]));
  } catch (err) {
    fail(res, err);
  }
});

router.get("/backtest/run/:id/missed", async (req, res) => {
  try {
    // stored on the run at completion — no recompute
    const run = (await runPython(["backtest_status", JSON.stringify({ run_id: req.params.id })])) as Record<string, unknown>;
    res.json({ run_id: req.params.id, missed: run?.missed ?? [] });
  } catch (err) {
    fail(res, err);
  }
});

router.get("/backtest/run/:id/validate", async (req, res) => {
  try {
    res.json(
      await runPython(
        ["backtest_validate", JSON.stringify({ run_id: req.params.id, sample: Number(req.query.sample) || 25 })],
        240_000,
      ),
    );
  } catch (err) {
    fail(res, err);
  }
});

router.get("/backtest/run/:id/decision/:symbol", async (req, res) => {
  try {
    res.json(
      await runPython([
        "backtest_decision_tree",
        JSON.stringify({ id: req.params.id, symbol: req.params.symbol, mode: "BACKTEST" }),
      ]),
    );
  } catch (err) {
    fail(res, err);
  }
});

router.get("/backtest/run/:id/replay", async (req, res) => {
  try {
    res.json(await runPython(["backtest_replay_bundle", JSON.stringify({ run_id: req.params.id })], 180_000));
  } catch (err) {
    fail(res, err);
  }
});

router.get("/backtest/run/:id/story/:tradeId", async (req, res) => {
  try {
    res.json(
      await runPython(["backtest_trade_story", JSON.stringify({ run_id: req.params.id, trade_id: req.params.tradeId })]),
    );
  } catch (err) {
    fail(res, err);
  }
});

router.get("/backtest/run/:id/explain/:symbol", async (req, res) => {
  try {
    res.json(
      await runPython([
        "backtest_explain",
        JSON.stringify({
          run_id: req.params.id,
          symbol: req.params.symbol,
          scan_id: req.query.scan_id ? String(req.query.scan_id) : undefined,
        }),
      ]),
    );
  } catch (err) {
    fail(res, err);
  }
});

router.get("/backtest/run/:id/search", async (req, res) => {
  try {
    res.json(
      await runPython(["backtest_search", JSON.stringify({ run_id: req.params.id, q: String(req.query.q || "") })]),
    );
  } catch (err) {
    fail(res, err);
  }
});

router.get("/backtest/run/:id/replay-verify", async (req, res) => {
  try {
    res.json(await runPython(["backtest_replay_verify", JSON.stringify({ run_id: req.params.id })], 180_000));
  } catch (err) {
    fail(res, err);
  }
});

router.get("/backtest/candles", async (req, res) => {
  try {
    res.json(
      await runPython([
        "backtest_candles",
        JSON.stringify({
          symbol: String(req.query.symbol || ""),
          interval: String(req.query.interval || "1d"),
          start: String(req.query.start || ""),
          end: String(req.query.end || ""),
        }),
      ]),
    );
  } catch (err) {
    fail(res, err);
  }
});

router.get("/backtest/cache", async (_req, res) => {
  try {
    res.json(await runPython(["backtest_cache_stats"]));
  } catch (err) {
    fail(res, err);
  }
});

export default router;
