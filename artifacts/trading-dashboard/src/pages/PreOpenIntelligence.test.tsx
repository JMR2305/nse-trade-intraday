// @vitest-environment jsdom
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/api", () => ({ apiJson: vi.fn() }));

import { apiJson } from "@/lib/api";
import PreOpenIntelligence from "./PreOpenIntelligence";

const apiMock = vi.mocked(apiJson);

function renderPage(snapshot: Record<string, unknown>) {
  apiMock.mockResolvedValue(snapshot);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PreOpenIntelligence />
    </QueryClientProvider>,
  );
}

describe("PreOpenIntelligence collection certification", () => {
  beforeEach(() => apiMock.mockReset());

  it("keeps an empty displayed batch explicitly uncertified even when the session phase is frozen", async () => {
    renderPage({
      success: true,
      trading_date: "2026-08-26",
      session: {
        status: "FROZEN",
        verified_collection_batch_id: "batch-verified",
        frozen_collection_batch_id: "batch-frozen",
      },
      collection_batch: {
        certification_status: "NO_VALID_SYMBOLS",
        certified: false,
        reason: "No valid symbols are available for the displayed trading date.",
        session_phase: "FROZEN",
        verified_collection_batch_id: "batch-verified",
        frozen_collection_batch_id: "batch-frozen",
        visible_valid_count: 0,
      },
      snapshots: [],
      valid_count: 0,
      stale_count: 0,
      label: "PAPER / ADVISORY ONLY",
    });

    await waitFor(() => expect(screen.getByTestId("preopen-session-phase").textContent).toContain("FROZEN"));
    expect(screen.getByTestId("preopen-collection-certification").textContent).toContain("Not certified");
    expect(screen.getByTestId("preopen-collection-warning").textContent).toContain("No valid symbols");
    expect(screen.getByTestId("preopen-collection-warning").textContent).toContain("batch-verified");
    expect(screen.getByTestId("preopen-collection-warning").textContent).toContain("batch-frozen");
    expect(screen.queryByText("Certified frozen batch")).toBeNull();
  });

  it("labels a collection certified only when the API marks matching batch proof certified", async () => {
    renderPage({
      success: true,
      trading_date: "2026-08-26",
      session: {
        status: "FROZEN",
        verified_collection_batch_id: "batch-verified",
        frozen_collection_batch_id: "batch-verified",
      },
      collection_batch: {
        certification_status: "CERTIFIED_FROZEN",
        certified: true,
        reason: "Verified and frozen batch pointers match complete durable coverage.",
        session_phase: "FROZEN",
        verified_collection_batch_id: "batch-verified",
        frozen_collection_batch_id: "batch-verified",
        visible_valid_count: 1,
      },
      snapshots: [],
      valid_count: 1,
      stale_count: 0,
      label: "PAPER / ADVISORY ONLY",
    });

    await waitFor(() => expect(screen.getByTestId("preopen-collection-certification").textContent).toContain("Certified frozen batch"));
    expect(screen.queryByTestId("preopen-collection-warning")).toBeNull();
  });
});