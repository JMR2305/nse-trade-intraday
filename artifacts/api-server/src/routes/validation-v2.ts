/**
 * validation-v2.ts — AI Validation Platform V2 Routes
 *
 * PAPER TRADING / RESEARCH ONLY — never places live orders.
 * Advisory only — never modifies production parameters automatically.
 *
 * Routes:
 *   POST  /validation-v2/backtest/run
 *   GET   /validation-v2/backtest/:runId
 *   GET   /validation-v2/backtest
 *   GET   /validation-v2/missed-opportunities
 *   POST  /validation-v2/optimizer/run
 *   GET   /validation-v2/optimizer/recommendation
 *   POST  /validation-v2/model-comparison
 *   GET   /validation-v2/performance
 *   GET   /validation-v2/session-timeline/:runId
 */

import { Router } from "express";
import { spawn, SpawnOptions } from "child_process";
import { PYTHON_DIR, PYTHON_BIN } from "../lib/python-env";

const router = Router();

/** Spawn Python and collect stdout as JSON. */
function runPython(args: string[], timeoutMs = 120_000): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const child = spawn(PYTHON_BIN, ["-u", "main.py", ...args], {
      cwd: PYTHON_DIR,
      env: { ...process.env },
    });

    let out = "";
    let err = "";
    child.stdout.on("data", (d: Buffer) => { out += d.toString(); });
    child.stderr.on("data", (d: Buffer) => { err += d.toString(); });

    const timer = setTimeout(() => {
      child.kill();
      reject(new Error(`Python timeout after ${timeoutMs}ms`));
    }, timeoutMs);

    child.on("close", (code) => {
      clearTimeout(timer);
      const raw = out.trim();
      if (!raw) {
        reject(new Error(`No output from Python (exit ${code}): ${err.slice(0, 300)}`));
        return;
      }
      // Find last complete JSON object/array in output
      const lastBrace = Math.max(raw.lastIndexOf("}"), raw.lastIndexOf("]"));
      const jsonStr = lastBrace >= 0 ? raw.slice(0, lastBrace + 1) : raw;
      try {
        resolve(JSON.parse(jsonStr));
      } catch {
        reject(new Error(`JSON parse error: ${jsonStr.slice(0, 200)}`));
      }
    });

    child.on("error", (e) => { clearTimeout(timer); reject(e); });
  });
}

const ADVISORY_HEADER = {
  "X-Advisory-Only": "true",
  "X-Paper-Trading": "true",
};

// ── Input validation constants ─────────────────────────────────────────────
const MAX_SYMBOLS = 20;
const MAX_GRID_COMBOS = 200;
const MAX_DATE_SPAN_DAYS = 730;   // 2 years

/** Defaults mirror Python's _DEFAULT_GRID. */
const GRID_DEFAULTS: Record<string, number[]> = {
  confidence_threshold: [55, 60, 65, 70],
  stop_pct:             [1.5, 2.0, 2.5],
  target_pct:           [3.0, 4.0, 5.0],
  position_size_pct:    [10, 15],
  min_rr:               [1.5, 2.0],
};

/**
 * Count the ACTUAL Cartesian product: for any dimension not in the supplied
 * grid, use the default length.  A supplied dimension must be a non-empty
 * array, otherwise returns -1 (invalid).
 */
function countActualGridCombos(grid: Record<string, unknown>): number {
  let product = 1;
  for (const [key, defaultVals] of Object.entries(GRID_DEFAULTS)) {
    const supplied = grid[key];
    if (supplied === undefined) {
      product *= defaultVals.length;
    } else if (Array.isArray(supplied) && supplied.length > 0) {
      product *= supplied.length;
    } else {
      return -1; // invalid dimension value
    }
  }
  return product;
}

/**
 * Parse and validate a date string. Returns null on invalid.
 */
function parseDate(s: unknown): Date | null {
  if (typeof s !== "string" || !/^\d{4}-\d{2}-\d{2}/.test(s)) return null;
  const d = new Date(s);
  return isNaN(d.getTime()) ? null : d;
}

