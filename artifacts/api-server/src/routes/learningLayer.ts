/**
 * learningLayer.ts — Phase 10D
 * Routes for Learning Agent + Knowledge Agent + Learning Layer aggregation.
 *
 * READ-ONLY · ADVISORY-ONLY
 * No model retraining, no parameter tuning, no automatic optimisation.
 * All outputs require operator review before adoption.
 */
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
      try { resolve(JSON.parse(stdout)); }
      catch { reject(new Error(code !== 0 ? (stderr || stdout) : "Invalid JSON from Python")); }
    });
  });
}

const handle = (cmd: string, timeout?: number) =>
  async (_req: any, res: any) => {
    try { res.json(await runPython([cmd], timeout)); }
    catch (e: any) { res.status(500).json({ error: e.message }); }
  };

// ── Learning Agent ────────────────────────────────────────────────────────────
router.get("/learning-layer/learning/snapshot", handle("agent_learning_snapshot", 120_000));
router.get("/learning-layer/learning/metrics",  handle("agent_learning_metrics",   90_000));
router.get("/learning-layer/learning/insights", handle("agent_learning_insights",  90_000));
router.get("/learning-layer/learning/status",   handle("agent_learning_status",    30_000));

// ── Knowledge Agent ───────────────────────────────────────────────────────────
router.get("/learning-layer/knowledge/snapshot", handle("agent_knowledge_snapshot", 120_000));
router.get("/learning-layer/knowledge/patterns", handle("agent_knowledge_patterns",  90_000));
router.get("/learning-layer/knowledge/lessons",  handle("agent_knowledge_lessons",   90_000));
router.get("/learning-layer/knowledge/memory",   handle("agent_knowledge_memory",    90_000));
router.get("/learning-layer/knowledge/status",   handle("agent_knowledge_status",    30_000));

// Knowledge search (query param: ?q=...)
router.get("/learning-layer/knowledge/search", async (req: any, res: any) => {
  try {
    const q = (req.query.q as string) || "";
    res.json(await runPython(["agent_knowledge_search", q], 60_000));
  } catch (e: any) { res.status(500).json({ error: e.message }); }
});

// ── Learning Layer Aggregate ──────────────────────────────────────────────────
router.get("/learning-layer/summary",     handle("agent_learning_summary",     180_000));
router.get("/learning-layer/timeline",    handle("agent_learning_timeline",     120_000));
router.get("/learning-layer/performance", handle("agent_learning_performance",   60_000));

export { router as learningLayerRouter };
export default router;
