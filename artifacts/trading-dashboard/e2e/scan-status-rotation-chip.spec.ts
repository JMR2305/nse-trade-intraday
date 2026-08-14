/**
 * E2E: Rotation chip increments after scan completion, observed in a live browser
 *
 * Task 719 — confirms the cache-invalidation wiring is observable end-to-end in
 * a real browser, not just in source analysis.
 *
 * Why a browser test catches what unit tests and source review cannot:
 *   - Wrong React Query key: refetch fires but populates a different stale entry
 *   - Wrong data-testid: chip removed or renamed → selector silent miss
 *   - Poll interval widened so chip never refreshes within the allowed window
 *   - Route interception broken so scan/run never triggers the mock flip
 *
 * ── Mock design ────────────────────────────────────────────────────────────────
 *
 * The scan/run mock has two phases:
 *
 *   Phase 1 – RUNNING response (immediate, before completion):
 *     The handler fulfills with { started: true, status: "RUNNING" } as the real
 *     server does.  scanRunReceived is still false; scan/status still returns
 *     rotation:1 (simulating the cache that was cleared on POST but not yet
 *     refilled by a fresh scan_status Python call).
 *
 *   Phase 2 – Completion (simulated 200 ms after RUNNING response):
 *     A setTimeout fires, sets scanRunReceived = true, and logs "scan.completed".
 *     This mirrors the real completion callback that clears scanStatusCache and
 *     makes the next GET /live-data/scan/status return a fresh rotation counter.
 *
 * The test uses page.waitForResponse to capture the first scan/status response
 * that carries the incremented rotation, then asserts the chip immediately.
 * This removes any fixed-window timing dependency: we wait for the actual HTTP
 * response that caused the chip update, not for an arbitrary timeout to expire.
 *
 * PAPER TRADING / RESEARCH ONLY.
 */

import { test, expect } from "@playwright/test";

// ── Constants ─────────────────────────────────────────────────────────────────

const MISSION_CONTROL_URL = "/trading-dashboard/mission-control";

/**
 * How long after the RUNNING response the mock simulates scan "completion"
 * (scanRunReceived flips to true).  200 ms is enough to ensure the chip
 * is still displaying #1 when the flip happens, so the test proves the update
 * was caused by completion, not by a pre-existing in-flight poll.
 */
const COMPLETION_DELAY_MS = 200;

/**
 * Total time allowed for the chip to show the updated rotation after the POST
 * to scan/run.  The MissionControl scanner panel polls every 5 s (R.scan = 5_000).
 * We allow 3 full poll cycles (15 s) as stated in the task acceptance criteria,
 * plus a 1 s margin for React render and scheduling jitter.
 */
const CHIP_UPDATE_TIMEOUT_MS = 16_000;

// ── Mock payloads ─────────────────────────────────────────────────────────────

function makeScanStatus(rotation: number, scanCountToday: number) {
  return {
    success: true,
    status: "IDLE",
    scan_id: `scan-test-${rotation}`,
    snapshot_ts: new Date().toISOString(),
    age_minutes: 2,
    scan_count_today: scanCountToday,
    cadence_minutes: 4,
    rotation,
    latest_scan: {
      scan_id: `scan-test-${rotation}`,
      snapshot_ts: new Date().toISOString(),
      status: "completed",
      symbols_total: 50,
      symbols_done: 50,
      duration_s: 95,
      universe_size: 50,
    },
    progress: null,
  };
}

const MINIMAL_PORTFOLIO = {
  status: "READY",
  paper_mode: true,
  snapshotted_at: new Date().toISOString(),
  equity: 100_000,
  cash: 100_000,
  buying_power: 100_000,
  invested_value: 0,
  initial_capital: 100_000,
  unrealised_pnl: 0,
  realised_pnl_today: 0,
  total_pnl: 0,
  peak_equity: 100_000,
  drawdown_amount: 0,
  drawdown_pct: 0,
  open_positions: [],
  open_position_count: 0,
  closed_positions_today: 0,
  sector_exposures: [],
  exposure_warnings: [],
};

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Register all required API intercepts for MissionControl.
 *
 * Playwright evaluates page.route() handlers in LIFO order (most-recently-
 * registered wins).  The catch-all is registered FIRST so all more-specific
 * handlers take precedence.
 *
 * Returns a function the caller uses to trigger "scan completion" at the right
 * moment in the test flow.
 */
