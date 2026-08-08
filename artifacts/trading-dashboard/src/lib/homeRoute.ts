/**
 * homeRoute.ts — Phase 25C.
 *
 * Which page is "Home" (the pinned top nav button)?
 *   - Preference "mission-control"  → always Mission Control
 *   - Preference "command-center"   → always Command Centre (legacy behaviour)
 *   - Preference "auto" (default)   → Mission Control during NSE market hours
 *                                     (Mon–Fri 09:00–15:30 IST), Command Centre
 *                                     otherwise.
 *
 * Pure navigation metadata — no business logic, no API calls.
 */

export type HomePreference = "auto" | "mission-control" | "command-center";

export const HOME_PREF_KEY = "apexquant_home_pref";

export function getHomePreference(): HomePreference {
  try {
    const v = localStorage.getItem(HOME_PREF_KEY);
    if (v === "mission-control" || v === "command-center" || v === "auto") return v;
  } catch { /* SSR / privacy mode */ }
  return "auto";
}

export function setHomePreference(pref: HomePreference): void {
  try { localStorage.setItem(HOME_PREF_KEY, pref); } catch { /* ignore */ }
}

/** Mon–Fri, 09:00 ≤ t < 15:30 IST (exported for tests; accepts an injected date). */
export function isMarketHoursIST(now: Date = new Date()): boolean {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata", hour12: false,
    weekday: "short", hour: "2-digit", minute: "2-digit",
  }).formatToParts(now);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  const weekday = get("weekday");
  if (weekday === "Sat" || weekday === "Sun") return false;
  const mins = parseInt(get("hour"), 10) * 60 + parseInt(get("minute"), 10);
  return mins >= 9 * 60 && mins < 15 * 60 + 30;
}

export interface HomeTarget { href: string; label: string }

export function getHomeTarget(now: Date = new Date(), pref: HomePreference = getHomePreference()): HomeTarget {
  const mission: HomeTarget = { href: "/mission-control", label: "Mission Control" };
  const command: HomeTarget = { href: "/command-center", label: "Command Centre" };
  if (pref === "mission-control") return mission;
  if (pref === "command-center") return command;
  return isMarketHoursIST(now) ? mission : command;
}
