/**
 * Task-32 — Exposure warning banner smoke tests
 *
 * Three areas covered:
 *
 * 1. Pure-logic unit tests: replicate the `exposureColor` helper and the
 *    warning-generation logic from PortfolioLive.tsx / portfolio_snapshot.py
 *    to assert correct behaviour at the 0.80 and 1.0 ratio thresholds.
 *
 * 2. Static source-analysis tests: read PortfolioLive.tsx and assert that the
 *    `ExposureWarningBanner` component has the expected conditional rendering
 *    branches, data-testid, and CSS class choices — so a future refactor
 *    cannot silently remove the guard or wrong-class a CRITICAL state.
 *
 * 3. Snapshot API shape tests: verify that portfolio_snapshot.py emits the
 *    required fields (`exposure_warnings`, `severity`, `ratio`) that the UI
 *    reads, so back-end changes that drop or rename fields are caught early.
 */

import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve, join } from "node:path";

// ── Paths ──────────────────────────────────────────────────────────────────

const DASHBOARD_SRC = resolve(__dirname, "..");
const PORTFOLIO_PAGE = join(DASHBOARD_SRC, "pages", "PortfolioLive.tsx");
const SNAPSHOT_PY = resolve(
  __dirname,
  "..",
  "..",
  "..",
  "api-server",
  "src",
  "python",
  "portfolio_snapshot.py",
);

const pageSrc = readFileSync(PORTFOLIO_PAGE, "utf8");
const snapshotPySrc = readFileSync(SNAPSHOT_PY, "utf8");

// ── Re-implemented helpers (mirrors PortfolioLive.tsx exactly) ─────────────

const WARNING_RATIO = 0.80;

function exposureColor(ratio: number): { bar: string; text: string } {
  if (ratio >= 1.0) return { bar: "bg-red-500",    text: "text-red-400" };
  if (ratio >= 0.8) return { bar: "bg-yellow-500", text: "text-yellow-400" };
  return              { bar: "bg-green-500",        text: "text-green-400" };
}

interface ExposureWarning {
  kind: "instrument" | "sector";
  name: string;
  exposure_pct: number;
  limit_pct: number;
  ratio: number;
  severity: "WARNING" | "CRITICAL";
}

/** Mirrors ExposureWarningBanner's banner-visible predicate */
function bannerShouldRender(warnings: ExposureWarning[]): boolean {
  return warnings.length > 0;
}

/** Mirrors ExposureWarningBanner's hasCritical → CSS class branch */
function bannerBorderClass(warnings: ExposureWarning[]): string {
  const hasCritical = warnings.some((w) => w.severity === "CRITICAL");
  return hasCritical
    ? "border-red-500/40 bg-red-500/10"
    : "border-yellow-500/40 bg-yellow-500/10";
}

/** Mirrors ExposureWarningBanner's heading text */
function bannerHeading(warnings: ExposureWarning[]): string {
  const hasCritical = warnings.some((w) => w.severity === "CRITICAL");
  return hasCritical ? "EXPOSURE LIMIT BREACHED" : "EXPOSURE LIMIT WARNING";
}

/** Mirrors portfolio_snapshot.py warning generation */
function buildWarnings(params: {
  exposurePct: number;
  limitPct: number;
}): ExposureWarning[] {
  const { exposurePct, limitPct } = params;
  const ratio = limitPct > 0 ? exposurePct / limitPct : 0;
  if (ratio < WARNING_RATIO) return [];
  return [
    {
      kind: "instrument",
      name: "TESTSYM",
      exposure_pct: exposurePct,
      limit_pct: limitPct,
      ratio: Math.round(ratio * 10000) / 10000,
      severity: ratio >= 1.0 ? "CRITICAL" : "WARNING",
    },
  ];
}

// ── 1. Pure-logic tests ────────────────────────────────────────────────────

describe("exposureColor helper — colour thresholds", () => {
  it("green below 80 %", () => {
    expect(exposureColor(0.0).bar).toBe("bg-green-500");
    expect(exposureColor(0.5).bar).toBe("bg-green-500");
    expect(exposureColor(0.799).bar).toBe("bg-green-500");
  });

  it("yellow at exactly 80 %", () => {
    expect(exposureColor(0.80).bar).toBe("bg-yellow-500");
    expect(exposureColor(0.80).text).toBe("text-yellow-400");
  });

  it("yellow between 80 % and 99.9 %", () => {
    expect(exposureColor(0.85).bar).toBe("bg-yellow-500");
    expect(exposureColor(0.999).bar).toBe("bg-yellow-500");
  });

  it("red at exactly 100 % (limit reached)", () => {
    expect(exposureColor(1.0).bar).toBe("bg-red-500");
    expect(exposureColor(1.0).text).toBe("text-red-400");
  });

  it("red above 100 % (limit breached)", () => {
    expect(exposureColor(1.2).bar).toBe("bg-red-500");
    expect(exposureColor(1.5).bar).toBe("bg-red-500");
  });
});

