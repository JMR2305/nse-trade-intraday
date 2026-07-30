import { Router } from "express";
import { spawn }  from "child_process";
import path       from "path";
import { PYTHON_BIN, PYTHON_DIR } from "../lib/python-env";

const router = Router();

function runPython(args: string[]): Promise<any> {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], {
      env: { ...process.env },
      cwd: PYTHON_DIR,
    });
    let out = "";
    let err = "";
    proc.stdout.on("data", (d) => (out += d.toString()));
    proc.stderr.on("data", (d) => (err += d.toString()));
    proc.on("close", (code) => {
      try {
        resolve(JSON.parse(out));
      } catch {
        reject(new Error(`observability parse error (exit ${code}): ${err.slice(0, 300)}`));
      }
    });
  });
}

router.get("/observability/summary", async (_req, res) => {
  try { res.json(await runPython(["observability_summary"])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

router.get("/observability/system", async (_req, res) => {
  try { res.json(await runPython(["observability_system"])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

router.get("/observability/performance", async (_req, res) => {
  try { res.json(await runPython(["observability_performance"])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

router.get("/observability/errors", async (_req, res) => {
  try { res.json(await runPython(["observability_errors"])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

router.get("/observability/alerts", async (_req, res) => {
  try { res.json(await runPython(["observability_alerts"])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

router.get("/observability/audit", async (_req, res) => {
  try { res.json(await runPython(["observability_audit"])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

router.get("/observability/snapshot", async (_req, res) => {
  try { res.json(await runPython(["observability_snapshot"])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

router.get("/observability/export", async (req, res) => {
  const fmt = (req.query.format as string) || "json";
  try {
    res.json(await runPython([fmt === "csv" ? "observability_export_csv" : "observability_export_json"]));
  } catch (e: any) { res.status(500).json({ error: e.message }); }
});

export default router;
