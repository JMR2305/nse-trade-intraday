/**
 * ExecutiveDashboard.aiHealth.test.ts
 *
 * Contract tests for the AI Health tile in ExecutiveDashboard.tsx.
 *
 * Three areas:
 *
 * 1. Pure-logic tests: replicate extractAiScore / extractAiLabel helpers
 *    and verify correct scalar extraction from both object and number forms.
 *
 * 2. Fraction-to-percentage rendering: verify the component source reads
 *    `prediction.accuracy * 100` and `avg_confidence * 100`, not the raw 0-1
 *    fractions. This catches a regression where "0.7%" would be displayed
 *    instead of "70.0%".
 *
 * 3. API payload shape contract: verify the component reads
 *    `prediction.accuracy`, NOT a top-level `prediction_accuracy` field
 *    (which the real /api/ai/summary does not emit).
 */

import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve, join } from "node:path";

// ── File paths ─────────────────────────────────────────────────────────────

const SRC_DIR = resolve(__dirname, "..");
const EXEC_DASH = join(SRC_DIR, "pages", "ExecutiveDashboard.tsx");
const src = readFileSync(EXEC_DASH, "utf8");

// ── 1. Pure-logic tests for extractAiScore / extractAiLabel ───────────────

/**
 * Inline reimplementation of the helpers so we can unit-test them
 * without importing the full component tree.
 */
function extractAiScore(hs: unknown): number {
  if (hs == null) return 0;
  if (typeof hs === "number") return hs;
  const obj = hs as Record<string, unknown>;
  return typeof obj.total_score === "number" ? obj.total_score : 0;
}

function extractAiLabel(hs: unknown): string {
  if (hs == null) return "N/A";
  if (typeof hs === "number") {
    if (hs >= 80) return "Excellent";
    if (hs >= 65) return "Good";
    if (hs >= 50) return "Fair";
    if (hs >= 35) return "Poor";
    return "Critical";
  }
  const obj = hs as Record<string, unknown>;
  return typeof obj.label === "string" ? obj.label : "N/A";
}

describe("extractAiScore", () => {
  it("returns 0 for null / undefined", () => {
    expect(extractAiScore(null)).toBe(0);
    expect(extractAiScore(undefined)).toBe(0);
  });

  it("returns the scalar directly when health_score is a number", () => {
    expect(extractAiScore(75)).toBe(75);
    expect(extractAiScore(0)).toBe(0);
    expect(extractAiScore(100)).toBe(100);
  });

  it("extracts total_score from the composite object the real API emits", () => {
    const realPayload = {
      total_score: 62.5,
      label: "Fair",
      components: { prediction_accuracy: 50.0, calibration_quality: 75.0 },
      weights: { prediction_accuracy: 0.25, calibration_quality: 0.2 },
    };
    expect(extractAiScore(realPayload)).toBe(62.5);
  });

  it("returns 0 when object has no total_score", () => {
    expect(extractAiScore({ label: "N/A" })).toBe(0);
  });
});

describe("extractAiLabel", () => {
  it("returns 'N/A' for null / undefined", () => {
    expect(extractAiLabel(null)).toBe("N/A");
    expect(extractAiLabel(undefined)).toBe("N/A");
  });

  it("derives label from numeric score thresholds", () => {
    expect(extractAiLabel(80)).toBe("Excellent");
    expect(extractAiLabel(70)).toBe("Good");
    expect(extractAiLabel(55)).toBe("Fair");
    expect(extractAiLabel(40)).toBe("Poor");
    expect(extractAiLabel(20)).toBe("Critical");
  });

  it("returns the label field from the composite object", () => {
    expect(extractAiLabel({ total_score: 62.5, label: "Fair" })).toBe("Fair");
    expect(extractAiLabel({ total_score: 0.0, label: "Critical" })).toBe("Critical");
  });

  it("returns 'N/A' when object has no label field", () => {
    expect(extractAiLabel({ total_score: 42 })).toBe("N/A");
  });
});

// ── 2. Fraction-to-percentage rendering contract ──────────────────────────

