/**
 * live-validation.ts — Phase 26B: Live Validation & Consistency API
 *
 * Read-only validation over canonical stores. During market hours the
 * phase20 scheduler generates a liveness snapshot every 5 minutes; these
 * routes expose snapshots, cross-page consistency runs, and the
 * deduplicated issue store.
 *
 * Routes:
 *   POST /live-validation/run          — run a liveness+consistency cycle now
 *   GET  /live-validation/summary      — latest snapshot + history + open issues
 *   GET  /live-validation/history      — recent snapshot summaries (?limit=)
 *   POST /live-validation/consistency  — run the cross-page consistency check
 *   GET  /live-validation/issues       — issue store (?status=&category=&limit=)
 *   POST /live-validation/issues/resolve — manually resolve one issue
 */

import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import path from "path";
import { PYTHON_DIR, PYTHON_BIN } from "../lib/python-env";

const router: IRouter = Router();

function runPython(args: string[], timeoutMs = 90_000): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], {
      cwd: PYTHON_DIR,
    });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      proc.kill("SIGTERM");
      reject(new Error(`Live validation Python timed out (${args[0] ?? "?"})`));
    }, timeoutMs);
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

// POST /api/live-validation/run — run one liveness + consistency cycle now
router.post("/live-validation/run", async (_req, res) => {
  try {
    res.json(await runPython(["live_validation_run"]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/live-validation/summary
router.get("/live-validation/summary", async (req, res) => {
  try {
    const limit = Math.max(1, Math.min(Number(req.query.limit) || 20, 200));
    res.json(await runPython(["live_validation_summary", JSON.stringify({ limit })]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/live-validation/history
router.get("/live-validation/history", async (req, res) => {
  try {
    const limit = Math.max(1, Math.min(Number(req.query.limit) || 50, 500));
    res.json(await runPython(["live_validation_history", JSON.stringify({ limit })]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/live-validation/consistency — cross-page consistency check
router.post("/live-validation/consistency", async (_req, res) => {
  try {
    res.json(await runPython(["consistency_run"]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/live-validation/issues?status=OPEN&category=SUBSYSTEM&limit=200
router.get("/live-validation/issues", async (req, res) => {
  try {
    const payload: Record<string, unknown> = {
      limit: Math.max(1, Math.min(Number(req.query.limit) || 200, 1000)),
    };
    if (req.query.status) payload.status = String(req.query.status);
    if (req.query.category) payload.category = String(req.query.category);
    res.json(await runPython(["issues_list", JSON.stringify(payload)]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/live-validation/issues/resolve — { category, key }
router.post("/live-validation/issues/resolve", async (req, res) => {
  try {
    const category = String(req.body?.category || "");
    const key = String(req.body?.key || "");
    if (!category || !key) {
      res.status(400).json({ error: "category and key are required" });
      return;
    }
    res.json(await runPython(["issue_resolve", JSON.stringify({ category, key })]));
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

export default router;
