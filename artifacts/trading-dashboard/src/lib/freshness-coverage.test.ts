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
import { ROUTE_FRESHNESS } from "@/components/RouteFreshnessIndicator";

const SRC = resolve(__dirname, "..");
const appSource = readFileSync(join(SRC, "App.tsx"), "utf8");
const layoutSource = readFileSync(
  join(SRC, "components", "layout", "AppLayout.tsx"),
  "utf8",
);
const routeIndicatorSource = readFileSync(
  join(SRC, "components", "RouteFreshnessIndicator.tsx"),
  "utf8",
);
const barSource = readFileSync(
  join(SRC, "components", "DataFreshnessBar.tsx"),
  "utf8",
);

/** Catch-all routes do not map to a page source file. */
const EXEMPT_COMPONENTS = new Set(["NotFound"]);
const VALID_ROUTE_VARIANTS = new Set(["scan", "historical", "none"]);

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
    it(`${path} (${component}) renders a local or registered route-level freshness indicator`, () => {
      const file = componentFile(component);
      expect(file, `import for ${component} not found in App.tsx`).toBeTruthy();
      const src = readFileSync(file as string, "utf8");
      const hasLocalBar = /<DataFreshnessBar\b/.test(src);
      const hasLocalMarker = /No live dataset used on this page/.test(src);
      const routeConfig = ROUTE_FRESHNESS[path];
      expect(
        hasLocalBar || hasLocalMarker || Boolean(routeConfig),
        `${component} must render a local freshness indicator or be covered by the route-level freshness registry`,
      ).toBe(true);
      if (routeConfig) {
        expect(
          VALID_ROUTE_VARIANTS.has(routeConfig.variant),
          `${path} must use a known freshness variant`,
        ).toBe(true);
      }
    });
  }

  it("does not retain route-level freshness entries for removed routes", () => {
    const registeredPaths = new Set(routes.map((route) => route.path));
    for (const path of Object.keys(ROUTE_FRESHNESS)) {
      expect(registeredPaths, `${path} is not registered in App.tsx`).toContain(path);
    }
  });

  it("renders route-level indicators through the shared layout", () => {
    expect(layoutSource).toContain("<RouteFreshnessIndicator");
    expect(routeIndicatorSource).toContain("<DataFreshnessBar");
    expect(routeIndicatorSource).toContain('data-testid="route-freshness-indicator"');
  });
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
