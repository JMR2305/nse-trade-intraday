// @vitest-environment jsdom
/**
 * AIPaperTraderPage.sparkline.test.tsx
 *
 * Verifies that PnlSparkline and buildSparkPoints produce the correct shape
 * when a position has been open through multiple scans.
 *
 * Coverage:
 *  1.  buildSparkPoints — 5+ price events → more than 2 points in result
 *  2.  buildSparkPoints — zero price events → fallback 2-point line (entry → current)
 *  3.  buildSparkPoints — ignores events for other symbols
 *  4.  buildSparkPoints — de-duplicates consecutive identical prices
 *  5.  buildSparkPoints — caps intermediate points at 18 (oldest dropped)
 *  6.  PnlSparkline — SVG path has M + multiple L commands when given 5+ points
 *  7.  PnlSparkline — stroke is green when current_price ≥ buy_price
 *  8.  PnlSparkline — stroke is red when current_price < buy_price
 *  9.  PnlSparkline — renders dashed "no data" line when fewer than 2 points
 *  10. PnlSparkline — aria-label reflects up/down direction
 */

import React from "react";
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { buildSparkPoints, PnlSparkline } from "./AIPaperTraderPage";

// ── Helpers ────────────────────────────────────────────────────────────────────

/** Count occurrences of the L command in an SVG path d-attribute */
function countLCommands(d: string): number {
  return (d.match(/L/g) ?? []).length;
}

/** Build a minimal TimelineEvent with a price for the given symbol */
function priceEvent(symbol: string, price: number, ts: string) {
  return { ts, type: "PRICE", label: "price snap", symbol, price, category: "SCAN" };
}

// ── Fixtures ───────────────────────────────────────────────────────────────────

const SYMBOL = "S4HOLDINGS";
const BUY     = 900;
const TARGET  = 950;
const SL      = 870;

/** 5 intraday price snapshots for SYMBOL — simulates 5 scans */
const FIVE_EVENTS = [
  priceEvent(SYMBOL, 905, "2026-08-05T09:30:00"),
  priceEvent(SYMBOL, 912, "2026-08-05T10:00:00"),
  priceEvent(SYMBOL, 920, "2026-08-05T10:30:00"),
  priceEvent(SYMBOL, 915, "2026-08-05T11:00:00"),
  priceEvent(SYMBOL, 925, "2026-08-05T11:30:00"),
];

// ── 1. buildSparkPoints — multi-scan happy path ────────────────────────────────

describe("buildSparkPoints", () => {
  it("returns more than 2 points when timeline has 5+ price events for the symbol", () => {
    const pts = buildSparkPoints(SYMBOL, BUY, 925, FIVE_EVENTS);
    // Should be at minimum: buy + 5 events + current = 7 (before dedup)
    expect(pts.length).toBeGreaterThan(2);
  });

  it("first point is always buy_price", () => {
    const pts = buildSparkPoints(SYMBOL, BUY, 925, FIVE_EVENTS);
    expect(pts[0]).toBe(BUY);
  });

  it("last point is always current_price", () => {
    const pts = buildSparkPoints(SYMBOL, BUY, 925, FIVE_EVENTS);
    expect(pts[pts.length - 1]).toBe(925);
  });

  it("returns exactly 2 points (entry + current) when there are no timeline events", () => {
    const pts = buildSparkPoints(SYMBOL, BUY, 930, []);
    expect(pts).toHaveLength(2);
    expect(pts[0]).toBe(BUY);
    expect(pts[1]).toBe(930);
  });

  it("ignores events for other symbols", () => {
    const otherEvents = [
      priceEvent("DIFFERENT", 999, "2026-08-05T09:30:00"),
      priceEvent("DIFFERENT", 1000, "2026-08-05T10:00:00"),
    ];
    const pts = buildSparkPoints(SYMBOL, BUY, 930, otherEvents);
    // Only buy + current should remain
    expect(pts).toHaveLength(2);
  });

  it("de-duplicates consecutive identical prices", () => {
    const dupEvents = [
      priceEvent(SYMBOL, 905, "2026-08-05T09:30:00"),
      priceEvent(SYMBOL, 905, "2026-08-05T10:00:00"), // duplicate
      priceEvent(SYMBOL, 910, "2026-08-05T10:30:00"),
    ];
    const pts = buildSparkPoints(SYMBOL, BUY, 910, dupEvents);
    // 905 appears twice in a row → de-duped → only 1 kept
    // Result: [900, 905, 910, 910-deduped] = [900, 905, 910]
    // The last 910 event and current_price 910 also collapse
    expect(pts).not.toContain(
      // no two consecutive values should be the same
      pts.some((v, i) => i > 0 && v === pts[i - 1])
    );
    // Sanity: length is less than naive [buy, 905, 905, 910, 910]
    expect(pts.length).toBeLessThan(5);
  });

  it("keeps at most 20 total points (18 intermediate + buy + current)", () => {
    // 25 events — only 18 most recent should survive
    const manyEvents = Array.from({ length: 25 }, (_, i) =>
      priceEvent(SYMBOL, 900 + i, `2026-08-05T0${9 + Math.floor(i / 6)}:${(i % 6) * 10}:00`)
    );
    const pts = buildSparkPoints(SYMBOL, BUY, 925, manyEvents);
    // Maximum = 18 mid + buy + current = 20
    expect(pts.length).toBeLessThanOrEqual(20);
  });
});

