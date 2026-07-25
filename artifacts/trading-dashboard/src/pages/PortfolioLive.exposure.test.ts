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
