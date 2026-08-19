// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { AgentDetailPanel } from "./AgentOperations";

vi.mock("@/lib/api", () => ({ apiJson: vi.fn() }));
import { apiJson } from "@/lib/api";

const mockApi = apiJson as ReturnType<typeof vi.fn>;

function TestClient({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      {children}
    </QueryClientProvider>
  );
}

afterEach(() => {
  cleanup();
  mockApi.mockReset();
});

describe("Agent Operations detail recovery", () => {
  it("explains that detail loading is retrying while an agent starts", async () => {
    mockApi.mockResolvedValue({
      available: false,
      status: "INITIALIZING",
      recoverable: true,
      message: "The Agent Framework is still initialising this agent. Retrying automatically.",
    });

    render(
      <TestClient>
        <AgentDetailPanel agentId="risk" onClose={vi.fn()} />
      </TestClient>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("agent-detail-recoverable")).toBeTruthy();
    });
    expect(screen.getByText("Agent details are retrying")).toBeTruthy();
    expect(screen.getByText(/Retrying automatically/)).toBeTruthy();
    expect(screen.queryByText("Failed to load")).toBeNull();
  });
});