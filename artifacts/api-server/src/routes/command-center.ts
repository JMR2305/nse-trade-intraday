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

// ── In-flight coalescing + 30-second Node.js cache for the slow summary ──────
// cmd_center_summary aggregates 10+ subsystems and takes ~14 s.
// Without coalescing, every concurrent browser tab spawns a separate Python
// process. With coalescing, all waiters share one result.
const SUMMARY_TTL_MS = 30_000;
let summaryCache:    { data: unknown; ts: number } | null = null;
let summaryInFlight: Promise<unknown> | null = null;

export function clearCommandCenterCache() {
  summaryCache    = null;
  summaryInFlight = null;
}

async function getSummaryCoalesced(): Promise<unknown> {
  // Serve cached result if fresh
  if (summaryCache && Date.now() - summaryCache.ts < SUMMARY_TTL_MS) {
    return summaryCache.data;
  }
  // Coalesce concurrent callers onto one in-flight request
  if (summaryInFlight) return summaryInFlight;

  summaryInFlight = runPython(["cmd_center_summary"], 90_000).then((data) => {
    summaryCache    = { data, ts: Date.now() };
    summaryInFlight = null;
    return data;
  }).catch((err) => {
    summaryInFlight = null;
    throw err;
  });

  return summaryInFlight;
}

router.get("/command-center/summary", async (req: any, res: any) => {
  try {
    res.json(await getSummaryCoalesced());
  } catch (e: any) {
    res.status(500).json({ error: e.message });
  }
});

// /command-center/briefing aggregates many subsystems (~22 s) — coalesce + cache 30 s
const BRIEFING_TTL = 30_000;
let briefingCache:    { data: unknown; ts: number } | null = null;
let briefingInFlight: Promise<unknown> | null = null;

router.get("/command-center/briefing", async (_req: any, res: any) => {
  try {
    if (briefingCache && Date.now() - briefingCache.ts < BRIEFING_TTL) {
      res.json(briefingCache.data);
      return;
    }
    if (!briefingInFlight) {
      briefingInFlight = runPython(["cmd_center_briefing"], 60_000)
        .then((d) => { briefingCache = { data: d, ts: Date.now() }; return d; })
        .finally(() => { briefingInFlight = null; });
    }
    res.json(await briefingInFlight);
  } catch (e: any) {
    res.status(500).json({ error: e.message });
  }
});
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
