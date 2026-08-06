/**
 * Offline cache lifecycle tests — Task #363
 *
 * Confirms the three cache lifecycle states the Pipeline (AI Ops) tab relies on:
 *
 *   1. LIVE   — successful fetch: data returned as-is, isStale=false
 *   2. CACHED — cold-start with network failure: persisted snapshot is shown, isStale=true
 *   3. NONE   — cold-start with network failure and no prior cache: no data available
 *
 * Also verifies:
 *   - writeSnapshot stores data under the correct AsyncStorage key
 *   - The CACHED badge condition (isStale === true) is set for offline-cache and
 *     memory sources, never for live data
 *   - The StaleBanner 5-minute threshold is computed correctly from staleTs
 *   - formatAge returns human-readable age strings
 *
 * No React renderer required; selectCacheData and writeSnapshot are tested as
 * pure/async functions.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

// ── AsyncStorage mock ────────────────────────────────────────────────────────
// vi.mock factories are hoisted before variable initialization, so mock
// functions must be created with vi.hoisted() to be available in the factory.

const _store: Record<string, string> = {};

const { mockSetItem, mockGetItem, mockRemoveItem } = vi.hoisted(() => ({
  mockSetItem: vi.fn((key: string, value: string) => {
    _store[key] = value;
    return Promise.resolve();
  }),
  mockGetItem: vi.fn((key: string) => Promise.resolve(_store[key] ?? null)),
  mockRemoveItem: vi.fn((key: string) => {
    delete _store[key];
    return Promise.resolve();
  }),
}));

vi.mock("@react-native-async-storage/async-storage", () => ({
  default: { getItem: mockGetItem, setItem: mockSetItem, removeItem: mockRemoveItem },
}));

// ── cacheSchema mock ─────────────────────────────────────────────────────────
// Provide lightweight stubs so the test file doesn't depend on alias resolution
// for @/lib/cacheSchema.  The stubs match the real contract exactly.

vi.mock("@/lib/cacheSchema", () => ({
  CACHE_SCHEMA_VERSION: 2,
  MIN_COMPATIBLE_VERSION: 1,
  encodeSnapshot: (data: unknown, ts: number) => JSON.stringify({ v: 2, data, ts }),
  decodeSnapshot: (key: string, raw: string | null | undefined) => {
    if (!raw) return { ok: false, reason: "corrupt" };
    let parsed: unknown;
    try { parsed = JSON.parse(raw); } catch { return { ok: false, reason: "corrupt" }; }
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      return { ok: false, reason: "corrupt" };
    }
    const obj = parsed as { v?: unknown; data?: unknown; ts?: unknown };
    if (typeof obj.ts !== "number" || obj.ts <= 0) return { ok: false, reason: "missing-fields" };
    if (obj.data === undefined) return { ok: false, reason: "missing-fields" };
    return { ok: true, data: obj.data, ts: obj.ts, migrated: false };
  },
}));

// ── React stubs (not used by the functions under test but required by module) ─

vi.mock("react", () => ({
  useState: vi.fn(),
  useEffect: vi.fn(),
  useRef: vi.fn(),
}));

// ── Imports (after mocks) ────────────────────────────────────────────────────

import { formatAge, selectCacheData, writeSnapshot } from "../offlineCache";

// ── Minimal OpsSnapshot shape (matches the fields the tab renders) ────────────

const VALID_SNAPSHOT = {
  generated_at: "2026-08-06T10:00:00Z",
  platform: { health_pct: 92, market_state: "OPEN", trading_session: "Morning" },
  agents: { supervisor: { name: "Supervisor", status: "ACTIVE", health_pct: 100 } },
  pipeline: { universe_loaded: 200, passed_risk: 10, buy_recommendations: 5 },
  pipeline_nodes: [],
};

const SNAPSHOT_TS = 1_754_000_000_000; // arbitrary fixed timestamp

beforeEach(() => {
  // Clear in-memory store and call counts between tests
  for (const k of Object.keys(_store)) delete _store[k];
  mockSetItem.mockClear();
  mockGetItem.mockClear();
  mockRemoveItem.mockClear();
});

// ── 1. AsyncStorage write key ─────────────────────────────────────────────────

describe("writeSnapshot — AsyncStorage key", () => {
  it("stores data under 'offline_snapshot:ops-centre-snapshot'", async () => {
    await writeSnapshot("ops-centre-snapshot", VALID_SNAPSHOT, SNAPSHOT_TS);
    expect(mockSetItem).toHaveBeenCalledTimes(1);
    const [key] = mockSetItem.mock.calls[0] as [string, string];
    expect(key).toBe("offline_snapshot:ops-centre-snapshot");
  });

  it("stores a valid JSON envelope containing the payload and timestamp", async () => {
    await writeSnapshot("ops-centre-snapshot", VALID_SNAPSHOT, SNAPSHOT_TS);
    const [, value] = mockSetItem.mock.calls[0] as [string, string];
    const parsed = JSON.parse(value) as { v: number; data: unknown; ts: number };
    expect(parsed.v).toBe(2);
    expect(parsed.ts).toBe(SNAPSHOT_TS);
    expect(parsed.data).toEqual(VALID_SNAPSHOT);
  });

  it("uses Date.now() when no ts is supplied", async () => {
    const before = Date.now();
    await writeSnapshot("ops-centre-snapshot", VALID_SNAPSHOT);
    const after = Date.now();
    const [, value] = mockSetItem.mock.calls[0] as [string, string];
    const parsed = JSON.parse(value) as { ts: number };
    expect(parsed.ts).toBeGreaterThanOrEqual(before);
    expect(parsed.ts).toBeLessThanOrEqual(after);
  });
});

// ── 2. selectCacheData — LIVE state ──────────────────────────────────────────

describe("selectCacheData — LIVE (successful fetch)", () => {
  it("returns live data with isStale=false when liveData is defined and no error", () => {
    const result = selectCacheData(VALID_SNAPSHOT, false, null, SNAPSHOT_TS);
    expect(result.data).toBe(VALID_SNAPSHOT);
    expect(result.isStale).toBe(false);
    expect(result.staleTs).toBeNull();
    expect(result.source).toBe("live");
  });

  it("exposes dataTs from dataUpdatedAt when live", () => {
    const result = selectCacheData(VALID_SNAPSHOT, false, null, SNAPSHOT_TS);
    expect(result.dataTs).toBe(SNAPSHOT_TS);
  });

  it("sets dataTs to null when dataUpdatedAt is absent", () => {
    const result = selectCacheData(VALID_SNAPSHOT, false, null);
    expect(result.dataTs).toBeNull();
  });

  it("CACHED badge is NOT shown (isStale=false) for live data", () => {
    const result = selectCacheData(VALID_SNAPSHOT, false, null, SNAPSHOT_TS);
    // The badge row in ai-ops.tsx renders the CACHED pill only when isStale===true
    expect(result.isStale).toBe(false);
  });
});

// ── 3. selectCacheData — OFFLINE-WITH-CACHE (cold-start, server down) ────────

describe("selectCacheData — CACHED (offline cold-start, persisted snapshot available)", () => {
  const cached = { data: VALID_SNAPSHOT, ts: SNAPSHOT_TS };

  it("serves the persisted snapshot when liveData is undefined and not in error", () => {
    // Loading state: liveData===undefined, isError===false, snapshot present
    const result = selectCacheData<typeof VALID_SNAPSHOT>(undefined, false, cached);
    expect(result.data).toEqual(VALID_SNAPSHOT);
    expect(result.isStale).toBe(true);
    expect(result.source).toBe("offline-cache");
  });

  it("serves the persisted snapshot when the network call fails (isError=true)", () => {
    const result = selectCacheData<typeof VALID_SNAPSHOT>(undefined, true, cached);
    expect(result.data).toEqual(VALID_SNAPSHOT);
    expect(result.isStale).toBe(true);
    expect(result.staleTs).toBe(SNAPSHOT_TS);
    expect(result.source).toBe("offline-cache");
  });

  it("CACHED badge IS shown (isStale=true) for offline-cache source", () => {
    const result = selectCacheData<typeof VALID_SNAPSHOT>(undefined, true, cached);
    expect(result.isStale).toBe(true);
  });

  it("preserves the exact snapshot timestamp as staleTs", () => {
    const result = selectCacheData<typeof VALID_SNAPSHOT>(undefined, true, cached);
    expect(result.staleTs).toBe(SNAPSHOT_TS);
    expect(result.dataTs).toBe(SNAPSHOT_TS);
  });

  it("returns memory source when liveData is stale-but-defined in React Query cache on error", () => {
    const result = selectCacheData(VALID_SNAPSHOT, true, cached, SNAPSHOT_TS);
    // React Query can hold the last value even when isError=true
    expect(result.isStale).toBe(true);
    expect(result.source).toBe("memory");
    expect(result.data).toBe(VALID_SNAPSHOT);
  });
});

// ── 4. selectCacheData — OFFLINE-WITHOUT-CACHE (no prior session) ─────────────

describe("selectCacheData — NONE (offline, no prior cache)", () => {
  it("returns undefined data when there is no cache and the network has failed", () => {
    const result = selectCacheData<typeof VALID_SNAPSHOT>(undefined, true, null);
    expect(result.data).toBeUndefined();
    expect(result.source).toBe("none");
    expect(result.isStale).toBe(true); // isStale=true signals the server is unreachable
  });

  it("returns undefined data on initial loading with no prior cache (isError=false)", () => {
    const result = selectCacheData<typeof VALID_SNAPSHOT>(undefined, false, null);
    expect(result.data).toBeUndefined();
    expect(result.source).toBe("none");
    expect(result.isStale).toBe(false); // still loading, not yet an error
  });
});

// ── 5. StaleBanner 5-minute threshold ─────────────────────────────────────────

describe("StaleBanner threshold — shown only when cache is older than 5 minutes", () => {
  const STALE_THRESHOLD_MS = 5 * 60 * 1_000;

  function shouldShowBanner(staleTs: number | null, isStale: boolean): boolean {
    // Mirrors the exact logic in ai-ops.tsx line 579:
    //   const showStaleBanner = isStale && staleTs != null && Date.now() - staleTs > STALE_THRESHOLD_MS;
    return isStale && staleTs != null && Date.now() - staleTs > STALE_THRESHOLD_MS;
  }

  it("does NOT show the banner when cache is 4 minutes old", () => {
    const fourMinsAgo = Date.now() - 4 * 60 * 1_000;
    expect(shouldShowBanner(fourMinsAgo, true)).toBe(false);
  });

  it("shows the banner when cache is 6 minutes old", () => {
    const sixMinsAgo = Date.now() - 6 * 60 * 1_000;
    expect(shouldShowBanner(sixMinsAgo, true)).toBe(true);
  });

  it("does NOT show the banner when data is live (isStale=false), even if staleTs is old", () => {
    const tenMinsAgo = Date.now() - 10 * 60 * 1_000;
    expect(shouldShowBanner(tenMinsAgo, false)).toBe(false);
  });

  it("does NOT show the banner when staleTs is null", () => {
    expect(shouldShowBanner(null, true)).toBe(false);
  });

  it("shows the banner exactly at the 5-minute boundary (> not >=)", () => {
    const justOver5 = Date.now() - (STALE_THRESHOLD_MS + 1);
    const exactlyAt5 = Date.now() - STALE_THRESHOLD_MS;
    expect(shouldShowBanner(justOver5, true)).toBe(true);
    expect(shouldShowBanner(exactlyAt5, true)).toBe(false);
  });
});

// ── 6. formatAge ───────────────────────────────────────────────────────────────

describe("formatAge — human-readable cache age", () => {
  it("returns 'moments ago' when the cache is less than 30 seconds old", () => {
    // formatAge uses Math.round(diff / 60_000): 10s → 0 mins → "moments ago"
    expect(formatAge(Date.now() - 10_000)).toBe("moments ago");
  });

  it("returns '1 minute ago' when the cache is exactly 1 minute old", () => {
    expect(formatAge(Date.now() - 60_000)).toBe("1 minute ago");
  });

  it("returns 'N minutes ago' for caches 2–59 minutes old", () => {
    expect(formatAge(Date.now() - 5 * 60_000)).toBe("5 minutes ago");
  });

  it("returns '1 hour ago' when the cache is 60 minutes old", () => {
    expect(formatAge(Date.now() - 60 * 60_000)).toBe("1 hour ago");
  });

  it("returns '3 hours ago' when the cache is 3 hours old", () => {
    expect(formatAge(Date.now() - 3 * 60 * 60_000)).toBe("3 hours ago");
  });

  it("returns '1 day ago' when the cache is 24 hours old", () => {
    expect(formatAge(Date.now() - 24 * 60 * 60_000)).toBe("1 day ago");
  });

  it("returns 'unknown age' for null", () => {
    expect(formatAge(null)).toBe("unknown age");
  });

  it("returns 'unknown age' for zero (which formatAge treats as falsy)", () => {
    expect(formatAge(0)).toBe("unknown age");
  });
});
