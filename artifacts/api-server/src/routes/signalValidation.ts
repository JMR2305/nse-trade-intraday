/**
 * signalValidation.ts — Phase 5C API routes
 *
 * 14 endpoints covering: status, summary, signals list, signal detail,
 * funnel, strategies, AI attribution, pre-open attribution, risk attribution,
 * regimes, missed opportunities, report, manual run, reconciliation.
 *
 * All responses carry label: "PAPER TRADING / ADVISORY ONLY".
 * SIGNAL_VALIDATION_ENABLED=false → every endpoint returns DISABLED body (200).
 * No order submission. No strategy modification.
 */
import { Router } from "express";
import { spawn } from "child_process";
import path from "path";

const router = Router();

const PYTHON_BIN = process.env.PYTHON_BIN ?? "python3";
const PYTHON_DIR = path.join(process.cwd(), "src", "python");

function runPython(args: string[]): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const child = spawn(PYTHON_BIN, ["main.py", ...args], {
      cwd: PYTHON_DIR,
      env: process.env,
    });
    let out = "";
    let err = "";
    child.stdout.on("data", (d: Buffer) => { out += d.toString(); });
    child.stderr.on("data", (d: Buffer) => { err += d.toString(); });
    child.on("close", (code) => {
      try {
        resolve(JSON.parse(out));
      } catch {
        if (code !== 0) {
          reject(new Error(err || `exit ${code}`));
        } else {
          resolve({ raw: out });
        }
      }
    });
  });
}

// 1. Status
router.get("/signal-validation/status", async (_req, res) => {
  try {
    res.json(await runPython(["signal_validation_status"]));
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

// 2. Summary (with funnel)
router.get("/signal-validation/summary", async (req, res) => {
  try {
    const date = (req.query.date as string) ?? "";
    const args = ["signal_validation_summary", ...(date ? [date] : [])];
    res.json(await runPython(args));
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

// 3. Signals list (paginated, filterable)
router.get("/signal-validation/signals", async (req, res) => {
  try {
    const date   = (req.query.date   as string) ?? "";
    const limit  = (req.query.limit  as string) ?? "100";
    const offset = (req.query.offset as string) ?? "0";
    const args = ["signal_validation_signals",
      ...(date ? [date] : [""]),
      limit, offset];
    res.json(await runPython(args));
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

// 4. Signal detail (includes lifecycle events + price checkpoints)
router.get("/signal-validation/signals/:signalId", async (req, res) => {
  try {
    const { signalId } = req.params;
    const date = (req.query.date as string) ?? "";
    const args = ["signal_validation_detail", signalId, ...(date ? [date] : [])];
    res.json(await runPython(args));
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

// 5. Signal funnel
router.get("/signal-validation/funnel", async (req, res) => {
  try {
    const date = (req.query.date as string) ?? "";
    res.json(await runPython(["signal_validation_funnel", ...(date ? [date] : [])]));
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

// 6. Strategy attribution
router.get("/signal-validation/strategies", async (req, res) => {
  try {
    const date = (req.query.date as string) ?? "";
    res.json(await runPython(["signal_validation_strategies", ...(date ? [date] : [])]));
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

// 7. AI attribution
router.get("/signal-validation/ai", async (req, res) => {
  try {
    const date = (req.query.date as string) ?? "";
    res.json(await runPython(["signal_validation_ai", ...(date ? [date] : [])]));
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

// 8. Pre-open attribution
router.get("/signal-validation/preopen", async (req, res) => {
  try {
    const date = (req.query.date as string) ?? "";
    res.json(await runPython(["signal_validation_preopen", ...(date ? [date] : [])]));
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

// 9. Risk attribution
router.get("/signal-validation/risk", async (req, res) => {
  try {
    const date = (req.query.date as string) ?? "";
    res.json(await runPython(["signal_validation_risk", ...(date ? [date] : [])]));
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

// 10. Regime attribution
router.get("/signal-validation/regimes", async (req, res) => {
  try {
    const date = (req.query.date as string) ?? "";
    res.json(await runPython(["signal_validation_regimes", ...(date ? [date] : [])]));
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

// 11. Missed opportunities (hypothetical P&L)
router.get("/signal-validation/missed", async (req, res) => {
  try {
    const date  = (req.query.date  as string) ?? "";
    const limit = (req.query.limit as string) ?? "50";
    res.json(await runPython(["signal_validation_missed",
      ...(date ? [date] : [""]), limit]));
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

// 12. Daily report
router.get("/signal-validation/report", async (req, res) => {
  try {
    const date = (req.query.date as string) ?? "";
    res.json(await runPython(["signal_validation_report", ...(date ? [date] : [])]));
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

// 13. Manual run (operator-triggered ingest)
router.post("/signal-validation/run-now", async (req, res) => {
  try {
    const date = (req.body?.date as string) ?? "";
    res.json(await runPython(["signal_validation_run_now", ...(date ? [date] : [])]));
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

// 14. Manual EOD reconciliation
router.post("/signal-validation/reconcile", async (req, res) => {
  try {
    const date = (req.body?.date as string) ?? "";
    res.json(await runPython(["signal_validation_reconcile", ...(date ? [date] : [])]));
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

export default router;
