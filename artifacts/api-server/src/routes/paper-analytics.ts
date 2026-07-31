import { Router } from "express";
import { spawn }  from "child_process";
import path       from "path";
import { PYTHON_BIN, PYTHON_DIR } from "../lib/python-env";

const router = Router();

function runPython(args: string[], timeoutMs = 90_000): Promise<any> {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], {
      env: { ...process.env },
      cwd: PYTHON_DIR,
    });
    let out = "";
    let err = "";
    proc.stdout.on("data", (d) => (out += d.toString()));
    proc.stderr.on("data", (d) => (err += d.toString()));
    const timer = setTimeout(() => {
      proc.kill();
      reject(new Error(`paper-analytics timeout after ${timeoutMs}ms`));
    }, timeoutMs);
    proc.on("close", (code) => {
      clearTimeout(timer);
      try {
        resolve(JSON.parse(out));
      } catch {
        reject(new Error(`paper-analytics parse error (exit ${code}): ${err.slice(0, 300)}`));
      }
    });
  });
}

router.get("/paper-analytics/summary", async (_req, res) => {
  try { res.json(await runPython(["paper_analytics_summary"])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

router.get("/paper-analytics/trades", async (_req, res) => {
  try { res.json(await runPython(["paper_analytics_trades"])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

router.get("/paper-analytics/strategies", async (_req, res) => {
  try { res.json(await runPython(["paper_analytics_strategies"])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

router.get("/paper-analytics/risk", async (_req, res) => {
  try { res.json(await runPython(["paper_analytics_risk"])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

router.get("/paper-analytics/preopen", async (_req, res) => {
  try { res.json(await runPython(["paper_analytics_preopen"])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

router.get("/paper-analytics/portfolio", async (_req, res) => {
  try { res.json(await runPython(["paper_analytics_portfolio"])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

router.get("/paper-analytics/learning", async (_req, res) => {
  try { res.json(await runPython(["paper_analytics_learning"])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

router.get("/paper-analytics/snapshot", async (_req, res) => {
  try { res.json(await runPython(["paper_analytics_snapshot"])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

router.get("/paper-analytics/export", async (req, res) => {
  const fmt = (req.query.format as string) || "json";
  try {
    res.json(await runPython([
      fmt === "csv" ? "paper_analytics_export_csv" : "paper_analytics_export_json",
    ]));
  } catch (e: any) { res.status(500).json({ error: e.message }); }
});

export default router;
