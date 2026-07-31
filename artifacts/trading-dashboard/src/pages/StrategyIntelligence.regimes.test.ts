/**
 * StrategyIntelligence.regimes.test.ts
 *
 * Tests for the Phase 13 → Strategy Intelligence regime taxonomy mapping and
 * the zero-trade synthetic-row logic.
 *
 * These are pure-logic tests that do NOT mount React components; they
 * exercise the exported constants and the rules that drive the Regimes tab UI.
 */

import { describe, it, expect } from "vitest";
import {
  PHASE13_TO_SI_REGIMES,
  PHASE13_TO_SI_PRIMARY,
} from "./StrategyIntelligence";

// ── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Mirrors the component logic: given a Phase 13 regime string, return the
 * SI equivalent labels (or [] if unknown).
 */
function siEquivalents(phase13: string | undefined): readonly string[] {
  if (!phase13) return [];
  return PHASE13_TO_SI_REGIMES[phase13] ?? [];
}

/**
 * Mirrors the component logic: given a Phase 13 regime string, return the
 * primary (best-single) SI label (or undefined if unknown).
 */
function siPrimary(phase13: string | undefined): string | undefined {
  if (!phase13) return undefined;
  return PHASE13_TO_SI_PRIMARY[phase13];
}

/**
 * Mirrors the synthetic-row creation logic in the component:
 *   - If the primary SI label is NOT in the existing matrix rows, produce a
 *     placeholder row with 0 trades.
 *   - If it IS already there, return null (no synthesis needed).
 */
function makeSyntheticRow(
  phase13: string | undefined,
  existingRegimes: string[],
): { regime: string; trades: number } | null {
  const primary = siPrimary(phase13);
  if (!primary) return null;
  if (existingRegimes.includes(primary)) return null;
  return { regime: primary, trades: 0 };
}

/**
 * Mirrors the per-row isLive check:
 *   A matrix row is "live" when its SI label is in the equivalents set for the
 *   active Phase 13 regime.
 */
function isRowLive(rowRegime: string, phase13: string | undefined): boolean {
  return siEquivalents(phase13).includes(rowRegime);
}

// ── Mapping completeness ──────────────────────────────────────────────────────

const KNOWN_PHASE13 = ["TRENDING_UP", "TRENDING_DOWN", "RANGE_BOUND", "VOLATILE", "CRISIS"];
const VALID_SI_LABELS = [
  "Strong Bullish", "Bullish", "Neutral", "Bearish",
  "Strong Bearish", "High Volatility", "Low Volatility",
];

describe("PHASE13_TO_SI_REGIMES", () => {
  it("covers every known Phase 13 value", () => {
    for (const p13 of KNOWN_PHASE13) {
      expect(PHASE13_TO_SI_REGIMES).toHaveProperty(p13);
    }
  });

  it("maps each Phase 13 value to at least one SI label", () => {
    for (const p13 of KNOWN_PHASE13) {
      const labels = PHASE13_TO_SI_REGIMES[p13];
      expect(labels.length).toBeGreaterThan(0);
    }
  });

  it("uses only valid SI label strings in all mappings", () => {
    for (const [p13, labels] of Object.entries(PHASE13_TO_SI_REGIMES)) {
      for (const label of labels) {
        expect(VALID_SI_LABELS).toContain(label);
      }
    }
  });

  it("maps TRENDING_UP to bullish SI labels", () => {
    const labels = PHASE13_TO_SI_REGIMES.TRENDING_UP;
    expect(labels).toContain("Bullish");
    expect(labels.some(l => l.includes("Bullish"))).toBe(true);
  });

  it("maps TRENDING_DOWN to bearish SI labels", () => {
    const labels = PHASE13_TO_SI_REGIMES.TRENDING_DOWN;
    expect(labels.some(l => l.includes("Bearish"))).toBe(true);
  });

  it("maps RANGE_BOUND to sideways/stable SI labels", () => {
    const labels = PHASE13_TO_SI_REGIMES.RANGE_BOUND;
    expect(labels).toContain("Neutral");
  });

  it("maps VOLATILE to High Volatility", () => {
    expect(PHASE13_TO_SI_REGIMES.VOLATILE).toContain("High Volatility");
  });

  it("maps CRISIS to a bearish SI label", () => {
    const labels = PHASE13_TO_SI_REGIMES.CRISIS;
    expect(labels.some(l => l.includes("Bearish"))).toBe(true);
  });
});

