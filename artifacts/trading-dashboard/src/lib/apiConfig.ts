/**
 * API configuration for the NSE Trading Dashboard (ApexQuant AI).
 *
 * Priority chain for API base URL:
 *   1. VITE_API_BASE_URL  — explicit URL (set in production or custom deployments)
 *   2. /api               — relative fallback (works on Replit via path-based proxy)
 *
 * Priority chain for SSE origin:
 *   1. VITE_WS_BASE_URL   — explicit SSE origin override
 *   2. same as API base   — shares origin with API by default
 *
 * Production guard: any resolved URL that contains localhost/127.0.0.1/0.0.0.0
 * throws a ConfigurationError at module evaluation time, before any component mounts.
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

function guardProduction(url: string, varName: string): void {
  if (import.meta.env.PROD && url && containsLocalhost(url)) {
    throw new ConfigurationError(
      `${varName} resolves to "${url}", which contains localhost/127.0.0.1. ` +
        "Production builds must use an HTTPS URL. " +
        `Set ${varName}=https://<deployment-domain> to fix this.`,
    );
  }
}

// ── URL resolution ───────────────────────────────────────────────────────────

const _rawApiBase = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";

/**
 * API base URL — used as the prefix for all API fetch calls.
 * Example values:
 *   - "/api"                           (default dev fallback)
 *   - "https://abc.repl.co/api"        (explicit prod URL)
 */
export const API_BASE_URL: string = _rawApiBase
  ? stripTrailingSlash(_rawApiBase)
  : "/api";

const _rawSseBase = (import.meta.env.VITE_WS_BASE_URL as string | undefined) ?? "";

/**
 * SSE base URL — used for the EventSource connection.
 * Defaults to the same origin as the API.
 */
export const SSE_BASE_URL: string = _rawSseBase
  ? stripTrailingSlash(_rawSseBase)
  : API_BASE_URL;

/** Full URL for the SSE stream endpoint. */
export const SSE_STREAM_URL: string = `${SSE_BASE_URL}/stream`;

// ── Production guards ────────────────────────────────────────────────────────

guardProduction(API_BASE_URL, "VITE_API_BASE_URL");
guardProduction(SSE_BASE_URL, "VITE_WS_BASE_URL");

// ── Public helpers ───────────────────────────────────────────────────────────

/**
 * Build a full API URL for a given path.
 * Paths that already start with "/" are joined directly; others get a "/" prepended.
 */
export function buildApiUrl(path: string): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE_URL}${p}`;
}

/**
 * API_BASE — backward-compatible alias used by existing hooks.
 * New code should prefer API_BASE_URL or buildApiUrl().
 * @deprecated Use API_BASE_URL from this module instead.
 */
export const API_BASE: string = API_BASE_URL;
