// @vitest-environment jsdom
/**
 * CommandCenter.staleness.badge.test.tsx — Task 370
 *
 * Render tests for StalenessTag confirming the amber "Cached · N ago" pill
 * appears when Date.now() advances more than 60 s past the source timestamp.
 *
 * Uses Vitest fake timers so the 1-second setInterval inside StalenessTag
 * can be driven forward without real wall-clock delay.
 *
 * Covered cases
 * ─────────────
 * 1. Fresh `dataUpdatedAt` (0 s old)  → green "Live" pill is shown.
 * 2. Advance 61 s via fake timers     → amber "Cached · 1m ago" pill appears.
 * 3. Fresh `generatedAt` ISO string   → green "Live" pill is shown.
 * 4. Advance 61 s                     → amber "Cached · 1m ago" pill appears.
 * 5. No source props                  → component renders nothing (null).
 * 6. Exactly 60 s old                 → still shows "Live" (threshold is > 60).
 * 7. 61 s old on initial render       → amber pill is shown immediately without
 *    needing to advance the timer.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, cleanup } from "@testing-library/react";
import { StalenessTag } from "./CommandCenter";

// ── setup ─────────────────────────────────────────────────────────────────────

const BASE_TIME = new Date("2026-08-06T10:00:00.000Z").getTime();

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(BASE_TIME);
});

afterEach(() => {
  vi.useRealTimers();
  cleanup();
});

// ── helpers ───────────────────────────────────────────────────────────────────

/** Advance fake clock by `ms` milliseconds, flushing all timers and effects. */
function advance(ms: number) {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

// ── tests ─────────────────────────────────────────────────────────────────────

describe("StalenessTag — dataUpdatedAt prop", () => {
  it("shows green Live pill when data is fresh (0 s old)", () => {
    render(<StalenessTag dataUpdatedAt={BASE_TIME} />);
    expect(screen.getByTitle("Data freshly fetched from the server")).toBeTruthy();
    expect(screen.getByText(/Live\s*·/)).toBeTruthy();
    expect(screen.queryByText(/Cached\s*·/)).toBeNull();
  });

  it("switches to amber Cached pill after the tab is idle for 61 s", () => {
    render(<StalenessTag dataUpdatedAt={BASE_TIME} />);

    // Initially green
    expect(screen.getByText(/Live\s*·/)).toBeTruthy();

    // Simulate the browser tab being left idle: clock advances 61 s
    advance(61_000);

    expect(screen.getByTitle("Showing cached data — snapshot is over 60 s old")).toBeTruthy();
    expect(screen.getByText(/Cached\s*·/)).toBeTruthy();
    expect(screen.queryByText(/Live\s*·/)).toBeNull();
  });

  it("pill text shows '1m ago' after 61 s", () => {
    render(<StalenessTag dataUpdatedAt={BASE_TIME} />);
    advance(61_000);
    expect(screen.getByText(/Cached\s*·\s*1m ago/)).toBeTruthy();
  });

  it("stays green at exactly 60 s (threshold is strictly > 60 s)", () => {
    render(<StalenessTag dataUpdatedAt={BASE_TIME} />);
    advance(60_000);
    // ageSecs = 60, isCached = (60 > 60) = false
    expect(screen.getByText(/Live\s*·/)).toBeTruthy();
    expect(screen.queryByText(/Cached\s*·/)).toBeNull();
  });
});

describe("StalenessTag — generatedAt ISO-string prop", () => {
  it("shows green Live pill when ISO timestamp is fresh", () => {
    const generatedAt = new Date(BASE_TIME).toISOString();
    render(<StalenessTag generatedAt={generatedAt} />);
    expect(screen.getByText(/Live\s*·/)).toBeTruthy();
  });

  it("switches to amber Cached pill after 61 s of idle time", () => {
    const generatedAt = new Date(BASE_TIME).toISOString();
    render(<StalenessTag generatedAt={generatedAt} />);

    advance(61_000);

    expect(screen.getByText(/Cached\s*·/)).toBeTruthy();
    expect(screen.queryByText(/Live\s*·/)).toBeNull();
  });

  it("amber pill shows correct age when already stale on mount (cache cold on first render)", () => {
    // Simulate returning to a tab after 2 minutes: timestamp is 120 s in the past
    const staleGeneratedAt = new Date(BASE_TIME - 120_000).toISOString();
    render(<StalenessTag generatedAt={staleGeneratedAt} />);

    // Should show amber immediately, without needing to advance the clock
    expect(screen.getByText(/Cached\s*·/)).toBeTruthy();
    expect(screen.getByText(/2m ago/)).toBeTruthy();
  });
});

describe("StalenessTag — edge cases", () => {
  it("renders nothing when no source props are provided", () => {
    const { container } = render(<StalenessTag />);
    expect(container.firstChild).toBeNull();
  });

  it("generatedAt takes precedence over dataUpdatedAt", () => {
    // generatedAt is 2 minutes stale; dataUpdatedAt is fresh — generatedAt wins
    const staleIso = new Date(BASE_TIME - 120_000).toISOString();
    render(<StalenessTag generatedAt={staleIso} dataUpdatedAt={BASE_TIME} />);
    // Because generatedAt is used, we should see amber (stale)
    expect(screen.getByText(/Cached\s*·/)).toBeTruthy();
  });
});
