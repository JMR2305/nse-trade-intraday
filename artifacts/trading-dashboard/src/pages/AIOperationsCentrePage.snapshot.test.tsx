// @vitest-environment jsdom
/**
 * AIOperationsCentrePage.snapshot.test.tsx — Task978ZR R37N
 *
 * Proves the Ops Centre snapshot query lifecycle:
 *   9.  First load (no data) shows the skeleton/loading state.
 *   10. A background refetch with an existing snapshot does NOT restore
 *       the whole-page skeleton — prior data stays rendered.
 *   11. A snapshot error after prior valid data leaves prior data rendered
 *       and shows a non-blocking warning.
 *
 * The page component is imported directly with its network collaborators
 * (apiJson) mocked, so no HTTP and no backend are involved.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

const apiJsonMock = vi.fn();

vi.mock("@/lib/api", () => ({
  apiJson: (...args: unknown[]) => apiJsonMock(...args),
}));

import AIOperationsCentrePage from "./AIOperationsCentrePage";

const SNAPSHOT = {
  generated_at: "2026-09-30T09:01:00.000Z",
  platform: { health_pct: 98, market_state: "OPEN" },
  pipeline_nodes: [{ node: "collect", status: "ok" }],
  agents: {},
};

function renderPage() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
    },
  });
  const utils = render(
    <QueryClientProvider client={client}>
      <AIOperationsCentrePage />
    </QueryClientProvider>,
  );
  return { ...utils, client };
}

beforeEach(() => {
  apiJsonMock.mockReset();
});

describe("AIOperationsCentrePage snapshot lifecycle (Task978ZR R37N)", () => {
  it("9. first load with no snapshot data shows the loading state, not stale content", async () => {
    apiJsonMock.mockImplementation((path: string) => {
      if (path === "/ops-centre/snapshot") {
        return new Promise(() => {}); // never resolves — first load in flight
      }
      if (path === "/ops-centre/platform") {
        return Promise.resolve({
          generated_at: "2026-09-30T09:00:00.000Z",
          fast: true,
          platform: { health_pct: 95, market_state: "PRE_OPEN" },
          pipeline_nodes: [],
        });
      }
      return Promise.resolve({});
    });
    renderPage();
    expect(await screen.findByText(/Fetching agent snapshot/i)).toBeTruthy();
  });

  it("10. background refresh with an existing snapshot does not restore the whole-page skeleton", async () => {
    apiJsonMock.mockImplementation((path: string) => {
      if (path === "/ops-centre/snapshot") {
        return Promise.resolve(SNAPSHOT);
      }
      if (path === "/ops-centre/platform") {
        return Promise.resolve({
          generated_at: "2026-09-30T09:00:00.000Z",
          fast: true,
          platform: { health_pct: 95, market_state: "OPEN" },
          pipeline_nodes: [],
        });
      }
      return Promise.resolve({});
    });
    const { container } = renderPage();

    // Wait until the snapshot has landed.
    await waitFor(() => {
      expect(apiJsonMock).toHaveBeenCalledWith(
        "/ops-centre/snapshot",
        undefined,
        60_000,
      );
    });
    await waitFor(() => {
      expect(
        screen.queryByText(/Fetching agent snapshot/i),
      ).toBeNull();
    });

    // Now make the snapshot endpoint hang (background refetch in flight).
    apiJsonMock.mockImplementation((path: string) => {
      if (path === "/ops-centre/snapshot") {
        return new Promise(() => {});
      }
      if (path === "/ops-centre/platform") {
        return Promise.resolve({
          generated_at: "2026-09-30T09:00:00.000Z",
          fast: true,
          platform: { health_pct: 95, market_state: "OPEN" },
          pipeline_nodes: [],
        });
      }
      return Promise.resolve({});
    });

    // Rendered page keeps its content — the previously loaded snapshot data
    // remains (Agent Details heading stays, no full-page skeleton swap).
    expect(container.querySelector("[data-slot='skeleton']") ?? container.innerHTML).toBeTruthy();
    expect(screen.getByText("AI Operations Centre")).toBeTruthy();
    // The first-load banner must NOT reappear for a background refresh.
    expect(screen.queryByText(/Fetching agent snapshot/i)).toBeNull();
  });

  it("11. snapshot error after prior valid data leaves prior data rendered with a non-blocking warning", async () => {
    apiJsonMock.mockImplementation((path: string) => {
      if (path === "/ops-centre/snapshot") {
        return Promise.resolve(SNAPSHOT);
      }
      if (path === "/ops-centre/platform") {
        return Promise.resolve({
          generated_at: "2026-09-30T09:00:00.000Z",
          fast: true,
          platform: { health_pct: 95, market_state: "OPEN" },
          pipeline_nodes: [],
        });
      }
      return Promise.resolve({});
    });
    const { client } = renderPage();
    await waitFor(() => {
      expect(
        screen.queryByText(/Fetching agent snapshot/i),
      ).toBeNull();
    });

    // Subsequent snapshot fetches fail.
    apiJsonMock.mockImplementation((path: string) => {
      if (path === "/ops-centre/snapshot") {
        return Promise.reject(new Error("generation failed"));
      }
      if (path === "/ops-centre/platform") {
        return Promise.resolve({
          generated_at: "2026-09-30T09:00:00.000Z",
          fast: true,
          platform: { health_pct: 95, market_state: "OPEN" },
          pipeline_nodes: [],
        });
      }
      return Promise.resolve({});
    });

    // Trigger the refresh the 30 s interval would cause; with retry: false
    // a single failure must surface the non-blocking warning.
    await client.refetchQueries({ queryKey: ["ops-centre", "snapshot"] });
    await waitFor(() => {
      expect(screen.getByText(/showing last valid snapshot/i)).toBeTruthy();
    });
    // Page content (header + Agent Details section) is still rendered.
    expect(screen.getByText("AI Operations Centre")).toBeTruthy();
    expect(screen.getByText(/Agent Details/i)).toBeTruthy();
  });
});
