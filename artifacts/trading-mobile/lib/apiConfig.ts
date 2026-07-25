/**
 * API configuration for the NSE Trading Mobile app (ApexQuant AI).
 *
 * Priority chain for API base URL:
 *   1. EXPO_PUBLIC_API_BASE_URL — explicit full URL (recommended for production)
 *   2. EXPO_PUBLIC_DOMAIN       — Replit dev domain; constructs https://<domain>/api
 *   3. /api                     — relative fallback (custom deployments with same-origin serving)
 *
 * Priority chain for SSE/WebSocket origin:
 *   1. EXPO_PUBLIC_WS_BASE_URL  — explicit SSE origin override
 *   2. EXPO_PUBLIC_API_BASE_URL — same origin as API
 *   3. EXPO_PUBLIC_DOMAIN-based URL
 *
 * Production guard: if the resolved API URL contains localhost/127.0.0.1, a
 * ConfigurationError is thrown at module load time.
 *
 * Trailing slashes are always stripped on resolved URLs.
 */

// ── Configuration error ─────────────────────────────────────────────────────

export class ConfigurationError extends Error {
  readonly name = "ConfigurationError";
  constructor(message: string) {
    super(message);
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function stripTrailingSlash(url: string): string {
  return url.replace(/\/+$/, "");
}

function containsLocalhost(url: string): boolean {
  return /localhost|127\.0\.0\.1|0\.0\.0\.0/.test(url);
}

// ── URL resolution ───────────────────────────────────────────────────────────

function resolveApiBaseUrl(): string {
  // 1. Explicit env var (highest priority)
  const explicit = process.env.EXPO_PUBLIC_API_BASE_URL;
  if (explicit) return stripTrailingSlash(explicit);

  // 2. Replit dev domain — constructs https://<domain>/api
  const domain = process.env.EXPO_PUBLIC_DOMAIN;
  if (domain) return `https://${domain}/api`;

  // 3. Relative fallback
  return "/api";
}

function resolveSseBaseUrl(apiBase: string): string {
  const explicit = process.env.EXPO_PUBLIC_WS_BASE_URL;
  if (explicit) return stripTrailingSlash(explicit);
  return apiBase;
}

/**
 * Resolved API base URL.
 * Used as the prefix for all API fetch calls in monitorApi.ts.
 */
export const API_BASE_URL: string = resolveApiBaseUrl();

/**
 * Resolved SSE/WS base URL.
 * Used for the SSE stream endpoint.
 */
export const SSE_BASE_URL: string = resolveSseBaseUrl(API_BASE_URL);

/** Full URL for the SSE stream endpoint. */
export const SSE_STREAM_URL: string = `${SSE_BASE_URL}/stream`;

// ── Production guard ─────────────────────────────────────────────────────────
// Expo bakes EXPO_PUBLIC_* at bundle time. The __DEV__ flag is true in the
// Expo dev client but false in production builds and EAS builds.
if (!__DEV__ && containsLocalhost(API_BASE_URL)) {
  throw new ConfigurationError(
    `EXPO_PUBLIC_API_BASE_URL resolves to "${API_BASE_URL}", which contains localhost/127.0.0.1. ` +
      "Production builds must use an HTTPS URL. " +
      "Set EXPO_PUBLIC_API_BASE_URL=https://<deployment-domain>/api to fix this.",
  );
}

// ── Backward-compatible alias ────────────────────────────────────────────────

/**
 * BASE — backward-compatible alias used by existing monitorApi.ts code.
 * @deprecated Use API_BASE_URL from this module instead.
 */
export const BASE: string = API_BASE_URL;