/**
 * Validate (and, for backtest/comparison, normalize) a date pair.
 * Returns an error string or null on success.
 * When start is given but end is omitted, end defaults to today.
 */
function validateDateRange(start: unknown, end: unknown): string | null {
  if (!start) return null;  // period-based fetch — safe
  const s = parseDate(start);
  if (!s) return `Invalid start_date '${start}' — expected YYYY-MM-DD.`;
  const resolvedEnd = end ?? new Date().toISOString().slice(0, 10);
  const e = parseDate(resolvedEnd);
  if (!e) return `Invalid end_date '${resolvedEnd}' — expected YYYY-MM-DD.`;
  if (s >= e) return `start_date must be before end_date.`;
  const spanDays = Math.round((e.getTime() - s.getTime()) / 86_400_000);
  if (spanDays > MAX_DATE_SPAN_DAYS) {
    return `Date span ${spanDays} days exceeds maximum ${MAX_DATE_SPAN_DAYS} days (2 years).`;
  }
  return null;
}

function validateBacktestBody(body: Record<string, unknown>): string | null {
  const symbols = body.symbols;
  if (Array.isArray(symbols) && symbols.length > MAX_SYMBOLS) {
    return `Too many symbols (${symbols.length}); maximum is ${MAX_SYMBOLS}.`;
  }
  const dateErr = validateDateRange(body.start_date, body.end_date);
  if (dateErr) return dateErr;
  return null;
}

function validateOptimizerBody(body: Record<string, unknown>): string | null {
  const symbols = body.symbols;
  if (Array.isArray(symbols) && symbols.length > MAX_SYMBOLS) {
    return `Too many symbols (${symbols.length}); maximum is ${MAX_SYMBOLS}.`;
  }
  const dateErr = validateDateRange(body.start_date, body.end_date);
  if (dateErr) return dateErr;
  const grid = (body.grid && typeof body.grid === "object")
    ? (body.grid as Record<string, unknown>)
    : {};
  const combos = countActualGridCombos(grid);
  if (combos === -1) {
    return "Each grid dimension must be a non-empty array of numbers.";
  }
  if (combos > MAX_GRID_COMBOS) {
    return (
      `Effective grid has ${combos} combinations (including defaults for any ` +
      `omitted dimensions); maximum is ${MAX_GRID_COMBOS}. Reduce values per parameter.`
    );
  }
  return null;
}

/** Spawn a Python process in the background (fire-and-forget). */
function spawnBackground(args: string[]): void {
  const opts: SpawnOptions = {
    cwd: PYTHON_DIR,
    env: { ...process.env },
    stdio: "ignore",
    detached: false,
  };
  try {
    const child = spawn(PYTHON_BIN, ["-u", "main.py", ...args], opts);
    child.on("error", () => { /* background process — ignore errors */ });
  } catch (_) { /* ignore */ }
}

/** POST /validation-v2/backtest/run — kick off a full backtest */
router.post("/validation-v2/backtest/run", async (req, res) => {
  try {
    res.set(ADVISORY_HEADER);
    const body = (req.body || {}) as Record<string, unknown>;
    const err = validateBacktestBody(body);
    if (err) { res.status(400).json({ error: err, label: "PAPER / RESEARCH ONLY" }); return; }
    // Enforce symbol cap before passing to Python
    if (Array.isArray(body.symbols)) {
      body.symbols = (body.symbols as string[]).slice(0, MAX_SYMBOLS);
    }
    const configJson = JSON.stringify(body);
    // Phase 1: create the run record synchronously (fast, < 1 s)
    const startResult = await runPython(
      ["validation_v2_backtest_start", configJson],
      15_000
    ) as Record<string, unknown>;

    if ((startResult as any).error) {
      res.status(400).json(startResult);
      return;
    }

    // Phase 2: execute backtest asynchronously — frontend polls GET /:runId for progress
    const runId = String((startResult as any).run_id ?? "");
    if (runId) {
      spawnBackground(["validation_v2_backtest_execute", runId, configJson]);
    }

    res.json(startResult);
  } catch (e: unknown) {
    res.status(500).json({ error: String(e), label: "PAPER / RESEARCH ONLY" });
  }
});

