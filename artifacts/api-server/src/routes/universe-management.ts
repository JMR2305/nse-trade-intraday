/**
 * Versioned custom-universe management API.
 *
 * All endpoints are session-authenticated.  The API never accepts an admin
 * token from browser code and never exposes the legacy active-master write
 * controls.  Python owns the durable append-only workflow and returns the
 * structured evidence used by the operator UI.
 */
import { Router, type IRouter, type Request, type Response } from "express";
import { spawn } from "child_process";
import path from "path";
import { randomUUID } from "crypto";
import { PYTHON_BIN, PYTHON_DIR } from "../lib/python-env";
import { requireApiKey } from "../lib/auth";
import { invalidateCoverageCache } from "./trading";

const router: IRouter = Router();
const api = Router();
const VERSION = "v1";

type JsonRecord = Record<string, unknown>;

function runPython(args: string[], timeoutMs = 30_000): Promise<JsonRecord> {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], {
      cwd: PYTHON_DIR,
      env: process.env,
    });
    let stdout = "";
    let stderr = "";
    let settled = false;
    const timer = setTimeout(() => {
      settled = true;
      proc.kill("SIGTERM");
      reject(new Error(`Python timed out after ${timeoutMs / 1000}s`));
    }, timeoutMs);
    proc.stdout.on("data", (data: Buffer) => { stdout += data.toString(); });
    proc.stderr.on("data", (data: Buffer) => { stderr += data.toString(); });
    proc.on("error", (error) => {
      clearTimeout(timer);
      if (!settled) reject(error);
    });
    proc.on("close", (code) => {
      clearTimeout(timer);
      if (settled) return;
      if (code !== 0) {
        reject(new Error(stderr || `Python exited ${code}`));
        return;
      }
      // A few Python dependencies log before the command result.  The
      // dispatcher contract is the final JSON object, not arbitrary stdout.
      const lines = stdout.trim().split(/\r?\n/).filter(Boolean);
      for (let index = lines.length - 1; index >= 0; index -= 1) {
        try {
          const parsed: unknown = JSON.parse(lines[index]);
          if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
            resolve(parsed as JsonRecord);
            return;
          }
        } catch {
          // Keep looking for the final JSON line.
        }
      }
      reject(new Error(`Failed to parse Python response: ${stdout.slice(-240)}`));
    });
  });
}

function requestId(req: Request): string {
  const id = (req as Request & { id?: unknown }).id;
  return typeof id === "string" || typeof id === "number" ? String(id) : randomUUID();
}

function bodyRecord(req: Request): JsonRecord {
  return req.body && typeof req.body === "object" && !Array.isArray(req.body)
    ? req.body as JsonRecord
    : {};
}

function versionParam(req: Request): number | null {
  const value = Number(req.params.version);
  return Number.isInteger(value) && value > 0 ? value : null;
}

function failureStatus(result: JsonRecord): number {
  switch (result.error) {
    case "typed_confirmation_mismatch":
    case "member_validation_failed":
    case "invalid_normalized_symbol":
    case "operation must be add, remove, restore, or update":
      return 400;
    case "stale_revision":
    case "draft_only_edit":
    case "draft_only_activation":
    case "duplicate_symbol":
      return 409;
    case "activation_locked":
      return 423;
    case "revision_not_found":
    case "base_revision_not_found":
    case "symbol_not_found":
      return 404;
    case "db_unavailable":
      return 503;
    default:
      return 422;
  }
}

async function command(
  req: Request,
  res: Response,
  name: string,
  payload?: JsonRecord,
  timeoutMs = 30_000,
): Promise<void> {
  try {
    const result = await runPython(
      payload === undefined ? [name] : [name, JSON.stringify(payload)],
      timeoutMs,
    );
    res.setHeader("X-Universe-API-Version", VERSION);
    if (result.success === false) {
      res.status(failureStatus(result)).json({ api_version: VERSION, ...result });
      return;
    }
    res.json({ api_version: VERSION, ...result });
  } catch (error) {
    res.status(502).json({
      api_version: VERSION,
      success: false,
      error: error instanceof Error ? error.message : String(error),
    });
  }
}

function requireVersion(req: Request, res: Response): number | null {
  const version = versionParam(req);
  if (version === null) {
    res.status(400).json({
      api_version: VERSION,
      success: false,
      error: "version must be a positive integer",
    });
    return null;
  }
  return version;
}

api.get("/active", (req, res) => command(req, res, "universe_management_active"));
api.get("/revisions", (req, res) => command(req, res, "universe_management_revisions"));
api.get("/audit", (req, res) => {
  const raw = Number(req.query.limit ?? 200);
  const limit = Number.isInteger(raw) ? Math.max(1, Math.min(raw, 500)) : 200;
  return command(req, res, "universe_management_audit", { limit });
});

