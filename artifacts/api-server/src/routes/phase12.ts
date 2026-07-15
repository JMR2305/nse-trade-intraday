/**
 * phase12.ts — Phase 12: Advanced Institutional Intelligence Layer
 *
 * Routes:
 *   GET  /api/phase12/analysis          — multi-factor fused analysis (cached 10 min)
 *   GET  /api/phase12/regime            — current market regime
 *   GET  /api/phase12/sector-rotation   — sector ranking + momentum
 *   POST /api/phase12/bundle            — generate + return diagnostic bundle
 *   GET  /api/phase12/bundle/download   — download JSON or CSV (?file=json|csv)
 *
 * PAPER TRADING ONLY — no real broker orders.
 */
import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import path from "path";
import fs from "fs";

const router: IRouter = Router();
const PYTHON_DIR = path.join(process.cwd(), "src", "python");

function runPython(args: string[], timeoutMs = 90_000): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const proc = spawn("python3", [path.join(PYTHON_DIR, "main.py"), ...args], {
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
        try { resolve(JSON.parse(stdout.trim())); }
        catch { reject(new Error(`Failed to parse Python output: ${stdout.slice(0, 200)}`)); }
      }
    });
    proc.on("error", (err) => { clearTimeout(timer); reject(err); });
  });
}

// GET /api/phase12/analysis
router.get("/phase12/analysis", async (req, res) => {
  try {
    const symbols = typeof req.query.symbols === "string" ? req.query.symbols : "";
    const force   = req.query.force === "true";
    const args    = ["phase12_analysis", symbols, ...(force ? ["force"] : [])];
    const data    = await runPython(args);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/phase12/regime
router.get("/phase12/regime", async (_req, res) => {
  try {
    const data = await runPython(["phase12_regime"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/phase12/sector-rotation
router.get("/phase12/sector-rotation", async (_req, res) => {
  try {
    const data = await runPython(["phase12_sector_rotation"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/phase12/bundle
router.post("/phase12/bundle", async (_req, res) => {
  try {
    const data = await runPython(["phase12_bundle"], 120_000);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/phase12/bundle/download?file=json|csv
router.get("/phase12/bundle/download", async (req, res) => {
  try {
    const kind = String(req.query.file ?? "json");
    if (!["json", "csv"].includes(kind)) {
      res.status(400).json({ success: false, error: "file must be json or csv" });
      return;
    }
    const fname = kind === "json" ? "phase12_diagnostic_bundle.json" : "phase12_summary.csv";
    const filePath = path.join(PYTHON_DIR, fname);
    // Always regenerate for honest point-in-time snapshot
    await runPython(["phase12_bundle"], 120_000);
    if (!fs.existsSync(filePath)) {
      res.status(500).json({ success: false, error: "Bundle file missing after generation" });
      return;
    }
    res.setHeader("Content-Type",
      kind === "json" ? "application/json; charset=utf-8" : "text/csv; charset=utf-8");
    res.setHeader("Content-Disposition", `attachment; filename="${fname}"`);
    fs.createReadStream(filePath).pipe(res);
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});

export default router;