/** GET /validation-v2/backtest — list all runs */
router.get("/validation-v2/backtest", async (_req, res) => {
  try {
    res.set(ADVISORY_HEADER);
    const result = await runPython(["validation_v2_backtest_list"]);
    res.json(result);
  } catch (e: unknown) {
    res.status(500).json({ error: String(e) });
  }
});

/** GET /validation-v2/backtest/:runId — full run details */
router.get("/validation-v2/backtest/:runId", async (req, res) => {
  try {
    res.set(ADVISORY_HEADER);
    const runId = String(req.params.runId || "");
    const result = await runPython(["validation_v2_backtest_get", runId], 60_000);
    res.json(result);
  } catch (e: unknown) {
    res.status(500).json({ error: String(e) });
  }
});

/** GET /validation-v2/missed-opportunities — all or by run */
router.get("/validation-v2/missed-opportunities", async (req, res) => {
  try {
    res.set(ADVISORY_HEADER);
    const runId = String(req.query.runId || "");
    const result = await runPython(["validation_v2_missed", runId]);
    res.json(result);
  } catch (e: unknown) {
    res.status(500).json({ error: String(e) });
  }
});

/** POST /validation-v2/optimizer/run — grid-search parameter combinations */
router.post("/validation-v2/optimizer/run", async (req, res) => {
  try {
    res.set(ADVISORY_HEADER);
    const body = (req.body || {}) as Record<string, unknown>;
    const err = validateOptimizerBody(body);
    if (err) { res.status(400).json({ error: err, label: "PAPER / RESEARCH ONLY" }); return; }
    // Enforce caps before passing to Python
    if (Array.isArray(body.symbols)) {
      body.symbols = (body.symbols as string[]).slice(0, MAX_SYMBOLS);
    }
    const result = await runPython(
      ["validation_v2_optimizer_run", JSON.stringify(body)],
      300_000   // 5 min: grid can be large (capped at 200 combos)
    );
    res.json(result);
  } catch (e: unknown) {
    res.status(500).json({ error: String(e) });
  }
});

/** GET /validation-v2/optimizer/recommendation — best found config */
router.get("/validation-v2/optimizer/recommendation", async (req, res) => {
  try {
    res.set(ADVISORY_HEADER);
    const runId = String(req.query.runId || "");
    const result = await runPython(["validation_v2_optimizer_recommendation", runId]);
    res.json(result);
  } catch (e: unknown) {
    res.status(500).json({ error: String(e) });
  }
});

/** POST /validation-v2/model-comparison — current vs candidate config */
router.post("/validation-v2/model-comparison", async (req, res) => {
  try {
    res.set(ADVISORY_HEADER);
    const body = (req.body || {}) as Record<string, unknown>;
    const err = validateBacktestBody(body);
    if (err) { res.status(400).json({ error: err, label: "PAPER / RESEARCH ONLY" }); return; }
    if (Array.isArray(body.symbols)) {
      body.symbols = (body.symbols as string[]).slice(0, MAX_SYMBOLS);
    }
    const result = await runPython(
      ["validation_v2_model_comparison", JSON.stringify(body)],
      180_000
    );
    res.json(result);
  } catch (e: unknown) {
    res.status(500).json({ error: String(e) });
  }
});

/** GET /validation-v2/performance — daily/weekly/monthly stats */
router.get("/validation-v2/performance", async (req, res) => {
  try {
    res.set(ADVISORY_HEADER);
    const period = String(req.query.period || "monthly");
    const result = await runPython(["validation_v2_performance", period], 30_000);
    res.json(result);
  } catch (e: unknown) {
    res.status(500).json({ error: String(e) });
  }
});

/** GET /validation-v2/session-timeline/:runId — playback event log */
router.get("/validation-v2/session-timeline/:runId", async (req, res) => {
  try {
    res.set(ADVISORY_HEADER);
    const runId = String(req.params.runId || "");
    const result = await runPython(["validation_v2_timeline", runId], 30_000);
    res.json(result);
  } catch (e: unknown) {
    res.status(500).json({ error: String(e) });
  }
});

export default router;
