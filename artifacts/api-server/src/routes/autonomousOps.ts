/**
 * autonomousOps.ts — Phase 10E
 * Autonomous Operations Layer API routes.
 *
 * READ-ONLY · ADVISORY-ONLY
 */
import { Router } from "express";
import path from "path";
import { spawn } from "child_process";
import { PYTHON_BIN, PYTHON_DIR } from "../lib/python-env";

export const autonomousOpsRouter = Router();

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

// Full autonomous operations snapshot
autonomousOpsRouter.get("/autonomous-ops/snapshot", async (_req, res) => {
  try {
    res.json(await run("agent_autonomous_ops_snapshot"));
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

// 8-component system health score
autonomousOpsRouter.get("/autonomous-ops/system-health", async (_req, res) => {
  try {
    res.json(await run("agent_system_health"));
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

// Scalability and capacity dashboard
autonomousOpsRouter.get("/autonomous-ops/scalability", async (_req, res) => {
  try {
    res.json(await run("agent_scalability_dashboard"));
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

// Extended supervisor (dependency validation, restart recs, etc.)
autonomousOpsRouter.get("/autonomous-ops/supervisor-extended", async (_req, res) => {
  try {
    res.json(await run("agent_supervisor_extended"));
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

// Capacity forecast (advisory)
autonomousOpsRouter.get("/autonomous-ops/capacity", async (_req, res) => {
  try {
    res.json(await run("agent_capacity_forecast"));
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});
