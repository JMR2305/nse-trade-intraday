/**
 * auth.ts — Operator authentication routes.
 *
 * POST /api/auth/login   — validate password, issue HttpOnly session cookie
 * POST /api/auth/logout  — invalidate session, clear cookie
 * GET  /api/auth/me      — check current session validity
 *
 * These routes are explicitly exempted from the requireApiKey middleware so
 * the login endpoint itself does not require an existing session.
 *
 * Password: the value of the SESSION_SECRET environment variable.
 * The operator enters this in the login form. It is never sent to the browser
 * and never embedded in built assets.
 */

import { Router, type IRouter } from "express";
import { logger } from "../lib/logger";
import { createSession, validateSession, deleteSession } from "../lib/session";
import { parseCookieField } from "../lib/auth";

const router: IRouter = Router();

const OPERATOR_PASSWORD = process.env["SESSION_SECRET"]?.trim() ?? "";

if (!OPERATOR_PASSWORD) {
  logger.warn(
    "SESSION_SECRET is not set. No operator will be able to log in. " +
      "Set SESSION_SECRET in the environment.",
  );
}

/**
 * Constant-time string comparison to prevent timing oracle attacks.
 * Returns false immediately when lengths differ (length is not secret here
 * since both values are fixed-length secrets, but we still iterate to keep
 * timing consistent).
 */
function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) {
    let diff = 0;
    for (let i = 0; i < b.length; i++) diff |= b.charCodeAt(i) ^ b.charCodeAt(i);
    return false;
  }
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

// POST /api/auth/login
router.post("/auth/login", (req, res) => {
  const password = String(req.body?.password ?? "");

  if (!OPERATOR_PASSWORD || !timingSafeEqual(password, OPERATOR_PASSWORD)) {
    logger.warn({ ip: req.ip }, "Failed operator login attempt");
    // Respond after a short fixed delay so timing doesn't reveal whether
    // the secret is set at all vs. wrong password.
    setTimeout(() => {
      res.status(401).json({ success: false, error: "Invalid credentials" });
    }, 300);
    return;
  }

  const token = createSession();
  const isProduction = process.env.NODE_ENV === "production";

  res.cookie("__session", token, {
    httpOnly: true,          // not readable by JS
    sameSite: "lax",         // CSRF protection for cross-site POST
    secure: isProduction,    // HTTPS-only in production
    maxAge: 24 * 60 * 60 * 1000, // 24 h
    path: "/",               // covers /api/* and the dashboard root
  });

  logger.info({ ip: req.ip }, "Operator login successful");
  res.json({ success: true });
});

// POST /api/auth/logout
router.post("/auth/logout", (req, res) => {
  const token = parseCookieField(req.headers.cookie ?? "", "__session");
  if (token) deleteSession(token);
  res.clearCookie("__session", { path: "/" });
  res.json({ success: true });
});

// GET /api/auth/me — lightweight session check used by the dashboard on load
router.get("/auth/me", (req, res) => {
  const token = parseCookieField(req.headers.cookie ?? "", "__session");
  if (token && validateSession(token)) {
    res.json({ authenticated: true });
  } else {
    res.status(401).json({ authenticated: false });
  }
});

export default router;
