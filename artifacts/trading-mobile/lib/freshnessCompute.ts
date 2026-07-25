/**
 * Pure freshness-classification logic — no React Native dependencies.
 *
 * Extracted from components/FreshnessLabel.tsx so it can be unit-tested in
 * vitest without needing to mock @expo/vector-icons or react-native.
 */

import type { SnapshotSource } from "./offlineCache";

/**
 * Canonical data-status vocabulary — Phase C + Phase 1B (Data Truthfulness).
 *
 * LIVE          — fresh data from a connected live feed (age < 5 min)
 * DELAYED       — provider connected but delivery is slow (was AGING)
 * STALE         — data age has crossed the staleness threshold
 * CACHED        — data from a previous snapshot; provider offline (was OFFLINE CACHE)
 * MARKET_CLOSED — outside NSE trading hours (weekend, holiday, or pre/post session)
 * UNAVAILABLE   — no data has ever been received
 */
export type FreshnessBand =
  | "LIVE"
  | "DELAYED"
  | "STALE"
  | "CACHED"
  | "MARKET_CLOSED"
  | "UNAVAILABLE";

export const FRESH_LIMIT_MS = 5 * 60_000;    // < 5 min  → LIVE
export const DELAYED_LIMIT_MS = 15 * 60_000; // < 15 min → DELAYED

/**
 * Classify the shown data. Ages are computed from the backend data timestamp
 * (fetch/snapshot time of a real payload), never from screen-render time.
 *
 * @param marketState — optional market state from the backend health response.
 *   When "CLOSED", "WEEKEND", or "PRE_OPEN" and data would otherwise be STALE,
 *   the band is promoted to the more informative MARKET_CLOSED.
 */
export function computeFreshness(
  ts: number | null | undefined,
  source: SnapshotSource,
  now: number,
  marketState?: "OPEN" | "CLOSED" | "WEEKEND" | "PRE_OPEN" | null,
): FreshnessBand {
  if (source === "none" || (!ts && source !== "live")) return "UNAVAILABLE";
  if (source === "offline-cache") return "CACHED";   // was "OFFLINE CACHE"
  if (!ts) return "LIVE"; // live data just arrived without a recorded ts
  const age = now - ts;
  if (age < FRESH_LIMIT_MS) return "LIVE";           // was "FRESH"
  if (age < DELAYED_LIMIT_MS) return "DELAYED";      // was "AGING"
  // STALE — if the market is known-closed, use the more informative label
  if (
    marketState === "CLOSED" ||
    marketState === "WEEKEND" ||
    marketState === "PRE_OPEN"
  ) {
    return "MARKET_CLOSED";
  }
  return "STALE";
}
