/**
 * executive.ts — Phase 5D.5 Executive Dashboard API routes.
 *
 * 3 read-only endpoints:
 *   GET /api/executive/summary  — full dashboard (all sections + executive score)
 *   GET /api/executive/health   — system health only (fast)
 *   GET /api/executive/widgets  — all widget data without the executive score
 *
 * EXECUTIVE_DASHBOARD_ENABLED=false → every endpoint returns { "status": "DISABLED" }.
 * No order submission. No strategy modification. No portfolio mutation.
 * PAPER TRADING / ADVISORY ONLY.
 */
import { Router } from "express";
import { spawn } from "child_process";
import path from "path";
import { PYTHON_DIR, PYTHON_BIN } from "../lib/python-env";

const router = Router();

function runPython(args: string[]): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const child = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], {
      cwd: PYTHON_DIR,
      env: process.env,
    });
    let out = "";
    let err = "";
    child.stdout.on("data", (d: Buffer) => { out += d.toString(); });
    child.stderr.on("data", (d: Buffer) => { err += d.toString(); });
    child.on("error", (e: Error) => reject(e));
    child.on("close", (code) => {
      try {
        resolve(JSON.parse(out));
      } catch {
        reject(new Error(code !== 0 ? err || `exit ${code}` : `Bad JSON: ${out.slice(0, 200)}`));
      }
    });
  });
}

router.get("/executive/summary", async (req, res) => {
  try { res.json(await runPython(["executive_summary"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

router.get("/executive/health", async (req, res) => {
  try { res.json(await runPython(["executive_health"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

router.get("/executive/widgets", async (req, res) => {
  try { res.json(await runPython(["executive_widgets"])); }
  catch (e) { res.status(500).json({ error: String(e) }); }
});

export default router;
