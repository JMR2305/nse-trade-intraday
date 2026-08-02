import { Router } from "express";
import path from "path";
import { spawn } from "child_process";
import { PYTHON_BIN, PYTHON_DIR } from "../lib/python-env";

const router = Router();

function runPython(args: string[], timeoutMs = 90_000): Promise<unknown> {
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

// ── AI Decision Agent ─────────────────────────────────────────────────────────
router.get("/decision-layer/ai-decision/snapshot",        handle("agent_ai_decision_snapshot",      120_000));
router.get("/decision-layer/ai-decision/recommendations", handle("agent_ai_decision_recommendations", 120_000));
router.get("/decision-layer/ai-decision/status",          handle("agent_ai_decision_status",          30_000));

router.get("/decision-layer/ai-decision/symbol/:symbol", async (req: any, res: any) => {
  try {
    const symbol = req.params.symbol as string;
    res.json(await runPython(["agent_ai_decision_symbol", symbol], 90_000));
  } catch (e: any) { res.status(500).json({ error: e.message }); }
});

// ── Execution Agent ───────────────────────────────────────────────────────────
router.get("/decision-layer/execution/snapshot", handle("agent_execution_snapshot", 180_000));
router.get("/decision-layer/execution/queue",    handle("agent_execution_queue",     180_000));
router.get("/decision-layer/execution/status",   handle("agent_execution_status",     30_000));

router.get("/decision-layer/execution/plan/:symbol", async (req: any, res: any) => {
  try {
    const symbol = req.params.symbol as string;
    res.json(await runPython(["agent_execution_plan", symbol], 120_000));
  } catch (e: any) { res.status(500).json({ error: e.message }); }
});

// ── Aggregate ─────────────────────────────────────────────────────────────────
router.get("/decision-layer/summary",     handle("agent_decision_summary",     180_000));
router.get("/decision-layer/timeline",    handle("agent_decision_timeline",     180_000));
router.get("/decision-layer/performance", handle("agent_decision_performance",   60_000));

export { router as decisionLayerRouter };
export default router;
