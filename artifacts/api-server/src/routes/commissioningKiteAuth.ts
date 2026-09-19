// Task978ZI — Commissioning-safe Kite authentication routes.
//
// While HEALTH_ONLY_NO_SCHEDULERS=true, the commissioning router exposes only
// the health probes. Zerodha's redirect to /api/kite/callback therefore 404s
// and the daily durable token cannot be established. This router adds the
// MINIMUM authentication surface required for commissioning:
//
//   GET /api/kite/login     → redirect to the official Kite login page
//   GET /api/kite/callback  → env-only request-token exchange through the
//                             reviewed durable path:
//                             kite_session_manager.exchange_request_token()
//                             → kite_token_store.save_token()
//                             → phase20_store.kv_set_durable()
//                             → phase20_kv["kite_token_v1"]
//
// It intentionally does NOT expose quotes, LTP, holdings, positions, orders,
// margins, instruments, disconnect, diagnostics, or any other Kite or
// application route. The full Kite router (routes/kite.ts) remains mounted
// only in normal mode. No scheduler, scanner, portfolio, or order surface is
// touched: this module only spawns the same `main.py kite_exchange` child the
// reviewed normal-mode callback uses, and the Python exchange path performs
// read-only market-data session persistence (no broker calls).
//
// Secrets: the API secret stays in the process environment of the spawned
// child; the request token is transferred via child environment only (never
// argv); neither the request token, the access token, nor the API secret is
// ever logged, echoed, or returned.

import { Router, type IRouter } from "express";

const router: IRouter = Router();

// Safe commissioning completion page (path only — no query material, no
// token echo). The Zerodha redirect target can never include secret data.
const COMMISSIONING_KITE_PAGE = "/commissioning/kite";

const REQUEST_TOKEN_PATTERN = /^[A-Za-z0-9]{8,64}$/;

async function runKiteExchange(requestToken: string): Promise<{
  success: boolean;
  state?: string;
  error?: string;
}> {
  // Dynamic import mirrors routes/health.ts: commissioning mode must not
  // load the Python environment (or any runtime module) at router mount
  // time — only inside the explicit callback subprocess path.
  const [{ spawn }, path, { PYTHON_DIR, PYTHON_BIN }] = await Promise.all([
    import("node:child_process"),
    import("node:path"),
    import("../lib/python-env.js"),
  ]);

  return new Promise((resolve) => {
    // `kite_exchange` reads KITE_REQUEST_TOKEN from its environment only;
    // it is never placed in argv, so it cannot leak through process listings.
    const proc = spawn(
      PYTHON_BIN,
      [path.join(PYTHON_DIR, "main.py"), "kite_exchange"],
      {
        cwd: PYTHON_DIR,
        env: { ...process.env, KITE_REQUEST_TOKEN: requestToken },
      },
    );
    let stdout = "";
    let stderr = "";
    let settled = false;
    const finish = (result: { success: boolean; state?: string; error?: string }) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      proc.removeAllListeners();
      resolve(result);
    };
    const timer = setTimeout(() => {
      proc.kill("SIGKILL");
      finish({ success: false, error: "timeout" });
    }, 20_000);
    proc.stdout.on("data", (d: Buffer) => { stdout += d.toString(); });
    proc.stderr.on("data", (d: Buffer) => { stderr += d.toString(); });
    proc.on("error", () => finish({ success: false, error: "spawn_failed" }));
    proc.on("close", (code) => {
      if (code !== 0) {
        // Deliberately opaque: child stderr may carry framework internals.
        finish({ success: false, error: "exchange_failed" });
        return;
      }
      try {
        const parsed = JSON.parse(stdout.trim()) as {
          success?: boolean;
          state?: string;
        };
        // Only the reviewed success contract is honored: success=true is
        // returned by main.py kite_exchange solely after
        // kite_token_store.save_token() durably committed phase20_kv
        // ["kite_token_v1"]. Token material is absent from the payload.
        finish({
          success: parsed.success === true,
          state: typeof parsed.state === "string" ? parsed.state : undefined,
        });
      } catch {
        finish({ success: false, error: "bad_python_output" });
      }
    });
  });
}

// GET /api/kite/login — redirect to the official Zerodha Kite login page.
router.get("/kite/login", (_req, res) => {
  const apiKey = process.env.ZERODHA_API_KEY || "";
  if (!apiKey) {
    return res.redirect(`${COMMISSIONING_KITE_PAGE}?auth=failed&reason=not_configured`);
  }
  // The API secret is never part of the login URL — only the public key.
  const loginUrl = `https://kite.zerodha.com/connect/login?api_key=${encodeURIComponent(apiKey)}&v=3`;
  res.redirect(loginUrl);
});

// GET /api/kite/callback — Zerodha redirects here with request_token & status.
router.get("/kite/callback", async (req, res) => {
  const status = String(req.query.status ?? "");
  const requestToken = typeof req.query.request_token === "string"
    ? req.query.request_token.trim()
    : "";

  // Fail closed on failed, missing, or malformed login responses.
  if (status !== "success") {
    return res.redirect(`${COMMISSIONING_KITE_PAGE}?auth=failed&reason=login_failed`);
  }
  if (!requestToken || !REQUEST_TOKEN_PATTERN.test(requestToken)) {
    return res.redirect(`${COMMISSIONING_KITE_PAGE}?auth=failed&reason=missing_token`);
  }

  let result: { success: boolean; state?: string; error?: string };
  try {
    result = await runKiteExchange(requestToken);
  } catch {
    // No error details are logged or echoed — they could carry token material.
    result = { success: false, error: "exchange_failed" };
  }
  if (!result.success) {
    return res.redirect(`${COMMISSIONING_KITE_PAGE}?auth=failed&reason=exchange_failed`);
  }
  // Success is claimed only after the durable save path has confirmed the
  // phase20_kv write (enforced inside the reviewed Python exchange flow).
  res.redirect(`${COMMISSIONING_KITE_PAGE}?auth=success`);
});

export default router;
