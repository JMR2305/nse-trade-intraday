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

router.get("/deployment/summary",         handle("deploy_summary"));
router.get("/deployment/readiness",       handle("deploy_readiness"));
router.get("/deployment/config",          handle("deploy_config"));
router.get("/deployment/backups",         handle("deploy_backups"));
router.get("/deployment/restore",         handle("deploy_restore"));
router.get("/deployment/rollback",        handle("deploy_rollback"));
router.get("/deployment/infrastructure",  handle("deploy_infrastructure"));
router.get("/deployment/continuity",      handle("deploy_continuity"));
router.get("/deployment/recommendations", handle("deploy_recommendations"));
router.get("/deployment/snapshot",        handle("deploy_snapshot"));

router.get("/deployment/export", async (req: any, res: any) => {
  const fmt = (req.query.format ?? "json") as string;
  try {
    if (fmt === "csv") {
      const data: any = await runPython(["deploy_export_csv"]);
      res.setHeader("Content-Type", "text/csv");
      res.setHeader("Content-Disposition", "attachment; filename=deployment_export.csv");
      res.send(data?.csv ?? "");
    } else {
      res.json(await runPython(["deploy_export_json"]));
    }
  } catch (e: any) {
    res.status(500).json({ error: e.message });
  }
});

export { router as deploymentRouter };
export default router;
