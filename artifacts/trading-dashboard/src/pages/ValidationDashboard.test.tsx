// @vitest-environment jsdom
/**
 * Phase 23.9 — Validation Dashboard component tests.
 *
 * Mounts the real <ValidationDashboard> with a mocked apiJson and verifies:
 *  - READY state renders the green banner + PASS domain cards
 *  - NOT READY state renders blockers and FAIL/WARN badges
 *  - Empty history renders the "No certification runs yet" state
 *  - INSUFFICIENT_EVIDENCE domains render the INSUFFICIENT badge
 *  - Acceptance section renders verdict + system rows
 *  - Export links exist for every report × format
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/api", () => ({
  API_BASE: "",
  apiJson: vi.fn(),
}));

import { apiJson } from "@/lib/api";
import ValidationDashboard from "./ValidationDashboard";

const mockApi = apiJson as unknown as ReturnType<typeof vi.fn>;

// ── Fixtures ──────────────────────────────────────────────────────────────────

const DOMAINS_ALL_PASS = Object.fromEntries(
  ["data", "pipeline", "portfolio", "replay", "ai_decision",
   "performance", "learning", "mission_control"].map((d) => [
    d,
    { verdict: "PASS", weight: 0.125, score_pct: 100, checks_total: 4,
      checks_failed: 0, checks_warned: 0 },
  ]),
);

const CERT_READY = {
  ok: true,
  cert_id: "CERT-ready001",
  created_at: "2026-08-08T10:00:00.000Z",
  certification_pct: 100,
  verdict: "READY",
  blockers: [] as string[],
  domains: DOMAINS_ALL_PASS,
};

const CERT_NOT_READY = {
  ...CERT_READY,
  cert_id: "CERT-fail001",
  certification_pct: 55,
  verdict: "NOT_READY",
  blockers: ["data: FAIL", "replay: WARN", "performance: INSUFFICIENT_EVIDENCE"],
  domains: {
    ...DOMAINS_ALL_PASS,
    data: { verdict: "FAIL", weight: 0.15, score_pct: 0, checks_total: 4,
            checks_failed: 2, checks_warned: 0 },
    replay: { verdict: "WARN", weight: 0.15, score_pct: 50, checks_total: 3,
              checks_failed: 0, checks_warned: 1 },
    performance: { verdict: "INSUFFICIENT_EVIDENCE", weight: 0.10,
                   score_pct: 0, checks_total: 0, checks_failed: 0,
                   checks_warned: 0 },
  },
};

const ACCEPTANCE = {
  ok: true,
  verdict: "ACCEPTED",
  accepted: true,
  score_pct: 98.5,
  checks_total: 40,
  checks_failed: 0,
  checks_warned: 1,
  systems: [
    { system: "Simulation Lab", module: "simulation_lab.py",
      verdict: "PASS", checks: [] },
    { system: "Certification Engine", module: "certification_engine.py",
      verdict: "PASS", checks: [] },
  ],
  runtime_checks: [],
};

function respondWith(cert: typeof CERT_READY | null) {
  mockApi.mockImplementation((path: string) => {
    if (path.startsWith("certification/history")) {
      return Promise.resolve({
        ok: true,
        items: cert
          ? [{ cert_id: cert.cert_id, created_at: cert.created_at,
               certification_pct: cert.certification_pct,
               verdict: cert.verdict, domains: {} }]
          : [],
      });
    }
    if (cert && path === `certification/${cert.cert_id}`) {
      return Promise.resolve(cert);
    }
    if (path === "phase239/acceptance") return Promise.resolve(ACCEPTANCE);
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ValidationDashboard />
    </QueryClientProvider>,
  );
}

// NOTE: never mockReset an API mock in beforeEach — in-flight React Query
// retries from the previous test would reject unhandled (Vitest 4).
// respondWith() overrides the implementation per test instead.
afterEach(() => cleanup());

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("ValidationDashboard", () => {
  it("renders READY banner and PASS domain cards", async () => {
    respondWith(CERT_READY);
    mount();
    // wait for the FULL cert report (all 8 domain cards), not just the
    // history row — "READY" appears in the history table first
    await waitFor(() =>
      expect(screen.getAllByText("PASS").length).toBeGreaterThanOrEqual(8));
    expect(screen.getAllByText("READY").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/CERT-ready001/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Mission Control")).toBeTruthy();
  });

  it("renders NOT READY with blockers, FAIL/WARN and INSUFFICIENT badges", async () => {
    respondWith(CERT_NOT_READY);
    mount();
    await waitFor(() => expect(screen.getByText("NOT READY")).toBeTruthy());
    expect(screen.getByText(/Blockers:/)).toBeTruthy();
    expect(screen.getAllByText("FAIL").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("WARN").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("INSUFFICIENT").length).toBeGreaterThanOrEqual(1);
  });

  it("renders empty state when there are no certification runs", async () => {
    respondWith(null);
    mount();
    await waitFor(() =>
      expect(screen.getByText("No certification runs yet")).toBeTruthy());
    expect(screen.getAllByText(/Run Certification/).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the acceptance section with verdict and system rows", async () => {
    respondWith(CERT_READY);
    mount();
    await waitFor(() =>
      expect(screen.getByText(/ACCEPTED · 98.5%/)).toBeTruthy());
    expect(screen.getByText("Simulation Lab")).toBeTruthy();
    expect(screen.getByText("Certification Engine")).toBeTruthy();
  });

  it("exposes export links for every report in all four formats", async () => {
    respondWith(CERT_READY);
    const { container } = mount();
    await waitFor(() => expect(screen.getByText("Export Reports")).toBeTruthy());
    for (const report of ["certification", "validation_logs", "simulation",
                          "comparison", "acceptance"]) {
      for (const fmt of ["pdf", "csv", "json", "md"]) {
        const link = container.querySelector(
          `a[href="/phase239/export/${report}/${fmt}"]`);
        expect(link, `missing export link ${report}/${fmt}`).toBeTruthy();
      }
    }
  });
});
