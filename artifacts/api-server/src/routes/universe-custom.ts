import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import path from "path";
import { PYTHON_BIN, PYTHON_DIR } from "../lib/python-env";

const router: IRouter = Router();

function retiredMutation(res: any): void {
  res.status(410).json({
    success: false,
    error: "retired_universe_mutation_route",
    replacement: "/api/universe/v1",
    message: "Direct active-universe changes are retired. Create and validate a draft revision through the authenticated versioned workflow.",
  });
}

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
  void req;
  retiredMutation(res);
}));

router.get("/universe/custom/symbols", wrap(async (_req, res) => {
  res.json(await runPython(["universe_custom_symbols"]));
}));

router.post("/universe/custom/refresh", wrap(async (_req, res) => {
  // Refreshing eligibility changes the current master and would bypass the
  // append-only revision workflow. It is deliberately not a management API.
  retiredMutation(res);
}));

// Retired direct-member mutation. The old admin header is intentionally not
// inspected: browser code must never carry an administrator credential.
router.post("/universe/custom/upsert", wrap(async (req, res) => {
  void req;
  retiredMutation(res);
}));

// Retired direct metadata mutation. Kite mapping is validated against a draft
// and captured with its immutable revision evidence instead.
router.post("/universe/custom/hydrate-instruments", wrap(async (req, res) => {
  void req;
  retiredMutation(res);
}));

router.get("/universe/custom/report", wrap(async (_req, res) => {
  res.json(await runPython(["universe_custom_report"]));
}));

export default router;