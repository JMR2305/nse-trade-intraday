/**
 * portfolio.ts — Live portfolio snapshot and health routes.
 *
 * Routes:
 *   GET   /api/portfolio/snapshot  — equity, positions, P&L, drawdown
 *   GET   /api/portfolio/health    — readiness / degraded status
 *   GET   /api/portfolio/config    — active PortfolioConfig snapshot (with operator overrides)
 *   PATCH /api/portfolio/config    — persist operator overrides to the durable
 *                                    Python-side store (survive restarts/hot-reloads)
 */
import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import path from "path";

import { PYTHON_DIR, PYTHON_BIN } from "../lib/python-env";

const router: IRouter = Router();

// ── Operator overrides ───────────────────────────────────────────────────────
// Overrides are persisted in the durable Python-side store (Postgres with a
// file fallback), so they survive Node hot-reloads and full server restarts
// until explicitly cleared via DELETE /api/portfolio/config/overrides. They
// overlay the environment-variable-based PortfolioConfig values without
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
): { error: string; field?: MutableField } | null {
  const get = (field: MutableField): number | undefined => {
    if (field in patch) return patch[field];
    return base[field] as number | undefined;
  };

  const minOv = get("min_order_value");
  const maxOv = get("max_order_value");
  if (minOv !== undefined && maxOv !== undefined && minOv >= maxOv)
    return { error: `min_order_value (${minOv}) must be less than max_order_value (${maxOv})` };

  const cashReserve = get("cash_reserve_pct");
  const portfolioExp = get("max_portfolio_exposure_pct");
  if (
    cashReserve !== undefined &&
    portfolioExp !== undefined &&
    cashReserve + portfolioExp > 1
  )
    return { error: `cash_reserve_pct + max_portfolio_exposure_pct must not exceed 1.0` };

  const portfolioExpPct = portfolioExp !== undefined
    ? portfolioExp
    : (base["max_portfolio_exposure_pct"] as number | undefined);

  const instrumentExp = get("max_instrument_exposure_pct");
  if (
    instrumentExp !== undefined &&
    portfolioExpPct !== undefined &&
    instrumentExp > portfolioExpPct
  ) {
    const limitStr = `${(portfolioExpPct * 100).toFixed(1)}%`;
    return {
      error: `Instrument limit (${(instrumentExp * 100).toFixed(1)}%) cannot exceed portfolio limit of ${limitStr}`,
      field: "max_instrument_exposure_pct",
    };
  }

  const sectorExp = get("max_sector_exposure_pct");
  if (
    sectorExp !== undefined &&
    portfolioExpPct !== undefined &&
    sectorExp > portfolioExpPct
  ) {
    const limitStr = `${(portfolioExpPct * 100).toFixed(1)}%`;
    return {
      error: `Sector limit (${(sectorExp * 100).toFixed(1)}%) cannot exceed portfolio limit of ${limitStr}`,
      field: "max_sector_exposure_pct",
    };
  }

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
 * Returns the active PortfolioConfig values, with any persisted operator
 * overrides merged on top.  The response includes:
 *   - `overrides`         — the current override values (durable store)
 *   - `overridden_fields` — list of field names that are currently overridden
 *
 * Overrides persist across server restarts until cleared via DELETE.
 */
router.get(
  "/portfolio/config",
  wrap(async (_req, res) => {
    const data = await runPython(["portfolio_config"]) as Record<string, unknown>;

    // The durable Python-side store is authoritative: Python merges it into
    // `config` and reports `overrides`/`overridden_fields`. No in-memory
    // overlay — memory can go stale relative to what strategies enforce.
    res.json(data);
  }),
);

/**
 * PATCH /api/portfolio/config
 *
 * Accepts a JSON body with a subset of mutable PortfolioConfig fields and
 * persists them as operator overrides in the durable store.  Only the fields
 * listed in MUTABLE_FIELDS are accepted; unknown or read-only fields are
 * rejected.
 *
 * Overrides are merged with existing ones and survive restarts; use
 * DELETE /api/portfolio/config/overrides to reset them all.
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
    let persistedOverrides: Record<string, number> = {};
    try {
      const cfgData = await runPython(["portfolio_config"]) as Record<string, unknown>;
      baseConfig = ((cfgData.config ?? {}) as Record<string, unknown>);
      persistedOverrides = ((cfgData.overrides ?? {}) as Record<string, number>);
    } catch {
      // If Python fails, validate against the patch alone; the durable
      // store re-validates the true merged state on write anyway.
      baseConfig = {};
    }

    // Build the proposed merged state
    const proposedMerge = { ...persistedOverrides, ...validated };
    const consistencyResult = validateConsistency(baseConfig, proposedMerge);
    if (consistencyResult) {
      res.status(422).json({
        error: consistencyResult.error,
        field_errors: consistencyResult.field
          ? { [consistencyResult.field]: consistencyResult.error }
          : {},
      });
      return;
    }

    // 4. Persist the overrides to the durable Python-side store so RUNNING
    // strategy/execution processes pick them up on their next decision
    // cycle (the Python layer re-validates the merged config and rejects
    // inconsistent combinations).
    let merged: Record<string, number>;
    try {
      const persisted = await runPython([
        "portfolio_overrides_set",
        JSON.stringify(validated),
      ]) as { overrides?: Record<string, number> };
      merged = persisted.overrides ?? { ...persistedOverrides, ...validated };
    } catch (e) {
      res.status(422).json({
        error: `Override rejected: ${(e as Error).message}`,
        field_errors: {},
      });
      return;
    }

    res.json({
      ok: true,
      overrides: merged,
      overridden_fields: Object.keys(merged),
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
  wrap(async (_req, res) => {
    // Clear the durable store; if this fails, wrap() reports the error
    // instead of falsely claiming the overrides are gone.
    await runPython(["portfolio_overrides_clear"]);
    res.json({ ok: true, overrides: {}, overridden_fields: [] });
  }),
);

export default router;
