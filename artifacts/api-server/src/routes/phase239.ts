/**
 * Phase 23.9 — Validation Dashboard export engine + final acceptance.
 *
 * GET /api/phase239/export/:report/:format
 *       report: certification | validation_logs | simulation |
 *               comparison | acceptance
 *       format: json | csv | md | pdf
 *       optional query: cert_id, limit
 * GET /api/phase239/acceptance — final acceptance report (canonical
 *       architecture audit; cached + single-flight)
 *
 * READ-ONLY over canonical stores. Exports stream in-memory content —
 * nothing in live trading state is modified.
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

// ── cache + single-flight so the slow acceptance audit never stacks ─────────
const cache = new Map<string, { at: number; value: unknown }>();
const inflight = new Map<string, Promise<unknown>>();
function cachedSingleFlight(
  key: string,
  factory: () => Promise<unknown>,
  ttlMs = 60_000,
): Promise<unknown> {
  const hit = cache.get(key);
  if (hit && Date.now() - hit.at < ttlMs) return Promise.resolve(hit.value);
  const running = inflight.get(key);
  if (running) return running;
  const p = factory()
    .then((value) => {
      cache.set(key, { at: Date.now(), value });
      return value;
    })
    .finally(() => inflight.delete(key));
  inflight.set(key, p);
  return p;
}

const MAX_ID_LEN = 64;
const cleanId = (v: unknown): string => String(v ?? "").slice(0, MAX_ID_LEN);

const REPORTS = new Set([
  "certification", "validation_logs", "simulation", "comparison", "readiness",
  "acceptance",
]);
const FORMATS = new Set(["json", "csv", "md", "pdf"]);

interface ExportResult {
  ok: boolean;
  error?: string;
  filename?: string;
  content_type?: string;
  content?: string;
  content_b64?: string;
}

// GET /api/phase239/export/:report/:format — download one report
router.get("/phase239/export/:report/:format", async (req, res) => {
  try {
    const report = String(req.params.report || "").toLowerCase();
    const format = String(req.params.format || "").toLowerCase();
    if (!REPORTS.has(report) || !FORMATS.has(format)) {
      res.status(400).json({
        success: false,
        error: `Unknown report/format — reports: ${[...REPORTS].join(", ")}; formats: ${[...FORMATS].join(", ")}`,
      });
      return;
    }
    const payload: Record<string, unknown> = { report, format };
    if (req.query.cert_id) payload.cert_id = cleanId(req.query.cert_id);
    if (req.query.limit) payload.limit = Number(req.query.limit) || 100;
    const result = (await runPython(
      ["p239_export", JSON.stringify(payload)],
      300_000,
    )) as ExportResult;
    if (!result?.ok) {
      res.status(422).json({ success: false, error: result?.error || "export failed" });
      return;
    }
    res.setHeader("Content-Type", result.content_type || "application/octet-stream");
    res.setHeader(
      "Content-Disposition",
      `attachment; filename=${result.filename || `phase23_${report}.${format}`}`,
    );
    if (result.content_b64) {
      res.send(Buffer.from(result.content_b64, "base64"));
    } else {
      res.send(String(result.content ?? ""));
    }
  } catch (err) {
    fail(res, err);
  }
});

// GET /api/phase239/acceptance — final acceptance report (JSON, for the UI)
router.get("/phase239/acceptance", async (_req, res) => {
  try {
    res.json(
      await cachedSingleFlight("acceptance", () =>
        runPython(["p239_acceptance"], 180_000),
      ),
    );
  } catch (err) {
    fail(res, err);
  }
});

export default router;
