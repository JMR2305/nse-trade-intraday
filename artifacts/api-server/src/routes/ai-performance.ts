/**
 * ai-performance.ts — Phase 5D.4 AI Performance Intelligence API routes.
 *
 * 6 read-only endpoints:
 *   GET /api/ai/summary
 *   GET /api/ai/confidence
 *   GET /api/ai/calibration
 *   GET /api/ai/predictions
 *   GET /api/ai/recommendations
 *   GET /api/ai/learning
 *
 * AI_PERFORMANCE_ENABLED=false → every endpoint returns { "status": "DISABLED" }.
 * No order submission. No strategy modification. No portfolio mutation.
 * PAPER TRADING / ADVISORY ONLY.
 */
import { Router } from "express";
import { spawn } from "child_process";
import path from "path";
import { PYTHON_DIR, PYTHON_BIN } from "../lib/python-env";

const router = Router();

function runPython(args: string[]): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const child = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], {
      cwd: PYTHON_DIR,
      env: process.env,
    });
    let out = "";
    let err = "";
    child.stdout.on("data", (d: Buffer) => { out += d.toString(); });
    child.stderr.on("data", (d: Buffer) => { err += d.toString(); });
    child.on("error", (e: Error) => reject(e));
    child.on("close", (code) => {
      try {
        resolve(JSON.parse(out));
      } catch {
        reject(new Error(code !== 0 ? err || `exit ${code}` : `Bad JSON: ${out.slice(0, 200)}`));
      }
    });
  });
}

router.get("/ai/summary",         async (req, res) => { try { res.json(await runPython(["ai_summary"]));         } catch (e) { res.status(500).json({ error: String(e) }); } });
router.get("/ai/confidence",      async (req, res) => { try { res.json(await runPython(["ai_confidence"]));      } catch (e) { res.status(500).json({ error: String(e) }); } });
router.get("/ai/calibration",     async (req, res) => { try { res.json(await runPython(["ai_calibration"]));     } catch (e) { res.status(500).json({ error: String(e) }); } });
router.get("/ai/predictions",     async (req, res) => { try { res.json(await runPython(["ai_predictions"]));     } catch (e) { res.status(500).json({ error: String(e) }); } });
router.get("/ai/recommendations", async (req, res) => { try { res.json(await runPython(["ai_recommendations"])); } catch (e) { res.status(500).json({ error: String(e) }); } });
router.get("/ai/learning",        async (req, res) => { try { res.json(await runPython(["ai_learning"]));        } catch (e) { res.status(500).json({ error: String(e) }); } });

export default router;
