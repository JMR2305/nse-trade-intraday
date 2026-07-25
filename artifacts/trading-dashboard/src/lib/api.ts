/**
 * Dashboard API client — ApexQuant AI.
 *
 * API_BASE is now resolved from apiConfig (VITE_API_BASE_URL env var with
 * Replit dev-domain fallback and production localhost guard).
 *
 * apiJson wraps fetch with:
 *   - AbortController timeout (15 s default, 10 s for health calls)
 *   - Typed ApiError with status, endpoint context
 *   - HTML error-page detection
 *   - Non-JSON body handling
 */

export { API_BASE_URL as API_BASE } from "./apiConfig";
import { API_BASE_URL } from "./apiConfig";

// ── Timeout constants (re-exported for hooks that want to reference them) ──

export const DEFAULT_TIMEOUT_MS = 15_000;
export const HEALTH_TIMEOUT_MS = 10_000;

// ── Error class ───────────────────────────────────────────────────────────────

export class ApiError extends Error {
  status: number;
  endpoint: string;
  constructor(message: string, status: number, endpoint: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.endpoint = endpoint;
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

function shorten(text: string, max = 200): string {
  const t = text.trim().replace(/\s+/g, " ");
  return t.length > max ? `${t.slice(0, max)}…` : t;
}

// ── Core fetch wrapper ────────────────────────────────────────────────────────

/**
 * Safe JSON fetch with AbortController timeout.
 *
 * @param path    API path relative to API_BASE (e.g. "/health/live")
 * @param init    Standard RequestInit options
 * @param timeoutMs  Per-request timeout in ms (default 15 s; use 10 s for health probes)
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export async function apiJson<T = any>(
  path: string,
  init?: RequestInit,
  timeoutMs = DEFAULT_TIMEOUT_MS,
): Promise<T> {
  const url = path.startsWith("/")
    ? `${API_BASE_URL}${path}`
    : `${API_BASE_URL}/${path}`;

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  let res: Response;
  try {
    res = await fetch(url, {
      ...init,
      signal: controller.signal,
    });
  } catch (e) {
    clearTimeout(timeoutId);
    if (e instanceof Error && e.name === "AbortError") {
      throw new ApiError(
        `Request timed out after ${timeoutMs / 1000}s`,
        408,
        url,
      );
    }
    throw new ApiError(`Network error contacting ${url}: ${String(e)}`, 0, url);
  }
  clearTimeout(timeoutId);

  const contentType = res.headers.get("content-type") || "";
  const text = await res.text();

  if (!text.trim()) {
    if (res.ok) return {} as T;
    throw new ApiError(
      `Server returned an empty response (HTTP ${res.status}) from ${url}`,
      res.status,
      url,
    );
  }

  const looksHtml =
    contentType.includes("text/html") ||
    /^\s*<!doctype html|^\s*<html/i.test(text);
  if (looksHtml) {
    throw new ApiError(
      `Expected JSON but received HTML from ${url} (HTTP ${res.status}). ` +
        "The API route may be misrouted.",
      res.status,
      url,
    );
  }

  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    throw new ApiError(
      `Invalid JSON from ${url} (HTTP ${res.status}): ${shorten(text)}`,
      res.status,
      url,
    );
  }

  if (!res.ok || (data && typeof data === "object" && (data as Record<string, unknown>).error)) {
    const msg =
      (data &&
        typeof data === "object" &&
        "error" in data &&
        (typeof (data as Record<string, unknown>).error === "string"
          ? (data as Record<string, unknown>).error
          : ((data as Record<string, unknown>).error as Record<string, unknown>)?.message)) ||
      `HTTP ${res.status}`;
    throw new ApiError(String(msg), res.status, url);
  }

  return data as T;
}

/**
 * Convenience wrapper for health/liveness endpoints — uses the 10 s timeout.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function healthJson<T = any>(path: string): Promise<T> {
  return apiJson<T>(path, undefined, HEALTH_TIMEOUT_MS);
}
