// @vitest-environment jsdom
import React, { useEffect, useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import {
  ScanBuildIdentity, ScanInfoChips, getBuildIdentityState, getScanPresentation, isScanStatusOlder, useMonotonicScanStatus,
} from "./MissionControl";
import { cacheBustedPath } from "@/components/mission/Widget";

function AsyncRaceProbe() {
  const [incoming, setIncoming] = useState<unknown>(undefined);
  useEffect(() => {
    queueMicrotask(() => setIncoming({
      completed_scans_today: 9,
      latest_scan: { snapshot_ts: "2026-08-19T08:10:00Z" },
    }));
    window.setTimeout(() => setIncoming({
      completed_scans_today: 8,
      latest_scan: { snapshot_ts: "2026-08-19T08:05:00Z" },
    }), 10);
  }, []);

  const monotonic = useMonotonicScanStatus({
    data: incoming,
    dataUpdatedAt: Date.now(),
    refetch: vi.fn(),
  } as never);
  return (
    <output data-testid="race-result" data-stale={String(monotonic.staleResponse)}>
      {monotonic.data?.completed_scans_today ?? "loading"}
    </output>
  );
}

describe("Mission Control scan freshness contract", () => {
  it("labels each durable scan metric explicitly instead of calling completions rotation", () => {
    render(
      <ScanInfoChips
        scanData={{
          completed_scans_today: 12,
          started_scans_today: 14,
          scheduler_ticks_today: 15,
          lock_busy_skips_today: 2,
          runtime: { owner: "scheduler-a:123" },
        }}
      />,
    );

    expect(screen.getByText("Completed")).toBeTruthy();
    expect(screen.getByText("12 today")).toBeTruthy();
    expect(screen.getByText("Started")).toBeTruthy();
    expect(screen.getByText("14 today")).toBeTruthy();
    expect(screen.getByText("Scheduler ticks")).toBeTruthy();
    expect(screen.getByText("15 today")).toBeTruthy();
    expect(screen.getByText("Lock-busy skips")).toBeTruthy();
    expect(screen.queryByText(/Rotation/)).toBeNull();
  });

  it("does not turn retained scan progress into an after-hours SCANNING state", () => {
    const presentation = getScanPresentation({
      market_state: "CLOSED",
      runtime: { status: "IDLE", heartbeat_at: "2026-08-20T11:30:00Z" },
      progress: { stage: "FETCHING", scan_id: "old-scan", started_at: "2026-08-20T11:29:00Z" },
    });

    expect(presentation.isScanning).toBe(false);
    expect(presentation.isAfterHoursMonitoring).toBe(true);
    expect(presentation.idleLabel).toBe("IDLE — MARKET CLOSED");
  });

  it("only calls the pipeline SCANNING while the scheduler reports SCANNING", () => {
    expect(getScanPresentation({
      market_state: "OPEN",
      runtime: { status: "SCANNING" },
      progress: { stage: "FETCHING", scan_id: "active-scan" },
    }).isScanning).toBe(true);
  });

  it("rejects a late response when its snapshot timestamp regresses", () => {
    const displayed = {
      completed_scans_today: 9,
      latest_scan: { snapshot_ts: "2026-08-19T08:10:00Z" },
    };
    const lateResponse = {
      completed_scans_today: 8,
      latest_scan: { snapshot_ts: "2026-08-19T08:05:00Z" },
    };
    expect(isScanStatusOlder(lateResponse, displayed)).toBe(true);
  });

  it("accepts the next IST day even when its completion counter resets", () => {
    const yesterday = {
      completed_scans_today: 52,
      latest_scan: { snapshot_ts: "2026-08-19T09:30:00Z" },
    };
    const today = {
      completed_scans_today: 1,
      latest_scan: { snapshot_ts: "2026-08-20T03:50:00Z" },
    };
    expect(isScanStatusOlder(today, yesterday)).toBe(false);
  });

  it("keeps a newer rendered scan when an older asynchronous response arrives later", async () => {
    render(<AsyncRaceProbe />);
    await waitFor(() => {
      expect(screen.getByTestId("race-result").textContent).toContain("9");
      expect(screen.getByTestId("race-result").getAttribute("data-stale")).toBe("true");
    });
  });

  it("adds a distinct cache-busting timestamp to live request paths", () => {
    expect(cacheBustedPath("/live-data/scan/status", 123)).toBe(
      "/live-data/scan/status?__aq_refresh=123",
    );
    expect(cacheBustedPath("/live-data/scan/status?view=compact", 456)).toBe(
      "/live-data/scan/status?view=compact&__aq_refresh=456",
    );
  });

  it("separates product version from exact UI/API deployment identity", () => {
    const { rerender } = render(
      <ScanBuildIdentity
        apiBuildId="apexquant-aaaaaaaaaaaa"
        uiBuildId="apexquant-aaaaaaaaaaaa"
        uiGitCommit={"a".repeat(40)}
        lastRefreshedAt={Date.UTC(2026, 7, 19, 13, 30, 0)}
      />,
    );
    expect(screen.getByTestId("mc-product-version").textContent).toContain("Product Version v1.0.0");
    expect(screen.getByTestId("mc-ui-build").textContent).toContain("UI Build apexquant-aaaaaaaaaaaa");
    expect(screen.getByTestId("mc-api-build").textContent).toContain("API Build apexquant-aaaaaaaaaaaa");
    expect(screen.getByTestId("mc-build-match").textContent).toContain("MATCH");
    expect(screen.getByTestId("mc-last-refreshed").textContent).toMatch(/Last refreshed .* IST/);

    rerender(
      <ScanBuildIdentity
        apiBuildId="apexquant-bbbbbbbbbbbb"
        uiBuildId="apexquant-aaaaaaaaaaaa"
        lastRefreshedAt={Date.UTC(2026, 7, 19, 13, 30, 0)}
      />,
    );
    expect(screen.getByTestId("mc-build-match").textContent).toContain("MISMATCH");
    expect(screen.getByTestId("mc-build-match").getAttribute("title")).toContain("coordinate a deployment");
  });

  it("keeps missing UI identity visibly actionable", () => {
    render(
      <ScanBuildIdentity
        apiBuildId="apexquant-aaaaaaaaaaaa"
        uiBuildId={null}
        lastRefreshedAt={0}
      />,
    );
    expect(getBuildIdentityState(null, "apexquant-aaaaaaaaaaaa")).toBe("missing-ui");
    expect(screen.getByTestId("mc-ui-build").textContent).toContain("unavailable");
    expect(screen.getByTestId("mc-build-match").textContent).toContain("UI IDENTITY UNAVAILABLE");
    expect(screen.getByTestId("mc-build-match").getAttribute("title")).toContain("rebuild");
  });

  it("does not call a missing API identity a match", () => {
    expect(getBuildIdentityState("apexquant-aaaaaaaaaaaa", undefined)).toBe("loading");
    expect(getBuildIdentityState("apexquant-aaaaaaaaaaaa", null)).toBe("missing-api");
    expect(getBuildIdentityState("apexquant-aaaaaaaaaaaa", "apexquant-aaaaaaaaaaa0")).toBe("mismatch");
    expect(getBuildIdentityState("apexquant-aaaaaaaaaaaa", "apexquant-aaaaaaaaaaaa")).toBe("match");
  });
});