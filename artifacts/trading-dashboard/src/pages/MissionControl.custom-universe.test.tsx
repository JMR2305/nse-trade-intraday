// @vitest-environment jsdom
import React from "react";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
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
  healthQueryState: { isLoading?: boolean } = {},
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
          isLoading: healthQueryState.isLoading ?? false,
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

  it("keeps Mission Control read-only and routes operators to version management without credential inputs", () => {
    renderCard();

    expect(screen.getByTestId("link-manage-custom-universe").getAttribute("href")).toBe("/custom-universe-management");
    expect(screen.getByTestId("mc-custom-universe-management-note").textContent).toMatch(/not available from Mission Control/i);
    expect(screen.queryByTestId("mc-custom-universe-admin-token")).toBeNull();
    expect(screen.queryByTestId("mc-approve-metadata-only-hydration")).toBeNull();
  });

  it("keeps mapping review visible while NIFTY 50 is active without exposing membership refresh controls", () => {
    renderCard("NIFTY_50");

    expect(screen.getByTestId("mc-custom-universe-inactive-note").textContent).toMatch(/prepare any future revision/i);
    expect(screen.getByTestId("mc-custom-universe-mapping-status")).toBeTruthy();
    expect(screen.getByTestId("mc-custom-universe-current-price-source").textContent).toBe("UNAVAILABLE / NOT PROVEN");
    expect(screen.getByTestId("mc-custom-universe-price-freshness").textContent).toBe("UNAVAILABLE / NOT PROVEN");
    expect(screen.queryByTestId("mc-refresh-low-price-universe")).toBeNull();
  });
});

