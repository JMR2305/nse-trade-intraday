// @vitest-environment jsdom
/**
 * AlertCenterWidget.test.tsx — Phase 25.1 Part 10 ack/dismiss upgrade.
 *
 * Ack reduces the critical count; dismiss hides the row and surfaces the
 * "N dismissed — restore" chip. Ack/dismiss state is display-level only,
 * persisted in localStorage keyed by severity|title.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { AlertCenterWidget } from "../IntelWidgets";

vi.mock("@/lib/api", () => ({ apiJson: vi.fn() }));
import { apiJson } from "@/lib/api";
const mockApi = apiJson as ReturnType<typeof vi.fn>;

function freshClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}
function Wrap({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={freshClient()}>{children}</QueryClientProvider>;
}

// NOTE (Vitest 4 + React Query): no mockReset in beforeEach — install a fresh
// implementation per test. localStorage IS cleared per test (component state).
afterEach(() => {
  cleanup();
  localStorage.clear();
});

// One CRITICAL + one WARNING via observability; ops/notif empty.
function installAlerts() {
  mockApi.mockImplementation(async (path: string) => {
    if (path === "/observability/alerts") {
      return {
        status: "OK",
        critical_alerts: [{ alert_id: "c1", severity: "CRITICAL", title: "DB down", detail: "connection lost", generated_at: new Date().toISOString() }],
        warnings: [{ alert_id: "w1", severity: "WARNING", title: "Slow scan", generated_at: new Date().toISOString() }],
        info: [],
      };
    }
    if (path === "/operations/alerts") return { status: "OK", alerts: [] };
    if (path.startsWith("/notifications/deliveries")) return { deliveries: [] };
    throw new Error(`unexpected path ${path}`);
  });
}

describe("AlertCenterWidget ack/dismiss", () => {
  it("ack reduces the critical count", async () => {
    installAlerts();
    render(<Wrap><AlertCenterWidget /></Wrap>);

    // "1 critical" badge present initially
    await waitFor(() => expect(screen.getByText(/1 critical/)).toBeTruthy());

    // Ack the (first) critical alert
    fireEvent.click(screen.getAllByTestId("mc-alert-ack")[0]);

    // critical badge disappears (acked no longer counts)
    await waitFor(() => expect(screen.queryByText(/1 critical/)).toBeNull());
    // the acked row remains visible with the "ack" marker
    expect(screen.getByTestId("mc-alert-acked")).toBeTruthy();
  });

  it("dismiss hides the row and shows the restore chip", async () => {
    installAlerts();
    render(<Wrap><AlertCenterWidget /></Wrap>);

    await waitFor(() => expect(screen.getByText("DB down")).toBeTruthy());
    expect(screen.getByText("Slow scan")).toBeTruthy();

    // dismiss the first row (CRITICAL sorts first)
    fireEvent.click(screen.getAllByTestId("mc-alert-dismiss")[0]);

    // dismissed row hidden
    await waitFor(() => expect(screen.queryByText("DB down")).toBeNull());
    // restore chip appears with count 1
    const restore = screen.getByTestId("mc-alert-restore");
    expect(restore.textContent).toMatch(/1 dismissed/);

    // clicking restore brings the row back
    fireEvent.click(restore);
    await waitFor(() => expect(screen.getByText("DB down")).toBeTruthy());
  });

  it("persists dismissed state in localStorage", async () => {
    installAlerts();
    render(<Wrap><AlertCenterWidget /></Wrap>);
    await waitFor(() => expect(screen.getByText("DB down")).toBeTruthy());
    fireEvent.click(screen.getAllByTestId("mc-alert-dismiss")[0]);
    await waitFor(() => {
      const raw = localStorage.getItem("mc-alert-state-v1");
      expect(raw).toBeTruthy();
      expect(JSON.parse(raw!)["CRITICAL|DB down"]).toBe("dismissed");
    });
  });
});
