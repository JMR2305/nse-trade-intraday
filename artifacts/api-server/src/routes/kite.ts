// Phase 19 — Zerodha Kite Connect live-data integration routes.
// READ-ONLY: quotes, holdings, positions, margins, orders, instruments.
// All order placement, modification, and cancellation endpoints are
// intentionally absent — those remain in the existing execution engine
// behind the two-step confirm flow and kill-switch (paper mode default).

import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import path from "path";

const router: IRouter = Router();
import { PYTHON_DIR, PYTHON_BIN } from "../lib/python-env";

function runPython(
  args: string[],
  timeoutMs = 30_000,
  extraEnv?: Record<string, string>,
): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], {
      cwd: PYTHON_DIR,
      env: extraEnv ? { ...process.env, ...extraEnv } : process.env,
    });
    let stdout = "";
    let stderr = "";
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
        try {
          const parsed = JSON.parse(stdout.trim());
          if (parsed.error) return reject(new Error(parsed.error));
        } catch { /* ignore */ }
        reject(new Error(stderr || `Python exited ${code}`));
      } else {
        try { resolve(JSON.parse(stdout.trim())); }
        catch { reject(new Error(`Failed to parse Python output: ${stdout.slice(0, 200)}`)); }
      }
    });
    proc.on("error", (err) => { clearTimeout(timer); reject(err); });
  });
}

const wrap = (fn: (req: any, res: any) => Promise<void>) =>
  async (req: any, res: any) => {
    try { await fn(req, res); }
    catch (err: unknown) {
      res.status(500).json({
        success: false,
        error: err instanceof Error ? err.message : String(err),
      });
    }
  };

// ── Session & connection ────────────────────────────────────────────────────

// GET /api/kite/status  — token health, session status, login URL
router.get("/kite/status", wrap(async (req, res) => {
  const force = req.query.force === "true";
  const args = ["kite_status"];
  if (force) args.push("--force");

  // Derive the public-facing callback URL from the request so operators
  // always see the exact URL they must register in the Zerodha developer
  // console.  Replit's reverse proxy sets x-forwarded-proto and
  // x-forwarded-host; we fall back gracefully for direct/localhost calls.
  const proto = (req.headers["x-forwarded-proto"] as string | undefined)
    ?? req.protocol
    ?? "https";
  const host  = (req.headers["x-forwarded-host"] as string | undefined)
    ?? (req.headers["host"] as string | undefined)
    ?? "unknown";
  // Strip any port from the forwarded-host so the URL stays clean.
  const publicHost = host.split(":")[0];
  const expectedCallbackUrl = process.env.KITE_CALLBACK_URL
    ?? `${proto}://${publicHost}/api/kite/callback`;

  const result = await runPython(args, 15_000, {
    KITE_CALLBACK_URL: expectedCallbackUrl,
  }) as Record<string, unknown>;

  // Always include the expected callback URL at the top level so the
  // frontend can display it for Zerodha developer console configuration.
  result.expected_callback_url = expectedCallbackUrl;

  res.json(result);
}));

// ── Phase 19A: secure login + callback flow ────────────────────────────────
// The API secret, SHA-256 checksum, request token, and access token are
// handled backend-only. They are never included in any response, log,
// export, or frontend state.

const DASHBOARD_KITE_PAGE = "/trading-dashboard/kite-connect";

// GET /api/kite/login — redirect the user to the official Zerodha Kite login
router.get("/kite/login", (_req, res) => {
  const apiKey = process.env.ZERODHA_API_KEY || "";
  if (!apiKey) {
    return res.redirect(`${DASHBOARD_KITE_PAGE}?auth=failed&reason=not_configured`);
  }
  const loginUrl = `https://kite.zerodha.com/connect/login?api_key=${encodeURIComponent(apiKey)}&v=3`;
  res.redirect(loginUrl);
});

// GET /api/kite/callback — Zerodha redirects here with request_token & status
router.get("/kite/callback", async (req, res) => {
  const status = String(req.query.status ?? "");
  const requestToken = typeof req.query.request_token === "string"
    ? req.query.request_token.trim()
    : "";

  // Reject failed, missing, or malformed login responses outright.
  if (status !== "success") {
    return res.redirect(`${DASHBOARD_KITE_PAGE}?auth=failed&reason=login_failed`);
  }
  if (!requestToken || !/^[A-Za-z0-9]{8,64}$/.test(requestToken)) {
    return res.redirect(`${DASHBOARD_KITE_PAGE}?auth=failed&reason=missing_token`);
  }

  try {
    // Token exchange happens entirely in the Python backend; the request
    // token is passed via env (not argv) and nothing secret is returned.
    const result = (await runPython(["kite_exchange"], 20_000, {
      KITE_REQUEST_TOKEN: requestToken,
    })) as { success?: boolean };
    if (result && result.success) {
      return res.redirect(`${DASHBOARD_KITE_PAGE}?auth=success`);
    }
    return res.redirect(`${DASHBOARD_KITE_PAGE}?auth=failed&reason=exchange_failed`);
  } catch {
    // Deliberately do not log or echo error details that could carry tokens.
    return res.redirect(`${DASHBOARD_KITE_PAGE}?auth=failed&reason=exchange_failed`);
  }
});