describe("Warning generation — near-limit position (ratio ≥ 0.80)", () => {
  it("generates a WARNING when exposure is exactly at 80 % of the limit", () => {
    // 16% exposure / 20% limit → ratio = 0.80
    const warnings = buildWarnings({ exposurePct: 16.0, limitPct: 20.0 });
    expect(warnings).toHaveLength(1);
    expect(warnings[0].severity).toBe("WARNING");
    expect(warnings[0].ratio).toBeCloseTo(0.8, 4);
  });

  it("generates a WARNING for any ratio in [0.80, 1.0)", () => {
    const warnings = buildWarnings({ exposurePct: 17.0, limitPct: 20.0 });
    expect(warnings[0].severity).toBe("WARNING");
    expect(bannerShouldRender(warnings)).toBe(true);
  });

  it("banner heading reads 'EXPOSURE LIMIT WARNING' for WARNING severity", () => {
    const warnings = buildWarnings({ exposurePct: 17.0, limitPct: 20.0 });
    expect(bannerHeading(warnings)).toBe("EXPOSURE LIMIT WARNING");
  });

  it("banner uses yellow border class for WARNING severity", () => {
    const warnings = buildWarnings({ exposurePct: 17.0, limitPct: 20.0 });
    expect(bannerBorderClass(warnings)).toContain("yellow");
    expect(bannerBorderClass(warnings)).not.toContain("red-500/40");
  });
});

describe("Warning banner absent — all ratios below threshold", () => {
  it("no warnings when exposure is well below the limit", () => {
    // 10% / 20% = ratio 0.5
    const warnings = buildWarnings({ exposurePct: 10.0, limitPct: 20.0 });
    expect(warnings).toHaveLength(0);
    expect(bannerShouldRender(warnings)).toBe(false);
  });

  it("no warnings when exposure is just under the 80 % threshold", () => {
    // 15.9% / 20% = ratio 0.795
    const warnings = buildWarnings({ exposurePct: 15.9, limitPct: 20.0 });
    expect(warnings).toHaveLength(0);
  });

  it("empty warnings array produces no banner", () => {
    expect(bannerShouldRender([])).toBe(false);
  });
});

describe("CRITICAL exposure — ratio ≥ 1.0", () => {
  it("severity is CRITICAL when exposure meets or exceeds the limit", () => {
    // 20% / 20% = ratio 1.0
    const warnings = buildWarnings({ exposurePct: 20.0, limitPct: 20.0 });
    expect(warnings[0].severity).toBe("CRITICAL");
    expect(warnings[0].ratio).toBeCloseTo(1.0, 4);
  });

  it("severity is CRITICAL when exposure exceeds the limit", () => {
    const warnings = buildWarnings({ exposurePct: 25.0, limitPct: 20.0 });
    expect(warnings[0].severity).toBe("CRITICAL");
  });

  it("banner heading reads 'EXPOSURE LIMIT BREACHED' for CRITICAL severity", () => {
    const warnings = buildWarnings({ exposurePct: 20.0, limitPct: 20.0 });
    expect(bannerHeading(warnings)).toBe("EXPOSURE LIMIT BREACHED");
  });

  it("banner uses red border class for CRITICAL severity", () => {
    const warnings = buildWarnings({ exposurePct: 20.0, limitPct: 20.0 });
    expect(bannerBorderClass(warnings)).toContain("red-500/40");
    expect(bannerBorderClass(warnings)).not.toContain("yellow");
  });

  it("exposureColor returns red bar at ratio 1.0", () => {
    const warnings = buildWarnings({ exposurePct: 20.0, limitPct: 20.0 });
    expect(exposureColor(warnings[0].ratio).bar).toBe("bg-red-500");
  });
});

// ── 2. Static source analysis — PortfolioLive.tsx ─────────────────────────

