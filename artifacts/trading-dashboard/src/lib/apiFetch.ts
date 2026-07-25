/**
 * apiFetch — typed fetch wrapper for the NSE Trading Dashboard (ApexQuant AI).
 *
 * Wraps every API request with:
 *   - AbortController timeouts (10 s for health, 15 s for data, configurable for mutations)
 *   - Typed error classes so callers can distinguish failure modes without inspecting raw strings
 *   - Non-JSON and HTML error-page detection
 *   - Consistent trailing-slash handling via apiConfig
 *
 * Error taxonomy:
 *   TimeoutError  — AbortController fired; request took longer than timeoutMs
 *   OfflineError  — fetch() threw a network/DNS error before a response arrived
 *   HttpError     — server responded with a non-2xx status
 *   NonJsonError  — server responded with HTML or an unparseable body
 *   SchemaError   — response was valid JSON but did not match expected shape
 */

import { buildApiUrl } from "./apiConfig";

// ── Timeout constants ────────────────────────────────────────────────────────

/** Timeout for health/liveness probes. */
export const HEALTH_TIMEOUT_MS = 10_000;

/** Default timeout for normal data requests. */
export const DEFAULT_TIMEOUT_MS = 15_000;

/** Timeout for long-running operations (scan, backtest, optimiser). */
export const LONG_TIMEOUT_MS = 120_000;

// ── Typed error classes ──────────────────────────────────────────────────────

export class TimeoutError extends Error {
  readonly name = "TimeoutError" as const;
  readonly timeoutMs: number;
  readonly url: string;
  constructor(url: string, timeoutMs: number) {
    super(`Request timed out after ${timeoutMs / 1000}s: ${url}`);
    Object.setPrototypeOf(this, new.target.prototype);
    this.timeoutMs = timeoutMs;
    this.url = url;
  }
}

export class OfflineError extends Error {
  readonly name = "OfflineError" as const;
  readonly url: string;
  readonly cause: unknown;
  constructor(url: string, cause: unknown) {
    const detail = cause instanceof Error ? cause.message : String(cause);
    super(`Network error contacting ${url}: ${detail}`);
    Object.setPrototypeOf(this, new.target.prototype);
    this.url = url;
    this.cause = cause;
  }
}

export class HttpError extends Error {
  readonly name = "HttpError" as const;
  readonly status: number;
  readonly url: string;
  readonly data: unknown;
  constructor(status: number, url: string, data: unknown) {
    const detail =
      data && typeof data === "object" && "error" in data
        ? String((data as Record<string, unknown>).error)
        : `HTTP ${status}`;
    super(detail);
    Object.setPrototypeOf(this, new.target.prototype);
    this.status = status;
    this.url = url;
    this.data = data;
  }
}

export class NonJsonError extends Error {
  readonly name = "NonJsonError" as const;
  readonly status: number;
  readonly url: string;
  readonly contentType: string | null;
  constructor(status: number, url: string, contentType: string | null) {
    super(
      `Expected JSON but received ${contentType ?? "unknown content-type"} ` +
        `from ${url} (HTTP ${status}). The API route may be misrouted.`,
    );
    Object.setPrototypeOf(this, new.target.prototype);
    this.status = status;
    this.url = url;
    this.contentType = contentType;
  }
}

export class SchemaError extends Error {
  readonly name = "SchemaError" as const;
  readonly url: string;
  readonly cause: unknown;
  constructor(url: string, cause: unknown) {
    const detail = cause instanceof Error ? cause.message : String(cause);
    super(`Response from ${url} did not match expected schema: ${detail}`);
    Object.setPrototypeOf(this, new.target.prototype);
    this.url = url;
    this.cause = cause;
  }
}

/** Union of all typed fetch errors produced by apiFetch. */
export type FetchError =
  | TimeoutError
  | OfflineError
  | HttpError
  | NonJsonError
  | SchemaError;

// ── Core fetch wrapper ───────────────────────────────────────────────────────

export interface ApiFetchOptions extends RequestInit {
  /**
   * Request timeout in milliseconds.
   * Defaults to DEFAULT_TIMEOUT_MS (15 s).
   * Use HEALTH_TIMEOUT_MS (10 s) for health probes.
   * Use LONG_TIMEOUT_MS (120 s) for scan/backtest mutations.
   */
  timeoutMs?: number;
  /**
   * When true, `path` is treated as an absolute URL and is not prefixed
   * by buildApiUrl(). Use for external URLs or pre-built absolute paths.
   */
  absoluteUrl?: boolean;
}

/**
 * Core fetch wrapper. Returns parsed JSON or throws a typed FetchError.
 *
 * @param path  API path (e.g. "/health/live") or absolute URL when absoluteUrl=true
 * @param options  RequestInit + apiFetch-specific options
 */
export async function apiFetch<T = unknown>(
  path: string,
  options: ApiFetchOptions = {},
): Promise<T> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, absoluteUrl = false, ...init } = options;
  const url = absoluteUrl ? path : buildApiUrl(path);

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  let res: Response;
  try {
    res = await fetch(url, {
      ...init,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(init.headers ?? {}),
      },
    });
  } catch (err) {
    clearTimeout(timeoutId);
    if (err instanceof Error && err.name === "AbortError") {
      throw new TimeoutError(url, timeoutMs);
    }
    throw new OfflineError(url, err);
  }
  clearTimeout(timeoutId);

  const contentType = res.headers.get("content-type");
  const text = await res.text();

  // Empty body — treat as empty object on success, or bare HttpError on failure
  if (!text.trim()) {
    if (res.ok) return {} as T;
    throw new HttpError(res.status, url, null);
  }

  // HTML error page detection
  const looksHtml =
    contentType?.includes("text/html") ||
    /^\s*<!doctype html|^\s*<html/i.test(text);
  if (looksHtml) {
    throw new NonJsonError(res.status, url, contentType ?? null);
  }

  // Parse JSON
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    throw new NonJsonError(res.status, url, contentType ?? null);
  }

  if (!res.ok) {
    throw new HttpError(res.status, url, data);
  }

  return data as T;
}

/**
 * Convenience wrapper for health/liveness endpoints — uses the shorter 10 s timeout.
 */
export function healthFetch<T = unknown>(
  path: string,
  options?: Omit<ApiFetchOptions, "timeoutMs">,
): Promise<T> {
  return apiFetch<T>(path, { ...options, timeoutMs: HEALTH_TIMEOUT_MS });
}

/**
 * Convenience wrapper for long-running mutations (scan, backtest, optimiser).
 * Uses LONG_TIMEOUT_MS and explicitly disables automatic retry.
 */
export function longFetch<T = unknown>(
  path: string,
  options?: Omit<ApiFetchOptions, "timeoutMs">,
): Promise<T> {
  return apiFetch<T>(path, { ...options, timeoutMs: LONG_TIMEOUT_MS });
}
