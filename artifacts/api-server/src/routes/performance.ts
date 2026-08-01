import { Router } from "express";
import path from "path";
import { spawn } from "child_process";
import { PYTHON_BIN, PYTHON_DIR } from "../lib/python-env";

const router = Router();

function runPython(args: string[], timeoutMs = 90_000): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], {
      cwd: PYTHON_DIR,
      env: { ...process.env },
    });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      proc.kill("SIGTERM");
      reject(new Error(`Python timeout after ${timeoutMs}ms`));
    }, timeoutMs);
    proc.stdout.on("data", (d: Buffer) => { stdout += d.toString(); });
    proc.stderr.on("data", (d: Buffer) => { stderr += d.toString(); });
    proc.on("close", (code) => {
      clearTimeout(timer);
      if (code !== 0) {
        try { resolve(JSON.parse(stdout)); } catch { reject(new Error(stderr || stdout)); }
      } else {
        try { resolve(JSON.parse(stdout)); } catch { reject(new Error("Invalid JSON from Python")); }
      }
    });
  });
}

const handle = (cmd: string, timeout?: number) =>
  async (req: any, res: any) => {
    try {
      res.json(await runPython([cmd], timeout));
    } catch (e: any) {
      res.status(500).json({ error: e.message });
    }
  };

router.get("/performance/summary",         handle("perf_summary"));
router.get("/performance/api",             handle("perf_api"));
router.get("/performance/database",        handle("perf_database"));
router.get("/performance/cache",           handle("perf_cache"));
router.get("/performance/scheduler",       handle("perf_scheduler"));
router.get("/performance/resources",       handle("perf_resources"));
router.get("/performance/frontend",        handle("perf_frontend"));
router.get("/performance/scalability",     handle("perf_scalability"));
router.get("/performance/benchmark",       handle("perf_benchmark"));
router.get("/performance/recommendations", handle("perf_recommendations"));
router.get("/performance/snapshot",        handle("perf_snapshot"));

router.get("/performance/export", async (req: any, res: any) => {
  const fmt = (req.query.format ?? "json") as string;
  try {
    if (fmt === "csv") {
      const data: any = await runPython(["perf_export_csv"]);
      res.setHeader("Content-Type", "text/csv");
      res.setHeader("Content-Disposition", "attachment; filename=performance_export.csv");
      res.send(data?.csv ?? "");
    } else {
      res.json(await runPython(["perf_export_json"]));
    }
  } catch (e: any) {
    res.status(500).json({ error: e.message });
  }
});

export { router as performanceRouter };
export default router;
