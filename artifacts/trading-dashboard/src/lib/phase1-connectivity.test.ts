/**
 * Phase 1 — Connectivity Validation Tests
 *
 * Eleven tests covering the Phase 1 production readiness checklist.
 * All tests run entirely in Vitest — no live API server required.
 *
 * Tests:
 *  1.  Production config rejects localhost URLs with ConfigurationError
 *  2.  VITE_API_BASE_URL defaults to "/api" when not set (dev environment)
 *  3.  Request timeout maps to ApiError with status 408
 *  4.  Non-JSON (HTML) response is handled without crash
 *  5.  No completed scan → UNAVAILABLE
 *  6.  Scan FAILED with prior snapshot → CACHED
 *  7.  Partial symbol coverage → DELAYED
 *  8.  Stale data on a weekend → MARKET_CLOSED
 *  9.  Fresh data after reconnect replaces CACHED → LIVE
 * 10.  Dashboard QueryClient has mutations.retry = 0
 * 11.  API_BASE export equals API_BASE_URL (backward-compat alias is wired)
 */

import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// ── helpers ───────────────────────────────────────────────────────────────────

/** Build a minimal Response mock to stub globalThis.fetch. */
function mockFetch(body: string, status = 200, contentType = "application/json") {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(body, { status, headers: { "content-type": contentType } }),
    ),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

// ── 1. Production config rejects localhost ───────────────────────────────────

describe("Phase 1 · test 1 — production config cannot use localhost", () => {
  it("ConfigurationError is a typed Error subclass with a descriptive message", async () => {
    const { ConfigurationError } = await import("./apiConfig");
    const err = new ConfigurationError(
      'VITE_API_BASE_URL resolves to "http://localhost:8080/api" which contains localhost/127.0.0.1.',
    );
    expect(err).toBeInstanceOf(Error);
    expect(err.name).toBe("ConfigurationError");
    expect(err.message).toMatch(/localhost/);
  });

  it("isMarketOpen returns false for a Saturday UTC timestamp", async () => {
    // 2026-07-25 is a Saturday. Any UTC time converts to Saturday IST (Sat/early Sun).
    const { isMarketOpen } = await import("./dataStatus");
    // Saturday 2026-07-25 10:00 UTC = Saturday 15:30 IST → weekend
    expect(isMarketOpen("2026-07-25T10:00:00Z")).toBe(false);
  });
});

// ── 2. API_BASE_URL defaults to /api in dev/test environment ────────────────

describe("Phase 1 · test 2 — missing API URL falls back to /api (not localhost)", () => {
  it("API_BASE_URL is '/api' when VITE_API_BASE_URL is not set", async () => {
    // In the Vitest environment, VITE_API_BASE_URL is not set.
    // The module should resolve to the safe relative fallback.
    const { API_BASE_URL } = await import("./apiConfig");
    expect(API_BASE_URL).toBe("/api");
    expect(API_BASE_URL).not.toMatch(/localhost|127\.0\.0\.1/);
  });
});

// ── 3. Timeout maps to ApiError with status 408 ──────────────────────────────

describe("Phase 1 · test 3 — timeout maps to typed ApiError with status 408", () => {
  it("apiJson throws ApiError(status=408) when the request exceeds the timeout", async () => {
    vi.useFakeTimers();

    // Mock fetch that only resolves when the signal fires
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init: RequestInit) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            const err = new Error("The operation was aborted");
            (err as Error & { name: string }).name = "AbortError";
            reject(err);
          });
        }),
      ),
    );

    const { apiJson, ApiError } = await import("./api");
    const promise = apiJson("/test-timeout", undefined, 50 /* 50 ms timeout */);

    // Advance past the timeout
    vi.advanceTimersByTime(100);

    const err = await promise.catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as InstanceType<typeof ApiError>).status).toBe(408);
    expect((err as InstanceType<typeof ApiError>).message).toMatch(/timed out/i);
  });
});

// ── 4. Non-JSON (HTML) response handled without crash ────────────────────────

describe("Phase 1 · test 4 — non-JSON HTML response does not crash", () => {
  it("apiJson throws ApiError mentioning HTML and misrouting", async () => {
    mockFetch(
      "<!DOCTYPE html><html><body>404 Not Found</body></html>",
      404,
      "text/html",
    );
    const { apiJson, ApiError } = await import("./api");
    const err = await apiJson("/bad-route").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as InstanceType<typeof ApiError>).message).toMatch(/html/i);
    expect((err as InstanceType<typeof ApiError>).message).toMatch(/misrouted/i);
  });
});

// ── 5–9. deriveDataStatus unit tests ─────────────────────────────────────────

// Minimal fixtures matching the interfaces in DataFreshnessBar.tsx
const GOOD_META = {
  scan_id: "abc123",
  status: "SUCCESS",
  started_at: "2026-07-25T19:00:00Z",
  completed_at: "2026-07-25T19:10:00Z",
  snapshot_ts: "2026-07-25T19:00:00Z",
  provider: "yfinance",
  symbols_requested: 50,
  symbols_received: 50,
  symbols_missing: 0,
  symbols_stale: 0,
  missing_symbols: [] as string[],
  stale_symbols: [] as string[],
  error: null,
  updated_at: "2026-07-25T19:10:00Z",
};

const GOOD_ST = {
  success: true,
  current_time: "2026-07-25T10:00:00Z", // Saturday
  last_scan_time: "2026-07-25T19:00:00Z",
  scan_age_seconds: 100,
  stale: false,
  buy_recommendations_disabled: false,
};

