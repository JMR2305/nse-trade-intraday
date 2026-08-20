import { describe, expect, it } from "vitest";
import { getUniverseEvidenceNotice } from "./backtestUniverseEvidence";

describe("backtest universe evidence notices", () => {
  it("warns when a run used the explicitly opted-in current membership fallback", () => {
    const notice = getUniverseEvidenceNotice("CURRENT_MEMBERSHIP_FALLBACK", {
      as_of_date: "2025-01-10",
      degraded: true,
    });

    expect(notice).toMatchObject({
      tone: "warning",
      heading: "Current universe membership fallback used",
    });
    expect(notice?.detail).toContain("No immutable universe snapshot existed as of 2025-01-10");
    expect(notice?.detail).toContain("look-ahead bias");
  });

  it("preserves a distinct verified status for an immutable snapshot-backed run", () => {
    const notice = getUniverseEvidenceNotice("HISTORICAL_SNAPSHOT", {
      as_of_date: "2025-01-10",
      snapshot_at: "2025-01-09T18:30:00+00:00",
      degraded: false,
    });

    expect(notice).toMatchObject({
      tone: "verified",
      heading: "Immutable historical universe snapshot used",
    });
    expect(notice?.detail).toContain("Membership was resolved from the recorded universe");
  });

  it("does not present a result notice when the run did not use the custom universe", () => {
    expect(getUniverseEvidenceNotice(undefined, undefined)).toBeNull();
  });
});