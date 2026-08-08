// @vitest-environment jsdom
/**
 * homeRoute.test.ts — Phase 25C default landing logic.
 */
import { describe, it, expect, beforeEach } from "vitest";
import {
  getHomeTarget, isMarketHoursIST, getHomePreference, setHomePreference, HOME_PREF_KEY,
} from "./homeRoute";

// Helpers: build a Date at a specific IST wall-clock time.
// IST = UTC+5:30 → 09:15 IST == 03:45 UTC.
const istDate = (isoUtc: string) => new Date(isoUtc);

const TUE_1000_IST = istDate("2026-08-04T04:30:00Z"); // Tue 10:00 IST
const TUE_2000_IST = istDate("2026-08-04T14:30:00Z"); // Tue 20:00 IST
const SAT_1000_IST = istDate("2026-08-08T04:30:00Z"); // Sat 10:00 IST
const TUE_0859_IST = istDate("2026-08-04T03:29:00Z"); // Tue 08:59 IST
const TUE_0900_IST = istDate("2026-08-04T03:30:00Z"); // Tue 09:00 IST
const TUE_1529_IST = istDate("2026-08-04T09:59:00Z"); // Tue 15:29 IST
const TUE_1530_IST = istDate("2026-08-04T10:00:00Z"); // Tue 15:30 IST

describe("isMarketHoursIST", () => {
  it("is true mid-session on a weekday", () => {
    expect(isMarketHoursIST(TUE_1000_IST)).toBe(true);
  });
  it("is false in the evening", () => {
    expect(isMarketHoursIST(TUE_2000_IST)).toBe(false);
  });
  it("is false on weekends even during the day", () => {
    expect(isMarketHoursIST(SAT_1000_IST)).toBe(false);
  });
  it("boundary: opens at 09:00, closes at 15:30", () => {
    expect(isMarketHoursIST(TUE_0859_IST)).toBe(false);
    expect(isMarketHoursIST(TUE_0900_IST)).toBe(true);
    expect(isMarketHoursIST(TUE_1529_IST)).toBe(true);
    expect(isMarketHoursIST(TUE_1530_IST)).toBe(false);
  });
});

describe("getHomeTarget", () => {
  it("auto → Mission Control during market hours", () => {
    expect(getHomeTarget(TUE_1000_IST, "auto").href).toBe("/mission-control");
  });
  it("auto → Command Centre outside market hours", () => {
    expect(getHomeTarget(TUE_2000_IST, "auto").href).toBe("/command-center");
    expect(getHomeTarget(SAT_1000_IST, "auto").href).toBe("/command-center");
  });
  it("explicit preferences override the clock", () => {
    expect(getHomeTarget(TUE_2000_IST, "mission-control").href).toBe("/mission-control");
    expect(getHomeTarget(TUE_1000_IST, "command-center").href).toBe("/command-center");
  });
});

describe("home preference persistence", () => {
  beforeEach(() => localStorage.clear());
  it("defaults to auto", () => {
    expect(getHomePreference()).toBe("auto");
  });
  it("round-trips through localStorage and rejects garbage", () => {
    setHomePreference("mission-control");
    expect(getHomePreference()).toBe("mission-control");
    localStorage.setItem(HOME_PREF_KEY, "nonsense");
    expect(getHomePreference()).toBe("auto");
  });
});