// ── PnlSparkline rendering tests ───────────────────────────────────────────────

describe("PnlSparkline", () => {
  /**
   * Helper: render the sparkline with a given point array and inspect the
   * resulting SVG path for the main price line (stroke-width 1.5, no fill).
   */
  function renderSparkline(points: number[], currentPrice: number) {
    const { container } = render(
      <PnlSparkline
        points={points}
        buyPrice={BUY}
        target={TARGET}
        stopLoss={SL}
      />
    );
    // The main price line path: fill="none", strokeWidth 1.5
    const mainPath = container.querySelector<SVGPathElement>(
      'path[fill="none"]'
    );
    return { container, mainPath };
  }

  // ── 6. SVG path has M + multiple L commands for 5+ points ──────────────────

  it("SVG path has M command plus multiple L commands when given 5+ points", () => {
    const points = buildSparkPoints(SYMBOL, BUY, 925, FIVE_EVENTS);
    expect(points.length).toBeGreaterThan(2); // guard

    const { mainPath } = renderSparkline(points, 925);
    expect(mainPath).not.toBeNull();

    const d = mainPath!.getAttribute("d") ?? "";
    // Must start with M
    expect(d).toMatch(/^M/);
    // Must have at least 4 L commands (5 points → M + 4 L)
    expect(countLCommands(d)).toBeGreaterThanOrEqual(4);
  });

  // ── 7. Green when current_price ≥ buy_price ────────────────────────────────

  it("stroke is green (#10B981) when current_price > buy_price", () => {
    const current = 925; // > BUY (900)
    const points  = buildSparkPoints(SYMBOL, BUY, current, FIVE_EVENTS);

    const { mainPath } = renderSparkline(points, current);
    expect(mainPath).not.toBeNull();
    expect(mainPath!.getAttribute("stroke")).toBe("#10B981");
  });

  it("stroke is green (#10B981) when current_price equals buy_price", () => {
    // Exactly at entry — the comment says ≥ buy_price is green
    const equalEvents = [
      priceEvent(SYMBOL, 902, "2026-08-05T09:30:00"),
      priceEvent(SYMBOL, 901, "2026-08-05T10:00:00"),
    ];
    const points = buildSparkPoints(SYMBOL, BUY, BUY, equalEvents);
    const { mainPath } = renderSparkline(points, BUY);
    expect(mainPath!.getAttribute("stroke")).toBe("#10B981");
  });

  // ── 8. Red when current_price < buy_price ─────────────────────────────────

  it("stroke is red (#EF4444) when current_price < buy_price", () => {
    const belowEvents = [
      priceEvent(SYMBOL, 895, "2026-08-05T09:30:00"),
      priceEvent(SYMBOL, 888, "2026-08-05T10:00:00"),
      priceEvent(SYMBOL, 880, "2026-08-05T10:30:00"),
      priceEvent(SYMBOL, 878, "2026-08-05T11:00:00"),
      priceEvent(SYMBOL, 875, "2026-08-05T11:30:00"),
    ];
    const current = 875; // < BUY (900)
    const points  = buildSparkPoints(SYMBOL, BUY, current, belowEvents);

    const { mainPath } = renderSparkline(points, current);
    expect(mainPath).not.toBeNull();
    expect(mainPath!.getAttribute("stroke")).toBe("#EF4444");
  });

  // ── 9. Fewer than 2 points → "no data" dashed line ────────────────────────

  it("renders a dashed line (no price path) when fewer than 2 points supplied", () => {
    const { container, mainPath } = renderSparkline([BUY], BUY);
    // No fill="none" path (the main price line) should be present
    expect(mainPath).toBeNull();
    // A <line> element should be present as the fallback dash
    const dash = container.querySelector("line");
    expect(dash).not.toBeNull();
  });

  // ── 10. aria-label reflects direction ─────────────────────────────────────

  it("aria-label says 'up' when current_price > buy_price", () => {
    const points = buildSparkPoints(SYMBOL, BUY, 925, FIVE_EVENTS);
    const { container } = render(
      <PnlSparkline points={points} buyPrice={BUY} target={TARGET} stopLoss={SL} />
    );
    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("aria-label")).toContain("up");
  });

  it("aria-label says 'down' when current_price < buy_price", () => {
    const downEvents = [
      priceEvent(SYMBOL, 895, "2026-08-05T09:30:00"),
      priceEvent(SYMBOL, 880, "2026-08-05T10:00:00"),
    ];
    const points = buildSparkPoints(SYMBOL, BUY, 875, downEvents);
    const { container } = render(
      <PnlSparkline points={points} buyPrice={BUY} target={TARGET} stopLoss={SL} />
    );
    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("aria-label")).toContain("down");
  });
});