api.get("/revisions/:version", (req, res) => {
  const version = requireVersion(req, res);
  if (version === null) return;
  return command(req, res, "universe_management_revision", { version });
});

api.get("/revisions/:version/members", (req, res) => {
  const version = requireVersion(req, res);
  if (version === null) return;
  return command(req, res, "universe_management_revision", { version });
});

api.get("/revisions/:version/mapping-coverage", (req, res) => {
  const version = requireVersion(req, res);
  if (version === null) return;
  return command(req, res, "universe_management_mapping", { version });
});

api.get("/revisions/:leftVersion/diff/:rightVersion", (req, res) => {
  const leftVersion = Number(req.params.leftVersion);
  const rightVersion = Number(req.params.rightVersion);
  if (![leftVersion, rightVersion].every((value) => Number.isInteger(value) && value > 0)) {
    res.status(400).json({ api_version: VERSION, success: false, error: "versions must be positive integers" });
    return;
  }
  return command(req, res, "universe_management_diff", {
    left_version: leftVersion,
    right_version: rightVersion,
  });
});

api.get("/diff", (req, res) => {
  const leftVersion = Number(req.query.left_version ?? req.query.from_version);
  const rightVersion = Number(req.query.right_version ?? req.query.to_version);
  if (![leftVersion, rightVersion].every((value) => Number.isInteger(value) && value > 0)) {
    res.status(400).json({ api_version: VERSION, success: false, error: "left_version and right_version are required" });
    return;
  }
  return command(req, res, "universe_management_diff", {
    left_version: leftVersion,
    right_version: rightVersion,
  });
});

api.post("/drafts", (req, res) => {
  const body = bodyRecord(req);
  const base = body.base_version;
  if (base !== undefined && (!Number.isInteger(Number(base)) || Number(base) < 1)) {
    res.status(400).json({ api_version: VERSION, success: false, error: "base_version must be a positive integer" });
    return;
  }
  return command(req, res, "universe_management_draft", {
    actor: "authenticated_operator",
    correlation_id: requestId(req),
    base_version: base === undefined ? undefined : Number(base),
    notes: typeof body.notes === "string" ? body.notes.slice(0, 500) : undefined,
  });
});

api.post("/drafts/:version/members", (req, res) => {
  const version = requireVersion(req, res);
  if (version === null) return;
  const body = bodyRecord(req);
  const operation = body.operation ?? body.action;
  if (typeof operation !== "string") {
    res.status(400).json({ api_version: VERSION, success: false, error: "operation is required" });
    return;
  }
  return command(req, res, "universe_management_edit", {
    version,
    operation,
    symbol: typeof body.symbol === "string" ? body.symbol : undefined,
    member: body.member && typeof body.member === "object" && !Array.isArray(body.member)
      ? body.member
      : undefined,
    metadata: body.metadata && typeof body.metadata === "object" && !Array.isArray(body.metadata)
      ? body.metadata
      : undefined,
    expected_hash: typeof body.expected_hash === "string" ? body.expected_hash : undefined,
    actor: "authenticated_operator",
    correlation_id: requestId(req),
  });
});

api.post("/revisions/:version/validate", (req, res) => {
  const version = requireVersion(req, res);
  if (version === null) return;
  return command(req, res, "universe_management_validate", {
    version,
    actor: "authenticated_operator",
    correlation_id: requestId(req),
  }, 60_000);
});

function activationPayload(req: Request, version: number): JsonRecord {
  const body = bodyRecord(req);
  return {
    version,
    confirmation: typeof body.confirmation === "string" ? body.confirmation : "",
    actor: "authenticated_operator",
    correlation_id: requestId(req),
  };
}

api.post("/revisions/:version/activation-request", (req, res) => {
  const version = requireVersion(req, res);
  if (version === null) return;
  return command(req, res, "universe_management_activation_request", activationPayload(req, version), 60_000);
});
api.post("/revisions/:version/activate", (req, res) => {
  const version = requireVersion(req, res);
  if (version === null) return;
  return command(req, res, "universe_management_activate", activationPayload(req, version), 60_000)
    .then(() => {
      // A successful activation changes scanner_coverage's expected symbol
      // set. Drop both the cached value and any pre-activation in-flight read
      // so a late response cannot become the next coverage result.
      if (res.statusCode >= 200 && res.statusCode < 300) {
        invalidateCoverageCache();
      }
    });
});

// Reads and writes in this contract are all operator-only, including reads.
router.use("/universe/v1", requireApiKey, api);
// Keep a descriptive alias for non-browser clients while preserving exactly
// the same handler and authentication contract.
router.use("/universe-management/v1", requireApiKey, api);

export default router;