describe("PortfolioLive.tsx — ExposureWarningBanner renders conditionally", () => {
  it("returns null for an empty warnings array (banner absent path)", () => {
    // The component must short-circuit before emitting any DOM nodes.
    expect(pageSrc).toMatch(/if\s*\(\s*warnings\.length\s*===\s*0\s*\)\s*return\s+null/);
  });

  it("renders a div with data-testid='banner-exposure-warnings'", () => {
    expect(pageSrc).toContain('data-testid="banner-exposure-warnings"');
  });

  it("applies red border class when hasCritical is true", () => {
    // Must map CRITICAL → border-red-500/40
    expect(pageSrc).toContain("border-red-500/40 bg-red-500/10");
  });

  it("applies yellow border class for WARNING (non-critical) severity", () => {
    expect(pageSrc).toContain("border-yellow-500/40 bg-yellow-500/10");
  });

  it("contains the heading text for WARNING severity", () => {
    expect(pageSrc).toContain("EXPOSURE LIMIT WARNING");
  });

  it("contains the heading text for CRITICAL severity", () => {
    expect(pageSrc).toContain("EXPOSURE LIMIT BREACHED");
  });

  it("gates banner rendering on exposureWarnings.length > 0", () => {
    // The page component must not render the banner when there are no warnings.
    expect(pageSrc).toMatch(/exposureWarnings\.length\s*>\s*0/);
  });

  it("warns when ANY warning has severity CRITICAL (hasCritical flag)", () => {
    expect(pageSrc).toMatch(/warnings\.some\s*\(\s*\(?w\)?\s*=>\s*w\.severity\s*===\s*"CRITICAL"\s*\)/);
  });

  it("WARNING_RATIO constant matches the backend _WARNING_RATIO (both 0.80)", () => {
    expect(pageSrc).toContain("const WARNING_RATIO = 0.80");
  });
});

describe("PortfolioLive.tsx — ExposureBar uses correct fill width clamping", () => {
  it("clamps the fill bar to 100 % via Math.min", () => {
    expect(pageSrc).toContain("Math.min(100, ratio * 100)");
  });

  it("derives ratio from exposurePct / limitPct", () => {
    expect(pageSrc).toContain("limitPct > 0 ? exposurePct / limitPct : 0");
  });
});

// ── 3. Backend shape tests — portfolio_snapshot.py ────────────────────────

describe("portfolio_snapshot.py — exposure_warnings shape", () => {
  it("emits the 'exposure_warnings' key in the returned dict", () => {
    expect(snapshotPySrc).toContain('"exposure_warnings": exposure_warnings');
  });

  it("sets severity to 'CRITICAL' at ratio >= 1.0", () => {
    expect(snapshotPySrc).toContain('"CRITICAL" if ratio >= 1.0 else "WARNING"');
  });

  it("only fires a warning when ratio >= _WARNING_RATIO (0.80)", () => {
    expect(snapshotPySrc).toContain("if ratio >= _WARNING_RATIO:");
    expect(snapshotPySrc).toContain("_WARNING_RATIO = 0.80");
  });

  it("includes 'kind', 'name', 'exposure_pct', 'limit_pct', 'ratio', 'severity' keys", () => {
    expect(snapshotPySrc).toContain('"kind":');
    expect(snapshotPySrc).toContain('"name":');
    expect(snapshotPySrc).toContain('"exposure_pct":');
    expect(snapshotPySrc).toContain('"limit_pct":');
    expect(snapshotPySrc).toContain('"ratio":');
    expect(snapshotPySrc).toContain('"severity":');
  });

  it("also checks sector exposures for warnings (not just instrument)", () => {
    expect(snapshotPySrc).toContain('"kind": "sector"');
    expect(snapshotPySrc).toContain('"kind": "instrument"');
  });

  it("emits instrument_limit_pct and sector_limit_pct so the UI can display limits", () => {
    expect(snapshotPySrc).toContain('"instrument_limit_pct": instrument_limit_pct');
    expect(snapshotPySrc).toContain('"sector_limit_pct": sector_limit_pct');
  });

  it("uses sector ratio from sector_exposures (not recomputed inline)", () => {
    // sector loop must reference se["ratio"], not recompute it
    expect(snapshotPySrc).toContain('if se["ratio"] >= _WARNING_RATIO:');
  });
});

// ── 4. Badge-count accuracy — badge-exposure-warnings-count ───────────────
//
// These tests assert the invariant: the badge text is always derived from
// `exposureWarnings.length` so it can never drift from the actual list.
// We cover four scenarios:
//   a) empty list  → badge absent
//   b) 1 warning   → badge shows "1 limit warning"
//   c) 2 warnings  → badge shows "2 limit warnings"
//   d) 3 warnings  → badge shows "3 limit warnings"
//   e) mixed kinds → instrument + sector warnings all go into the same count

