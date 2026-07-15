/**
 * health.ts — Phase 11: liveness / readiness / details probes.
 * PAPER TRADING ONLY — research system.
 */
import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import path from "path";
import fs from "fs";
import { HealthCheckResponse } from "@workspace/api-zod";
import { getStreamStats } from "./stream";

const router: IRouter = Router();

const PYTHON_DIR = path.join(process.cwd(), "src", "python");
const STARTED_AT = Date.now();

function runPython(args: string[], timeoutMs = 20_000): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const proc = spawn("python3", [path.join(PYTHON_DIR, "main.py"), ...args], { cwd: PYTHON_DIR });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => { proc.kill("SIGKILL"); reject(new Error("timeout")); }, timeoutMs);
    proc.stdout.on("data", (d: Buffer) => { stdout += d.toString(); });
    proc.stderr.on("data", (d: Buffer) => { stderr += d.toString(); });
    proc.on("close", (code) => {
      clearTimeout(timer);
      if (code !== 0) reject(new Error(stderr || `exit ${code}`));
      else {
        try { resolve(JSON.parse(stdout.trim())); }
        catch { reject(new Error("bad json")); }
      }
    });
    proc.on("error", reject);
  });
}

router.get("/healthz", (_req, res) => {
  const data = HealthCheckResponse.parse({ status: "ok" });
  res.json(data);
});

// Liveness: process is up.
router.get("/health/live", (_req, res) => {
  res.json({ status: "ok", uptime_s: Math.round((Date.now() - STARTED_AT) / 1000) });
});

// Readiness: python runtime + scan cache file reachable.
router.get("/health/ready", async (_req, res) => {
  const checks: Record<string, boolean> = {
    python_runtime: false,
    scan_cache_readable: false,
  };
  try {
    const ms = (await runPython(["market_status"])) as Record<string, unknown>;
    checks["python_runtime"] = Boolean(ms && ms["state"]);
  } catch { /* stays false */ }
  try {
    fs.accessSync(path.join(PYTHON_DIR, "phase7_scan_cache.json"), fs.constants.R_OK);
    checks["scan_cache_readable"] = true;
  } catch { /* stays false */ }
  const ready = checks["python_runtime"] === true;
  res.status(ready ? 200 : 503).json({ status: ready ? "ready" : "not_ready", checks });
});

// Details: full observability payload (honest nulls on failure).
router.get("/health/details", async (_req, res) => {
  let live: unknown = null;
  let liveError: string | null = null;
  try { live = await runPython(["live_health_v2"], 30_000); }
  catch (err) { liveError = err instanceof Error ? err.message : String(err); }
  const mem = process.memoryUsage();
  res.json({
    status: liveError ? "degraded" : "ok",
    uptime_s: Math.round((Date.now() - STARTED_AT) / 1000),
    node_version: process.version,
    memory_rss_mb: Math.round(mem.rss / 1024 / 1024),
    stream: getStreamStats(),
    live_data: live,
    live_data_error: liveError,
    mode: "PAPER_TRADING_RESEARCH_ONLY",
  });
});

export default router;
