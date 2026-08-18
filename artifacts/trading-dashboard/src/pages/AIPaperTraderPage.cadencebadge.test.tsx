// @vitest-environment jsdom
/**
 * AIPaperTraderPage.cadencebadge.test.tsx
 *
 * Verifies the Intraday Scan Cadence badge logic (cadenceBadgeState):
 *  - Explicit closed states (CLOSED / POST_CLOSE / HOLIDAY) → "Market closed",
 *    regardless of coverage/gap quality.
 *  - OPEN with good coverage → "On Track"; OPEN with poor coverage → "Review".
 *  - UNKNOWN / undefined market state (loading or failed health-v2) must NOT
 *    be presented as a confirmed market closure.
 */
import { describe, it, expect } from "vitest";
import { cadenceBadgeState } from "./AIPaperTraderPage";

describe("cadenceBadgeState", () => {
  it("shows Market closed for CLOSED even when coverage is poor", () => {
    const b = cadenceBadgeState("CLOSED", false, false);
    expect(b.label).toBe("Market closed");
    expect(b.marketClosed).toBe(true);
  });

  it("shows Market closed for POST_CLOSE and HOLIDAY", () => {
    expect(cadenceBadgeState("POST_CLOSE", true, true).label).toBe("Market closed");
    expect(cadenceBadgeState("HOLIDAY", true, true).label).toBe("Market closed");
  });

  it("shows On Track during OPEN with good coverage and gaps", () => {
    const b = cadenceBadgeState("OPEN", true, true);
    expect(b.label).toBe("On Track");
    expect(b.marketClosed).toBe(false);
  });

  it("shows Review during OPEN with poor coverage", () => {
    expect(cadenceBadgeState("OPEN", false, true).label).toBe("Review");
    expect(cadenceBadgeState("OPEN", true, false).label).toBe("Review");
  });

  it("does NOT claim Market closed when health state is UNKNOWN or missing", () => {
    expect(cadenceBadgeState("UNKNOWN", true, true).marketClosed).toBe(false);
    expect(cadenceBadgeState(undefined, true, true).marketClosed).toBe(false);
    expect(cadenceBadgeState("UNKNOWN", true, true).label).toBe("On Track");
    expect(cadenceBadgeState(undefined, false, false).label).toBe("Review");
  });

  it("keeps Review reserved for degraded in-session coverage in PRE_OPEN too", () => {
    expect(cadenceBadgeState("PRE_OPEN", false, false).label).toBe("Review");
  });
});
