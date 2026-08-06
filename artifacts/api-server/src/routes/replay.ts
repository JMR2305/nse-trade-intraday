/**
 * replay.ts — Feature 11-16: Operations Centre Replay Mode API
 *
 * Routes:
 *   GET  /replay/sessions                    — list available scan sessions
 *   GET  /replay/sessions/:scanId            — full pipeline replay for a scan
 *   GET  /replay/sessions/:scanId/symbol/:symbol — per-symbol journey + thinking
 *   GET  /replay/sessions/:scanId/comparison — AI decisions vs actual outcomes
 *   GET  /replay/sessions/:scanId/summary    — executive replay summary
 */

import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import path from "path";
import { PYTHON_DIR, PYTHON_BIN } from "../lib/python-env";

const router: IRouter = Router();

function runPython(args: string[]): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], {
      cwd: PYTHON_DIR,
    });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      proc.kill("SIGTERM");
      reject(new Error(`Replay Python timed out (${args[0] ?? "?"})`));
    }, 30_000);
    proc.stdout.on("data", (d: Buffer) => { stdout += d.toString(); });
    proc.stderr.on("data", (d: Buffer) => { stderr += d.toString(); });
    proc.on("close", (code) => {
      clearTimeout(timer);
      if (code !== 0) {
        try {
          const p = JSON.parse(stdout.trim());
          if (p.error) return reject(new Error(p.error));
        } catch { /* ignore */ }
        reject(new Error(stderr || `Python exited ${code}`));
      } else {
        try { resolve(JSON.parse(stdout.trim())); }
        catch { reject(new Error(`Bad JSON: ${stdout.slice(0, 200)}`)); }
      }
    });
    proc.on("error", reject);
  });
}

// GET /api/replay/sessions
router.get("/replay/sessions", async (_req, res) => {
  try {
    res.json(await runPython(["replay_sessions"]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/replay/sessions/:scanId — full pipeline replay
router.get("/replay/sessions/:scanId", async (req, res) => {
  try {
    const scanId = String(req.params.scanId || "latest");
    res.json(await runPython(["replay_build", scanId]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/replay/sessions/:scanId/symbol/:symbol
router.get("/replay/sessions/:scanId/symbol/:symbol", async (req, res) => {
  try {
    const scanId = String(req.params.scanId || "latest");
    const symbol = String(req.params.symbol || "").toUpperCase();
    res.json(await runPython(["replay_symbol", scanId, symbol]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/replay/sessions/:scanId/comparison — Feature 14
router.get("/replay/sessions/:scanId/comparison", async (req, res) => {
  try {
    const scanId = String(req.params.scanId || "latest");
    res.json(await runPython(["replay_comparison", scanId]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/replay/sessions/:scanId/summary — Feature 16
router.get("/replay/sessions/:scanId/summary", async (req, res) => {
  try {
    const scanId = String(req.params.scanId || "latest");
    res.json(await runPython(["replay_summary", scanId]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

export default router;
