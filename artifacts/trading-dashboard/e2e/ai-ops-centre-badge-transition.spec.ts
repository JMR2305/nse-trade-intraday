/**
 * E2E: AI Operations Centre badge transitions Cached → Live
 *
 * Task 322 — confirms the amber "Cached snapshot" badge disappears and the
 * emerald "Live" badge appears the moment the slow /ops-centre/snapshot query
 * resolves, NOT only after the next page reload.
 *
 * Without this test, a future refactor to the effectivePlatform merge logic
 * (snapshotData → fast:false path, line ~954 of AIOperationsCentrePage.tsx)
 * could silently leave the badge stuck on "Cached snapshot" even after the
 * full scan has landed.
 *
 * Approach
 * ────────
 * 1. Register route intercepts BEFORE navigation (Playwright LIFO order —
 *    specific routes last so they win over the catch-all).
 * 2. /ops-centre/platform  → immediately returns fast:true  (cached state).
 * 3. /ops-centre/snapshot  → hangs until we explicitly resolve it mid-test
 *    (simulates the slow query still in-flight while the fast one has landed).
 * 4. Assert the amber "Cached snapshot" badge is visible.
 * 5. Fulfill the snapshot route with a full snapshot (fast:false implied by
 *    the merge logic: snapshotData present → effectivePlatform.fast = false).
 * 6. Assert the emerald "Live" badge appears; "Cached snapshot" disappears.
 */

import { test, expect, type Route } from "@playwright/test";

// ── Constants ─────────────────────────────────────────────────────────────────

const AI_OPS_URL = "/trading-dashboard/ai-operations-centre";
const NOW = new Date().toISOString();

// ── Mock payloads ─────────────────────────────────────────────────────────────

/**
 * Fast platform response — fast:true means health_pct came from the last-scan
 * KV cache, not freshly computed.  This is what the page sees on first render.
 */
const FAST_PLATFORM = {
  generated_at: NOW,
  fast: true,
  advisory_only: true,
  cache_ts: NOW,
  platform: {
    health_pct: 85,
    status: "OPERATIONAL",
    scan_id: "scan-001",
    scan_number: 1,
    scan_status: "COMPLETE",
    market_state: "OPEN",
    trading_session: "REGULAR",
    current_time_ist: "10:30:00",
    last_refresh_ist: "10:25:00",
    next_refresh_est: "10:35:00",
    scan_interval_min: 10,
  },
  pipeline_nodes: [],
};

/**
 * Full snapshot response — this is what the slow query returns after ~22-30 s
 * in production.  When snapshotData is present the page sets
 * effectivePlatform.fast = false, which switches the badge to "Live".
 */
