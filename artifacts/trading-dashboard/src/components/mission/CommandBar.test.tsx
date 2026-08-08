// @vitest-environment jsdom
/**
 * CommandBar.test.tsx — Phase 25C operator command bar.
 *
 * Verifies:
 *  - all 9 actions render
 *  - Emergency Stop and Pause AI require explicit confirmation
 *  - cancel closes the dialog without calling any endpoint
 *  - confirm fires the control endpoint(s) and shows success feedback
 *  - Start Scan needs no confirmation and reports errors inline
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CommandBar } from "./CommandBar";

vi.mock("@/lib/api", () => ({ apiJson: vi.fn() }));
import { apiJson } from "@/lib/api";
const mockApi = apiJson as ReturnType<typeof vi.fn>;

const navigateMock = vi.fn();
vi.mock("wouter", async (importOriginal) => {
  const actual = await importOriginal<typeof import("wouter")>();
  return { ...actual, useLocation: () => ["/mission-control", navigateMock] };
});

function renderBar() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <CommandBar />
    </QueryClientProvider>,
  );
}

beforeEach(() => { mockApi.mockReset(); navigateMock.mockReset(); });
afterEach(() => cleanup());

describe("CommandBar", () => {
  it("renders all nine actions", () => {
    renderBar();
    for (const id of [
      "start-scan", "pause-ai", "resume-ai", "emergency-stop", "replay-today",
      "run-backtest", "generate-report", "open-investigation", "open-learning",
    ]) {
      expect(screen.getByTestId(`mc-cmd-${id}`)).toBeTruthy();
    }
  });

  it("Emergency Stop requires confirmation and calls abort + kill switch", async () => {
    mockApi.mockResolvedValue({ success: true });
    renderBar();
    fireEvent.click(screen.getByTestId("mc-cmd-emergency-stop"));
    // No endpoint call before confirm
    expect(mockApi).not.toHaveBeenCalled();
    expect(screen.getByTestId("mc-cmd-confirm")).toBeTruthy();

    fireEvent.click(screen.getByTestId("mc-cmd-confirm-btn"));
    await waitFor(() => expect(screen.getByTestId("mc-cmd-feedback")).toBeTruthy());
    const paths = mockApi.mock.calls.map((c) => c[0]);
    expect(paths).toContain("/live-data/scan/abort");
    expect(paths).toContain("/risk/kill-switch/trigger");
    expect(screen.getByTestId("mc-cmd-feedback").textContent).toMatch(/Emergency stop complete/i);
  });

  it("Pause AI requires confirmation; cancel calls nothing", () => {
    renderBar();
    fireEvent.click(screen.getByTestId("mc-cmd-pause-ai"));
    expect(screen.getByTestId("mc-cmd-confirm")).toBeTruthy();
    fireEvent.click(screen.getByTestId("mc-cmd-cancel"));
    expect(screen.queryByTestId("mc-cmd-confirm")).toBeNull();
    expect(mockApi).not.toHaveBeenCalled();
  });

  it("Pause AI confirm triggers the kill switch", async () => {
    mockApi.mockResolvedValue({ success: true });
    renderBar();
    fireEvent.click(screen.getByTestId("mc-cmd-pause-ai"));
    fireEvent.click(screen.getByTestId("mc-cmd-confirm-btn"));
    await waitFor(() => expect(mockApi).toHaveBeenCalled());
    expect(mockApi.mock.calls[0][0]).toBe("/risk/kill-switch/trigger");
  });

  it("Start Scan fires without confirmation and shows success", async () => {
    mockApi.mockResolvedValue({ started: true, status: "RUNNING" });
    renderBar();
    fireEvent.click(screen.getByTestId("mc-cmd-start-scan"));
    await waitFor(() => expect(screen.getByTestId("mc-cmd-feedback")).toBeTruthy());
    expect(mockApi.mock.calls[0][0]).toBe("/live-data/scan/run");
    expect(screen.getByTestId("mc-cmd-feedback").textContent).toMatch(/Scan started/i);
  });

  it("Start Scan surfaces endpoint failure inline", async () => {
    mockApi.mockRejectedValue(new Error("scanner offline"));
    renderBar();
    fireEvent.click(screen.getByTestId("mc-cmd-start-scan"));
    await waitFor(() => expect(screen.getByTestId("mc-cmd-feedback")).toBeTruthy());
    expect(screen.getByTestId("mc-cmd-feedback").textContent).toMatch(/scanner offline/);
  });

  it("Resume AI posts acknowledge without a confirm dialog", async () => {
    mockApi.mockResolvedValue({ success: true });
    renderBar();
    fireEvent.click(screen.getByTestId("mc-cmd-resume-ai"));
    await waitFor(() => expect(mockApi).toHaveBeenCalled());
    expect(mockApi.mock.calls[0][0]).toBe("/risk/kill-switch/resume");
    expect(JSON.parse((mockApi.mock.calls[0][1] as RequestInit).body as string)).toEqual({ acknowledge: true });
  });

  it("navigation actions deep-link without endpoint calls", async () => {
    renderBar();
    fireEvent.click(screen.getByTestId("mc-cmd-replay-today"));
    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith("/replay"));
    fireEvent.click(screen.getByTestId("mc-cmd-open-investigation"));
    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith("/investigation-center"));
    fireEvent.click(screen.getByTestId("mc-cmd-open-learning"));
    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith("/ai-learning-center"));
    expect(mockApi).not.toHaveBeenCalled();
  });
});
