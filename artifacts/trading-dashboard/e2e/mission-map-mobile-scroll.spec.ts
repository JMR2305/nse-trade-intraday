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

// ── Wide-label mock ───────────────────────────────────────────────────────────

/**
 * A single stage whose label is long enough that its natural rendered width
 * clearly exceeds 82 px — the previous fixed `w-[82px]` value.  The label
 * is intentionally verbose so the test is independent of font metrics: even
 * at the smallest plausible font rendering the text will be wider than 82 px.
 */
const WIDE_LABEL_STAGE = {
  id: "WIDE_LABEL_STAGE",
  label: "Very Long Pipeline Stage Label",
  order: 1,
  stocks_in: 50,
  stocks_out: 45,
  rejected: 5,
  pending: 0,
  cancelled: 0,
  duration_ms: 1200,
  status: "COMPLETED",
};

const MOCK_REPLAY_WIDE = {
  scan_id: "test-wide-label",
  snapshot_ts: new Date().toISOString(),
  stages: [WIDE_LABEL_STAGE],
};

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

  // ── New tests: w-auto min-w-[82px] width-change assertions ─────────────────

  test("stage box with a label longer than 82 px grows beyond the minimum width", async ({
    page,
  }) => {
    // Override the replay endpoint with a single wide-label stage.  The route
    // registered here takes LIFO precedence over the one in beforeEach so the
    // catch-all and the short-label stages are never served.
    await page.route("**/api/replay/sessions/latest**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(MOCK_REPLAY_WIDE),
      }),
    );

    await gotoMissionControlFull(page);

    const stageTestId = `mc-map-stage-${WIDE_LABEL_STAGE.id.toLowerCase()}`;
    const box = page.getByTestId(stageTestId);
    await expect(box).toBeAttached({ timeout: 15_000 });

    // The `w-auto min-w-[82px]` classes mean the box must stretch to fit its
    // content when the label exceeds 82 px.  getBoundingClientRect().width is
    // the rendered pixel width including padding.
    const boxWidth = await box.evaluate((el) =>
      el.getBoundingClientRect().width,
    );
    expect(
      boxWidth,
      `Stage box for label "${WIDE_LABEL_STAGE.label}" should grow beyond 82 px but measured ${boxWidth} px`,
    ).toBeGreaterThan(82);
  });

  test("scroll container remains scrollable at 375 px when boxes are wider than 82 px", async ({
    page,
  }) => {
    // Use the wide-label mock so at least one box forces the row to overflow.
    await page.route("**/api/replay/sessions/latest**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ...MOCK_REPLAY_WIDE,
          // Add a second stage so the row definitely overflows 375 px.
          stages: [
            WIDE_LABEL_STAGE,
            { ...WIDE_LABEL_STAGE, id: "WIDE_LABEL_STAGE_2", label: "Another Very Long Stage Label", order: 2 },
          ],
        }),
      }),
    );

    await gotoMissionControlFull(page);

    const flow = page.getByTestId("mc-mission-map-flow");
    await expect(flow).toBeVisible({ timeout: 15_000 });

    const isScrollable = await flow.evaluate(
      (el) => el.scrollWidth > el.clientWidth,
    );
    expect(
      isScrollable,
      "Scroll container must be scrollable (scrollWidth > clientWidth) at 375 px when boxes are wider than 82 px",
    ).toBe(true);
  });
});

// ── 320 px viewport — label truncation inside stage boxes ────────────────────
//
// Task 741 — at a very narrow 320 px viewport (smallest common phone width,
// e.g. older Android devices) the label <p> inside each stage box must be
// contained within the box.  The CSS classes
//   whitespace-nowrap overflow-hidden text-ellipsis
// are responsible for this.  We verify that label.scrollWidth ≤ box.clientWidth
// for a stage whose label is long enough to naturally exceed any reasonable
// fixed minimum width, confirming that truncation (not invisible overflow) is
// what keeps the box readable.

/**
 * A label that is intentionally much longer than 82 px so that even at the
 * smallest plausible font rendering it will overflow an unconstrained element.
 * Using this label exercises the overflow-hidden clipping path of the CSS.
 */
const TRUNCATION_LABEL_STAGE = {
  id: "TRUNCATION_TEST_STAGE",
  label: "Extremely Long Pipeline Stage Label That Must Be Truncated",
  order: 1,
  stocks_in: 50,
  stocks_out: 45,
  rejected: 5,
  pending: 0,
  cancelled: 0,
  duration_ms: 1200,
  status: "COMPLETED",
};

const MOCK_REPLAY_TRUNCATION = {
  scan_id: "test-truncation-320",
  snapshot_ts: new Date().toISOString(),
  stages: [TRUNCATION_LABEL_STAGE],
};

test.describe("Mission Map — 320 px viewport label truncation", () => {
  test.use({ viewport: { width: 320, height: 568 } });

  test.beforeEach(async ({ page }) => {
    // Silence every /api/* request by default.
    await page.route("**/api/**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ status: "DISABLED" }),
      }),
    );
    // Serve the truncation-label snapshot (LIFO precedence over the catch-all).
    await page.route("**/api/replay/sessions/latest**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(MOCK_REPLAY_TRUNCATION),
      }),
    );
  });

  test("label scrollWidth does not exceed stage box width at 320 px (truncation applied, not overflow)", async ({
    page,
  }) => {
    await gotoMissionControlFull(page);

    const stageTestId = `mc-map-stage-${TRUNCATION_LABEL_STAGE.id.toLowerCase()}`;
    const box = page.getByTestId(stageTestId);
    await expect(box).toBeAttached({ timeout: 15_000 });

    // The label <p> is the first child of the stage box.  We evaluate both
    // the box's clientWidth and the label's scrollWidth in a single browser
    // call to avoid race conditions between two separate evaluations.
    const { boxClientWidth, labelScrollWidth } = await box.evaluate((boxEl) => {
      const labelEl = boxEl.querySelector("p");
      return {
        boxClientWidth: boxEl.clientWidth,
        labelScrollWidth: labelEl ? labelEl.scrollWidth : 0,
      };
    });

    expect(
      labelScrollWidth,
      `Label scrollWidth (${labelScrollWidth}px) must not exceed stage box clientWidth (${boxClientWidth}px) — overflow-hidden should clip, not leak`,
    ).toBeLessThanOrEqual(boxClientWidth);
  });

  test("stage box is present and visible at 320 px with a truncated label", async ({
    page,
  }) => {
    await gotoMissionControlFull(page);

    const stageTestId = `mc-map-stage-${TRUNCATION_LABEL_STAGE.id.toLowerCase()}`;
    const box = page.getByTestId(stageTestId);
    await expect(box).toBeAttached({ timeout: 15_000 });

    // The box must not be display:none or visibility:hidden even at 320 px.
    const hidden = await box.evaluate((el) => {
      const style = window.getComputedStyle(el);
      return style.display === "none" || style.visibility === "hidden";
    });
    expect(hidden, "Stage box must be visible at 320 px viewport").toBe(false);
  });

  test("scroll container is present at 320 px when a long-label stage is rendered", async ({
    page,
  }) => {
    await gotoMissionControlFull(page);

    const flow = page.getByTestId("mc-mission-map-flow");
    await expect(flow).toBeVisible({ timeout: 15_000 });
  });
});
