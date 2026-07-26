/**
 * session.ts — In-memory session store for operator authentication.
 *
 * Sessions are keyed by a cryptographically random 32-byte hex token stored
 * in an HttpOnly cookie. A background interval evicts expired sessions.
 *
 * Single-operator model: there is no per-user table. Any caller who presents
 * a valid session token is treated as the authenticated operator.
 *
 * TTL: 24 hours. The operator must re-login after the session expires.
 */

import { randomBytes } from "crypto";

interface Session {
  expiresAt: number;
}

const SESSION_TTL_MS = 24 * 60 * 60 * 1000; // 24 hours
const CLEANUP_INTERVAL_MS = 5 * 60 * 1000;   // sweep every 5 min

const store = new Map<string, Session>();

/** Create a new session and return its token. */
export function createSession(): string {
  const token = randomBytes(32).toString("hex");
  store.set(token, { expiresAt: Date.now() + SESSION_TTL_MS });
  return token;
}

/** Returns true when the token exists and has not expired. */
export function validateSession(token: string): boolean {
  const session = store.get(token);
  if (!session) return false;
  if (Date.now() > session.expiresAt) {
    store.delete(token);
    return false;
  }
  return true;
}

/** Invalidate a session (logout). No-op for unknown tokens. */
export function deleteSession(token: string): void {
  store.delete(token);
}

// Background cleanup — prevents unbounded memory growth from expired sessions.
const _cleanup = setInterval(() => {
  const now = Date.now();
  for (const [token, session] of store) {
    if (now > session.expiresAt) store.delete(token);
  }
}, CLEANUP_INTERVAL_MS);
_cleanup.unref(); // don't block process exit
