/**
 * Canonical data-status vocabulary — Phase C (Data Truthfulness).
 *
 * Every data-bearing component must show exactly one of these labels.
 * The label must be derived from backend metadata, never from browser time.
 *
 * LIVE      — fresh data from a connected live feed (age < 5 min, no missing symbols)
 * DELAYED   — provider connected but delivery is slow or some symbols are missing
 * CACHED    — data is from a previous snapshot; provider is offline / scan failed
 * STALE     — data age has crossed the staleness threshold (default 90 min)
 * DEMO      — paper / mock mode; no real market data used
 * UNAVAILABLE — no data has ever been received or all data has been purged
 */
export type DataStatus =
  | "LIVE"
  | "DELAYED"
  | "CACHED"
  | "STALE"
  | "DEMO"
  | "UNAVAILABLE";

/** Map a DataStatus to a Tailwind text-colour class for the dashboard. */
export const DATA_STATUS_COLOR: Record<DataStatus, string> = {
  LIVE:        "text-emerald-400",
  DELAYED:     "text-warn",
  CACHED:      "text-sky-400",
  STALE:       "text-warn",
  DEMO:        "text-violet-400",
  UNAVAILABLE: "text-red-400",
};

/** Map a DataStatus to a connection-dot colour (hex) for inline use. */
export const DATA_STATUS_DOT: Record<DataStatus, string> = {
  LIVE:        "#34d399", // emerald-400
  DELAYED:     "#f59e0b", // amber-400  (warn)
  CACHED:      "#38bdf8", // sky-400
  STALE:       "#f59e0b", // amber-400  (warn)
  DEMO:        "#a78bfa", // violet-400
  UNAVAILABLE: "#f87171", // red-400
};