// ── Primary mapping ───────────────────────────────────────────────────────────

describe("PHASE13_TO_SI_PRIMARY", () => {
  it("covers every known Phase 13 value", () => {
    for (const p13 of KNOWN_PHASE13) {
      expect(PHASE13_TO_SI_PRIMARY).toHaveProperty(p13);
    }
  });

  it("returns a valid SI label for every Phase 13 value", () => {
    for (const p13 of KNOWN_PHASE13) {
      const label = PHASE13_TO_SI_PRIMARY[p13];
      expect(VALID_SI_LABELS).toContain(label);
    }
  });

  it("primary is always one of the equivalents for the same Phase 13 value", () => {
    for (const p13 of KNOWN_PHASE13) {
      const primary = PHASE13_TO_SI_PRIMARY[p13];
      const equivalents = PHASE13_TO_SI_REGIMES[p13];
      expect(equivalents).toContain(primary);
    }
  });
});

// ── siEquivalents helper ──────────────────────────────────────────────────────

describe("siEquivalents (component logic)", () => {
  it("returns [] for undefined input", () => {
    expect(siEquivalents(undefined)).toEqual([]);
  });

  it("returns [] for an unknown Phase 13 string", () => {
    expect(siEquivalents("UNKNOWN_REGIME")).toEqual([]);
  });

  it("returns non-empty array for each known Phase 13 value", () => {
    for (const p13 of KNOWN_PHASE13) {
      expect(siEquivalents(p13).length).toBeGreaterThan(0);
    }
  });

  it("returns ['Neutral', 'Low Volatility'] for RANGE_BOUND", () => {
    expect(siEquivalents("RANGE_BOUND")).toContain("Neutral");
    expect(siEquivalents("RANGE_BOUND")).toContain("Low Volatility");
  });

  it("returns ['High Volatility'] for VOLATILE", () => {
    expect(siEquivalents("VOLATILE")).toEqual(["High Volatility"]);
  });
});

// ── isRowLive helper (row-highlight logic) ────────────────────────────────────

describe("isRowLive (row-highlight logic)", () => {
  it("highlights 'Neutral' when Phase 13 is RANGE_BOUND", () => {
    expect(isRowLive("Neutral", "RANGE_BOUND")).toBe(true);
  });

  it("highlights 'Low Volatility' when Phase 13 is RANGE_BOUND", () => {
    expect(isRowLive("Low Volatility", "RANGE_BOUND")).toBe(true);
  });

  it("does NOT highlight 'Bullish' when Phase 13 is RANGE_BOUND", () => {
    expect(isRowLive("Bullish", "RANGE_BOUND")).toBe(false);
  });

  it("highlights 'Bullish' when Phase 13 is TRENDING_UP", () => {
    expect(isRowLive("Bullish", "TRENDING_UP")).toBe(true);
  });

  it("highlights 'Strong Bullish' when Phase 13 is TRENDING_UP", () => {
    expect(isRowLive("Strong Bullish", "TRENDING_UP")).toBe(true);
  });

  it("does NOT highlight 'Strong Bullish' when Phase 13 is TRENDING_DOWN", () => {
    expect(isRowLive("Strong Bullish", "TRENDING_DOWN")).toBe(false);
  });

  it("highlights 'Bearish' when Phase 13 is TRENDING_DOWN", () => {
    expect(isRowLive("Bearish", "TRENDING_DOWN")).toBe(true);
  });

  it("highlights 'Strong Bearish' when Phase 13 is CRISIS", () => {
    expect(isRowLive("Strong Bearish", "CRISIS")).toBe(true);
  });

  it("highlights 'High Volatility' when Phase 13 is VOLATILE", () => {
    expect(isRowLive("High Volatility", "VOLATILE")).toBe(true);
  });

  it("returns false for all rows when Phase 13 is undefined", () => {
    for (const si of VALID_SI_LABELS) {
      expect(isRowLive(si, undefined)).toBe(false);
    }
  });

  it("returns false when Phase 13 is unknown", () => {
    expect(isRowLive("Neutral", "SIDEWAYS_WEIRD")).toBe(false);
  });
});

// ── Synthetic zero-trade row logic ─────────────────────────────────────────────

