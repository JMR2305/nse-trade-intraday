/**
 * auth.ts — Session-based authentication middleware.
 *
 * All routes except explicitly public paths require a valid operator session
 * delivered via an HttpOnly cookie named `__session`.  The cookie is issued
 * by POST /api/auth/login after the operator supplies the SESSION_SECRET.
 *
 * Public paths (no session required):
 *   GET  /healthz         — liveness probe
 *   GET  /health/live     — liveness probe
 *   GET  /health/ready    — readiness probe
 *   POST /auth/login      — issues the session cookie (must be public)
 *   POST /auth/logout     — clears the session cookie (graceful even if invalid)
 *   GET  /auth/me         — returns 401 for unauthenticated callers (always safe)
 *
 * The browser sends the session cookie automatically on every same-origin
 * request, including EventSource (SSE), so no X-API-Key header or URL token
 * is needed in any client code.
 */

import { type Request, type Response, type NextFunction } from "express";
import { logger } from "./logger";
import { validateSession } from "./session";

// ── Public paths — no session required ───────────────────────────────────────

const PUBLIC_EXACT = new Set([
  "/healthz",
  "/health/live",
  "/health/ready",
  "/auth/login",
  "/auth/logout",
  "/auth/me",
]);

function isPublic(path: string): boolean {
  const bare = path.split("?")[0].replace(/\/+$/, "") || "/";
  return PUBLIC_EXACT.has(bare);
}

// ── Cookie helper ─────────────────────────────────────────────────────────────

/**
 * Extract a single field value from a Cookie header string.
 * Returns undefined when the field is absent.
 *
 * Exported so auth routes can reuse it without depending on cookie-parser.
 */
export function parseCookieField(cookieHeader: string, field: string): string | undefined {
  for (const part of cookieHeader.split(";")) {
    const [rawKey, ...rest] = part.split("=");
    if (rawKey.trim() === field) {
      return rest.join("=").trim() || undefined;
    }
  }
  return undefined;
}

// ── Middleware ────────────────────────────────────────────────────────────────

export function requireApiKey(
  req: Request,
  res: Response,
  next: NextFunction,
): void {
  if (isPublic(req.path)) {
    next();
    return;
  }

  const token = parseCookieField(req.headers.cookie ?? "", "__session");
  if (token && validateSession(token)) {
    next();
    return;
  }

  logger.warn(
    { method: req.method, path: req.path, ip: req.ip },
    "Rejected unauthenticated request",
  );
  res.status(401).json({ success: false, error: "Unauthorized" });
}
