/**
 * Disabled-by-default advisory bot integration.
 *
 * GET  /api/advisory/status
 * POST /api/advisory/run-preview
 *
 * This is a read-only, fixture-only preview surface. It never loads
 * production data and has no Phase 20, broker, scheduler, or settings-write
 * integration.
 */
import { Router, type Response } from "express";
import { spawn } from "node:child_process";
import path from "node:path";
import { PYTHON_BIN, PYTHON_DIR } from "../lib/python-env";
import { readAdvisoryFlags } from "../lib/advisoryFlags";
import { requireApiKey } from "../lib/auth";

const router = Router();
const MANUAL_RUNNER = path.join(PYTHON_DIR, "advisory_bots", "manual_runner.py");
const PREVIEW_MIN_INTERVAL_MS = 15_000;

function unavailable(res: Response): void {
  res.status(404).json({
    status: "DISABLED",
    advisory_only: true,
    paper_only: true,
    error: "Advisory integration is unavailable.",
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isPreviewPayload(value: unknown): value is Record<string, unknown> {
  if (!isRecord(value)) return false;
  return (
    typeof value.scan_id === "string" &&
    value.scan_id.trim().length > 0 &&
    Array.isArray(value.universe_rows) &&
    Array.isArray(value.scan_items) &&
    isRecord(value.settings)
  );
}

export class AdvisoryPreviewGate {
  private inFlight = false;
  private nextAllowedAt = 0;

  tryEnter(now = Date.now()): { allowed: true } | { allowed: false; retryAfterMs: number } {
    if (this.inFlight) {
      return { allowed: false, retryAfterMs: PREVIEW_MIN_INTERVAL_MS };
    }
    if (now < this.nextAllowedAt) {
      return { allowed: false, retryAfterMs: this.nextAllowedAt - now };
    }
    this.inFlight = true;
    this.nextAllowedAt = now + PREVIEW_MIN_INTERVAL_MS;
    return { allowed: true };
  }

  release(): void {
    this.inFlight = false;
  }
}

const previewGate = new AdvisoryPreviewGate();

function runManualRunner(
  payload: Record<string, unknown>,
  persist: boolean,
): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const args = [MANUAL_RUNNER, "--stdin"];
    if (persist) args.push("--persist");
    const child = spawn(PYTHON_BIN, args, {
      cwd: PYTHON_DIR,
      env: process.env,
      stdio: ["pipe", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    let settled = false;
    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      if (!settled) {
        settled = true;
        reject(new Error("advisory preview timed out"));
      }
    }, 15_000);

    child.stdout.on("data", (chunk: Buffer) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk: Buffer) => {
      stderr += chunk.toString();
    });
    child.on("error", (error) => {
      clearTimeout(timer);
      if (!settled) {
        settled = true;
        reject(error);
      }
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      if (settled) return;
      settled = true;
      try {
        const result = JSON.parse(stdout);
        if (code !== 0) {
          reject(new Error(String((result as { error?: unknown }).error ?? stderr)));
          return;
        }
        resolve(result);
      } catch {
        reject(new Error(stderr || `Invalid advisory preview response (exit ${code})`));
      }
    });
    child.stdin.write(JSON.stringify(payload));
    child.stdin.end();
  });
}

// Preserve the disabled-state 404, but require an authenticated operator as
// soon as an environment explicitly enables the optional API surface.
router.use("/advisory", (req, res, next) => {
  if (!readAdvisoryFlags().advisoryApiEnabled) {
    unavailable(res);
    return;
  }
  requireApiKey(req, res, next);
});

router.get("/advisory/status", (_req, res) => {
  const flags = readAdvisoryFlags();
  res.json({
    status: flags.advisoryBotsEnabled ? "ENABLED" : "DISABLED",
    advisory_only: true,
    paper_only: true,
    manual_only: true,
    scheduler_hook: false,
    last_run_at: null,
    flags: {
      advisory_bots_enabled: flags.advisoryBotsEnabled,
      advisory_bots_api_enabled: flags.advisoryApiEnabled,
      advisory_bots_ui_enabled: flags.advisoryUiEnabled,
      advisory_bots_persist_enabled: flags.advisoryPersistEnabled,
      advisory_bots_scheduler_enabled: flags.advisorySchedulerEnabled,
    },
  });
});

router.post("/advisory/run-preview", async (req, res) => {
  const flags = readAdvisoryFlags();
  if (!flags.advisoryBotsEnabled) {
    unavailable(res);
    return;
  }
  if (!isPreviewPayload(req.body)) {
    res.status(400).json({
      status: "INVALID_REQUEST",
      advisory_only: true,
      paper_only: true,
      error: "scan_id, universe_rows, scan_items, and settings are required",
    });
    return;
  }

  const requestedPersistence = req.body.persist === true;
  if (requestedPersistence && (
    !flags.advisoryPersistEnabled || !flags.persistenceEnvironmentAllowed
  )) {
    res.status(403).json({
      status: "PERSISTENCE_DISABLED",
      advisory_only: true,
      paper_only: true,
      error: "Advisory persistence requires its flag in an explicitly attested development or test environment.",
    });
    return;
  }

  const payload = {
    scan_id: req.body.scan_id,
    universe_rows: req.body.universe_rows,
    scan_items: req.body.scan_items,
    settings: req.body.settings,
    market_context: req.body.market_context,
    risk_inputs: req.body.risk_inputs,
    build_id: req.body.build_id,
    config_hash: req.body.config_hash,
  };

  const gate = previewGate.tryEnter();
  if (!gate.allowed) {
    res.status(429).json({
      status: "PREVIEW_RATE_LIMITED",
      advisory_only: true,
      paper_only: true,
      error: "A manual advisory preview is already running or was started recently.",
      retry_after_ms: gate.retryAfterMs,
    });
    return;
  }
  try {
    res.json(await runManualRunner(payload, requestedPersistence));
  } catch (error) {
    res.status(502).json({
      status: "PREVIEW_FAILED",
      advisory_only: true,
      paper_only: true,
      error: error instanceof Error ? error.message : "Advisory preview failed",
    });
  } finally {
    previewGate.release();
  }
});

export default router;