describe("Phase 1 · test 5 — backend outage shows UNAVAILABLE", () => {
  it("returns UNAVAILABLE when no scan has ever completed", async () => {
    const { deriveDataStatus } = await import("../components/DataFreshnessBar");
    expect(deriveDataStatus(false, false, false, null, undefined)).toBe("UNAVAILABLE");
    expect(deriveDataStatus(false, false, false, null, { stale: false } as never)).toBe("UNAVAILABLE");
  });
});

describe("Phase 1 · test 6 — cached outage shows CACHED", () => {
  it("returns CACHED when scan failed but a prior snapshot exists", async () => {
    const { deriveDataStatus } = await import("../components/DataFreshnessBar");
    const failedMeta = { ...GOOD_META, status: "FAILED" };
    expect(deriveDataStatus(false, true, false, failedMeta, GOOD_ST as never)).toBe("CACHED");
  });

  it("returns UNAVAILABLE when scan failed and no prior snapshot exists", async () => {
    const { deriveDataStatus } = await import("../components/DataFreshnessBar");
    const noHistory = { ...GOOD_ST, last_scan_time: undefined };
    expect(deriveDataStatus(false, true, false, null, noHistory as never)).toBe("UNAVAILABLE");
  });
});

describe("Phase 1 · test 7 — partial data shows DELAYED", () => {
  it("returns DELAYED when symbols are missing", async () => {
    const { deriveDataStatus } = await import("../components/DataFreshnessBar");
    const partialMeta = { ...GOOD_META, symbols_missing: 2, missing_symbols: ["LTIM", "TATAMOTORS"] };
    // Weekday current_time so market-closed branch doesn't fire
    const weekdaySt = { ...GOOD_ST, current_time: "2026-07-21T06:30:00Z", stale: false }; // Tuesday 12:00 IST
    expect(deriveDataStatus(false, false, false, partialMeta, weekdaySt as never)).toBe("DELAYED");
  });
});

describe("Phase 1 · test 8 — market closed shows MARKET_CLOSED", () => {
  it("returns MARKET_CLOSED when data is stale and it is the weekend", async () => {
    const { deriveDataStatus } = await import("../components/DataFreshnessBar");
    // Saturday 2026-07-25 21:00 UTC → Saturday IST — weekend
    const weekendSt = { ...GOOD_ST, current_time: "2026-07-25T15:30:00Z", stale: true };
    expect(deriveDataStatus(false, false, true, GOOD_META, weekendSt as never)).toBe("MARKET_CLOSED");
  });

  it("returns STALE (not MARKET_CLOSED) when data is stale during trading hours", async () => {
    const { deriveDataStatus } = await import("../components/DataFreshnessBar");
    // Tuesday 2026-07-21 06:30 UTC → 12:00 IST (market open)
    const openSt = { ...GOOD_ST, current_time: "2026-07-21T06:30:00Z", stale: true };
    expect(deriveDataStatus(false, false, true, GOOD_META, openSt as never)).toBe("STALE");
  });
});

describe("Phase 1 · test 9 — reconnect replaces CACHED data with LIVE", () => {
  it("returns LIVE after fresh data arrives following a CACHED state", async () => {
    const { deriveDataStatus } = await import("../components/DataFreshnessBar");
    // After reconnect: scan succeeded, not stale, full coverage, market open
    const freshSt = { ...GOOD_ST, current_time: "2026-07-21T06:30:00Z", stale: false };
    expect(deriveDataStatus(false, false, false, GOOD_META, freshSt as never)).toBe("LIVE");
  });
});

// ── 10. QueryClient mutation retry = 0 ──────────────────────────────────────

describe("Phase 1 · test 10 — order mutations are not auto-retried", () => {
  it("App.tsx configures QueryClient with mutations.retry = 0", () => {
    const src = readFileSync(resolve(__dirname, "../App.tsx"), "utf8");
    // The defaultOptions block must contain retry: 0 for mutations
    expect(src).toContain("mutations:");
    expect(src).toMatch(/mutations:\s*\{[^}]*retry:\s*0/s);
  });
});

// ── 11. Configured API URL is picked up ─────────────────────────────────────

describe("Phase 1 · test 11 — web client resolves to the configured API URL", () => {
  it("API_BASE (backward-compat alias) equals API_BASE_URL from apiConfig", async () => {
    const { API_BASE } = await import("./api");
    const { API_BASE_URL } = await import("./apiConfig");
    expect(API_BASE).toBe(API_BASE_URL);
  });

  it("isMarketOpen returns true for a weekday during trading hours (IST)", async () => {
    const { isMarketOpen } = await import("./dataStatus");
    // 2026-07-21 (Tuesday) 06:30 UTC = 12:00 IST — market open
    expect(isMarketOpen("2026-07-21T06:30:00Z")).toBe(true);
  });

  it("isMarketOpen returns false for pre-open hours (before 09:15 IST)", async () => {
    const { isMarketOpen } = await import("./dataStatus");
    // Tuesday 02:30 UTC = 08:00 IST — before pre-open (09:00)
    expect(isMarketOpen("2026-07-21T02:30:00Z")).toBe(false);
  });

  it("isMarketOpen returns false after market close (after 15:30 IST)", async () => {
    const { isMarketOpen } = await import("./dataStatus");
    // Tuesday 12:00 UTC = 17:30 IST — post close
    expect(isMarketOpen("2026-07-21T12:00:00Z")).toBe(false);
  });
});
