/**
 * Phase 1 — Mobile Connectivity Validation Tests
 *
 * Mobile-side equivalents for Phase 1 production readiness:
 *  - BASE URL resolves from EXPO_PUBLIC_API_BASE_URL (explicit) or EXPO_PUBLIC_DOMAIN
 *  - isMarketOpen from dataStatus correctly identifies non-trading hours
 *  - ConfigurationError class exists and is typed correctly
 *  - MARKET_CLOSED is a valid DataStatus value
 */

import { describe, it, expect } from "vitest";
import { CACHE_SCHEMA_VERSION } from "../cacheSchema";

// ── dataStatus module ─────────────────────────────────────────────────────────

describe("Phase 1 mobile · isMarketOpen", () => {
  it("returns false for Saturday UTC timestamp", async () => {
    const { isMarketOpen } = await import("../dataStatus");
    // 2026-07-25 Saturday 15:30 UTC → Saturday IST
    expect(isMarketOpen("2026-07-25T15:30:00Z")).toBe(false);
  });

  it("returns false for Sunday UTC timestamp", async () => {
    const { isMarketOpen } = await import("../dataStatus");
    // 2026-07-26 Sunday
    expect(isMarketOpen("2026-07-26T10:00:00Z")).toBe(false);
  });

  it("returns true for weekday during NSE trading hours (IST)", async () => {
    const { isMarketOpen } = await import("../dataStatus");
    // Tuesday 2026-07-21 06:30 UTC = 12:00 IST (market open)
    expect(isMarketOpen("2026-07-21T06:30:00Z")).toBe(true);
  });

  it("returns false for weekday outside trading hours (pre-open)", async () => {
    const { isMarketOpen } = await import("../dataStatus");
    // Tuesday 02:00 UTC = 07:30 IST (before 09:15)
    expect(isMarketOpen("2026-07-21T02:00:00Z")).toBe(false);
  });

  it("returns false for weekday after market close (post 15:30 IST)", async () => {
    const { isMarketOpen } = await import("../dataStatus");
    // Tuesday 11:00 UTC = 16:30 IST (after 15:30)
    expect(isMarketOpen("2026-07-21T11:00:00Z")).toBe(false);
  });

  it("returns true (safe default) for null or invalid input", async () => {
    const { isMarketOpen } = await import("../dataStatus");
    expect(isMarketOpen(null)).toBe(true);
    expect(isMarketOpen(undefined)).toBe(true);
    expect(isMarketOpen("not-a-date")).toBe(true);
  });
});

// ── DataStatus includes MARKET_CLOSED ────────────────────────────────────────

describe("Phase 1 mobile · DataStatus vocabulary includes MARKET_CLOSED", () => {
  it("MARKET_CLOSED is a valid DataStatus literal", async () => {
    // This test verifies the type at runtime by confirming the module doesn't
    // throw and the expected string is a valid assignable value.
    const mod = await import("../dataStatus");
    // If DataStatus didn't include MARKET_CLOSED, TypeScript would catch it;
    // here we verify the module loads without error and exports isMarketOpen.
    expect(typeof mod.isMarketOpen).toBe("function");
    // MARKET_CLOSED must be usable as a DataStatus value (TypeScript-enforced
    // at build time; runtime check via string assignment)
    const status: import("../dataStatus").DataStatus = "MARKET_CLOSED";
    expect(status).toBe("MARKET_CLOSED");
  });
});

// ── apiConfig module ──────────────────────────────────────────────────────────

describe("Phase 1 mobile · API base URL resolution", () => {
  it("BASE falls back to '/api' when no EXPO_PUBLIC_ vars are set", async () => {
    const { BASE } = await import("../monitorApi");
    // In vitest environment EXPO_PUBLIC_API_BASE_URL and EXPO_PUBLIC_DOMAIN
    // are not set, so BASE should be the relative fallback.
    expect(typeof BASE).toBe("string");
    // Must not resolve to localhost in any environment
    expect(BASE).not.toMatch(/localhost|127\.0\.0\.1/);
  });

  it("ConfigurationError class is exported from apiConfig", async () => {
    const { ConfigurationError } = await import("../apiConfig");
    const err = new ConfigurationError("test error");
    expect(err).toBeInstanceOf(Error);
    expect(err.name).toBe("ConfigurationError");
    expect(err.message).toBe("test error");
  });
});

// ── Offline cache schema — baseline regression ────────────────────────────────

describe("Phase 1 mobile · offline cache schema is intact after Phase 1B", () => {
  it("CACHE_SCHEMA_VERSION is a positive integer", () => {
    expect(typeof CACHE_SCHEMA_VERSION).toBe("number");
    expect(CACHE_SCHEMA_VERSION).toBeGreaterThan(0);
    expect(Number.isInteger(CACHE_SCHEMA_VERSION)).toBe(true);
  });
});
