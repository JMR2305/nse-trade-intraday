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
      if (code !== 0) {
        try { resolve(JSON.parse(stdout)); } catch { reject(new Error(stderr || stdout)); }
      } else {
        try { resolve(JSON.parse(stdout)); } catch { reject(new Error("Invalid JSON from Python")); }
      }
    });
  });
}

const handle = (cmd: string, timeout?: number) =>
  async (_req: any, res: any) => {
    try {
      res.json(await runPython([cmd], timeout));
    } catch (e: any) {
      res.status(500).json({ error: e.message });
    }
  };

// ── Supervisor ────────────────────────────────────────────────────────────────
router.get("/agent-framework/supervisor/snapshot", handle("agent_supervisor_snapshot", 60_000));
router.get("/agent-framework/supervisor/alerts",   handle("agent_supervisor_alerts",   30_000));
router.get("/agent-framework/scalability",         handle("agent_scalability",         30_000));

// ── Agent registry ────────────────────────────────────────────────────────────
router.get("/agent-framework/agents", handle("agent_list", 30_000));

router.get("/agent-framework/agents/:agentId", async (req: any, res: any) => {
  try {
    const agentId = req.params.agentId as string;
    res.json(await runPython(["agent_detail", agentId], 30_000));
  } catch (e: any) {
    res.status(500).json({ error: e.message });
  }
});

// ── Market Data Agent ─────────────────────────────────────────────────────────
router.get("/agent-framework/market-data/snapshot", handle("agent_market_data_snapshot", 60_000));
router.get("/agent-framework/market-data/metrics",  handle("agent_market_data_metrics",  30_000));

// ── Research Agent ────────────────────────────────────────────────────────────
router.get("/agent-framework/research/snapshot", handle("agent_research_snapshot", 60_000));
router.get("/agent-framework/research/metrics",  handle("agent_research_metrics",  30_000));

export { router as agentFrameworkRouter };
export default router;
