// @vitest-environment jsdom
/**
 * Mission Control reload behavior for a transient Agent Framework startup.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { AiHealthWidget } from "../IntelWidgets";
import { AgentMetricsWidget } from "../DeepWidgets";

vi.mock("@/lib/api", () => ({ apiJson: vi.fn() }));
import { apiJson } from "@/lib/api";
const mockApi = apiJson as ReturnType<typeof vi.fn>;

function ReloadClient({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      {children}
    </QueryClientProvider>
  );
}

function MissionControlAgentWidgets() {
  return (
    <>
      <AiHealthWidget />
      <AgentMetricsWidget />
    </>
  );
}

afterEach(() => cleanup());

describe("Mission Control agent status reload", () => {
  it("keeps both agent widgets informative across a reload while agents initialise", async () => {
    mockApi.mockImplementation(async (path: string) => {
      if (path === "/agent-framework/agents") {
        return {
          available: false,
          status: "UNAVAILABLE",
          recoverable: true,
          message: "The Agent Framework is still initialising. Retrying automatically.",
          agents: [],
        };
      }
      if (path === "/autonomous-ops/snapshot") return {};
      throw new Error(`unexpected path ${path}`);
    });

    const firstLoad = render(
      <ReloadClient><MissionControlAgentWidgets /></ReloadClient>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("mc-ai-health-recoverable")).toBeTruthy();
      expect(screen.getByTestId("mc-agent-metrics-recoverable")).toBeTruthy();
    });
    expect(screen.queryByText("Failed to load")).toBeNull();

    firstLoad.unmount();
    render(<ReloadClient><MissionControlAgentWidgets /></ReloadClient>);

    await waitFor(() => {
      expect(screen.getAllByText(/Retrying automatically/)).toHaveLength(2);
    });
    expect(screen.queryByText("Failed to load")).toBeNull();
  });
});