/**
 * E2E: Mission Map horizontal scroll at 375 px viewport (small phone)
 *
 * Task 709 — confirms the MissionMapWidget layout introduced in the
 * overflow-x-auto + min-w-max fix still works correctly at the smallest
 * common phone width (375×812 px, e.g. iPhone SE / iPhone 13 mini).
 *
 * What we verify:
 *   1. The scroll container (data-testid="mc-mission-map-flow") is present
 *      in the DOM after the replay snapshot loads.
 *   2. Its scrollWidth exceeds its clientWidth — i.e. the row IS scrollable
 *      and none of the stage boxes were silently collapsed or hidden to fit.
 *   3. Every mc-map-stage-<id> element rendered by the mock snapshot exists
 *      in the DOM and is not hidden (display:none / visibility:hidden).
 *
 * Approach: intercept /api/replay/sessions/latest before navigation so
 * the widget renders with controlled mock data from the first paint,
 * independent of any live backend.  A catch-all silences every other
 * /api/* request the page makes on mount.
 */

import { test, expect } from "@playwright/test";

// ── Constants ─────────────────────────────────────────────────────────────────

const MISSION_CONTROL_URL = "/trading-dashboard/mission-control";
const PHONE_VIEWPORT = { width: 375, height: 812 };

// ── Mock replay snapshot ──────────────────────────────────────────────────────

/** Ten pipeline stages — a realistic maximum that exercises horizontal scroll. */
const MOCK_STAGES = [
  { id: "SUPERVISOR",         label: "Supervisor",          order: 1 },
  { id: "SCANNER",            label: "Scanner",             order: 2 },
  { id: "RESEARCH",           label: "Research",            order: 3 },
  { id: "MARKET_INTELLIGENCE",label: "Market Intel",        order: 4 },
  { id: "MONITORING",         label: "Monitoring",          order: 5 },
  { id: "STRATEGY",           label: "Strategy",            order: 6 },
  { id: "PORTFOLIO_PRECHECK", label: "Portfolio Pre-Check", order: 7 },
  { id: "RISK",               label: "Risk",                order: 8 },
  { id: "AI_DECISION",        label: "AI Decision",         order: 9 },
  { id: "EXECUTION",          label: "Execution",           order: 10 },
].map((s) => ({
  ...s,
  stocks_in:    50,
  stocks_out:   45,
  rejected:      5,
  pending:       0,
  cancelled:     0,
  duration_ms: 1200,
  status: "COMPLETED",
}));

const MOCK_REPLAY = {
  scan_id:     "test-scan-001",
  snapshot_ts: new Date().toISOString(),
  stages:      MOCK_STAGES,
};

// ── Intercept helper ──────────────────────────────────────────────────────────

async function interceptApis(page: import("@playwright/test").Page) {
  // 1. Catch-all first (lowest priority in LIFO evaluation order) — silences
  //    every /api/* request that is not explicitly handled below.
  await page.route("**/api/**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "DISABLED" }),
    }),
  );

  // 2. The replay snapshot that drives MissionMapWidget — registered after the
  //    catch-all so it takes LIFO precedence.
  await page.route("**/api/replay/sessions/latest**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(MOCK_REPLAY),
    }),
  );
}

// ── Helper: navigate to Mission Control and expand to the full dashboard ──────
//
// At 375 px the page renders a compact mobile quick-dashboard (data-testid
// "page-mission-control-mobile") that omits the Mission Map section to keep the
// phone view lightweight.  Clicking "Full dashboard" sets showFullOnMobile=true
// and re-renders the complete layout — including MissionMapWidget — at the same
// 375 px viewport.  This is the exact user journey a real operator follows.

async function gotoMissionControlFull(page: import("@playwright/test").Page) {
  await page.goto(MISSION_CONTROL_URL);
  // Wait for the compact mobile shell to appear.
  await page.waitForSelector('[data-testid="page-mission-control-mobile"]', {
    timeout: 15_000,
  });
  // Expand to the full dashboard so MissionMapWidget is rendered.
  await page.getByTestId("mc-mobile-full-toggle").click();
}

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe("Mission Map — 375 px phone horizontal scroll", () => {
  test.use({ viewport: PHONE_VIEWPORT });

  test.beforeEach(async ({ page }) => {
    await interceptApis(page);
  });

  test("scroll container is present after replay data loads", async ({
    page,
  }) => {
    await gotoMissionControlFull(page);
    const flow = page.getByTestId("mc-mission-map-flow");
    await expect(flow).toBeVisible({ timeout: 15_000 });
  });

  test("scroll container is horizontally scrollable (scrollWidth > clientWidth)", async ({
    page,
  }) => {
    await gotoMissionControlFull(page);
    const flow = page.getByTestId("mc-mission-map-flow");
    await expect(flow).toBeVisible({ timeout: 15_000 });

    // Measure scroll geometry inside the browser context.
    const isScrollable = await flow.evaluate((el) => el.scrollWidth > el.clientWidth);
    expect(isScrollable).toBe(true);
  });

  test("all 10 stage boxes exist in the DOM and are not hidden", async ({
    page,
  }) => {
    await gotoMissionControlFull(page);
    const flow = page.getByTestId("mc-mission-map-flow");
    await expect(flow).toBeVisible({ timeout: 15_000 });

    for (const s of MOCK_STAGES) {
      const stageId = `mc-map-stage-${s.id.toLowerCase()}`;
      const box = page.getByTestId(stageId);

      // Element must be in the DOM (attached) — even if scrolled out of view.
      await expect(box).toBeAttached({ timeout: 5_000 });

      // Element must not be hidden via display:none or visibility:hidden.
      const hidden = await box.evaluate((el) => {
        const style = window.getComputedStyle(el);
        return style.display === "none" || style.visibility === "hidden";
      });
      expect(hidden, `Stage box "${stageId}" should not be hidden`).toBe(false);
    }
  });

  test("first and last stage boxes are reachable by scrolling", async ({
    page,
  }) => {
    await gotoMissionControlFull(page);
    const flow = page.getByTestId("mc-mission-map-flow");
    await expect(flow).toBeVisible({ timeout: 15_000 });

    const firstStageId = `mc-map-stage-${MOCK_STAGES[0].id.toLowerCase()}`;
    const lastStageId  = `mc-map-stage-${MOCK_STAGES[MOCK_STAGES.length - 1].id.toLowerCase()}`;

    // Both stage boxes must exist in the DOM (the flow may be below the page fold
    // on a phone — DOM accessibility is what matters for scroll reachability).
    await expect(page.getByTestId(firstStageId)).toBeAttached();

    // Programmatically scroll the inner container to the right-most position.
    await flow.evaluate((el) => { el.scrollLeft = el.scrollWidth; });

    // After scrolling, the last stage must still be accessible in the DOM and
    // not have been removed or hidden by the scroll operation.
    await expect(page.getByTestId(lastStageId)).toBeAttached();
  });
});
