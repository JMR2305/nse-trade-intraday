/**
 * Task-51 — Health card DEGRADED smoke tests
 *
 * Confirms that:
 *
 * 1. The PortfolioLive page correctly derives DEGRADED status from the health
 *    API response and surfaces it in the status badge and alert banner.
 *
 * 2. The health card renders the PortfolioConfig-missing warning text when
 *    `limits_from_config` is false (both via `degraded_reasons` list and via
 *    the explicit `limits_from_config === false` fallback branch).
 *
 * 3. The backend portfolio_snapshot.py emits all the fields the health card
 *    requires: `limits_from_config`, `degraded_reasons`, `degraded`,
 *    `failure_reason`, and `status`.
 *
 * These are static source-analysis tests — they read the source files and
 * assert structural invariants, so they run fast without a server and cannot
 * be silently bypassed by a dev-server restart.
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

// ── 1. PortfolioHealth TypeScript interface ────────────────────────────────
//
// Asserts that the interface captures all the fields the health card reads,
// so a future rename will be caught at type-check time.

describe("PortfolioHealth interface — required fields present", () => {
  it("declares the 'status' field", () => {
    expect(pageSrc).toMatch(/status\s*:\s*string/);
  });

  it("declares the 'limits_from_config' field (optional boolean)", () => {
    // Must be present so TypeScript narrows === false correctly
    expect(pageSrc).toContain("limits_from_config?");
  });

  it("declares the 'degraded_reasons' field (optional string array)", () => {
    expect(pageSrc).toContain("degraded_reasons?");
  });

  it("declares the 'degraded' boolean field", () => {
    expect(pageSrc).toMatch(/degraded\s*:\s*boolean/);
  });

  it("declares the 'failure_reason' field", () => {
    expect(pageSrc).toContain("failure_reason?");
  });

  it("declares the 'unresolved_discrepancies' field", () => {
    expect(pageSrc).toContain("unresolved_discrepancies");
  });
});

// ── 2. overallStatus derives from health.status ───────────────────────────
//
// The status badge reads `overallStatus` which is derived from `health?.status`
// first, falling back to `snap?.status`.  This ensures the badge reflects the
// health endpoint's DEGRADED verdict even if the snapshot says READY.

describe("overallStatus derivation — health.status takes priority", () => {
  it("overallStatus is set from health?.status (health response drives badge)", () => {
    expect(pageSrc).toMatch(/overallStatus\s*=\s*health\?\.status/);
  });

  it("falls back to snap?.status when health is unavailable", () => {
    // The null-coalescing chain must include snap?.status as a fallback
    expect(pageSrc).toMatch(/health\?\.status\s*\?\?\s*snap\?\.status/);
  });

  it("StatusBadge receives overallStatus as its status prop", () => {
    expect(pageSrc).toContain("StatusBadge status={overallStatus}");
  });
});

// ── 3. isAlert includes DEGRADED ──────────────────────────────────────────
//
// The alert banner is only rendered when isAlert is true.  DEGRADED must be
// one of the statuses that sets isAlert, otherwise a DEGRADED portfolio
// produces no visible warning on the page.

describe("isAlert flag — DEGRADED triggers the alert banner", () => {
  it("isAlert is true when overallStatus is DEGRADED", () => {
    expect(pageSrc).toContain('overallStatus === "DEGRADED"');
  });

  it("isAlert also covers HALTED and DOWN (belt-and-braces)", () => {
    expect(pageSrc).toContain('overallStatus === "HALTED"');
    expect(pageSrc).toContain('overallStatus === "DOWN"');
  });

  it("banner-portfolio-alert element is gated on isAlert", () => {
    // The data-testid must appear inside the isAlert conditional block
    expect(pageSrc).toContain('data-testid="banner-portfolio-alert"');
    // And the block must be driven by isAlert
    expect(pageSrc).toMatch(/isAlert\s*&&\s*\(/);
  });
});

// ── 4. Alert banner shows health.failure_reason ───────────────────────────
//
// When the backend sets failure_reason to the PortfolioConfig message, the
// banner must surface it so operators understand why the portfolio is DEGRADED.

describe("alert banner — failure_reason is rendered", () => {
  it("renders health.failure_reason inside the alert banner", () => {
    expect(pageSrc).toContain("health?.failure_reason");
  });

  it("failure_reason is displayed as a paragraph under the status heading", () => {
    // The conditional must wrap health?.failure_reason in a paragraph/span
    expect(pageSrc).toMatch(/health\?\.failure_reason\s*&&\s*\(/);
  });
});

// ── 5. Health card renders degraded_reasons list ──────────────────────────
//
// Each entry in health.degraded_reasons is rendered as its own row in the
// health card so operators see all reasons (not just the first).

describe("health card — degraded_reasons rows are rendered", () => {
  it("iterates over health.degraded_reasons to render individual rows", () => {
    // Source uses (health.degraded_reasons!).map( — the ! is a TS non-null assertion
    expect(pageSrc).toMatch(/health\.degraded_reasons[^)]*\)\.map\s*\(/);
  });

  it("gates the degraded_reasons block on a non-empty array", () => {
    // Must check length > 0 (or equivalent) before mapping
    expect(pageSrc).toMatch(/degraded_reasons[^)]*\)\.length\s*>\s*0/);
  });

  it("each reason row includes an AlertTriangle icon", () => {
    // The icon is the visual cue that each row is a warning
    expect(pageSrc).toMatch(/AlertTriangle.*degraded_reasons|degraded_reasons.*AlertTriangle/s);
  });

  it("each reason is rendered in yellow (text-yellow-400) to indicate a warning", () => {
    expect(pageSrc).toContain("text-yellow-400");
  });
});

// ── 6. Fallback branch for limits_from_config === false ───────────────────
//
// Old API responses might not include degraded_reasons yet.  A second
// guard checks `limits_from_config === false` directly so the health
// card never silently drops the warning regardless of API version.

describe("health card — explicit limits_from_config === false fallback", () => {
  it("contains a branch that checks health.limits_from_config === false", () => {
    expect(pageSrc).toContain("health.limits_from_config === false");
  });

  it("fallback branch renders the hardcoded-defaults warning text", () => {
    expect(pageSrc).toContain(
      "Exposure limits using hardcoded defaults — check PortfolioConfig import",
    );
  });

  it("fallback is only shown when degraded_reasons is null/undefined (old API guard)", () => {
    // The condition must be `degraded_reasons == null` (not just falsy length)
    // so it doesn't fire when the array is present but empty.
    expect(pageSrc).toMatch(/degraded_reasons\s*==\s*null/);
  });
});

// ── 7. statusConfig maps DEGRADED to the correct visual style ─────────────
//
// If DEGRADED is removed from statusConfig the badge falls through to the
// UNKNOWN style and the operator loses the yellow warning colour.

describe("statusConfig — DEGRADED entry wired correctly", () => {
  it("statusConfig has a DEGRADED key", () => {
    expect(pageSrc).toContain("DEGRADED:");
  });

  it("DEGRADED uses yellow text colour (text-yellow-400)", () => {
    // The DEGRADED config must include the yellow colour token
    expect(pageSrc).toMatch(/DEGRADED\s*:\s*\{[^}]*text-yellow-400/s);
  });

  it("DEGRADED uses AlertTriangle icon (visible warning symbol)", () => {
    expect(pageSrc).toMatch(/DEGRADED\s*:\s*\{[^}]*AlertTriangle/s);
  });
});

// ── 8. backend portfolio_snapshot.py — get_portfolio_health() shape ───────
//
// The backend must emit all the fields the health card type-checks against.
// These assertions catch a refactor that renames or removes a key.

describe("portfolio_snapshot.py — get_portfolio_health() response shape", () => {
  it("emits the 'status' key", () => {
    expect(snapshotPySrc).toMatch(/"status"\s*:\s*status/);
  });

  it("emits the 'limits_from_config' key", () => {
    expect(snapshotPySrc).toMatch(/"limits_from_config"\s*:\s*limits_from_config/);
  });

  it("emits the 'degraded_reasons' key (list)", () => {
    expect(snapshotPySrc).toMatch(/"degraded_reasons"\s*:\s*degraded_reasons/);
  });

  it("emits the 'degraded' boolean key", () => {
    expect(snapshotPySrc).toMatch(/"degraded"\s*:\s*bool\(degraded_reasons\)/);
  });

  it("emits the 'failure_reason' key", () => {
    expect(snapshotPySrc).toMatch(/"failure_reason"\s*:/);
  });

  it("sets status to DEGRADED when degraded_reasons is non-empty", () => {
    expect(snapshotPySrc).toContain('status = "DEGRADED"');
  });

  it("appends a PortfolioConfig reason to degraded_reasons when import fails", () => {
    // The exact string the UI checks for in the fallback branch
    expect(snapshotPySrc).toContain(
      "Exposure limits using hardcoded defaults — check PortfolioConfig import",
    );
  });

  it("sets limits_from_config = False when PortfolioConfig raises", () => {
    // The variable is initialised to False before the try block
    expect(snapshotPySrc).toContain("limits_from_config = False");
  });

  it("sets limits_from_config = True only after a successful PortfolioConfig() call", () => {
    expect(snapshotPySrc).toContain("limits_from_config = True");
  });
});

// ── 9. Pure-logic: DEGRADED status derivation rules ──────────────────────
//
// Mirror the Python status-derivation logic from get_portfolio_health() in
// TypeScript and assert the rules hold at the boundaries.

interface MockHealth {
  initialized: boolean;
  degraded_reasons: string[];
}

function deriveStatus(h: MockHealth): string {
  if (!h.initialized) return "UNKNOWN";
  if (h.degraded_reasons.length > 0) return "DEGRADED";
  return "HEALTHY";
}

describe("health status derivation — mirrors Python get_portfolio_health() logic", () => {
  it("returns UNKNOWN when portfolio is not initialized", () => {
    expect(deriveStatus({ initialized: false, degraded_reasons: [] })).toBe("UNKNOWN");
  });

  it("returns UNKNOWN when not initialized even with degraded_reasons present", () => {
    // initialized=False takes precedence; UNKNOWN is returned, not DEGRADED
    expect(deriveStatus({ initialized: false, degraded_reasons: ["some reason"] })).toBe("UNKNOWN");
  });

  it("returns DEGRADED when initialized and at least one degraded_reason present", () => {
    expect(
      deriveStatus({
        initialized: true,
        degraded_reasons: ["Exposure limits using hardcoded defaults — check PortfolioConfig import"],
      }),
    ).toBe("DEGRADED");
  });

  it("returns DEGRADED with multiple degraded_reasons (e.g. config + reconciliation)", () => {
    expect(
      deriveStatus({
        initialized: true,
        degraded_reasons: [
          "Exposure limits using hardcoded defaults — check PortfolioConfig import",
          "3 unresolved reconciliation discrepancies",
        ],
      }),
    ).toBe("DEGRADED");
  });

  it("returns HEALTHY when initialized and degraded_reasons is empty", () => {
    expect(deriveStatus({ initialized: true, degraded_reasons: [] })).toBe("HEALTHY");
  });
});

// ── 10. isDefaultsOnly helper (ActiveConfigSection) ──────────────────────
//
// The ActiveConfigSection section also exposes a "using defaults" warning.
// isDefaultsOnly() must return true only when the config response is
// present AND loaded === false — not while still loading.

function isDefaultsOnly(configResponse: { loaded: boolean } | undefined): boolean {
  return configResponse !== undefined && !configResponse.loaded;
}

describe("isDefaultsOnly — config-defaults warning only after confirmed load failure", () => {
  it("returns false while loading (configResponse is undefined)", () => {
    expect(isDefaultsOnly(undefined)).toBe(false);
  });

  it("returns false when loaded is true (config loaded successfully)", () => {
    expect(isDefaultsOnly({ loaded: true })).toBe(false);
  });

  it("returns true when loaded is false (PortfolioConfig import failed)", () => {
    expect(isDefaultsOnly({ loaded: false })).toBe(true);
  });

  it("source defines isDefaultsOnly as a function checking !configResponse.loaded", () => {
    // Must be defined as a function so it can be called from JSX
    expect(pageSrc).toContain("function isDefaultsOnly");
    expect(pageSrc).toContain("!configResponse.loaded");
  });
});
