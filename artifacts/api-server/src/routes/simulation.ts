/**
 * Phase 23.8A — AI Simulation Laboratory.
 *
 * ALL endpoints are read-only + advisory over the canonical stores. Sim
 * state lives only in dedicated append-only tables (sim_scenarios /
 * sim_runs) — the live portfolio, paper ledger, event store and settings
 * are never modified.
 *
 * POST /api/simulation/scenario          { name, base_run_id, params }
 * GET  /api/simulation/scenarios
 * POST /api/simulation/run               { scenario_id | run_id+params, label }
 * GET  /api/simulation/runs
 * GET  /api/simulation/run/:id
 * POST /api/simulation/compare           { sim_ids }        — unlimited rows
 * POST /api/simulation/risk-compare      { run_id, rules_a, rules_b }
 * GET  /api/simulation/stress/portfolio
 * GET  /api/simulation/stress/execution
 */
import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import path from "path";
import { PYTHON_BIN, PYTHON_DIR } from "../lib/python-env";

const router: IRouter = Router();

function runPython(args: string[], timeoutMs = 120_000): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], {
      cwd: PYTHON_DIR,
      env: process.env,
    });
    const timer = setTimeout(() => {
      proc.kill("SIGKILL");
      reject(new Error(`python timed out after ${timeoutMs}ms`));
    }, timeoutMs);
    let out = "";
    let err = "";
    proc.stdout.on("data", (d) => (out += d));
    proc.stderr.on("data", (d) => (err += d));
    proc.on("close", (code) => {
      clearTimeout(timer);
      if (code !== 0) return reject(new Error(err || `python exited ${code}`));
      try {
        resolve(JSON.parse(out));
      } catch {
        reject(new Error("invalid JSON from python"));
      }
    });
  });
}

function fail(res: any, err: unknown): void {
  res.status(500).json({
    success: false,
    error: err instanceof Error ? err.message : String(err),
  });
}

// ── input bounds ────────────────────────────────────────────────────────────
const MAX_ID_LEN = 64;
const cleanId = (v: unknown): string => String(v ?? "").slice(0, MAX_ID_LEN);
function cleanParams(p: unknown): Record<string, unknown> {
  if (!p || typeof p !== "object") return {};
  const out: Record<string, unknown> = {};
  let n = 0;
  for (const [k, v] of Object.entries(p as Record<string, unknown>)) {
    if (++n > 24) break;
    if (typeof v === "number" && Number.isFinite(v)) out[k.slice(0, 40)] = v;
    else if (typeof v === "string") out[k.slice(0, 40)] = v.slice(0, 80);
  }
  return out;
}

// ── single-flight guard: identical concurrent sim runs share one process ───
const inflight = new Map<string, Promise<unknown>>();
function singleFlight(key: string, factory: () => Promise<unknown>): Promise<unknown> {
  const hit = inflight.get(key);
  if (hit) return hit;
  const p = factory().finally(() => inflight.delete(key));
  inflight.set(key, p);
  return p;
}

router.post("/simulation/scenario", async (req, res) => {
  try {
    res.json(await runPython(["sim_scenario_create", JSON.stringify({
      name: String(req.body?.name ?? "Scenario").slice(0, 60),
      base_run_id: req.body?.base_run_id
        ? cleanId(req.body.base_run_id) : undefined,
      params: cleanParams(req.body?.params),
    })], 60_000));
  } catch (err) { fail(res, err); }
});

router.get("/simulation/scenarios", async (_req, res) => {
  try {
    res.json(await runPython(["sim_scenarios"], 60_000));
  } catch (err) { fail(res, err); }
});

router.post("/simulation/run", async (req, res) => {
  try {
    const payload = {
      scenario_id: req.body?.scenario_id
        ? cleanId(req.body.scenario_id) : undefined,
      run_id: req.body?.run_id ? cleanId(req.body.run_id) : undefined,
      params: cleanParams(req.body?.params),
      label: req.body?.label
        ? String(req.body.label).slice(0, 60) : undefined,
    };
    const key = `run:${JSON.stringify(payload)}`;
    res.json(await singleFlight(key, () =>
      runPython(["sim_run", JSON.stringify(payload)], 300_000)));
  } catch (err) { fail(res, err); }
});

router.get("/simulation/runs", async (req, res) => {
  try {
    res.json(await runPython(["sim_runs", JSON.stringify({
      limit: Number(req.query.limit) || 100,
    })], 60_000));
  } catch (err) { fail(res, err); }
});

router.get("/simulation/run/:id", async (req, res) => {
  try {
    res.json(await runPython(["sim_run_get",
      JSON.stringify({ sim_id: cleanId(req.params.id) })], 60_000));
  } catch (err) { fail(res, err); }
});

router.post("/simulation/compare", async (req, res) => {
  try {
    // Unlimited comparison — every id is fetched directly by primary key.
    const sim_ids = (Array.isArray(req.body?.sim_ids) ? req.body.sim_ids : [])
      .map(cleanId).filter(Boolean);
    res.json(await runPython(["sim_compare",
      JSON.stringify({ sim_ids })], 300_000));
  } catch (err) { fail(res, err); }
});

router.post("/simulation/risk-compare", async (req, res) => {
  try {
    const payload = {
      run_id: cleanId(req.body?.run_id),
      rules_a: cleanParams(req.body?.rules_a),
      rules_b: cleanParams(req.body?.rules_b),
    };
    const key = `risk:${JSON.stringify(payload)}`;
    res.json(await singleFlight(key, () =>
      runPython(["sim_risk_compare", JSON.stringify(payload)], 300_000)));
  } catch (err) { fail(res, err); }
});

router.get("/simulation/stress/portfolio", async (_req, res) => {
  try {
    res.json(await singleFlight("stress:portfolio", () =>
      runPython(["sim_stress_portfolio"], 120_000)));
  } catch (err) { fail(res, err); }
});

router.get("/simulation/stress/execution", async (_req, res) => {
  try {
    res.json(await singleFlight("stress:execution", () =>
      runPython(["sim_stress_execution"], 120_000)));
  } catch (err) { fail(res, err); }
});

export default router;
