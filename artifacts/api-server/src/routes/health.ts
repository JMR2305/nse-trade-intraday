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
import { runtimeIdentity } from "../lib/runtimeIdentity";

const router: IRouter = Router();

import { PYTHON_DIR, PYTHON_BIN } from "../lib/python-env";
const STARTED_AT = Date.now();

function runPython(args: string[], timeoutMs = 20_000): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], { cwd: PYTHON_DIR });
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

// Readiness: python runtime + scan cache file reachable + portfolio config loaded.
router.get("/health/ready", async (_req, res) => {
  const checks: Record<string, boolean> = {
    python_runtime: false,
    scan_cache_readable: false,
    portfolio_config_loaded: false,
  };
  const warnings: string[] = [];
  try {
    const ms = (await runPython(["market_status"])) as Record<string, unknown>;
    checks["python_runtime"] = Boolean(ms && ms["state"]);
  } catch { /* stays false */ }
  try {
    fs.accessSync(path.join(PYTHON_DIR, "phase7_scan_cache.json"), fs.constants.R_OK);
    checks["scan_cache_readable"] = true;
  } catch { /* stays false */ }
  // Portfolio config: a load failure silently reverts risk limits to
  // hardcoded defaults — surface it as an explicit warning, never silently.
  try {
    const cfg = (await runPython(["portfolio_config"])) as Record<string, unknown>;
    checks["portfolio_config_loaded"] = cfg?.["loaded"] === true;
    if (cfg?.["loaded"] !== true) {
      warnings.push(
        `Portfolio config failed to load (${String(cfg?.["error"] ?? "unknown error")}) — ` +
        "risk limits are falling back to hardcoded defaults; operator-saved limits are NOT active."
      );
    }
  } catch (err) {
    warnings.push(
      `Portfolio config check failed (${err instanceof Error ? err.message : String(err)}) — ` +
      "risk limits may be falling back to hardcoded defaults."
    );
  }
  // Market-hours scanner coverage: a weekend data gap (e.g. 48/50) must
  // self-resolve at Monday open — flag loudly if it does NOT.
  try {
    const cov = (await runPython(["scanner_coverage"])) as Record<string, unknown>;
    checks["scanner_coverage_ok"] = cov?.["ok"] !== false;
    if (cov?.["ok"] === false && cov?.["warning"]) {
      warnings.push(String(cov["warning"]));
    }
  } catch (err) {
    // Probe failure is not a readiness blocker, but never fail silently.
    checks["scanner_coverage_ok"] = false;
    warnings.push(
      `Scanner coverage probe failed (${err instanceof Error ? err.message : String(err)}).`
    );
  }
  const ready = checks["python_runtime"] === true;
  res.status(ready ? 200 : 503).json({
    status: ready ? "ready" : "not_ready",
    checks,
    ...(warnings.length > 0 ? { warnings } : {}),
  });
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
    runtime_identity: runtimeIdentity(),
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
