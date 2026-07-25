/**
 * Canonical data-status vocabulary — Phase C + Phase 1B (Data Truthfulness).
 * Mirrors artifacts/trading-dashboard/src/lib/dataStatus.ts.
 *
 * LIVE          — fresh data from a connected live feed (age < 5 min)
 * DELAYED       — provider connected but delivery is slow or some symbols missing
 * CACHED        — data from a previous snapshot; provider offline / scan failed
 * STALE         — data age has crossed the staleness threshold
 * MARKET_CLOSED — market is outside trading hours (weekend, holiday, or pre/post session)
 * DEMO          — paper / mock mode; no real market data used
 * UNAVAILABLE   — no data has ever been received
 */
export type DataStatus =
  | "LIVE"
  | "DELAYED"
  | "CACHED"
  | "STALE"
  | "MARKET_CLOSED"
  | "DEMO"
  | "UNAVAILABLE";

/**
 * Determine whether NSE is currently in its trading session.
 * Uses a UTC ISO timestamp from the backend — never from the device clock.
 *
 * @param utcIso — ISO 8601 UTC string, e.g. "2026-07-25T21:00:14Z"
 */
export function isMarketOpen(utcIso: string | null | undefined): boolean {
  if (!utcIso) return true;
  const d = new Date(utcIso);
  if (isNaN(d.getTime())) return true;

  const IST_OFFSET_MS = (5 * 60 + 30) * 60 * 1000;
  const ist = new Date(d.getTime() + IST_OFFSET_MS);

  const dayOfWeek = ist.getUTCDay();
  if (dayOfWeek === 0 || dayOfWeek === 6) return false;

  const minuteOfDay = ist.getUTCHours() * 60 + ist.getUTCMinutes();
  return minuteOfDay >= 9 * 60 + 15 && minuteOfDay < 15 * 60 + 30;
}