describe("makeSyntheticRow (zero-trade row synthesis)", () => {
  it("returns null when phase13 is undefined", () => {
    expect(makeSyntheticRow(undefined, [])).toBeNull();
  });

  it("returns null when phase13 is unknown", () => {
    expect(makeSyntheticRow("MYSTERY", [])).toBeNull();
  });

  it("creates a zero-trade placeholder when the primary SI label is absent from matrix", () => {
    // RANGE_BOUND primary → "Neutral"
    const row = makeSyntheticRow("RANGE_BOUND", ["Bullish", "Bearish"]);
    expect(row).not.toBeNull();
    expect(row!.regime).toBe("Neutral");
    expect(row!.trades).toBe(0);
  });

  it("does NOT create a row when the primary SI label already exists in the matrix", () => {
    // RANGE_BOUND primary → "Neutral"; it already exists
    const row = makeSyntheticRow("RANGE_BOUND", ["Neutral", "Bearish"]);
    expect(row).toBeNull();
  });

  it("synthesises 'Bullish' for TRENDING_UP when matrix has no bullish data", () => {
    const row = makeSyntheticRow("TRENDING_UP", ["Neutral", "High Volatility"]);
    expect(row!.regime).toBe("Bullish");
    expect(row!.trades).toBe(0);
  });

  it("synthesises 'Bearish' for TRENDING_DOWN when matrix is empty", () => {
    const row = makeSyntheticRow("TRENDING_DOWN", []);
    expect(row!.regime).toBe("Bearish");
    expect(row!.trades).toBe(0);
  });

  it("synthesises 'High Volatility' for VOLATILE when matrix is empty", () => {
    const row = makeSyntheticRow("VOLATILE", []);
    expect(row!.regime).toBe("High Volatility");
    expect(row!.trades).toBe(0);
  });

  it("synthesises 'Strong Bearish' for CRISIS when matrix has only Neutral", () => {
    const row = makeSyntheticRow("CRISIS", ["Neutral"]);
    expect(row!.regime).toBe("Strong Bearish");
    expect(row!.trades).toBe(0);
  });

  it("synthetic row primary label is always in the equivalents set", () => {
    for (const p13 of KNOWN_PHASE13) {
      const row = makeSyntheticRow(p13, []); // empty matrix, always synthesises
      if (row) {
        const equivalents = siEquivalents(p13);
        expect(equivalents).toContain(row.regime);
      }
    }
  });
});

// ── Per-strategy coverage aggregation logic ───────────────────────────────────

describe("per-strategy coverage aggregation", () => {
  /**
   * Mirrors the component logic for summing regime_breakdown trades across
   * all SI equivalents for the active Phase 13 regime.
   */
  function aggregateCoverage(
    regimeBreakdown: Record<string, { trades: number; win_rate: number; net_pnl: number }>,
    phase13: string,
  ): { cnt: number; winRateAvg: number; netPnlSum: number } {
    const equivalents = siEquivalents(phase13);
    let cnt = 0, winRateSum = 0, netPnlSum = 0;
    for (const siLabel of equivalents) {
      const rb = regimeBreakdown[siLabel];
      if (rb && rb.trades > 0) {
        cnt         += rb.trades;
        winRateSum  += rb.win_rate * rb.trades;
        netPnlSum   += rb.net_pnl;
      }
    }
    return { cnt, winRateAvg: cnt > 0 ? winRateSum / cnt : 0, netPnlSum };
  }

  it("sums Bullish + Strong Bullish trades for TRENDING_UP", () => {
    const breakdown = {
      Bullish:       { trades: 5, win_rate: 60, net_pnl: 1000 },
      "Strong Bullish": { trades: 3, win_rate: 80, net_pnl: 2000 },
      Bearish:       { trades: 2, win_rate: 30, net_pnl: -500 },
    };
    const result = aggregateCoverage(breakdown, "TRENDING_UP");
    expect(result.cnt).toBe(8); // 5 + 3, Bearish excluded
    expect(result.netPnlSum).toBe(3000); // 1000 + 2000
    // Weighted win rate: (60*5 + 80*3) / 8 = (300 + 240) / 8 = 67.5
    expect(result.winRateAvg).toBeCloseTo(67.5, 2);
  });

  it("returns 0 when strategy has no trades in any equivalent regime", () => {
    const breakdown = {
      Bearish:          { trades: 4, win_rate: 40, net_pnl: -400 },
      "High Volatility": { trades: 2, win_rate: 50, net_pnl: 100 },
    };
    // RANGE_BOUND → Neutral, Low Volatility — neither in breakdown
    const result = aggregateCoverage(breakdown, "RANGE_BOUND");
    expect(result.cnt).toBe(0);
  });

  it("counts only Neutral and Low Volatility for RANGE_BOUND", () => {
    const breakdown = {
      Neutral:         { trades: 6, win_rate: 55, net_pnl: 800 },
      "Low Volatility": { trades: 2, win_rate: 70, net_pnl: 400 },
      Bullish:         { trades: 10, win_rate: 65, net_pnl: 2000 },
    };
    const result = aggregateCoverage(breakdown, "RANGE_BOUND");
    expect(result.cnt).toBe(8); // 6 + 2
    expect(result.netPnlSum).toBe(1200); // 800 + 400
  });

  it("returns 0 for VOLATILE when only non-volatility regimes exist", () => {
    const breakdown = {
      Neutral: { trades: 5, win_rate: 60, net_pnl: 500 },
      Bullish: { trades: 3, win_rate: 70, net_pnl: 300 },
    };
    const result = aggregateCoverage(breakdown, "VOLATILE");
    expect(result.cnt).toBe(0);
  });

  it("counts High Volatility trades for VOLATILE", () => {
    const breakdown = {
      "High Volatility": { trades: 4, win_rate: 45, net_pnl: -200 },
      Neutral:           { trades: 8, win_rate: 60, net_pnl: 900 },
    };
    const result = aggregateCoverage(breakdown, "VOLATILE");
    expect(result.cnt).toBe(4);
    expect(result.netPnlSum).toBe(-200);
  });
});

