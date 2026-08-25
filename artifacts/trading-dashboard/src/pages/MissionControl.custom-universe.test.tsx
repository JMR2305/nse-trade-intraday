// @vitest-environment jsdom
import React from "react";
import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  LowPriceUniverseCard,
  manualScanAuditPresentation,
  summarizeCurrentPriceProvenance,
} from "./MissionControl";

const status = {
  active_universe: "CUSTOM_LOW_PRICE_SECTOR",
  custom_universe_name: "CUSTOM_LOW_PRICE_SECTOR",
  active_count: 5,
  instrument_metadata: {
    active_count: 5,
    complete_mapping_count: 3,
    newest_cache_date: "2026-08-25",
    cache_age_days: 1,
    invalid_mapping_count: 1,
    stale_mapping_count: 1,
    refresh_required: true,
    provenance: "kite_instrument_cache",
    approval_required: true,
    confirmation_required: "HYDRATE_INSTRUMENT_METADATA_ONLY",
  },
};

function renderCard(
  activeUniverse = "CUSTOM_LOW_PRICE_SECTOR",
  marketDataReadiness?: Record<string, unknown>,
  statusPatch: Record<string, unknown> = {},
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <LowPriceUniverseCard
        statusQ={{
          data: { ...status, ...statusPatch, active_universe: activeUniverse },
          dataUpdatedAt: Date.now(),
          isLoading: false,
          isError: false,
        } as never}
        symbolsQ={{ data: { symbols: [] }, dataUpdatedAt: Date.now(), isLoading: false, isError: false } as never}
        marketDataHealthQ={{
          data: marketDataReadiness ? { market_data_readiness: marketDataReadiness } : undefined,
          dataUpdatedAt: Date.now(),
          isLoading: false,
          isError: false,
        } as never}
      />
    </QueryClientProvider>,
  );
}

describe("LowPriceUniverseCard mapping freshness", () => {
  it("shows mapping coverage, freshness, provenance, and a refresh warning", () => {
    renderCard();

    expect(screen.getByTestId("mc-custom-universe-mapping-coverage").textContent).toContain("3 / 5 active");
    expect(screen.getByTestId("mc-custom-universe-newest-mapping-date").textContent).toContain("2026-08-25");
    expect(screen.getByTestId("mc-custom-universe-mapping-age").textContent).toContain("1 day (oldest)");
    expect(screen.getByTestId("mc-custom-universe-mapping-provenance").textContent).toContain("kite_instrument_cache");
    expect(screen.getByTestId("mc-custom-universe-mapping-refresh-status").textContent).toContain("REFRESH REQUIRED");
    expect(screen.getByText(/does not update these mappings automatically/i)).toBeTruthy();
  });

  it("keeps metadata hydration disabled until both administrator credential and exact confirmation are supplied", () => {
    renderCard();

    const approve = screen.getByTestId("mc-approve-metadata-only-hydration") as HTMLButtonElement;
    expect(approve.disabled).toBe(true);

    fireEvent.change(screen.getByTestId("mc-custom-universe-admin-token"), {
      target: { value: "operator-token" },
    });
    expect(approve.disabled).toBe(true);

    fireEvent.change(screen.getByTestId("mc-custom-universe-metadata-confirmation"), {
      target: { value: "HYDRATE_INSTRUMENT_METADATA_ONLY" },
    });
    expect(approve.disabled).toBe(false);
    expect(screen.getByText(/does not refresh membership or choose symbols/i)).toBeTruthy();
  });

  it("keeps mapping review visible while NIFTY 50 is active without exposing membership refresh controls", () => {
    renderCard("NIFTY_50");

    expect(screen.getByTestId("mc-custom-universe-inactive-note").textContent).toMatch(/before switching modes/i);
    expect(screen.getByTestId("mc-custom-universe-mapping-status")).toBeTruthy();
    expect(screen.getByTestId("mc-custom-universe-current-price-source").textContent).toBe("UNAVAILABLE / NOT PROVEN");
    expect(screen.getByTestId("mc-custom-universe-price-freshness").textContent).toBe("UNAVAILABLE / NOT PROVEN");
    expect(screen.queryByTestId("mc-refresh-low-price-universe")).toBeNull();
  });
});

