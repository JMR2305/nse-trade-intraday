import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import path from "path";
import { PYTHON_BIN, PYTHON_DIR } from "../lib/python-env";

const router: IRouter = Router();

const ACTIVE_REQUIRED_FIELDS = [
  "sector",
  "company_name",
  "yahoo_symbol",
  "kite_symbol",
  "price_min",
  "price_max",
  "ohlcv_available",
] as const;
const METADATA_HYDRATION_CONFIRMATION = "HYDRATE_INSTRUMENT_METADATA_ONLY";

function validateActiveRows(rows: unknown[]): string | null {
  for (const [index, candidate] of rows.entries()) {
    if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) {
      return `row ${index} must be an object`;
    }

    const row = candidate as Record<string, unknown>;
    if (row["is_active"] !== true) continue;

    const missing = ACTIVE_REQUIRED_FIELDS.filter((field) => {
      if (!(field in row) || row[field] === null || row[field] === undefined) {
        return true;
      }
      return typeof row[field] === "string" && row[field].trim() === "";
    });
    if (missing.length > 0) {
      const symbol = typeof row["symbol"] === "string" && row["symbol"].trim()
        ? ` for ${row["symbol"]}`
        : "";
      return `active row ${index}${symbol} must include non-null: ${missing.join(", ")}`;
    }
  }
  return null;
}

function runPython(args: string[], timeoutMs = 30_000): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], {
      cwd: PYTHON_DIR,
      env: process.env,
    });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      proc.kill("SIGTERM");
      reject(new Error(`Python timed out after ${timeoutMs / 1000}s`));
    }, timeoutMs);
    proc.stdout.on("data", (data: Buffer) => { stdout += data.toString(); });
    proc.stderr.on("data", (data: Buffer) => { stderr += data.toString(); });
    proc.on("error", (error) => { clearTimeout(timer); reject(error); });
    proc.on("close", (code) => {
      clearTimeout(timer);
      if (code !== 0) return reject(new Error(stderr || `Python exited ${code}`));
      try {
        resolve(JSON.parse(stdout.trim()));
      } catch {
        reject(new Error(`Failed to parse Python response: ${stdout.slice(-240)}`));
      }
    });
  });
}

const wrap = (handler: (req: any, res: any) => Promise<void>) =>
  async (req: any, res: any) => {
    try {
      await handler(req, res);
    } catch (error) {
      res.status(500).json({
        success: false,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  };

// Read-only/advisory universe management. Refresh only writes scanner metadata;
// it never calls a broker order API.
router.get("/universe/custom/status", wrap(async (_req, res) => {
  res.json(await runPython(["universe_custom_status"]));
}));

router.post("/universe/active", wrap(async (req, res) => {
  const active = req.body?.active_intraday_universe;
  if (active !== "NIFTY_50" && active !== "CUSTOM_LOW_PRICE_SECTOR") {
    res.status(400).json({ success: false, error: "Invalid universe mode" });
    return;
  }
  res.json(await runPython([
    "phase20_settings_update",
    JSON.stringify({ patch: { active_intraday_universe: active } }),
  ]));
}));

router.get("/universe/custom/symbols", wrap(async (_req, res) => {
  res.json(await runPython(["universe_custom_symbols"]));
}));

router.post("/universe/custom/refresh", wrap(async (_req, res) => {
  res.json(await runPython(["universe_custom_refresh"], 180_000));
}));

// Operator-approved direct upsert of the symbol row list.
// Accepts { rows: [...] } — idempotent ON CONFLICT DO UPDATE.
// Protected by UNIVERSE_ADMIN_TOKEN (x-admin-token header). Fail-closed: if
// the env var is unset the route is effectively disabled.
router.post("/universe/custom/upsert", wrap(async (req, res) => {
  const expectedToken = process.env.UNIVERSE_ADMIN_TOKEN;
  const providedToken = req.headers["x-admin-token"];
  if (!expectedToken || providedToken !== expectedToken) {
    res.status(403).json({ success: false, error: "Forbidden: valid x-admin-token header required" });
    return;
  }
  const rows = req.body?.rows;
  if (!Array.isArray(rows) || rows.length === 0) {
    res.status(400).json({ success: false, error: "rows must be a non-empty array" });
    return;
  }
  const validationError = validateActiveRows(rows);
  if (validationError) {
    res.status(400).json({ success: false, error: validationError });
    return;
  }
  res.json(await runPython([
    "universe_custom_upsert",
    JSON.stringify({ rows }),
  ]));
}));

// A metadata refresh is separate from the cache refresh and from membership
// maintenance. It is protected by the same admin credential as an upsert and
// requires an exact confirmation so current provenance is never overwritten
// implicitly.
router.post("/universe/custom/hydrate-instruments", wrap(async (req, res) => {
  const expectedToken = process.env.UNIVERSE_ADMIN_TOKEN;
  const providedToken = req.headers["x-admin-token"];
  if (!expectedToken || providedToken !== expectedToken) {
    res.status(403).json({ success: false, error: "Forbidden: valid x-admin-token header required" });
    return;
  }
  if (req.body?.confirmation !== METADATA_HYDRATION_CONFIRMATION) {
    res.status(400).json({
      success: false,
      error: `confirmation must equal ${METADATA_HYDRATION_CONFIRMATION}`,
    });
    return;
  }
  res.json(await runPython([
    "universe_custom_hydrate_instruments",
    "--approve-metadata-only-hydration",
  ], 60_000));
}));

router.get("/universe/custom/report", wrap(async (_req, res) => {
  res.json(await runPython(["universe_custom_report"]));
}));

export default router;