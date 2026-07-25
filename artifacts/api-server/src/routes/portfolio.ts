/**
 * portfolio.ts — Live portfolio snapshot and health routes.
 *
 * Routes:
 *   GET   /api/portfolio/snapshot  — equity, positions, P&L, drawdown
 *   GET   /api/portfolio/health    — readiness / degraded status
 *   GET   /api/portfolio/config    — active PortfolioConfig snapshot (with session overrides)
 *   PATCH /api/portfolio/config    — write session-level overrides (reset on server restart)
 */
import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import path from "path";

import { PYTHON_DIR, PYTHON_BIN } from "../lib/python-env";

const router: IRouter = Router();

// ── Session-level overrides ─────────────────────────────────────────────────
// These are held in process memory and are reset when the server restarts.
// They overlay the environment-variable-based PortfolioConfig values without
// modifying the actual config or environment.

/** All field names that may be overridden by an operator at runtime. */
type MutableField =
  | "max_open_positions"
  | "max_pending_orders"
  | "max_daily_loss_pct"
  | "max_drawdown_pct"
  | "max_capital_per_strategy_pct"
  | "min_order_value"
  | "max_order_value"
  | "max_instrument_exposure_pct"
  | "max_sector_exposure_pct"
  | "max_strategy_exposure_pct"
  | "max_portfolio_exposure_pct"
  | "cash_reserve_pct"
  | "default_risk_per_trade_pct";

type FieldKind = "pct" | "int" | "money";

interface FieldDef {
  kind: FieldKind;
  min?: number;
  max?: number;
}

const MUTABLE_FIELDS: Record<MutableField, FieldDef> = {
  max_open_positions:           { kind: "int",   min: 1 },
  max_pending_orders:           { kind: "int",   min: 1 },
  max_daily_loss_pct:           { kind: "pct" },
  max_drawdown_pct:             { kind: "pct" },
  max_capital_per_strategy_pct: { kind: "pct" },
  min_order_value:              { kind: "money", min: 1 },
  max_order_value:              { kind: "money", min: 1 },
  max_instrument_exposure_pct:  { kind: "pct" },
  max_sector_exposure_pct:      { kind: "pct" },
  max_strategy_exposure_pct:    { kind: "pct" },
  max_portfolio_exposure_pct:   { kind: "pct" },
  cash_reserve_pct:             { kind: "pct" },
  default_risk_per_trade_pct:   { kind: "pct" },
};

const sessionOverrides: Partial<Record<MutableField, number>> = {};

/** Validate a single incoming field value. Returns an error string or null. */
function validateField(field: MutableField, raw: unknown): string | null {
  const def = MUTABLE_FIELDS[field];
  const num = Number(raw);
  if (!Number.isFinite(num)) return `${field}: must be a finite number`;
  if (def.kind === "pct") {
    if (num <= 0 || num > 1) return `${field}: must be in range (0, 1]`;
  } else if (def.kind === "int") {
    if (!Number.isInteger(num)) return `${field}: must be an integer`;
    if (def.min !== undefined && num < def.min)
      return `${field}: must be ≥ ${def.min}`;
  } else if (def.kind === "money") {
    if (num <= 0) return `${field}: must be positive`;
  }
  return null;
}

/** Cross-field consistency check applied after all individual fields pass. */
function validateConsistency(
  base: Record<string, unknown>,
  patch: Partial<Record<MutableField, number>>,
): string | null {
  const get = (field: MutableField): number | undefined => {
    if (field in patch) return patch[field];
    return base[field] as number | undefined;
  };

  const minOv = get("min_order_value");
  const maxOv = get("max_order_value");
  if (minOv !== undefined && maxOv !== undefined && minOv >= maxOv)
    return `min_order_value (${minOv}) must be less than max_order_value (${maxOv})`;

  const cashReserve = get("cash_reserve_pct");
  const portfolioExp = get("max_portfolio_exposure_pct");
  if (
    cashReserve !== undefined &&
    portfolioExp !== undefined &&
    cashReserve + portfolioExp > 1
  )
    return `cash_reserve_pct + max_portfolio_exposure_pct must not exceed 1.0`;

  return null;
}

// ── Python runner ────────────────────────────────────────────────────────────

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

// ── Routes ───────────────────────────────────────────────────────────────────

/**
 * GET /api/portfolio/snapshot
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
 */
router.get(
  "/portfolio/health",
  wrap(async (_req, res) => {
    const data = await runPython(["portfolio_health"]);
    res.json(data);
  }),
);