// POST /api/kite/disconnect — clear the backend-stored access token
router.post("/kite/disconnect", wrap(async (_req, res) => {
  const result = await runPython(["kite_disconnect"], 10_000) as {
    success?: boolean;
  };
  if (!result.success) {
    return res.status(503).json(result);
  }
  res.json(result);
}));

// POST /api/kite/invalidate  — flush probe cache (forces fresh probe on next status call)
router.post("/kite/invalidate", wrap(async (_req, res) => {
  res.json(await runPython(["kite_invalidate"], 10_000));
}));

// ── Market data (read-only) ─────────────────────────────────────────────────

// GET /api/kite/quote?symbols=RELIANCE,TCS,INFY
router.get("/kite/quote", wrap(async (req, res) => {
  const raw = req.query.symbols as string | undefined;
  if (!raw) {
    return res.status(400).json({ success: false, error: "symbols query param required" });
  }
  const symbols = raw.split(",").map((s: string) => s.trim().toUpperCase()).filter(Boolean);
  if (symbols.length === 0) {
    return res.status(400).json({ success: false, error: "No valid symbols provided" });
  }
  res.json(await runPython(["kite_quote", symbols.join(",")], 20_000));
}));

// GET /api/kite/ltp?symbols=RELIANCE,TCS
router.get("/kite/ltp", wrap(async (req, res) => {
  const raw = req.query.symbols as string | undefined;
  if (!raw) {
    return res.status(400).json({ success: false, error: "symbols query param required" });
  }
  const symbols = raw.split(",").map((s: string) => s.trim().toUpperCase()).filter(Boolean);
  res.json(await runPython(["kite_ltp", symbols.join(",")], 20_000));
}));

// ── Account data (read-only) ────────────────────────────────────────────────

// GET /api/kite/holdings  — Demat holdings from broker (read-only display)
router.get("/kite/holdings", wrap(async (_req, res) => {
  res.json(await runPython(["kite_holdings"], 15_000));
}));

// GET /api/kite/positions  — Intraday/overnight positions (read-only display)
router.get("/kite/positions", wrap(async (_req, res) => {
  res.json(await runPython(["kite_positions"], 15_000));
}));

// GET /api/kite/margins  — Available cash / margin (read-only display)
router.get("/kite/margins", wrap(async (_req, res) => {
  res.json(await runPython(["kite_margins"], 15_000));
}));

// GET /api/kite/orders?limit=50  — Order history sync (read-only display)
router.get("/kite/orders", wrap(async (req, res) => {
  const limit = Number(req.query.limit) || 50;
  res.json(await runPython(["kite_orders", String(Math.min(limit, 200))], 15_000));
}));

// ── Instrument search ───────────────────────────────────────────────────────

// GET /api/kite/instruments/search?q=RELI&limit=20
router.get("/kite/instruments/search", wrap(async (req, res) => {
  const q = String(req.query.q || "").trim();
  const limit = Number(req.query.limit) || 20;
  res.json(await runPython(["kite_instrument_search", q, String(limit)], 30_000));
}));

// POST /api/kite/instruments/refresh  — Force-refresh daily instrument cache
router.post("/kite/instruments/refresh", wrap(async (_req, res) => {
  res.json(await runPython(["kite_instrument_refresh", "--force"], 60_000));
}));

// GET /api/kite/instruments/status  — Cache metadata
router.get("/kite/instruments/status", wrap(async (_req, res) => {
  res.json(await runPython(["kite_instrument_cache_status"], 10_000));
}));

// ── Diagnostics ─────────────────────────────────────────────────────────────

// GET /api/kite/diagnostics  — Full connectivity + provider + data freshness report
router.get("/kite/diagnostics", wrap(async (_req, res) => {
  res.json(await runPython(["kite_diagnostics"], 30_000));
}));

// ── Safety notice (no order endpoints here — intentional) ──────────────────
// Order placement remains in /api/broker/order/preview + confirm1 + confirm2
// behind the paper-trading default and kill-switch.

export default router;
