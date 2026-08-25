// @vitest-environment jsdom
import React from "react";
import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LowPriceUniverseCard } from "./MissionControl";

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

function renderCard(activeUniverse = "CUSTOM_LOW_PRICE_SECTOR") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <LowPriceUniverseCard
        statusQ={{
          data: { ...status, active_universe: activeUniverse },
          dataUpdatedAt: Date.now(),
          isLoading: false,
          isError: false,
        } as never}
        symbolsQ={{ data: { symbols: [] }, dataUpdatedAt: Date.now(), isLoading: false, isError: false } as never}
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
    expect(screen.queryByTestId("mc-refresh-low-price-universe")).toBeNull();
  });
});