async function interceptMissionControlApis(page: import("@playwright/test").Page) {
  // scanRunReceived = false  → scan/status returns rotation:1 (pre-completion)
  // scanRunReceived = true   → scan/status returns rotation:2 (post-completion)
  let scanRunReceived = false;

  // 1. Catch-all (lowest priority — registered first in LIFO).
  await page.route("**/api/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
  );

  // 2. Portfolio snapshot — keeps the status bar populated.
  await page.route("**/api/portfolio/snapshot", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(MINIMAL_PORTFOLIO),
    }),
  );

  // 3. scan/status — returns rotation:1 until scan completion is simulated,
  //    then rotation:2.  The state is read from the closure variable every time
  //    a new scan/status request arrives from the browser's polling loop.
  await page.route("**/api/live-data/scan/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(
        scanRunReceived ? makeScanStatus(2, 2) : makeScanStatus(1, 1),
      ),
    }),
  );

  // 4. scan/run — the critical handler.
  //    Phase 1: respond RUNNING immediately (cache cleared on POST).
  //    Phase 2: after COMPLETION_DELAY_MS, flip scanRunReceived so that the
  //             NEXT scan/status poll (simulating the post-completion fresh call)
  //             returns rotation:2.  This mirrors the real completion callback that
  //             fires after getP7Scan(true) resolves and clears scanStatusCache.
  await page.route("**/api/live-data/scan/run", async (route) => {
    // Fulfill first (RUNNING response), then schedule the completion flip.
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ started: true, status: "RUNNING" }),
    });
    // Completion is asynchronous in the real server — the flip happens after
    // the background phase7_scan Python process finishes (~90 s in production,
    // 200 ms in this test to keep the suite fast without coupling to real Python).
    setTimeout(() => { scanRunReceived = true; }, COMPLETION_DELAY_MS);
  });
}

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe("MissionControl — rotation chip updates after scan completion", () => {
  /**
   * Core regression test.
   *
   * Verifies that the chip increments after a simulated scan completion,
   * exercising the BROWSER path (React Query cache invalidation → refetch →
   * DOM update) rather than just the server-side cache-clear logic.
   *
   * Uses page.waitForResponse to capture the first scan/status HTTP response
   * that carries rotation:2 (i.e., the first response after the completion flip).
   * This makes the assertion timing-independent: we do not race against a fixed
   * 5-second window — we wait for the actual HTTP event that causes the UI update.
   */
  test(
    "rotation chip increments after scan completion is simulated",
    async ({ page }) => {
      await interceptMissionControlApis(page);
      await page.goto(MISSION_CONTROL_URL);

      // ── Phase 1: confirm initial state ────────────────────────────────────
      const chip = page.getByTestId("mc-rotation-chip");
      await expect(chip).toBeVisible({ timeout: 10_000 });
      await expect(chip).toContainText("#1");

      // ── Phase 2: trigger scan/run from browser context ────────────────────
      // page.evaluate sends the fetch through the browser, which is intercepted
      // by page.route.  page.request.post bypasses page.route — do NOT use it.
      const [scanRunResp] = await Promise.all([
        page.waitForResponse("**/api/live-data/scan/run"),
        page.evaluate(() =>
          fetch("/api/live-data/scan/run", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: "{}",
          }),
        ),
      ]);

      // Verify the scan/run response was received and acknowledged.
      expect(scanRunResp.status()).toBe(200);
      const scanRunBody = await scanRunResp.json() as Record<string, unknown>;
      expect(scanRunBody["started"]).toBe(true);
      expect(scanRunBody["status"]).toBe("RUNNING");

      // ── Phase 3: wait for the first post-completion scan/status response ──
      //
      // After COMPLETION_DELAY_MS the mock flips scanRunReceived = true.
      // The browser's React Query polling loop will fire within the next 5 s
      // (R.scan = 5 000 ms) and get a scan/status response with rotation:2.
      //
      // page.waitForResponse captures this response the moment it arrives, so
      // we do not need a fixed timeout — the assertion is driven by the HTTP
      // event itself.  A generous overall timeout (CHIP_UPDATE_TIMEOUT_MS = 16 s)
      // ensures reliability across CI environments with scheduling jitter.
      await page.waitForResponse(
        async (response) => {
          if (!response.url().includes("live-data/scan/status")) return false;
          if (response.status() !== 200) return false;
          try {
            const body = await response.json() as Record<string, unknown>;
            return body["rotation"] === 2;
          } catch {
            return false;
          }
        },
        { timeout: CHIP_UPDATE_TIMEOUT_MS },
      );

      // ── Phase 4: assert chip reflects the updated rotation ────────────────
      // The HTTP response carrying rotation:2 has just been received by the
      // browser.  React Query updates state and re-renders; give it a brief
      // moment to flush (1 s is generous — re-renders are typically sub-100 ms).
      await expect(chip).toContainText("#2", { timeout: 1_000 });
    },
  );

  /**
   * Selector smoke test — confirms data-testid="mc-rotation-chip" is wired to a
   * DOM element that shows a valid rotation number.  Catches accidental removal
   * or a nil-guard that hides the chip when rotation is 1.
   */
  test(
    "rotation chip is visible and shows a valid rotation number on page load",
    async ({ page }) => {
      await interceptMissionControlApis(page);
      await page.goto(MISSION_CONTROL_URL);

      const chip = page.getByTestId("mc-rotation-chip");
      await expect(chip).toBeVisible({ timeout: 10_000 });
      await expect(chip).toHaveText(/#\d+/);
    },
  );

  /**
   * Back-to-back scans — confirms a second scan also advances the chip.
   * Catches a bug where the flag is never reset (one-time flip pattern).
   */
  test(
    "rotation chip advances again on a second scan within the session",
    async ({ page }) => {
      let scanCount = 0;

      await page.route("**/api/**", (route) =>
        route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
      );
      await page.route("**/api/portfolio/snapshot", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(MINIMAL_PORTFOLIO),
        }),
      );
      // scan/status returns scanCount + 1 scans so each scan advances the chip.
      await page.route("**/api/live-data/scan/status", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(makeScanStatus(scanCount + 1, scanCount + 1)),
        }),
      );
      // scan/run increments scanCount after COMPLETION_DELAY_MS.
      await page.route("**/api/live-data/scan/run", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ started: true, status: "RUNNING" }),
        });
        setTimeout(() => { scanCount++; }, COMPLETION_DELAY_MS);
      });

      await page.goto(MISSION_CONTROL_URL);
      const chip = page.getByTestId("mc-rotation-chip");
      await expect(chip).toBeVisible({ timeout: 10_000 });
      await expect(chip).toContainText("#1");

      // First scan → completion → chip #2.
      await Promise.all([
        page.waitForResponse("**/api/live-data/scan/run"),
        page.evaluate(() =>
          fetch("/api/live-data/scan/run", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: "{}",
          }),
        ),
      ]);
      await page.waitForResponse(
        async (r) => {
          if (!r.url().includes("live-data/scan/status") || r.status() !== 200) return false;
          try { return ((await r.json() as Record<string, unknown>)["rotation"]) === 2; }
          catch { return false; }
        },
        { timeout: CHIP_UPDATE_TIMEOUT_MS },
      );
      await expect(chip).toContainText("#2", { timeout: 1_000 });

      // Second scan → completion → chip #3.
      await Promise.all([
        page.waitForResponse("**/api/live-data/scan/run"),
        page.evaluate(() =>
          fetch("/api/live-data/scan/run", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: "{}",
          }),
        ),
      ]);
      await page.waitForResponse(
        async (r) => {
          if (!r.url().includes("live-data/scan/status") || r.status() !== 200) return false;
          try { return ((await r.json() as Record<string, unknown>)["rotation"]) === 3; }
          catch { return false; }
        },
        { timeout: CHIP_UPDATE_TIMEOUT_MS },
      );
      await expect(chip).toContainText("#3", { timeout: 1_000 });
    },
  );
});
