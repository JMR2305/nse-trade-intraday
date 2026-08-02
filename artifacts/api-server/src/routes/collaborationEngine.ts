/**
 * collaborationEngine.ts — Phase 10E
 * Collaborative Intelligence Layer API routes.
 *
 * READ-ONLY · ADVISORY-ONLY
 */
import { Router } from "express";
import path from "path";
import { spawn } from "child_process";
import { PYTHON_BIN, PYTHON_DIR } from "../lib/python-env";

export const collaborationEngineRouter = Router();

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
      if (code !== 0) return reject(new Error(stderr.slice(-500) || `Exit ${code}`));
      try { resolve(JSON.parse(stdout)); }
      catch { reject(new Error(`Bad JSON: ${stdout.slice(0, 200)}`)); }
    });
  });
}

const run = (cmd: string) => runPython([cmd]);

// Full collaboration snapshot
collaborationEngineRouter.get("/collab/snapshot", async (_req, res) => {
  try {
    res.json(await run("agent_collab_snapshot"));
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

// Agent collaboration graph (nodes + edges)
collaborationEngineRouter.get("/collab/graph", async (_req, res) => {
  try {
    res.json(await run("agent_collab_graph"));
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

// Decision lineage (end-to-end traceability)
collaborationEngineRouter.get("/collab/lineage", async (_req, res) => {
  try {
    res.json(await run("agent_collab_lineage"));
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

// Advisory collaboration alerts
collaborationEngineRouter.get("/collab/alerts", async (_req, res) => {
  try {
    res.json(await run("agent_collab_alerts"));
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

// Collaboration health summary
collaborationEngineRouter.get("/collab/health", async (_req, res) => {
  try {
    res.json(await run("agent_collab_health"));
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

// Agent communication monitor
collaborationEngineRouter.get("/collab/comm-monitor", async (_req, res) => {
  try {
    res.json(await run("agent_collab_comm_monitor"));
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

// Dependency report
collaborationEngineRouter.get("/collab/dependencies", async (_req, res) => {
  try {
    res.json(await run("agent_collab_dependencies"));
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

// Collaboration layer summary (for Command Centre)
collaborationEngineRouter.get("/collab/summary", async (_req, res) => {
  try {
    res.json(await run("agent_collab_summary"));
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

// Collaboration timeline (Phase-9-compatible)
collaborationEngineRouter.get("/collab/timeline", async (_req, res) => {
  try {
    res.json(await run("agent_collab_timeline"));
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

// Collaboration performance
collaborationEngineRouter.get("/collab/performance", async (_req, res) => {
  try {
    res.json(await run("agent_collab_performance"));
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});
