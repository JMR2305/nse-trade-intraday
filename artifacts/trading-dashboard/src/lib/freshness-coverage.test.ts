/**
 * Phase 19C — Route-level freshness coverage test.
 *
 * Parses App.tsx for every registered route, resolves each route's page
 * component file, and asserts that the page renders a freshness indicator:
 *   - <DataFreshnessBar ... />  (any variant, incl. "none" which renders
 *     "No live dataset used on this page")
 *
 * The test FAILS when a new data-driven route is added without a freshness
 * indicator. It also checks:
 *   - the freshness bar uses backend metadata (no browser-time fabrication)
 *   - IST formatting is applied
 *   - no secrets appear in the component
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve, join } from "node:path";

const SRC = resolve(__dirname, "..");
const appSource = readFileSync(join(SRC, "App.tsx"), "utf8");
const barSource = readFileSync(
  join(SRC, "components", "DataFreshnessBar.tsx"),
  "utf8",
);

/** Routes whose page is allowed to have no freshness bar. */
const EXEMPT_COMPONENTS = new Set(["NotFound"]);

function registeredRoutes(): { path: string; component: string }[] {
  const routes: { path: string; component: string }[] = [];
  const re = /<Route\s+path="([^"]+)"\s+component=\{(\w+)\}/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(appSource))) {
    routes.push({ path: m[1], component: m[2] });
  }
  return routes;
}

function componentFile(name: string): string | null {
  // Match: import X from "@/pages/Y"; (default import)
  const re = new RegExp(
    `import\\s+${name}\\s+from\\s+"@/(pages/[^"]+)"`,
  );
  const m = appSource.match(re);
  if (!m) return null;
  return join(SRC, `${m[1]}.tsx`);
}

describe("Phase 19C — every registered page shows a freshness indicator", () => {
  const routes = registeredRoutes();

  it("finds a meaningful number of routes in App.tsx", () => {
    expect(routes.length).toBeGreaterThanOrEqual(40);
  });

  for (const { path, component } of routes) {
    if (EXEMPT_COMPONENTS.has(component)) continue;
    it(`${path} (${component}) renders DataFreshnessBar or the no-live-dataset marker`, () => {
      const file = componentFile(component);
      expect(file, `import for ${component} not found in App.tsx`).toBeTruthy();
      const src = readFileSync(file as string, "utf8");
      const hasBar = /<DataFreshnessBar\b/.test(src);
      const hasMarker = /No live dataset used on this page/.test(src);
      expect(
        hasBar || hasMarker,
        `${component} must render <DataFreshnessBar> (any variant) or the "No live dataset used on this page" marker`,
      ).toBe(true);
    });
  }
});

describe("Phase 19C — DataFreshnessBar integrity", () => {
  it("uses backend metadata endpoints, not fabricated browser time", () => {
    expect(barSource).toContain("/phase15/staleness");
    expect(barSource).toContain("/live-data/scan/status");
    // Timestamps must come from response fields; the component must never
    // seed a timestamp from the browser clock.
    expect(barSource).not.toMatch(/new Date\(\)/);
    expect(barSource).not.toMatch(/Date\.now\(\)/);
  });

  it("formats times in IST (Asia/Kolkata)", () => {
    expect(barSource).toContain('timeZone: "Asia/Kolkata"');
    expect(barSource).toContain("IST");
  });

  it("keeps stale-data protection visible", () => {
    expect(barSource).toContain("STALE");
    expect(barSource).toContain("FAILED");
    expect(barSource).toContain("buy_recommendations_disabled");
  });

  it("contains no secret-looking values", () => {
    expect(barSource).not.toMatch(/api[_-]?key|secret|token|password/i);
  });

  it("shows an expandable detail panel", () => {
    expect(barSource).toContain("button-freshness-toggle");
  });
});
