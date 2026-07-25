/**
 * Canonical data-status vocabulary — Phase C (Data Truthfulness).
 * Mirrors artifacts/trading-dashboard/src/lib/dataStatus.ts.
 *
 * LIVE      — fresh data from a connected live feed (age < 5 min)
 * DELAYED   — provider connected but delivery is slow or some symbols missing
 * CACHED    — data from a previous snapshot; provider offline / scan failed
 * STALE     — data age has crossed the staleness threshold
 * DEMO      — paper / mock mode; no real market data used
 * UNAVAILABLE — no data has ever been received
 */
export type DataStatus =
  | "LIVE"
  | "DELAYED"
  | "CACHED"
  | "STALE"
  | "DEMO"
  | "UNAVAILABLE";
