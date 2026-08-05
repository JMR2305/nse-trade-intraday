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

// ── Agent registry (slow ~5-8 s — canonical ops_centre backend) ──────────────
// get_agent_list_canonical() calls all 12 agent snapshot functions in parallel.
// Without coalescing, every tab on Agent Operations spawns its own subprocess.
// 30 s Node.js cache + in-flight coalescing keeps it snappy after warm-up.
const AGENTS_LIST_TTL = 30_000;
let agentsListCache:    { data: unknown; ts: number } | null = null;
let agentsListInFlight: Promise<unknown> | null = null;

router.get("/agent-framework/agents", async (_req: any, res: any) => {
  try {
    if (agentsListCache && Date.now() - agentsListCache.ts < AGENTS_LIST_TTL) {
      res.json(agentsListCache.data);
      return;
    }
    if (!agentsListInFlight) {
      agentsListInFlight = runPython(["agent_list"], 30_000)
        .then((d) => { agentsListCache = { data: d, ts: Date.now() }; return d; })
        .finally(() => { agentsListInFlight = null; });
    }
    res.json(await agentsListInFlight);
  } catch (e: any) {
    res.status(500).json({ error: e.message });
  }
});

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
router.get("/agent-framework/market-data/status",   handle("agent_market_data_status",   30_000));

// ── Research Agent ────────────────────────────────────────────────────────────
router.get("/agent-framework/research/snapshot", handle("agent_research_snapshot", 60_000));
router.get("/agent-framework/research/metrics",  handle("agent_research_metrics",  30_000));
router.get("/agent-framework/research/status",   handle("agent_research_status",   30_000));

// ── Monitoring Agent ──────────────────────────────────────────────────────────
router.get("/agent-framework/monitoring/snapshot", handle("agent_monitoring_snapshot", 60_000));
router.get("/agent-framework/monitoring/status",   handle("agent_monitoring_status",   30_000));

export { router as agentFrameworkRouter };
export default router;
