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

router.get("/command-center/summary",  handle("cmd_center_summary",  90_000));
router.get("/command-center/briefing", handle("cmd_center_briefing", 60_000));
router.get("/command-center/alerts",   handle("cmd_center_alerts",   60_000));
router.get("/command-center/timeline", handle("cmd_center_timeline", 30_000));

router.get("/command-center/export", async (req: any, res: any) => {
  const fmt = (req.query.format ?? "json") as string;
  try {
    if (fmt === "csv") {
      const data: any = await runPython(["cmd_center_export_csv"]);
      res.setHeader("Content-Type", "text/csv");
      res.setHeader("Content-Disposition", "attachment; filename=command_center_export.csv");
      res.send(data?.csv ?? "");
    } else {
      res.json(await runPython(["cmd_center_export_json"]));
    }
  } catch (e: any) {
    res.status(500).json({ error: e.message });
  }
});

export { router as commandCenterRouter };
export default router;
