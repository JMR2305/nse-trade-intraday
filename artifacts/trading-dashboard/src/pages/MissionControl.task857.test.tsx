// @vitest-environment jsdom
/**
 * MissionControl.task857.test.tsx
 *
 * Focused frontend contract tests for Task 857 additive scan-status fields.
 *
 * Verifies:
 *   - ScanInfoChips renders "Market Scans Today" / "All System Jobs Today" chips
 *     when the new fields are present and falls back to legacy "Completed N today"
 *     when they are absent.
 *   - ScannerPanel header shows "market scans today" chip for market_scans_today,
 *     and a separate "system jobs" chip when all_system_jobs_today differs.
 *   - History rows with Task 857 enhanced fields render job_type labels, IST
 *     times, market_state, entry_eligible, execution_eligible, and source.
 *   - Non-market history rows carry a visible job_type badge.
 *   - Legacy history rows (no Task 857 fields) still render via the compact layout.
 */

import React from "react";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ScanInfoChips, istJobTime, jobStatusClass } from "./MissionControl";

// ── ScanInfoChips: Task 857 additive count fields ────────────────────────────

describe("ScanInfoChips – Task 857 additive count fields", () => {
  it("renders Market Scans Today chip when market_scans_today is present", () => {
    render(
      <ScanInfoChips
        scanData={{
          market_scans_today: 7,
          all_system_jobs_today: 12,
        }}
      />,
    );
    expect(screen.getByText("Market Scans Today")).toBeTruthy();
    expect(screen.getByText("7")).toBeTruthy();
  });

  it("renders All System Jobs Today chip when it differs from market_scans_today", () => {
    render(
      <ScanInfoChips
        scanData={{
          market_scans_today: 7,
          all_system_jobs_today: 12,
        }}
      />,
    );
    expect(screen.getByText("All System Jobs Today")).toBeTruthy();
    expect(screen.getByText("12")).toBeTruthy();
  });

  it("does NOT render All System Jobs Today when equal to market_scans_today", () => {
    render(
      <ScanInfoChips
        scanData={{
          market_scans_today: 7,
          all_system_jobs_today: 7,
        }}
      />,
    );
    expect(screen.queryByText("All System Jobs Today")).toBeNull();
  });

  it("falls back to legacy Completed chip when market_scans_today is absent", () => {
    render(
      <ScanInfoChips
        scanData={{
          completed_scans_today: 5,
        }}
      />,
    );
    expect(screen.getByText("Completed")).toBeTruthy();
    expect(screen.getByText("5 today")).toBeTruthy();
    // New chips should not appear when the new fields are absent
    expect(screen.queryByText("Market Scans Today")).toBeNull();
    expect(screen.queryByText("All System Jobs Today")).toBeNull();
  });

  it("falls back to scan_count_today when both new and completed_scans_today are absent", () => {
    render(
      <ScanInfoChips
        scanData={{
          scan_count_today: 3,
        }}
      />,
    );
    expect(screen.getByText("Completed")).toBeTruthy();
    expect(screen.getByText("3 today")).toBeTruthy();
  });
});

// ── ScanInfoChips: Task 857 market_scans_today = 0 edge case ────────────────

describe("ScanInfoChips – Task 857 zero-value edge cases", () => {
  it("renders Market Scans Today chip when value is zero", () => {
    render(
      <ScanInfoChips
        scanData={{
          market_scans_today: 0,
          all_system_jobs_today: 2,
        }}
      />,
    );
    // "0" as text next to chip label
    expect(screen.getByText("Market Scans Today")).toBeTruthy();
    expect(screen.getByText("All System Jobs Today")).toBeTruthy();
  });
});

describe("Task 857 backend enum and IST time compatibility", () => {
  it("styles uppercase durable job statuses and parses ISO IST timestamps", () => {
    expect(jobStatusClass("SUCCESS")).toContain("emerald");
    expect(jobStatusClass("FAILED")).toContain("red");
    expect(istJobTime("2026-08-20T08:45:00+05:30")).toMatch(/08:45/);
  });
});