// ── Source analysis: no raw string comparison to Phase 13 labels ──────────────

import fs from "fs";
import path from "path";

describe("source-level taxonomy guard", () => {
  const src = fs.readFileSync(
    path.join(__dirname, "StrategyIntelligence.tsx"),
    "utf-8",
  );

  const phase13Labels = ["TRENDING_UP", "TRENDING_DOWN", "RANGE_BOUND", "VOLATILE", "CRISIS"];
  const siLabels = ["Strong Bullish", "Bullish", "Neutral", "Bearish", "Strong Bearish", "High Volatility", "Low Volatility"];

  it("defines PHASE13_TO_SI_REGIMES mapping constant", () => {
    expect(src).toContain("PHASE13_TO_SI_REGIMES");
  });

  it("defines PHASE13_TO_SI_PRIMARY mapping constant", () => {
    expect(src).toContain("PHASE13_TO_SI_PRIMARY");
  });

  it("uses liveSiEquivalents (mapped set) for row highlighting, not raw livePhase13Regime", () => {
    // Row LIVE check must use liveSiEquivalents.includes, not livePhase13Regime ===
    expect(src).toContain("liveSiEquivalents.includes(r.regime)");
  });

  it("exports PHASE13_TO_SI_REGIMES for testability", () => {
    expect(src).toContain("export const PHASE13_TO_SI_REGIMES");
  });

  it("exports PHASE13_TO_SI_PRIMARY for testability", () => {
    expect(src).toContain("export const PHASE13_TO_SI_PRIMARY");
  });

  it("covers all 5 Phase 13 values in the mapping definition", () => {
    for (const label of phase13Labels) {
      expect(src).toContain(label);
    }
  });

  it("references SI label strings in the mapping definition", () => {
    // At least the primary targets should appear as string literals
    for (const label of ["Bullish", "Bearish", "Neutral", "High Volatility"]) {
      expect(src).toContain(label);
    }
  });

  it("synthesises a zero-trade row when the mapped SI label is absent from the matrix", () => {
    expect(src).toContain("syntheticRow");
    expect(src).toContain("trades: 0");
  });

  it("sums regime_breakdown trades across all SI equivalents for a Phase 13 regime", () => {
    // The coverage table iterates liveSiEquivalents and accumulates cnt
    expect(src).toContain("for (const siLabel of liveSiEquivalents)");
  });

  it("does not use raw Phase 13 strings as regime_breakdown keys for lookup", () => {
    // Should NOT do regime_breakdown["RANGE_BOUND"] or regime_breakdown["TRENDING_UP"] etc.
    for (const label of phase13Labels) {
      // The Phase 13 label should NOT appear as a lookup key in regime_breakdown
      expect(src).not.toContain(`regime_breakdown["${label}"]`);
      expect(src).not.toContain(`regime_breakdown['${label}']`);
    }
  });
});
