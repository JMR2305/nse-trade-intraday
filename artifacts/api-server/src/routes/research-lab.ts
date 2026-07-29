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
        reject(new Error(`research-lab parse error (exit ${code}): ${err.slice(0, 300)}`));
      }
    });
  });
}

router.get("/research-lab/summary", async (_req, res) => {
  try { res.json(await runPython(["research_lab_summary"])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

router.get("/research-lab/strategies", async (_req, res) => {
  try { res.json(await runPython(["research_lab_strategies"])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

router.get("/research-lab/simulations", async (_req, res) => {
  try { res.json(await runPython(["research_lab_simulations"])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

router.get("/research-lab/replay", async (_req, res) => {
  try { res.json(await runPython(["research_lab_replay"])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

router.get("/research-lab/benchmark", async (_req, res) => {
  try { res.json(await runPython(["research_lab_benchmark"])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

router.get("/research-lab/reports", async (_req, res) => {
  try { res.json(await runPython(["research_lab_reports"])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

router.get("/research-lab/snapshot", async (_req, res) => {
  try { res.json(await runPython(["research_lab_snapshot"])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

router.get("/research-lab/export", async (req, res) => {
  const fmt = (req.query.format as string) || "json";
  try { res.json(await runPython(["research_lab_export", fmt])); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
});

export default router;
