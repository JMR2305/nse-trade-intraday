export const API_BASE = "/api";

export class ApiError extends Error {
  status: number;
  endpoint: string;
  constructor(message: string, status: number, endpoint: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.endpoint = endpoint;
  }
}

function shorten(text: string, max = 200): string {
  const t = text.trim().replace(/\s+/g, " ");
  return t.length > max ? `${t.slice(0, max)}…` : t;
}

/**
 * Safe JSON fetch: never calls response.json() blindly.
 * - Reads the body as text first
 * - Detects empty bodies and HTML error pages
 * - Surfaces backend error messages with status + endpoint context
 */
export async function apiJson<T = any>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const url = path.startsWith("/") ? `${API_BASE}${path}` : `${API_BASE}/${path}`;
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch (e) {
    throw new ApiError(`Network error contacting ${url}: ${String(e)}`, 0, url);
  }

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
      `Expected JSON but received HTML from ${url} (HTTP ${res.status}). The API route may be misrouted.`,
      res.status,
      url,
    );
  }

  let data: any;
  try {
    data = JSON.parse(text);
  } catch {
    throw new ApiError(
      `Invalid JSON from ${url} (HTTP ${res.status}): ${shorten(text)}`,
      res.status,
      url,
    );
  }

  if (!res.ok || (data && typeof data === "object" && data.error)) {
    const msg =
      (data && (typeof data.error === "string" ? data.error : data.error?.message)) ||
      `HTTP ${res.status}`;
    throw new ApiError(msg, res.status, url);
  }

  return data as T;
}