/**
 * GET /api/portfolio/config
 *
 * Returns the active PortfolioConfig values, with any session-level operator
 * overrides merged on top.  The response includes:
 *   - `overrides`         — the current session override values
 *   - `overridden_fields` — list of field names that are currently overridden
 *
 * Overrides are held in process memory and are cleared on server restart.
 */
router.get(
  "/portfolio/config",
  wrap(async (_req, res) => {
    const data = await runPython(["portfolio_config"]) as Record<string, unknown>;

    // Merge session overrides into the config snapshot
    const baseConfig = (data.config ?? {}) as Record<string, unknown>;
    const overriddenFields = Object.keys(sessionOverrides) as MutableField[];
    const mergedConfig = { ...baseConfig };
    for (const field of overriddenFields) {
      mergedConfig[field] = sessionOverrides[field];
    }

    res.json({
      ...data,
      config: mergedConfig,
      overrides: { ...sessionOverrides },
      overridden_fields: overriddenFields,
    });
  }),
);

/**
 * PATCH /api/portfolio/config
 *
 * Accepts a JSON body with a subset of mutable PortfolioConfig fields and
 * stores them as session-level overrides.  Only the fields listed in
 * MUTABLE_FIELDS are accepted; unknown or read-only fields are rejected.
 *
 * Overrides are merged with existing ones (send an empty object to clear
 * specific fields is not supported; restart the server to reset all overrides).
 *
 * Body: { [field: MutableField]: number }
 * Response: { ok: true, overrides: Record<MutableField, number>, overridden_fields: string[] }
 *         | { error: string, field_errors: Record<string, string> }
 */
router.patch(
  "/portfolio/config",
  wrap(async (req, res) => {
    const body = req.body as Record<string, unknown>;

    if (!body || typeof body !== "object" || Array.isArray(body)) {
      res.status(400).json({ error: "Request body must be a JSON object" });
      return;
    }

    const keys = Object.keys(body);
    if (keys.length === 0) {
      res.status(400).json({ error: "Request body must contain at least one field" });
      return;
    }

    // 1. Reject any unknown or immutable fields
    const unknownFields = keys.filter((k) => !(k in MUTABLE_FIELDS));
    if (unknownFields.length > 0) {
      res.status(400).json({
        error: `Unknown or read-only field(s): ${unknownFields.join(", ")}`,
        field_errors: Object.fromEntries(unknownFields.map((f) => [f, "not a mutable field"])),
      });
      return;
    }

    // 2. Validate each field individually
    const fieldErrors: Record<string, string> = {};
    const validated: Partial<Record<MutableField, number>> = {};

    for (const key of keys as MutableField[]) {
      const err = validateField(key, body[key]);
      if (err) {
        fieldErrors[key] = err;
      } else {
        validated[key] = Number(body[key]);
      }
    }

    if (Object.keys(fieldErrors).length > 0) {
      res.status(422).json({
        error: "Validation failed",
        field_errors: fieldErrors,
      });
      return;
    }

    // 3. Cross-field consistency check against the merged state
    // Fetch base config from Python to get current env values for fields not being overridden
    let baseConfig: Record<string, unknown> = {};
    try {
      const cfgData = await runPython(["portfolio_config"]) as Record<string, unknown>;
      baseConfig = ((cfgData.config ?? {}) as Record<string, unknown>);
    } catch {
      // If Python fails, use only the current overrides as base
      baseConfig = { ...sessionOverrides };
    }

    // Build the proposed merged state
    const proposedMerge = { ...sessionOverrides, ...validated };
    const consistencyError = validateConsistency(baseConfig, proposedMerge);
    if (consistencyError) {
      res.status(422).json({
        error: consistencyError,
        field_errors: {},
      });
      return;
    }

    // 4. Apply validated overrides
    for (const [k, v] of Object.entries(validated) as [MutableField, number][]) {
      sessionOverrides[k] = v;
    }

    const overriddenFields = Object.keys(sessionOverrides) as MutableField[];
    res.json({
      ok: true,
      overrides: { ...sessionOverrides },
      overridden_fields: overriddenFields,
      applied: Object.keys(validated),
    });
  }),
);

/**
 * DELETE /api/portfolio/config/overrides
 *
 * Clears all session-level overrides, restoring the env-var-based defaults.
 */
router.delete(
  "/portfolio/config/overrides",
  (_req, res) => {
    for (const key of Object.keys(sessionOverrides) as MutableField[]) {
      delete sessionOverrides[key];
    }
    res.json({ ok: true, overrides: {}, overridden_fields: [] });
  },
);

export default router;
