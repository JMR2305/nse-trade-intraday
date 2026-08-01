/**
 * security.ts — Phase 8.6
 * Security & Compliance Centre API routes.
 *
 * READ-ONLY. ADVISORY-ONLY.
 * Never modifies secrets, credentials, users, feature flags,
 * configuration, services, orders, portfolio, or trading state.
 */
import { Router } from "express";
import { spawn }  from "child_process";
import path       from "path";
import { PYTHON_BIN, PYTHON_DIR } from "../lib/python-env";

const router = Router();

function runPython(args: string[], timeoutMs = 90_000): Promise<any> {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], { cwd: PYTHON_DIR });
    let stdout = "", stderr = "";
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      proc.kill("SIGTERM");
      reject(new Error(`Python timed out after ${timeoutMs / 1000}s`));
    }, timeoutMs);
    proc.stdout.on("data", (d: Buffer) => { stdout += d.toString(); });
    proc.stderr.on("data", (d: Buffer) => { stderr += d.toString(); });
    proc.on("close", (code) => {
      clearTimeout(timer);
      if (timedOut) return;
      if (code !== 0) {
        try { const p = JSON.parse(stdout.trim()); if (p.error) return reject(new Error(p.error)); } catch {}
        reject(new Error(stderr || `Python exited ${code}`));
      } else {
        try { resolve(JSON.parse(stdout.trim())); }
        catch { reject(new Error(`Failed to parse Python output: ${stdout.slice(0, 200)}`)); }
      }
    });
    proc.on("error", (err) => { clearTimeout(timer); reject(err); });
  });
}

const handle = (cmd: string, timeout?: number) => async (_req: any, res: any) => {
  try { res.json(await runPython([cmd], timeout)); }
  catch (e: any) { res.status(500).json({ error: e.message }); }
};

// ── GET /api/security/* ────────────────────────────────────────────────────────

router.get("/security/summary",      handle("sec_summary"));
router.get("/security/auth",         handle("sec_auth"));
router.get("/security/sessions",     handle("sec_sessions"));
router.get("/security/secrets",      handle("sec_secrets"));
router.get("/security/config",       handle("sec_config"));
router.get("/security/api",          handle("sec_api"));
router.get("/security/dependencies", handle("sec_dependencies", 60_000));
router.get("/security/audit",        handle("sec_audit"));
router.get("/security/compliance",   handle("sec_compliance", 60_000));
router.get("/security/alerts",       handle("sec_alerts"));
router.get("/security/snapshot",     handle("sec_snapshot"));

// Export — supports ?format=csv or ?format=json (default json)
router.get("/security/export", async (req: any, res: any) => {
  const fmt = String(req.query.format ?? "json").toLowerCase();
  try {
    const data = await runPython([fmt === "csv" ? "sec_export_csv" : "sec_export_json"], 90_000);
    if (fmt === "csv") {
      const csv = typeof data === "object" ? (data as any).csv ?? "" : String(data);
      res.setHeader("Content-Type", "text/csv");
      res.setHeader("Content-Disposition", `attachment; filename="security_export_${new Date().toISOString().slice(0,10)}.csv"`);
      res.send(csv);
      return;
    }
    res.json(data);
  } catch (e: any) { res.status(500).json({ error: e.message }); }
});

export default router;