const FULL_SNAPSHOT = {
  generated_at: NOW,
  platform: {
    health_pct: 88,
    status: "OPERATIONAL",
    scan_id: "scan-001",
    scan_number: 1,
    scan_status: "COMPLETE",
    market_state: "OPEN",
    trading_session: "REGULAR",
    current_time_ist: "10:31:00",
    last_refresh_ist: "10:31:00",
    next_refresh_est: "10:41:00",
    scan_interval_min: 10,
  },
  pipeline: {
    universe_loaded: 50,
    stocks_reviewed: 50,
    passed_market_data: 48,
    passed_research: 40,
    passed_intelligence: 35,
    passed_monitoring: 30,
    passed_strategy: 20,
    passed_risk: 15,
    buy_recommendations: 5,
    paper_orders_executed: 2,
    open_positions: 2,
  },
  pipeline_nodes: [],
  agents: {},
  rejection_summary: [],
  performance_metrics: {
    avg_scan_duration_ms: 0,
    success_rate_pct: 100,
    total_scans_today: 1,
    total_signals_today: 5,
    total_orders_today: 2,
  },
  bottleneck: null,
  operator_summary: "Platform operating normally.",
  missed_opportunities: [],
  confidence_distribution: {},
  recommendation_leaderboard: { top_buy: [], top_watch: [], top_sell: [] },
  pipeline_heatmap: [],
  smart_insights: [],
  executive_summary: "All systems nominal.",
  agent_load_monitor: {},
};

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe("AI Operations Centre — cache-vs-live badge transition", () => {
  /**
   * Task 367 — reverse-path test.
   *
   * After the snapshot has resolved and the badge is showing "Live", the
   * snapshot endpoint begins returning 500 (network failure / Python crash).
   * React Query retains the last successful snapshotData while isError is
   * true, so effectivePlatform must explicitly check !snapshotError to revert
   * to the fast/cached platform response and show the amber badge again.
   *
   * Approach
   * ────────
   * 1. Install a fake clock BEFORE navigation so React Query timer-based
   *    refetches are under test control.
   * 2. Both /ops-centre/platform (fast:true) and /ops-centre/snapshot (full
   *    data) resolve immediately → emerald "Live" badge appears.
   * 3. A closure flag flips to make the snapshot route return 500 for all
   *    subsequent requests (including retries).
   * 4. page.clock.fastForward(35 000) advances past the 30 s refetch interval
   *    and the retry back-off delays, firing all pending timers instantly.
   * 5. The badge must revert to amber "Cached snapshot"; "Live" must disappear.
   */
  test(
    "badge reverts to amber 'Cached snapshot' when the snapshot errors " +
      "after 'Live' was already shown, without a page reload",
    async ({ page }) => {
      // Install fake clock before navigation so all timers (React Query
      // refetchInterval, retry back-off) are controlled by fastForward.
      await page.clock.install();

      // Flag toggled mid-test to switch snapshot from success → failure.
      let snapshotShouldFail = false;

      // ── Register intercepts (LIFO: catch-all first, specific routes last) ───

      // 1. Catch-all — satisfies any /api/* request not specifically intercepted.
      await page.route("**/api/**", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: "{}",
        }),
      );

      // 2. Agents endpoint — empty-but-valid shape.
      await page.route("**/api/ops-centre/agents", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ agents: {}, generated_at: NOW }),
        }),
      );

      // 3. Snapshot endpoint — succeeds initially, then fails once the flag
      //    is set.  A single route handler handles both phases so there is no
      //    race between unroute() and an in-flight retry.
      await page.route("**/api/ops-centre/snapshot", (route) => {
        if (snapshotShouldFail) {
          return route.fulfill({
            status: 500,
            contentType: "application/json",
            body: JSON.stringify({ error: "internal server error" }),
          });
        }
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(FULL_SNAPSHOT),
        });
      });

      // 4. Fast platform endpoint — always fast:true (cached data).
      await page.route("**/api/ops-centre/platform", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(FAST_PLATFORM),
        }),
      );

      // ── Navigate ─────────────────────────────────────────────────────────────
      await page.goto(AI_OPS_URL);

      // ── Phase 1: snapshot resolved → emerald "Live" badge must appear ────────
      const liveBadge = page.locator(
        '[title="Health % was freshly computed from this snapshot"]',
      );
      const cachedBadge = page.locator(
        '[title="Health % is from the last full scan, not freshly computed"]',
      );

      await expect(liveBadge).toBeVisible({ timeout: 10_000 });
      await expect(cachedBadge).not.toBeVisible();

      // ── Phase 2: flip the snapshot to fail; advance the clock ────────────────
      // Flip the flag so all subsequent snapshot requests (refetch + retries)
      // return 500.
      snapshotShouldFail = true;

      // Fast-forward 35 s:
      //   • 30 s  — fires the refetchInterval timer → React Query refetches
      //   • +5 s  — covers retry back-off delays (retry:2, ~1 s + ~2 s default)
      // All pending setTimeout / setInterval callbacks execute synchronously.
      await page.clock.fastForward(35_000);

      // ── Phase 3: badge must revert to amber "Cached snapshot" ────────────────
      // After retries are exhausted isError=true; effectivePlatform falls back
      // to platformData (fast:true) → PlatformStatusBar renders the amber badge.
      await expect(cachedBadge).toBeVisible({ timeout: 15_000 });
      await expect(liveBadge).not.toBeVisible();
    },
  );

  test(
    "badge switches from amber 'Cached snapshot' to emerald 'Live' " +
      "the moment the snapshot query resolves, without a page reload",
    async ({ page }) => {
      // Slot to hold the deferred snapshot route so we can fulfil it later.
      let pendingSnapshotRoute: Route | null = null;

      // ── Register intercepts (LIFO: catch-all first, specific routes last) ───

      // 1. Catch-all — satisfies any /api/* request that isn't specifically
      //    intercepted (agents, timeline, etc.) so the page doesn't hang on them.
      await page.route("**/api/**", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: "{}",
        }),
      );

      // 2. Agents endpoint — returns an empty but valid shape so the mid-speed
      //    query doesn't throw while snapshot is still pending.
      await page.route("**/api/ops-centre/agents", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ agents: {}, generated_at: NOW }),
        }),
      );

      // 3. Snapshot endpoint — stalls; we'll resolve it manually mid-test to
      //    simulate the slow query landing after the fast one.
      await page.route("**/api/ops-centre/snapshot", (route) => {
        pendingSnapshotRoute = route;
        // Intentionally do NOT call route.fulfill() yet — the request hangs.
      });

      // 4. Fast platform endpoint — resolves immediately with fast:true so the
      //    amber badge renders as soon as the page mounts.
      await page.route("**/api/ops-centre/platform", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(FAST_PLATFORM),
        }),
      );

      // ── Navigate ─────────────────────────────────────────────────────────────
      await page.goto(AI_OPS_URL);

      // ── Phase 1: amber "Cached snapshot" badge must be visible ───────────────
      // The fast platform query has resolved (fast:true); snapshot is still
      // in-flight.  PlatformStatusBar renders the amber badge.
      //
      // Use the `title` attribute to pin the locator to the exact badge span
      // (both badges carry a descriptive tooltip, making them unambiguous even
      // when other navigation items on the page also contain the word "Live").
      const cachedBadge = page.locator(
        '[title="Health % is from the last full scan, not freshly computed"]',
      );
      await expect(cachedBadge).toBeVisible({ timeout: 10_000 });

      // Confirm the emerald "Live" badge is NOT yet present.
      const liveBadge = page.locator(
        '[title="Health % was freshly computed from this snapshot"]',
      );
      await expect(liveBadge).not.toBeVisible();

      // ── Phase 2: resolve the snapshot — simulates slow query landing ─────────
      // pendingSnapshotRoute is guaranteed to be set because the page must have
      // issued the snapshot request before the fast platform query resolved (both
      // are fired on mount).  If somehow it is null the test fails explicitly.
      expect(pendingSnapshotRoute).not.toBeNull();
      await (pendingSnapshotRoute as Route).fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(FULL_SNAPSHOT),
      });

      // ── Phase 3: emerald "Live" badge must appear; amber one must disappear ──
      // React Query receives the snapshot response and re-renders the page.
      // effectivePlatform.fast flips to false → PlatformStatusBar shows "Live".
      await expect(liveBadge).toBeVisible({ timeout: 10_000 });
      await expect(cachedBadge).not.toBeVisible();
    },
  );
});
