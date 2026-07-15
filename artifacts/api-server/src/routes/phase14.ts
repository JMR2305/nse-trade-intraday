/**
 * phase14.ts — Phase 14: Adaptive Paper-Trade Learning, Calibration & Model Governance
 *
 * Routes:
 *   GET  /api/phase14/dataset                — completed-trade learning dataset (first 200 rows)
 *   GET  /api/phase14/evaluation             — outcome evaluation report
 *   GET  /api/phase14/adjustments            — adaptive learning adjustments
 *   POST /api/phase14/calibration/train      — train new versioned calibrator
 *   GET  /api/phase14/calibration            — calibration status + history
 *   GET  /api/phase14/registry               — model registry (champion/challengers)
 *   POST /api/phase14/registry/challenger    — create challenger from latest evidence
 *   GET  /api/phase14/registry/checklist/:id — promotion checklist
 *   POST /api/phase14/registry/review/:id    — approve/reject/archive (human only)
 *   POST /api/phase14/registry/rollback      — one-click rollback to previous champion
 *   GET  /api/phase14/drift                  — compute drift indicators
 *   GET  /api/phase14/alerts                 — informational alerts
 *   GET  /api/phase14/audit-log              — governance audit log
 *   GET  /api/phase14/verification           — Phase 14 verification summary
 *   POST /api/phase14/bundle                 — build full diagnostic bundle
 *   GET  /api/phase14/bundle/download        — download bundle (?file=json|csv)
 *   GET  /api/phase14/export/:name           — export one artifact (json+csv)
 *   POST /api/phase14/decision-context       — per-decision learning context
 *
 * RESEARCH / PAPER LEARNING ONLY — no real broker orders, no auto-promotion.
 */
import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import path from "path";
import fs from "fs";

const router: IRouter = Router();
const PYTHON_DIR = path.join(process.cwd(), "src", "python");

function runPython(args: string[], timeoutMs = 90_000): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const proc = spawn("python3", [path.join(PYTHON_DIR, "main.py"), ...args], { cwd: PYTHON_DIR });
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
        reject(new Error(stderr || `Python exited ${code}`));
      } else {
        try { resolve(JSON.parse(stdout.trim())); }
        catch { reject(new Error(`Failed to parse Python output: ${stdout.slice(0, 200)}`)); }
      }
    });
    proc.on("error", (err) => { clearTimeout(timer); reject(err); });
  });
}

const wrap = (fn: (req: any, res: any) => Promise<void>) =>
  async (req: any, res: any) => {
    try { await fn(req, res); }
    catch (err: unknown) {
      res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
    }
  };

router.get("/phase14/dataset", wrap(async (_req, res) => {
  res.json(await runPython(["phase14_dataset"], 120_000));
}));

router.get("/phase14/evaluation", wrap(async (_req, res) => {
  res.json(await runPython(["phase14_evaluation"], 120_000));
}));

router.get("/phase14/adjustments", wrap(async (_req, res) => {
  res.json(await runPython(["phase14_adjustments"], 120_000));
}));

router.post("/phase14/calibration/train", wrap(async (_req, res) => {
  res.json(await runPython(["phase14_calibration_train"], 120_000));
}));

router.get("/phase14/calibration", wrap(async (_req, res) => {
  res.json(await runPython(["phase14_calibration_status"]));
}));

router.get("/phase14/registry", wrap(async (_req, res) => {
  res.json(await runPython(["phase14_registry"]));
}));

router.post("/phase14/registry/challenger", wrap(async (req, res) => {
  const desc = typeof req.body?.description === "string" ? req.body.description : "";
  res.json(await runPython(["phase14_challenger_create", desc], 120_000));
}));

router.get("/phase14/registry/checklist/:id", wrap(async (req, res) => {
  res.json(await runPython(["phase14_promotion_checklist", req.params.id], 120_000));
}));

router.post("/phase14/registry/review/:id", wrap(async (req, res) => {
  const { action, approver } = req.body as { action?: string; approver?: string };
  if (!action || !["APPROVE", "REJECT", "ARCHIVE"].includes(action.toUpperCase())) {
    res.status(400).json({ success: false, error: "action must be APPROVE, REJECT, or ARCHIVE" });
    return;
  }
  res.json(await runPython(["phase14_model_review", req.params.id, action, approver ?? "human"], 120_000));
}));

router.post("/phase14/registry/rollback", wrap(async (_req, res) => {
  res.json(await runPython(["phase14_rollback"]));
}));

router.get("/phase14/drift", wrap(async (_req, res) => {
  res.json(await runPython(["phase14_drift"], 120_000));
}));

router.get("/phase14/alerts", wrap(async (_req, res) => {
  res.json(await runPython(["phase14_alerts"]));
}));

router.get("/phase14/audit-log", wrap(async (_req, res) => {
  res.json(await runPython(["phase14_audit_log"]));
}));

router.get("/phase14/verification", wrap(async (_req, res) => {
  res.json(await runPython(["phase14_verification"], 120_000));
}));

router.post("/phase14/bundle", wrap(async (_req, res) => {
  res.json(await runPython(["phase14_bundle"], 120_000));
}));

router.get("/phase14/bundle/download", wrap(async (req, res) => {
  const kind = String(req.query.file ?? "json");
  if (!["json", "csv"].includes(kind)) {
    res.status(400).json({ success: false, error: "file must be json or csv" });
    return;
  }
  const fname = kind === "json" ? "phase14_diagnostic_bundle.json" : "phase14_summary.csv";
  const filePath = path.join(PYTHON_DIR, fname);
  await runPython(["phase14_bundle"], 120_000);
  if (!fs.existsSync(filePath)) {
    res.status(500).json({ success: false, error: "Bundle file missing after generation" });
    return;
  }
  res.setHeader("Content-Type", kind === "json" ? "application/json; charset=utf-8" : "text/csv; charset=utf-8");
  res.setHeader("Content-Disposition", `attachment; filename="${fname}"`);
  fs.createReadStream(filePath).pipe(res);
}));

const EXPORTABLE = ["dataset", "evaluation", "calibration", "adjustments", "registry", "drift", "audit_log"];
router.get("/phase14/export/:name", wrap(async (req, res) => {
  const { name } = req.params;
  if (!EXPORTABLE.includes(name)) {
    res.status(400).json({ success: false, error: `name must be one of ${EXPORTABLE.join(", ")}` });
    return;
  }
  const format = String(req.query.format ?? "json");
  const result = await runPython(["phase14_export", name], 120_000) as any;
  if (format === "csv") {
    res.setHeader("Content-Type", "text/csv; charset=utf-8");
    res.setHeader("Content-Disposition", `attachment; filename="phase14_${name}.csv"`);
    res.send(result.csv ?? "");
  } else {
    res.setHeader("Content-Disposition", `attachment; filename="phase14_${name}.json"`);
    res.json(result.json ?? result);
  }
}));

router.post("/phase14/decision-context", wrap(async (req, res) => {
  res.json(await runPython(["phase14_decision_context", JSON.stringify(req.body ?? {})], 60_000));
}));

router.post("/phase14/decision-batch", wrap(async (req, res) => {
  const items = Array.isArray(req.body?.items) ? req.body.items : [];
  res.json(await runPython(["phase14_decision_batch", JSON.stringify(items)], 90_000));
}));

router.get("/phase14/qa", wrap(async (req, res) => {
  const question = typeof req.query.question === "string" ? req.query.question : "";
  res.json(await runPython(["phase14_qa", question], 60_000));
}));

export default router;