describe("LowPriceUniverseCard current price provenance", () => {
  it("shows a recorded closed-market Kite quote from the health-v2 response", () => {
    renderCard("CUSTOM_LOW_PRICE_SECTOR", {
      kite_connected: true,
      current_quote_provider: "ZERODHA_KITE",
      current_quote_timestamp: "2026-08-25T09:53:23Z",
      current_quote_freshness: "MARKET_CLOSED_LAST_KNOWN",
      historical_ohlcv_provider: "YFINANCE",
      scan_provenance_state: "SCHEDULED",
    });

    expect(screen.getByTestId("mc-custom-universe-kite-connection").textContent).toBe("CONNECTED");
    expect(screen.getByTestId("mc-custom-universe-provenance-mappings").textContent).toBe("3 / 5");
    expect(screen.getByTestId("mc-custom-universe-current-price-source").textContent).toBe("ZERODHA_KITE");
    expect(screen.getByTestId("mc-custom-universe-last-quote").textContent).toBe("2026-08-25T09:53:23Z");
    expect(screen.getByTestId("mc-custom-universe-price-freshness").textContent).toBe("MARKET CLOSED / LAST KNOWN");
    expect(screen.getByTestId("mc-custom-universe-historical-provider").textContent).toBe("YFINANCE");
    expect(screen.getByTestId("mc-custom-universe-scan-provenance").textContent).toBe("SCHEDULED");
  });

  it("shows a recorded closed-market Yahoo quote without relabeling historical OHLCV", () => {
    renderCard("CUSTOM_LOW_PRICE_SECTOR", {
      kite_connected: true,
      current_quote_provider: "YFINANCE",
      current_quote_timestamp: "2026-08-25T10:00:00Z",
      current_quote_freshness: "MARKET_CLOSED_LAST_KNOWN",
      historical_ohlcv_provider: "ZERODHA_KITE",
      scan_provenance_state: "SCHEDULED",
    });

    expect(screen.getByTestId("mc-custom-universe-current-price-source").textContent).toBe("YFINANCE");
    expect(screen.getByTestId("mc-custom-universe-last-quote").textContent).toBe("2026-08-25T10:00:00Z");
    expect(screen.getByTestId("mc-custom-universe-price-freshness").textContent).toBe("MARKET CLOSED / LAST KNOWN");
    expect(screen.getByTestId("mc-custom-universe-historical-provider").textContent).toBe("ZERODHA_KITE");
    expect(screen.getByTestId("mc-custom-universe-scan-provenance").textContent).toBe("SCHEDULED");
  });

  it("uses the market-open provider and freshness reported by the API", () => {
    renderCard("CUSTOM_LOW_PRICE_SECTOR", {
      kite_connected: true,
      symbols_on_kite: 5,
      symbols_fallback: 0,
      current_quote_provider: "YFINANCE",
      current_quote_timestamp: "2026-08-26T04:30:00Z",
      current_quote_freshness: "LIVE",
      historical_ohlcv_provider: "YFINANCE",
      scan_provenance_state: "SCHEDULED",
    });

    expect(screen.getByTestId("mc-custom-universe-current-price-source").textContent).toBe("YFINANCE");
    expect(screen.getByTestId("mc-custom-universe-last-quote").textContent).toBe("2026-08-26T04:30:00Z");
    expect(screen.getByTestId("mc-custom-universe-price-freshness").textContent).toBe("LIVE");
  });

  it("does not infer a Kite quote source from Kite connection or coverage alone", () => {
    renderCard("CUSTOM_LOW_PRICE_SECTOR", {
      kite_connected: true,
      symbols_on_kite: 5,
      symbols_fallback: 0,
      kite_quote_timestamps_fresh: true,
      market_timestamp_fresh: true,
    });

    expect(screen.getByTestId("mc-custom-universe-kite-connection").textContent).toBe("CONNECTED");
    expect(screen.getByTestId("mc-custom-universe-current-price-source").textContent).toBe("UNAVAILABLE / NOT PROVEN");
    expect(screen.getByTestId("mc-custom-universe-last-quote").textContent).toBe("UNAVAILABLE / NOT PROVEN");
    expect(screen.getByTestId("mc-custom-universe-price-freshness").textContent).toBe("UNAVAILABLE / NOT PROVEN");
  });

  it("shows unavailable only when provider, timestamp, or freshness evidence is missing or malformed", () => {
    const providerMissing = summarizeCurrentPriceProvenance(5, {
      current_quote_timestamp: "2026-08-25T10:00:00Z",
      current_quote_freshness: "MARKET_CLOSED_LAST_KNOWN",
    });
    const timestampMissing = summarizeCurrentPriceProvenance(5, {
      current_quote_provider: "ZERODHA_KITE",
      current_quote_freshness: "MARKET_CLOSED_LAST_KNOWN",
    });
    const malformedTimestamp = summarizeCurrentPriceProvenance(5, {
      current_quote_provider: "ZERODHA_KITE",
      current_quote_timestamp: "not-a-timestamp",
      current_quote_freshness: "MARKET_CLOSED_LAST_KNOWN",
    });
    const trulyUnavailable = summarizeCurrentPriceProvenance(5, {
      current_quote_provider: "UNAVAILABLE_NOT_PROVEN",
      current_quote_timestamp: "2026-08-25T10:00:00Z",
      current_quote_freshness: "UNAVAILABLE_NOT_PROVEN",
    });

    for (const provenance of [providerMissing, timestampMissing, malformedTimestamp, trulyUnavailable]) {
      expect(provenance.currentPriceSource).toBe("UNAVAILABLE / NOT PROVEN");
      expect(provenance.lastQuote).toBeNull();
      expect(provenance.freshness).toBe("UNAVAILABLE / NOT PROVEN");
    }
  });

  it("does not call the initial health request unavailable before it resolves", () => {
    renderCard("CUSTOM_LOW_PRICE_SECTOR", undefined, {}, { isLoading: true });

    expect(screen.getByTestId("mc-custom-universe-current-price-source").textContent)
      .toBe("LOADING CURRENT QUOTE PROVENANCE…");
    expect(screen.getByTestId("mc-custom-universe-price-freshness").textContent)
      .toBe("LOADING CURRENT QUOTE PROVENANCE…");
  });

  it("keeps explicit historical and scan provenance when current quote evidence is unavailable", () => {
    renderCard("CUSTOM_LOW_PRICE_SECTOR", {
      current_quote_provider: "UNAVAILABLE_NOT_PROVEN",
      historical_ohlcv_provider: "YFINANCE",
      scan_provenance_state: "SCHEDULED",
    });

    expect(screen.getByTestId("mc-custom-universe-current-price-source").textContent).toBe("UNAVAILABLE / NOT PROVEN");
    expect(screen.getByTestId("mc-custom-universe-historical-provider").textContent).toBe("YFINANCE");
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