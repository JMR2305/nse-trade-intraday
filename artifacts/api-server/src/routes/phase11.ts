/**
 * phase11.ts — Phase 11: Autonomous Paper Trading Platform Routes
 *
 * PAPER ONLY — NO LIVE ORDERS — NO REAL MONEY
 * All routes are advisory/display; execution is handled by Phase 20.
 */
import { Router } from "express";
import path from "path";
import { spawn } from "child_process";
import { PYTHON_DIR, PYTHON_BIN } from "../lib/python-env";

const router = Router();

// ── Inline Python runner (same pattern as phase12/13/…) ───────────────────────
function runPython(args: string[], timeoutMs = 90_000): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], {
      env: { ...process.env },
    });
    let stdout = "";
    let stderr = "";
    proc.stdout.on("data", (d: Buffer) => { stdout += d.toString(); });
    proc.stderr.on("data", (d: Buffer) => { stderr += d.toString(); });
    const timer = setTimeout(() => { proc.kill(); reject(new Error(`Python timeout after ${timeoutMs}ms`)); }, timeoutMs);
    proc.on("close", (code) => {
      clearTimeout(timer);
      if (code !== 0) return reject(new Error(stderr || `Python exited with code ${code}`));
      try {
        resolve(JSON.parse(stdout));
      } catch {
        reject(new Error(`JSON parse error: ${stdout.slice(0, 200)}`));
      }
    });
  });
}

const TIMEOUT_FAST   = 30_000;
const TIMEOUT_MEDIUM = 60_000;
const TIMEOUT_SLOW   = 90_000;

const handle = (cmd: string[], timeout = TIMEOUT_FAST) =>
  async (_req: any, res: any) => {
    try {
      res.json(await runPython(cmd, timeout));
    } catch (e: any) {
      res.status(500).json({ error: e.message });
    }
  };

// ── Capital Config ─────────────────────────────────────────────────────────
router.get("/capital/config", handle(["phase11_capital_config"], TIMEOUT_FAST));

router.put("/capital/config", async (req: any, res: any) => {
  try {
    const patch = JSON.stringify(req.body ?? {});
    res.json(await runPython(["phase11_capital_config_update", patch], TIMEOUT_FAST));
  } catch (e: any) {
    res.status(500).json({ error: e.message });
  }
});

router.get("/capital/topups", async (req: any, res: any) => {
  try {
    const limit = String(req.query.limit ?? "50");
    res.json(await runPython(["phase11_topup_log", JSON.stringify({ limit })], TIMEOUT_FAST));
  } catch (e: any) {
    res.status(500).json({ error: e.message });
  }
});

router.post("/capital/topup-check", handle(["phase11_topup_check"], TIMEOUT_FAST));

// ── Portfolio ──────────────────────────────────────────────────────────────
router.get("/portfolio",               handle(["phase11_portfolio"],        TIMEOUT_MEDIUM));
router.get("/portfolio/open-positions", handle(["phase11_open_positions"],   TIMEOUT_MEDIUM));

router.get("/portfolio/closed-positions", async (req: any, res: any) => {
  try {
    const limit = String(req.query.limit ?? "100");
    res.json(await runPython(["phase11_closed_positions", JSON.stringify({ limit })], TIMEOUT_MEDIUM));
  } catch (e: any) {
    res.status(500).json({ error: e.message });
  }
});

// ── Recommendation Queue ───────────────────────────────────────────────────
router.get("/recommendations", handle(["phase11_recommendation_queue"], TIMEOUT_SLOW));

// ── Timeline ───────────────────────────────────────────────────────────────
router.get("/timeline", async (req: any, res: any) => {
  try {
    const payload = JSON.stringify({ date: req.query.date ?? "", limit: req.query.limit ?? 200 });
    res.json(await runPython(["phase11_timeline", payload], TIMEOUT_MEDIUM));
  } catch (e: any) {
    res.status(500).json({ error: e.message });
  }
});

// ── Calendar ───────────────────────────────────────────────────────────────
router.get("/calendar", async (req: any, res: any) => {
  try {
    const payload = JSON.stringify({ year: req.query.year ?? "", month: req.query.month ?? "" });
    res.json(await runPython(["phase11_calendar", payload], TIMEOUT_MEDIUM));
  } catch (e: any) {
    res.status(500).json({ error: e.message });
  }
});

