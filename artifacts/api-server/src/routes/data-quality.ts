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
      reject(new Error(`data-quality timeout after ${timeoutMs}ms`));
    }, timeoutMs);
    proc.on("close", (code) => {
      clearTimeout(timer);
      try {
        resolve(JSON.parse(out));
      } catch {
        reject(new Error(`data-quality parse error (exit ${code}): ${err.slice(0, 300)}`));
      }
    });
  });
}

router.get("/data-quality/summary",   async (_req, res) => {
  try { res.json(await runPython(["data_quality_summary"])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

router.get("/data-quality/market",    async (_req, res) => {
  try { res.json(await runPython(["data_quality_market"])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

router.get("/data-quality/preopen",   async (_req, res) => {
  try { res.json(await runPython(["data_quality_preopen"])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

router.get("/data-quality/paper",     async (_req, res) => {
  try { res.json(await runPython(["data_quality_paper"])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

router.get("/data-quality/portfolio", async (_req, res) => {
  try { res.json(await runPython(["data_quality_portfolio"])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

router.get("/data-quality/ai",        async (_req, res) => {
  try { res.json(await runPython(["data_quality_ai"])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

router.get("/data-quality/signals",   async (_req, res) => {
  try { res.json(await runPython(["data_quality_signals"])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

router.get("/data-quality/config",    async (_req, res) => {
  try { res.json(await runPython(["data_quality_config"])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

router.get("/data-quality/alerts",    async (_req, res) => {
  try { res.json(await runPython(["data_quality_alerts"])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

router.get("/data-quality/snapshot",  async (_req, res) => {
  try { res.json(await runPython(["data_quality_snapshot"])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

router.get("/data-quality/export",    async (req, res) => {
  const fmt = (req.query.format as string) || "json";
  try {
    res.json(await runPython([
      fmt === "csv" ? "data_quality_export_csv" : "data_quality_export_json",
    ]));
  } catch (e: any) { res.status(500).json({ error: e.message }); }
});

export default router;
