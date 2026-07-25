/**
 * Canonical data-status vocabulary — Phase C + Phase 1B (Data Truthfulness).
 *
 * Every data-bearing component must show exactly one of these labels.
 * The label must be derived from backend metadata, never from browser time.
 *
 * LIVE          — fresh data from a connected live feed (age < 5 min, no missing symbols)
 * DELAYED       — provider connected but delivery is slow or some symbols are missing
 * CACHED        — data is from a previous snapshot; provider is offline / scan failed
 * STALE         — data age has crossed the staleness threshold (default 90 min)
 * MARKET_CLOSED — market is outside trading hours (weekend, holiday, or pre/post session)
 * DEMO          — paper / mock mode; no real market data used
 * UNAVAILABLE   — no data has ever been received or all data has been purged
 */
export type DataStatus =
  | "LIVE"
  | "DELAYED"
  | "CACHED"
  | "STALE"
  | "MARKET_CLOSED"
  | "DEMO"
  | "UNAVAILABLE";

/** Map a DataStatus to a Tailwind text-colour class for the dashboard. */
export const DATA_STATUS_COLOR: Record<DataStatus, string> = {
  LIVE:          "text-emerald-400",
  DELAYED:       "text-warn",
  CACHED:        "text-sky-400",
  STALE:         "text-warn",
  MARKET_CLOSED: "text-slate-400",
  DEMO:          "text-violet-400",
  UNAVAILABLE:   "text-red-400",
};

/** Map a DataStatus to a connection-dot colour (hex) for inline use. */
export const DATA_STATUS_DOT: Record<DataStatus, string> = {
  LIVE:          "#34d399", // emerald-400
  DELAYED:       "#f59e0b", // amber-400  (warn)
  CACHED:        "#38bdf8", // sky-400
  STALE:         "#f59e0b", // amber-400  (warn)
  MARKET_CLOSED: "#94a3b8", // slate-400  (neutral — not an error)
  DEMO:          "#a78bfa", // violet-400
  UNAVAILABLE:   "#f87171", // red-400
};

/**
 * Determine whether NSE is currently in its trading session.
 * Uses a UTC ISO timestamp from the backend (e.g. `current_time` in the
 * staleness response) — never from the browser clock.
 *
 * NSE trading hours (IST, UTC+5:30):
 *   Pre-open  09:00–09:15
 *   Open      09:15–15:30
 *   Sat/Sun   always closed
 *
 * Returns true when the market is open (or we cannot determine the state).
 * Returns false when it is definitively weekend / outside session hours.
 *
 * @param utcIso — ISO 8601 UTC string, e.g. "2026-07-25T21:00:14Z"
 */
export function isMarketOpen(utcIso: string | null | undefined): boolean {
  if (!utcIso) return true; // unknown → assume open to avoid false MARKET_CLOSED
  const d = new Date(utcIso);
  if (isNaN(d.getTime())) return true;

  // Shift to IST (UTC + 5h 30m)
  const IST_OFFSET_MS = (5 * 60 + 30) * 60 * 1000;
  const ist = new Date(d.getTime() + IST_OFFSET_MS);

  const dayOfWeek = ist.getUTCDay(); // 0 = Sunday, 6 = Saturday
  if (dayOfWeek === 0 || dayOfWeek === 6) return false; // weekend

  const minuteOfDay = ist.getUTCHours() * 60 + ist.getUTCMinutes();
  const OPEN_MINUTE  = 9 * 60 + 15; // 09:15
  const CLOSE_MINUTE = 15 * 60 + 30; // 15:30
  return minuteOfDay >= OPEN_MINUTE && minuteOfDay < CLOSE_MINUTE;
}