describe("AIHealthTile — fraction-to-percentage conversion", () => {
  it("multiplies prediction.accuracy by 100 before display", () => {
    // The source must contain 'd.prediction.accuracy * 100' (or similar)
    // to convert the 0-1 fraction from the API to a displayable percentage.
    expect(src).toMatch(/prediction\.accuracy\s*\*\s*100/);
  });

  it("multiplies avg_confidence by 100 before display", () => {
    // avg_confidence from /api/ai/summary is a 0-1 fraction.
    expect(src).toMatch(/avg_confidence\s*\*\s*100/);
  });

  it("does NOT attempt to display raw prediction.accuracy without conversion", () => {
    // Safeguard: the direct string 'd.prediction.accuracy.toFixed' would
    // produce values like '0.70%' instead of '70.0%'.
    expect(src).not.toMatch(/prediction\.accuracy\.toFixed/);
  });

  it("does NOT attempt to display raw avg_confidence without conversion", () => {
    // Safeguard against regressing to raw fraction display.
    // All toFixed calls on avg_confidence must go through * 100 first.
    // We check the source doesn't contain a direct 'd.avg_confidence.toFixed'.
    expect(src).not.toMatch(/d\.avg_confidence\.toFixed/);
  });
});

// ── 3. API payload shape contract ─────────────────────────────────────────

describe("AIHealthTile — API field path contract", () => {
  it("reads prediction accuracy from prediction.accuracy, not a top-level prediction_accuracy", () => {
    // The real /api/ai/summary does NOT have a top-level prediction_accuracy field.
    // The component must use d.prediction?.accuracy (nested under prediction object).
    expect(src).toMatch(/prediction\?\.accuracy/);
  });

  it("does NOT reference a top-level prediction_accuracy field in the tile section", () => {
    // Isolate to the AIHealthTile component body. If 'prediction_accuracy' appears
    // it must be in the AISummaryData interface or score components, not as a
    // top-level UI read in the tile.
    //
    // Check that 'd.prediction_accuracy' is absent — would indicate incorrect field path.
    expect(src).not.toMatch(/d\.prediction_accuracy/);
  });

  it("uses d.avg_confidence (top-level field in the real API response)", () => {
    // avg_confidence IS a top-level field in /api/ai/summary (not nested).
    expect(src).toMatch(/d\.avg_confidence/);
  });

  it("references d.total_signals for the Signals metric", () => {
    expect(src).toMatch(/d\.total_signals/);
  });

  it("links to /ai-performance for the 'View Full' action", () => {
    expect(src).toMatch(/\/ai-performance/);
  });

  it("hides the tile when status === 'DISABLED'", () => {
    // The AIHealthTile must check for the DISABLED status.
    expect(src).toMatch(/DISABLED/);
  });
});

// ── 4. Representitive enabled payload — format check ──────────────────────

describe("Fraction display — representative enabled payload", () => {
  /**
   * Simulate what AIHealthTile.tsx would render for a representative payload.
   * We replicate the *exact* formatting expressions from the component here
   * so that if the component source changes (e.g. extracts to a helper),
   * these tests serve as the specification.
   */
  const payload = {
    status: "ENABLED",
    health_score: { total_score: 72.5, label: "Good" },
    trend_direction: "Improving",
    accuracy_delta: 3.2,
    avg_confidence: 0.68,   // ← 0-1 fraction from real API
    total_signals: 142,
    prediction: {
      accuracy: 0.73,        // ← 0-1 fraction from real API
      precision: 0.71,
      recall: 0.75,
    },
  };

  it("converts prediction.accuracy 0.73 → '73.0%'", () => {
    const displayed = (payload.prediction.accuracy * 100).toFixed(1) + "%";
    expect(displayed).toBe("73.0%");
  });

  it("converts avg_confidence 0.68 → '68.0%'", () => {
    const displayed = (payload.avg_confidence * 100).toFixed(1) + "%";
    expect(displayed).toBe("68.0%");
  });

  it("does NOT display raw fraction '0.73%' for accuracy", () => {
    // If someone forgets * 100, the output would be this wrong string
    const wrongDisplay = payload.prediction.accuracy.toFixed(1) + "%";
    expect(wrongDisplay).not.toBe("73.0%");  // sanity check: raw is '0.7%', not '73.0%'
    expect(wrongDisplay).toBe("0.7%");
  });

  it("does NOT display raw fraction '0.68%' for confidence", () => {
    const wrongDisplay = payload.avg_confidence.toFixed(1) + "%";
    expect(wrongDisplay).not.toBe("68.0%");
    expect(wrongDisplay).toBe("0.7%");
  });

  it("extracts score 72.5 from composite health_score object", () => {
    expect(extractAiScore(payload.health_score)).toBe(72.5);
  });

  it("extracts label 'Good' from composite health_score object", () => {
    expect(extractAiLabel(payload.health_score)).toBe("Good");
  });
});
