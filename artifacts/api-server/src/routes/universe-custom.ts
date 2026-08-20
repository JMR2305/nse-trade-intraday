import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import path from "path";
import { PYTHON_BIN, PYTHON_DIR } from "../lib/python-env";

const router: IRouter = Router();

function runPython(args: string[], timeoutMs = 30_000): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], {
      cwd: PYTHON_DIR,
      env: process.env,
    });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      proc.kill("SIGTERM");
      reject(new Error(`Python timed out after ${timeoutMs / 1000}s`));
    }, timeoutMs);
    proc.stdout.on("data", (data: Buffer) => { stdout += data.toString(); });
    proc.stderr.on("data", (data: Buffer) => { stderr += data.toString(); });
    proc.on("error", (error) => { clearTimeout(timer); reject(error); });
    proc.on("close", (code) => {
      clearTimeout(timer);
      if (code !== 0) return reject(new Error(stderr || `Python exited ${code}`));
      try {
        resolve(JSON.parse(stdout.trim()));
      } catch {
        reject(new Error(`Failed to parse Python response: ${stdout.slice(-240)}`));
      }
    });
  });
}

const wrap = (handler: (req: any, res: any) => Promise<void>) =>
  async (req: any, res: any) => {
    try {
      await handler(req, res);
    } catch (error) {
      res.status(500).json({
        success: false,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  };

// Read-only/advisory universe management. Refresh only writes scanner metadata;
// it never calls a broker order API.
router.get("/universe/custom/status", wrap(async (_req, res) => {
  res.json(await runPython(["universe_custom_status"]));
}));

router.post("/universe/active", wrap(async (req, res) => {
  const active = req.body?.active_intraday_universe;
  if (active !== "NIFTY_50" && active !== "CUSTOM_LOW_PRICE_SECTOR") {
    res.status(400).json({ success: false, error: "Invalid universe mode" });
    return;
  }
  res.json(await runPython([
    "phase20_settings_update",
    JSON.stringify({ patch: { active_intraday_universe: active } }),
  ]));
}));

router.get("/universe/custom/symbols", wrap(async (_req, res) => {
  res.json(await runPython(["universe_custom_symbols"]));
}));

router.post("/universe/custom/refresh", wrap(async (_req, res) => {
  res.json(await runPython(["universe_custom_refresh"], 180_000));
}));

router.get("/universe/custom/report", wrap(async (_req, res) => {
  res.json(await runPython(["universe_custom_report"]));
}));

export default router;