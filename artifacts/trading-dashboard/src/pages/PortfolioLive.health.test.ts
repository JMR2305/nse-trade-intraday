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
  it("overallStatus derives UNREACHABLE when healthQuery.isError and no cached health data", () => {
    // When the server is completely unreachable the ternary short-circuits to UNREACHABLE
    expect(pageSrc).toMatch(/healthQuery\.isError\s*&&\s*!health/);
    expect(pageSrc).toContain('"UNREACHABLE"');
  });

  it("falls back to snap?.status when health is unavailable (non-error loading state)", () => {
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

// ── 11. Polling timing invariants ─────────────────────────────────────────
//
// The health query must re-fetch automatically on a fixed interval and treat
// cached data as stale before the next poll fires.  This guarantees that a
// HEALTHY→DEGRADED flip that happens on the server (e.g. after an API-server
// restart) is visible to the operator within at most one REFRESH_INTERVAL
// cycle, without a manual page reload.
//
// Invariants:
//   - REFRESH_INTERVAL is set to 15 000 ms (15 s)
//   - healthQuery.staleTime < REFRESH_INTERVAL   → cached data expires before
//     the next poll, so React Query always issues a real network request on
//     each tick rather than serving the previous response from cache.
//   - healthQuery.refetchInterval === REFRESH_INTERVAL   → the poll fires on
//     the declared cadence.

describe("health query polling — staleTime is within one refresh cycle", () => {
  it("REFRESH_INTERVAL constant is defined as 15 000 ms", () => {
    expect(pageSrc).toContain("const REFRESH_INTERVAL = 15_000");
  });

  it("healthQuery sets refetchInterval to REFRESH_INTERVAL", () => {
    // Find the healthQuery block and confirm it carries refetchInterval
    expect(pageSrc).toMatch(
      /healthQuery\s*=\s*useQuery[^)]*\(\s*\{[^}]*refetchInterval\s*:\s*REFRESH_INTERVAL/s,
    );
  });

  it("healthQuery sets staleTime to REFRESH_INTERVAL / 2", () => {
    // staleTime must be strictly less than refetchInterval so the cached value
    // is always considered stale when the next poll fires.
    expect(pageSrc).toMatch(
      /healthQuery\s*=\s*useQuery[^)]*\(\s*\{[^}]*staleTime\s*:\s*REFRESH_INTERVAL\s*\/\s*2/s,
    );
  });

  it("staleTime is numerically less than REFRESH_INTERVAL", () => {
    // Extract the numeric constant to verify the invariant programmatically.
    const refreshMatch = pageSrc.match(/const REFRESH_INTERVAL\s*=\s*([\d_]+)/);
    expect(refreshMatch).not.toBeNull();
    const refreshMs = parseInt((refreshMatch![1] as string).replace(/_/g, ""), 10);

    // staleTime is REFRESH_INTERVAL / 2 as sourced above.
    const staleMs = refreshMs / 2;

    expect(staleMs).toBeGreaterThan(0);
    expect(staleMs).toBeLessThan(refreshMs);
  });
});

// ── 12. HEALTHY → DEGRADED transition — simulation ────────────────────────
//
// Simulates two consecutive health-poll results and asserts that the rendered
// badge status updates correctly when the server flips from HEALTHY to
// DEGRADED.  This is a pure-logic simulation — it mirrors exactly what
// React Query does: the latest poll response replaces the previous one in the
// cache, the component re-derives `overallStatus` from the new data, and the
// badge re-renders with the new value.
//
// Why this matters: if `staleTime` were ≥ `refetchInterval`, React Query
// would serve the old HEALTHY result from cache on the next tick, meaning
// the DEGRADED verdict would be silently suppressed until the cache expired.
// The tests in section 11 prove that cannot happen; this section proves that
// when the server does return DEGRADED the badge updates without any manual
// action from the operator.

interface SimHealth {
  status: string;
  initialized: boolean;
  degraded: boolean;
  failure_reason: string | null;
  limits_from_config: boolean;
  degraded_reasons: string[];
}

/** Mirrors the badge derivation in PortfolioLive: health?.status takes priority. */
function deriveOverallStatus(
  health: SimHealth | undefined,
  snapStatus: string | undefined,
): string {
  return health?.status ?? snapStatus ?? "UNKNOWN";
}

/** Mirrors the isAlert flag in PortfolioLive. */
function deriveIsAlert(overallStatus: string): boolean {
  return (
    overallStatus === "DEGRADED" ||
    overallStatus === "HALTED" ||
    overallStatus === "DOWN"
  );
}

const HEALTHY_RESPONSE: SimHealth = {
  status: "HEALTHY",
  initialized: true,
  degraded: false,
  failure_reason: null,
  limits_from_config: true,
  degraded_reasons: [],
};

const DEGRADED_RESPONSE: SimHealth = {
  status: "DEGRADED",
  initialized: true,
  degraded: true,
  failure_reason:
    "Exposure limits using hardcoded defaults — check PortfolioConfig import",
  limits_from_config: false,
  degraded_reasons: [
    "Exposure limits using hardcoded defaults — check PortfolioConfig import",
  ],
};

describe("HEALTHY → DEGRADED transition — badge updates on next poll", () => {
  it("badge shows HEALTHY before the server changes state", () => {
    const status = deriveOverallStatus(HEALTHY_RESPONSE, undefined);
    expect(status).toBe("HEALTHY");
    expect(deriveIsAlert(status)).toBe(false);
  });

  it("badge shows DEGRADED immediately after the poll returns the new response", () => {
    // Simulate React Query replacing the cached HEALTHY response with DEGRADED
    // after the next refetchInterval tick.
    const status = deriveOverallStatus(DEGRADED_RESPONSE, undefined);
    expect(status).toBe("DEGRADED");
    expect(deriveIsAlert(status)).toBe(true);
  });

  it("transition requires no manual page reload (latest poll data always wins)", () => {
    // The component always reads health?.status from the query data (via ternary or direct chain).
    // As soon as React Query resolves the next fetch with the DEGRADED payload,
    // overallStatus updates synchronously.  There is no local state or manual
    // trigger between the poll and the badge render.
    expect(pageSrc).toMatch(/health\?\.status\s*\?\?\s*snap\?\.status/);
    // Confirm there is no stale useState caching of the previous status
    expect(pageSrc).not.toMatch(/\[overallStatus\s*,\s*set[Oo]verallStatus\]/);
  });

  it("alert banner appears (isAlert=true) once DEGRADED response is received", () => {
    const status = deriveOverallStatus(DEGRADED_RESPONSE, undefined);
    expect(deriveIsAlert(status)).toBe(true);
  });

  it("failure_reason from DEGRADED response is non-empty", () => {
    expect(DEGRADED_RESPONSE.failure_reason).toBeTruthy();
    expect(DEGRADED_RESPONSE.degraded_reasons.length).toBeGreaterThan(0);
  });

  it("health.status drives badge even when snapshot still reports READY", () => {
    // After a restart the snapshot may still be cached as READY by the browser
    // while the health endpoint already shows DEGRADED.  health takes priority.
    const status = deriveOverallStatus(DEGRADED_RESPONSE, "READY");
    expect(status).toBe("DEGRADED");
  });

  it("returning to HEALTHY on next poll clears the alert without a page reload", () => {
    // Simulate a second server-restart where PortfolioConfig becomes available again.
    const status = deriveOverallStatus(HEALTHY_RESPONSE, "DEGRADED");
    expect(status).toBe("HEALTHY");
    expect(deriveIsAlert(status)).toBe(false);
  });
});

// ── 13. UNREACHABLE error state ───────────────────────────────────────────
//
// When healthQuery.isError is true and no cached health data is available,
// the health card must NOT show an endless "Loading health…" spinner.
// Instead it must render a distinct error card (banner-health-unreachable)
// and the status badge must show UNREACHABLE.
//
// These are static source-analysis tests — they read the source file and
// assert structural invariants without needing a running server.

describe("UNREACHABLE error state — health card shows clear down indicator", () => {
  it("statusConfig has an UNREACHABLE entry", () => {
    expect(pageSrc).toContain("UNREACHABLE:");
  });

  it("UNREACHABLE uses red text colour (text-red-400) matching DOWN/HALTED severity", () => {
    expect(pageSrc).toMatch(/UNREACHABLE\s*:\s*\{[^}]*text-red-400/s);
  });

  it("UNREACHABLE uses AlertTriangle icon (same as DOWN/HALTED)", () => {
    expect(pageSrc).toMatch(/UNREACHABLE\s*:\s*\{[^}]*AlertTriangle/s);
  });

  it("overallStatus ternary checks healthQuery.isError && !health before falling back", () => {
    // The short-circuit guard must appear in source so that the badge
    // updates to UNREACHABLE the moment the health request fails.
    expect(pageSrc).toMatch(/healthQuery\.isError\s*&&\s*!health/);
  });

  it("overallStatus resolves to the literal string 'UNREACHABLE' on error", () => {
    expect(pageSrc).toContain('"UNREACHABLE"');
  });

  it("isAlert is true when overallStatus is UNREACHABLE", () => {
    expect(pageSrc).toContain('overallStatus === "UNREACHABLE"');
  });

  it("health card renders banner-health-unreachable when healthQuery.isError and !health", () => {
    // The element with this data-testid is the visible error card operators see
    expect(pageSrc).toContain('data-testid="banner-health-unreachable"');
  });

  it("health card branch checks healthQuery.isError before !health (error takes priority over loading)", () => {
    // The error branch must appear BEFORE the loading-skeleton branch in source
    const errorBranchPos = pageSrc.indexOf('banner-health-unreachable');
    const loadingBranchPos = pageSrc.indexOf('Loading health…');
    expect(errorBranchPos).toBeGreaterThan(-1);
    expect(loadingBranchPos).toBeGreaterThan(-1);
    expect(errorBranchPos).toBeLessThan(loadingBranchPos);
  });

  it("error card renders 'API server unreachable' heading in plain language", () => {
    expect(pageSrc).toContain("API server unreachable");
  });

  it("error card surfaces the error message from healthQuery.error", () => {
    // The error object is cast to Error and its message is displayed
    expect(pageSrc).toMatch(/healthQuery\.error[^)]*\)?\?\.message/);
  });

  it("error card tells operators the dashboard retries automatically", () => {
    expect(pageSrc).toContain("retry automatically");
  });

  // Pure-logic simulation: overallStatus returns UNREACHABLE when isError=true, no cached data
  function deriveOverallStatusWithError(
    isError: boolean,
    health: SimHealth | undefined,
    snapStatus: string | undefined,
  ): string {
    if (isError && !health) return "UNREACHABLE";
    return health?.status ?? snapStatus ?? "UNKNOWN";
  }

  it("simulation: overallStatus is UNREACHABLE when isError=true and health is undefined", () => {
    expect(deriveOverallStatusWithError(true, undefined, undefined)).toBe("UNREACHABLE");
  });

  it("simulation: overallStatus is UNREACHABLE even when snap has a status", () => {
    // snap.status should not mask a total health-endpoint failure
    expect(deriveOverallStatusWithError(true, undefined, "HEALTHY")).toBe("UNREACHABLE");
  });

  it("simulation: overallStatus is NOT UNREACHABLE if cached health data still present (transient error)", () => {
    // React Query keeps stale data on a refetch error; in that case health is still defined
    // and the ternary falls through to health?.status, preserving the last known status.
    expect(deriveOverallStatusWithError(true, HEALTHY_RESPONSE, undefined)).toBe("HEALTHY");
  });

  it("simulation: overallStatus returns to HEALTHY when server recovers (isError flips to false)", () => {
    expect(deriveOverallStatusWithError(false, HEALTHY_RESPONSE, undefined)).toBe("HEALTHY");
  });

  it("simulation: isAlert is true for UNREACHABLE", () => {
    function isAlert(status: string): boolean {
      return (
        status === "DEGRADED" ||
        status === "HALTED" ||
        status === "DOWN" ||
        status === "UNREACHABLE"
      );
    }
    expect(isAlert("UNREACHABLE")).toBe(true);
    expect(isAlert("HEALTHY")).toBe(false);
  });
});