// GET /api/phase11/daily-summary?date=YYYY-MM-DD
router.get("/daily-summary", async (req: any, res: any) => {
  try {
    const payload = JSON.stringify({ date: req.query.date ?? "" });
    res.json(await runPython(["phase11_daily_summary", payload], TIMEOUT_SLOW));
  } catch (e: any) {
    res.status(500).json({ error: e.message });
  }
});

// ── Replay ─────────────────────────────────────────────────────────────────
router.get("/replay", async (req: any, res: any) => {
  try {
    const d = String(req.query.date ?? "");
    if (!d) return res.status(400).json({ error: "date parameter required (YYYY-MM-DD)" });
    const payload = JSON.stringify({ date: d });
    res.json(await runPython(["phase11_replay", payload], TIMEOUT_SLOW));
  } catch (e: any) {
    res.status(500).json({ error: e.message });
  }
});

// ── Reports ────────────────────────────────────────────────────────────────
router.get("/reports/daily", async (req: any, res: any) => {
  try {
    const payload = JSON.stringify({ date: req.query.date ?? "" });
    res.json(await runPython(["phase11_daily_report", payload], TIMEOUT_SLOW));
  } catch (e: any) {
    res.status(500).json({ error: e.message });
  }
});

router.get("/reports/weekly", async (req: any, res: any) => {
  try {
    const payload = JSON.stringify({ week_start: req.query.week_start ?? "" });
    res.json(await runPython(["phase11_weekly_report", payload], TIMEOUT_SLOW));
  } catch (e: any) {
    res.status(500).json({ error: e.message });
  }
});

router.get("/reports/monthly", async (req: any, res: any) => {
  try {
    const payload = JSON.stringify({ year: req.query.year ?? "", month: req.query.month ?? "" });
    res.json(await runPython(["phase11_monthly_report", payload], TIMEOUT_SLOW));
  } catch (e: any) {
    res.status(500).json({ error: e.message });
  }
});

// ── AI Performance ─────────────────────────────────────────────────────────
router.get("/ai-performance", handle(["phase11_ai_performance"], TIMEOUT_SLOW));

// ── Learning ───────────────────────────────────────────────────────────────
router.get("/learning", handle(["phase11_learning"], TIMEOUT_SLOW));

// ── Snapshot (Command Centre card) ────────────────────────────────────────
router.get("/snapshot", handle(["phase11_snapshot"], TIMEOUT_MEDIUM));

// ── Daily Session Management ───────────────────────────────────────────────
// GET  /phase11/session/status  — returns today's initialisation state
router.get("/session/status", handle(["daily_session_status"], TIMEOUT_FAST));

// POST /phase11/session/init    — force-initialise today's session
router.post("/session/init", async (req: any, res: any) => {
  try {
    const force = Boolean(req.body?.force ?? false);
    res.json(await runPython(["daily_session_init", JSON.stringify({ force })], TIMEOUT_MEDIUM));
  } catch (e: any) {
    res.status(500).json({ error: e.message });
  }
});

// POST /phase11/session/enable-autonomous  — enable auto paper entries
router.post("/session/enable-autonomous", handle(["daily_session_enable_autonomous"], TIMEOUT_FAST));

// POST /phase11/session/disable-autonomous — disable auto paper entries
router.post("/session/disable-autonomous", handle(["daily_session_disable_autonomous"], TIMEOUT_FAST));

// GET  /phase11/session/agents  — verify / warm-start all 11 agents
router.get("/session/agents", handle(["daily_session_verify_agents"], TIMEOUT_MEDIUM));

// ── Price Snapshots ────────────────────────────────────────────────────────
// POST /api/phase11/price-snapshots/record
// Record current_price for every open position (call this post-scan).
router.post("/price-snapshots/record", async (req: any, res: any) => {
  try {
    const scan_id = String(req.body?.scan_id ?? "");
    res.json(await runPython(
      ["phase11_record_price_snapshots", JSON.stringify({ scan_id })],
      TIMEOUT_FAST,
    ));
  } catch (e: any) {
    res.status(500).json({ error: e.message });
  }
});

// GET /api/phase11/price-history
// ?symbol=RELIANCE  → { symbol, prices[], timestamps[], count, as_of }
// (no param)        → { snapshots: { [symbol]: number[] }, as_of }
router.get("/price-history", async (req: any, res: any) => {
  try {
    const symbol = String(req.query.symbol ?? "");
    const limit  = Number(req.query.limit  ?? 50);
    res.json(await runPython(
      ["phase11_price_history", JSON.stringify({ symbol, limit })],
      TIMEOUT_FAST,
    ));
  } catch (e: any) {
    res.status(500).json({ error: e.message });
  }
});

export default router;
