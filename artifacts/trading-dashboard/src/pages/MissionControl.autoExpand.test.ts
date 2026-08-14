// @vitest-environment node
/**
 * MissionControl.autoExpand.test.ts
 *
 * Unit tests for the selectActiveStage() helper that drives the auto-expand
 * behaviour of the pipeline symbol grid during live scans (Task #708).
 *
 * Tests are pure-function, no DOM required.
 */

import { describe, it, expect } from "vitest";
import { selectActiveStage } from "./MissionControl";

// Helper: build a StageSummary-like object (only the fields selectActiveStage reads).
function stage(name: string, lastTs: string | null) {
  return {
    stage: name,
    events: 0,
    completed: 0,
    rejected: 0,
    errors: 0,
    last_ts: lastTs,
    last_symbol: null,
  } as const;
}

const NOW = 1_000_000_000_000; // fixed epoch ms for deterministic tests

// 30 s ago — "fresh"
const ts30s = new Date(NOW - 30_000).toISOString();
// 45 s ago — "fresh" (< 60 s)
const ts45s = new Date(NOW - 45_000).toISOString();
// 90 s ago — "stale" (≥ 60 s)
const ts90s = new Date(NOW - 90_000).toISOString();

describe("selectActiveStage", () => {
  it("returns null when there are no stages", () => {
    expect(selectActiveStage([], null, NOW)).toBeNull();
  });

  it("returns null when scanning is idle (all timestamps stale)", () => {
    const stages = [stage("SCANNER", ts90s), stage("STRATEGY", ts90s)];
    expect(selectActiveStage(stages, null, NOW)).toBeNull();
  });

  it("returns the only fresh stage", () => {
    const stages = [stage("SCANNER", ts90s), stage("STRATEGY", ts30s)];
    expect(selectActiveStage(stages, null, NOW)).toBe("STRATEGY");
  });

  it("picks the stage with the NEWEST last_ts when multiple are fresh", () => {
    // SUPERVISOR (ts45s) and SCANNER (ts30s) are both fresh;
    // SCANNER is newer so it should win — not SUPERVISOR (which comes first in order).
    const stages = [stage("SUPERVISOR", ts45s), stage("SCANNER", ts30s)];
    expect(selectActiveStage(stages, null, NOW)).toBe("SCANNER");
  });

  it("prefers progressStage over the newest-ts heuristic", () => {
    // Backend says STRATEGY is active even though SCANNER has a newer timestamp.
    const stages = [stage("SUPERVISOR", ts45s), stage("SCANNER", ts30s), stage("STRATEGY", ts90s)];
    expect(selectActiveStage(stages, "STRATEGY", NOW)).toBe("STRATEGY");
  });

  it("falls back to newest-ts heuristic when progressStage is null", () => {
    const stages = [stage("SUPERVISOR", ts45s), stage("SCANNER", ts30s)];
    expect(selectActiveStage(stages, null, NOW)).toBe("SCANNER");
  });

  it("falls back to newest-ts heuristic when progressStage is empty string", () => {
    const stages = [stage("SUPERVISOR", ts45s), stage("SCANNER", ts30s)];
    expect(selectActiveStage(stages, "", NOW)).toBe("SCANNER");
  });

  it("ignores stages with null last_ts", () => {
    const stages = [stage("SUPERVISOR", null), stage("SCANNER", ts30s)];
    expect(selectActiveStage(stages, null, NOW)).toBe("SCANNER");
  });

  it("returns null when all stages have null last_ts", () => {
    const stages = [stage("SUPERVISOR", null), stage("SCANNER", null)];
    expect(selectActiveStage(stages, null, NOW)).toBeNull();
  });

  it("stage exactly at the 60 s boundary is treated as stale", () => {
    // 60_000 ms ago — NOT fresh (condition is < 60_000)
    const tsExact60 = new Date(NOW - 60_000).toISOString();
    const stages = [stage("SCANNER", tsExact60)];
    expect(selectActiveStage(stages, null, NOW)).toBeNull();
  });

  it("stage 1 ms inside the window is treated as fresh", () => {
    const ts59999 = new Date(NOW - 59_999).toISOString();
    const stages = [stage("SCANNER", ts59999)];
    expect(selectActiveStage(stages, null, NOW)).toBe("SCANNER");
  });

  it("transition: returns new active stage when pipeline advances", () => {
    // First call: SCANNER is newest-active
    const stagesA = [stage("SUPERVISOR", ts45s), stage("SCANNER", ts30s)];
    expect(selectActiveStage(stagesA, null, NOW)).toBe("SCANNER");

    // Transition: STRATEGY becomes newest-active (SCANNER's ts is still fresh but older)
    const tsNow = new Date(NOW - 5_000).toISOString();
    const stagesB = [stage("SUPERVISOR", ts45s), stage("SCANNER", ts30s), stage("STRATEGY", tsNow)];
    expect(selectActiveStage(stagesB, null, NOW)).toBe("STRATEGY");
  });
});
