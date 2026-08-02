import { Router } from "express";
import path from "path";
import { spawn } from "child_process";
import { PYTHON_BIN, PYTHON_DIR } from "../lib/python-env";

const router = Router();

function runPython(args: string[], timeoutMs = 60_000): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], {
      cwd: PYTHON_DIR,
      env: { ...process.env },
    });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      proc.kill("SIGTERM");
      reject(new Error(`Python timeout after ${timeoutMs}ms`));
    }, timeoutMs);
    proc.stdout.on("data", (d: Buffer) => { stdout += d.toString(); });
    proc.stderr.on("data", (d: Buffer) => { stderr += d.toString(); });
    proc.on("close", (code) => {
      clearTimeout(timer);
      try { resolve(JSON.parse(stdout)); }
      catch { reject(new Error(code !== 0 ? (stderr || stdout) : "Invalid JSON from Python")); }
    });
  });
}

const handle = (cmd: string, timeout?: number) =>
  async (_req: any, res: any) => {
    try { res.json(await runPython([cmd], timeout)); }
    catch (e: any) { res.status(500).json({ error: e.message }); }
  };

// ── Market Intelligence Agent ─────────────────────────────────────────────────
router.get("/analysis-agents/market-intelligence/snapshot", handle("agent_market_intelligence_snapshot", 60_000));
router.get("/analysis-agents/market-intelligence/status",   handle("agent_market_intelligence_status",   30_000));

// ── Stock Monitoring Agent ────────────────────────────────────────────────────
router.get("/analysis-agents/stock-monitoring/snapshot", handle("agent_stock_monitoring_snapshot", 60_000));
router.get("/analysis-agents/stock-monitoring/events",   handle("agent_stock_monitoring_events",   30_000));
router.get("/analysis-agents/stock-monitoring/priority", handle("agent_stock_monitoring_priority",  30_000));

// ── Strategy Agent ────────────────────────────────────────────────────────────
router.get("/analysis-agents/strategy/snapshot", handle("agent_strategy_snapshot", 90_000));

router.get("/analysis-agents/strategy/symbol/:symbol", async (req: any, res: any) => {
  try {
    const symbol = req.params.symbol as string;
    res.json(await runPython(["agent_strategy_symbol", symbol], 60_000));
  } catch (e: any) { res.status(500).json({ error: e.message }); }
});

// ── Risk Agent ────────────────────────────────────────────────────────────────
router.get("/analysis-agents/risk/snapshot", handle("agent_risk_snapshot", 60_000));
router.get("/analysis-agents/risk/detail",   handle("agent_risk_detail",   30_000));

// ── Aggregate / Timeline / Performance ───────────────────────────────────────
router.get("/analysis-agents/summary",     handle("agent_analysis_summary",     90_000));
router.get("/analysis-agents/timeline",    handle("agent_analysis_timeline",     60_000));
router.get("/analysis-agents/performance", handle("agent_analysis_performance",  30_000));

export { router as analysisAgentsRouter };
export default router;