/** Build an instrument warning at the given ratio. */
function makeInstrumentWarning(ratio: number): ExposureWarning {
  const limitPct = 20;
  return {
    kind: "instrument",
    name: "TESTSYM",
    exposure_pct: ratio * limitPct,
    limit_pct: limitPct,
    ratio,
    severity: ratio >= 1.0 ? "CRITICAL" : "WARNING",
  };
}

/** Build a sector warning at the given ratio. */
function makeSectorWarning(ratio: number): ExposureWarning {
  const limitPct = 35;
  return {
    kind: "sector",
    name: "IT",
    exposure_pct: ratio * limitPct,
    limit_pct: limitPct,
    ratio,
    severity: ratio >= 1.0 ? "CRITICAL" : "WARNING",
  };
}

/** Mirrors the badge text rendered by PortfolioLive.tsx line 560. */
function badgeText(warnings: ExposureWarning[]): string {
  return `${warnings.length} limit warning${warnings.length !== 1 ? "s" : ""}`;
}

describe("badge-exposure-warnings-count — count stays in sync with warnings list", () => {
  // ── a) Empty list: badge must not appear ──────────────────────────────
  it("badge is absent when exposure_warnings is empty", () => {
    const warnings: ExposureWarning[] = [];
    // The page gates the badge on exposureWarnings.length > 0
    expect(warnings.length > 0).toBe(false);
    expect(bannerShouldRender(warnings)).toBe(false);
  });

  // ── b) 1 warning: badge shows "1 limit warning" (singular) ───────────
  it("badge count equals 1 for a single instrument warning", () => {
    const warnings = [makeInstrumentWarning(0.85)];
    expect(warnings.length).toBe(1);
    expect(badgeText(warnings)).toBe("1 limit warning");
  });

  // ── c) 2 warnings: badge shows "2 limit warnings" (plural) ───────────
  it("badge count equals 2 for two simultaneous warnings", () => {
    const warnings = [makeInstrumentWarning(0.85), makeInstrumentWarning(0.90)];
    expect(warnings.length).toBe(2);
    expect(badgeText(warnings)).toBe("2 limit warnings");
  });

  // ── d) 3 warnings: badge shows "3 limit warnings" ────────────────────
  it("badge count equals 3 for three simultaneous warnings", () => {
    const warnings = [
      makeInstrumentWarning(0.82),
      makeInstrumentWarning(0.95),
      makeInstrumentWarning(1.05),
    ];
    expect(warnings.length).toBe(3);
    expect(badgeText(warnings)).toBe("3 limit warnings");
  });

  // ── e) Mixed kinds: both instrument and sector contribute to the count ─
  it("instrument and sector warnings both count toward the same badge total", () => {
    const warnings: ExposureWarning[] = [
      makeInstrumentWarning(0.85), // instrument — near limit
      makeSectorWarning(0.92),     // sector — near limit
    ];
    expect(warnings.length).toBe(2);
    expect(warnings.filter((w) => w.kind === "instrument")).toHaveLength(1);
    expect(warnings.filter((w) => w.kind === "sector")).toHaveLength(1);
    // Both kinds must be included in the badge text, not just one kind
    expect(badgeText(warnings)).toBe("2 limit warnings");
  });

  it("three mixed warnings (2 instrument + 1 sector) produce a single badge count of 3", () => {
    const warnings: ExposureWarning[] = [
      makeInstrumentWarning(0.82),
      makeSectorWarning(0.95),
      makeInstrumentWarning(1.1), // CRITICAL instrument
    ];
    expect(warnings.length).toBe(3);
    expect(badgeText(warnings)).toBe("3 limit warnings");
  });
});

describe("PortfolioLive.tsx — badge-exposure-warnings-count source contract", () => {
  it("badge element carries data-testid='badge-exposure-warnings-count'", () => {
    expect(pageSrc).toContain('data-testid="badge-exposure-warnings-count"');
  });

  it("badge is gated on exposureWarnings.length > 0 (absent when empty)", () => {
    // The badge must be inside the same conditional as the banner
    expect(pageSrc).toMatch(/exposureWarnings\.length\s*>\s*0/);
  });

  it("badge text is derived directly from exposureWarnings.length (no cached copy)", () => {
    // The literal text interpolation must reference exposureWarnings.length
    expect(pageSrc).toMatch(/exposureWarnings\.length\}\s*limit warning/);
  });

  it("badge uses plural 'warnings' when count is not 1 (ternary present)", () => {
    // Plural ternary: `warning${exposureWarnings.length !== 1 ? "s" : ""}`
    expect(pageSrc).toMatch(/exposureWarnings\.length\s*!==\s*1\s*\?\s*"s"\s*:\s*""/);
  });
});
