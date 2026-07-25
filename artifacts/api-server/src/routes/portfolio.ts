/**
 * portfolio.ts — Live portfolio snapshot and health routes.
 *
 * Routes:
 *   GET /api/portfolio/snapshot  — equity, positions, P&L, drawdown
 *   GET /api/portfolio/health    — readiness / degraded status
 *
 * READ-ONLY. No state mutations here.
 */
import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import path from "path";

import { PYTHON_DIR, PYTHON_BIN } from "../lib/python-env";

const router: IRouter = Router();

function runPython(args: string[], timeoutMs = 30_000): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], {
      cwd: PYTHON_DIR,
    });
    let stdout = "";
    let stderr = "";
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      proc.kill("SIGTERM");
      reject(new Error(`Python timed out after ${timeoutMs / 1000}s`));
    }, timeoutMs);
    proc.stdout.on("data", (d: Buffer) => { stdout += d.toString(); });
    proc.stderr.on("data", (d: Buffer) => { stderr += d.toString(); });
    proc.on("close", (code) => {
      clearTimeout(timer);
      if (timedOut) return;
      if (code !== 0) {
        try {
          const parsed = JSON.parse(stdout.trim());
          if (parsed.error) return reject(new Error(parsed.error));
        } catch { /* ignore */ }
        reject(new Error(stderr || `Python exited with code ${code}`));
      } else {
        try {
          resolve(JSON.parse(stdout.trim()));
        } catch {
          reject(new Error(`Failed to parse Python output: ${stdout.slice(0, 200)}`));
        }
      }
    });
  });
}

const wrap = (fn: (req: any, res: any) => Promise<void>) =>
  (req: any, res: any) => {
    fn(req, res).catch((e: Error) =>
      res.status(500).json({ error: e.message })
    );
  };

/**
 * GET /api/portfolio/snapshot
 *
 * Returns current equity, buying power, open positions with unrealised P&L,
 * today's realised P&L, and drawdown from peak.
 */
router.get(
  "/portfolio/snapshot",
  wrap(async (_req, res) => {
    const data = await runPython(["portfolio_snapshot"]);
    res.json(data);
  }),
);

/**
 * GET /api/portfolio/health
 *
 * Returns portfolio readiness / health status.
 */
router.get(
  "/portfolio/health",
  wrap(async (_req, res) => {
    const data = await runPython(["portfolio_health"]);
    res.json(data);
  }),
);

export default router;