describe("LowPriceUniverseCard current price provenance", () => {
  it("separates connected Kite mappings from Yahoo current-price fallback", () => {
    renderCard("CUSTOM_LOW_PRICE_SECTOR", {
      kite_connected: true,
      symbols_on_kite: 0,
      symbols_fallback: 5,
      symbols_stale: 0,
      symbols_unavailable: 0,
      symbols_synthetic: 0,
    });

    expect(screen.getByTestId("mc-custom-universe-kite-connection").textContent).toBe("CONNECTED");
    expect(screen.getByTestId("mc-custom-universe-provenance-mappings").textContent).toBe("3 / 5");
    expect(screen.getByTestId("mc-custom-universe-current-price-source").textContent).toBe("Yahoo Finance fallback");
    expect(screen.getByTestId("mc-custom-universe-price-freshness").textContent).toBe("FALLBACK");
    expect(screen.getByTestId("mc-custom-universe-fallback-count").textContent).toBe("5");
    expect(screen.queryByText("Kite LTP")).toBeNull();
  });

  it("shows complete Kite mappings separately from a live Kite current-price source", () => {
    renderCard("CUSTOM_LOW_PRICE_SECTOR", {
      kite_connected: true,
      symbols_on_kite: 5,
      symbols_fallback: 0,
      symbols_stale: 0,
      symbols_unavailable: 0,
      symbols_synthetic: 0,
      kite_quote_timestamps_fresh: true,
      market_timestamp_fresh: true,
    }, {
      instrument_metadata: {
        ...status.instrument_metadata,
        complete_mapping_count: 5,
        invalid_mapping_count: 0,
        stale_mapping_count: 0,
        refresh_required: false,
      },
    });

    expect(screen.getByTestId("mc-custom-universe-kite-connection").textContent).toBe("CONNECTED");
    expect(screen.getByTestId("mc-custom-universe-provenance-mappings").textContent).toBe("5 / 5");
    expect(screen.getByTestId("mc-custom-universe-current-price-source").textContent).toBe("Kite live LTP");
    expect(screen.getByTestId("mc-custom-universe-price-freshness").textContent).toBe("LIVE");
    expect(screen.getByTestId("mc-custom-universe-fallback-count").textContent).toBe("0");
  });

  it("never presents expired Kite quotes as live LTP even with complete Kite coverage", () => {
    renderCard("CUSTOM_LOW_PRICE_SECTOR", {
      kite_connected: true,
      symbols_on_kite: 5,
      symbols_fallback: 0,
      symbols_stale: 0,
      symbols_unavailable: 0,
      symbols_synthetic: 0,
      kite_quote_timestamps_fresh: false,
      invalid_live_quote_timestamp_symbols: ["WIPRO"],
      market_timestamp_fresh: false,
    });

    expect(screen.getByTestId("mc-custom-universe-current-price-source").textContent).toBe("Kite quote timestamps stale");
    expect(screen.getByTestId("mc-custom-universe-price-freshness").textContent).toBe("STALE");
    expect(screen.queryByText("Kite live LTP")).toBeNull();
  });

  it("renders explicit stale, unavailable, and synthetic outcomes without relabeling them as Kite", () => {
    expect(summarizeCurrentPriceProvenance(5, {
      kite_connected: true, symbols_on_kite: 5, symbols_fallback: 0, symbols_stale: 1,
      symbols_unavailable: 0, symbols_synthetic: 0,
    }).freshness).toBe("STALE");
    expect(summarizeCurrentPriceProvenance(5, {
      kite_connected: true, symbols_on_kite: 4, symbols_fallback: 0, symbols_stale: 0,
      symbols_unavailable: 1, symbols_synthetic: 0,
    }).freshness).toBe("UNAVAILABLE");
    expect(summarizeCurrentPriceProvenance(5, {
      kite_connected: true, symbols_on_kite: 5, symbols_fallback: 0, symbols_stale: 0,
      symbols_unavailable: 0, symbols_synthetic: 1,
    }).freshness).toBe("SYNTHETIC");
  });

  it("shows a closed market's recorded quote as last known and keeps historical OHLCV distinct", () => {
    renderCard("CUSTOM_LOW_PRICE_SECTOR", {
      kite_connected: true,
      symbols_on_kite: 0,
      symbols_fallback: 5,
      symbols_stale: 0,
      symbols_unavailable: 0,
      symbols_synthetic: 0,
      current_quote_provider: "YFINANCE",
      current_quote_timestamp: "2026-08-25T10:00:00Z",
      current_quote_freshness: "MARKET_CLOSED_LAST_KNOWN",
      historical_ohlcv_provider: "YFINANCE",
      scan_provenance_state: "SCHEDULED",
    });

    expect(screen.getByTestId("mc-custom-universe-current-price-source").textContent).toBe("Yahoo Finance");
    expect(screen.getByTestId("mc-custom-universe-last-quote").textContent).toBe("2026-08-25T10:00:00Z");
    expect(screen.getByTestId("mc-custom-universe-price-freshness").textContent).toBe("MARKET CLOSED / LAST KNOWN");
    expect(screen.getByTestId("mc-custom-universe-historical-provider").textContent).toBe("Yahoo Finance");
    expect(screen.getByTestId("mc-custom-universe-scan-provenance").textContent).toBe("SCHEDULED");
  });
});

describe("manual scan audit presentation", () => {
  it("keeps legacy manual scans explicitly unavailable instead of inventing an actor", () => {
    expect(manualScanAuditPresentation({ legacy: true })).toMatchObject({
      legacy: true,
      triggeredBy: "unavailable",
      approval: "UNKNOWN",
    });
  });

  it("renders safe persisted audit identifiers for a future manual scan", () => {
    expect(manualScanAuditPresentation({
      actor_type: "operator_api",
      actor_id_or_label: "unavailable",
      request_method: "POST",
      request_endpoint: "/api/live-data/scan/run",
      request_id: "scan-123",
      approval_status: "NOT_REQUIRED",
    })).toEqual({
      legacy: false,
      triggeredBy: "operator_api (unavailable)",
      endpoint: "POST /api/live-data/scan/run",
      approval: "NOT_REQUIRED",
      requestId: "scan-123",
    });
  });
});