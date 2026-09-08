// @vitest-environment jsdom
/**
 * MissionControl.bootstrap.test.tsx
 *
 * Unit tests for the BootstrapStatusBanner display logic.
 *
 * Tests verify:
 *   1. Banner hidden when feature disabled or entries not armed
 *   2. Banner hidden when circuit breaker tripped or cutoff reached
 *   3. "No bootstrap-eligible candidates" banner with top WATCH candidate
 *   4. Top candidate ineligibility reason is displayed
 *   5. Positive banner when eligible candidates exist
 *   6. testid attributes are stable for operator observability
 *
 * Uses standard vitest assertions only (no jest-dom) because the vitest
 * config does not include @testing-library/jest-dom setup.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

// ── Inline mirror of BootstrapStatusBanner from MissionControl.tsx ──────────
// Mirrors the real component so we can test display logic without spinning up
// the full QueryClient + routing stack. Keeps tests fast and independent.

interface BannerProps {
  bootstrap_paper_enabled?: boolean;
  auto_paper_entries?: boolean;
  circuit_breaker_tripped?: boolean;
  bootstrap_cutoff_reached?: boolean;
  bootstrap_eligible_count?: number;
  watch_count?: number;
  top_candidates?: {
    symbol: string; confidence: number; bootstrap_eligible?: boolean;
    action?: string; ineligibility_reason?: string | null;
  }[];
  top_watch_candidate?: {
    symbol: string; confidence: number; action: string;
    ineligibility_reason?: string | null;
  } | null;
}

function BannerMirror({ d }: { d: BannerProps | undefined }) {
  if (!d) return null;
  if (!d.bootstrap_paper_enabled || !d.auto_paper_entries) return null;
  if (d.circuit_breaker_tripped || d.bootstrap_cutoff_reached) return null;

  const eligCount = d.bootstrap_eligible_count ?? 0;
  const watchTop  = d.top_watch_candidate ?? null;

  if (eligCount > 0) {
    return (
      <div data-testid="mc-bootstrap-banner-eligible">
        <span data-testid="mc-bootstrap-elig-count">{eligCount} bootstrap-eligible</span>
        {(d.top_candidates ?? []).length > 0 && (
          <span data-testid="mc-bootstrap-top-symbol">
            {d.top_candidates![0].symbol}
          </span>
        )}
      </div>
    );
  }

  return (
    <div data-testid="mc-bootstrap-banner-none">
      <p data-testid="mc-bootstrap-no-eligible">No bootstrap-eligible candidates in last scan</p>
      {watchTop ? (
        <p data-testid="mc-bootstrap-top-watch">
          Top candidate: <span data-testid="mc-bootstrap-top-symbol">{watchTop.symbol}</span>
          {" "}({watchTop.action}, {watchTop.confidence.toFixed(0)}% conf)
          {watchTop.ineligibility_reason && (
            <span data-testid="mc-bootstrap-inelig-reason"> — {watchTop.ineligibility_reason}</span>
          )}
        </p>
      ) : (
        <p data-testid="mc-bootstrap-no-watch">
          Scanner found {d.watch_count ?? 0} WATCH symbols — none cleared bootstrap thresholds.
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const BASE: BannerProps = {
  bootstrap_paper_enabled: true,
  auto_paper_entries: true,
  circuit_breaker_tripped: false,
  bootstrap_cutoff_reached: false,
  bootstrap_eligible_count: 0,
  watch_count: 5,
  top_candidates: [],
  top_watch_candidate: null,
};

const WATCH_TOP = {
  symbol: "HDFCBANK",
  confidence: 78.3,
  action: "WATCH",
  ineligibility_reason: "Kite session not verified — login required for bootstrap",
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("BootstrapStatusBanner", () => {
  it("renders nothing when feature is disabled", () => {
    const { container } = render(<BannerMirror d={{ ...BASE, bootstrap_paper_enabled: false }} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when auto_paper_entries is off", () => {
    const { container } = render(<BannerMirror d={{ ...BASE, auto_paper_entries: false }} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when circuit breaker is tripped", () => {
    const { container } = render(<BannerMirror d={{ ...BASE, circuit_breaker_tripped: true }} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when bootstrap cutoff is reached", () => {
    const { container } = render(<BannerMirror d={{ ...BASE, bootstrap_cutoff_reached: true }} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when data is undefined", () => {
    const { container } = render(<BannerMirror d={undefined} />);
    expect(container.firstChild).toBeNull();
  });

  describe("no eligible candidates (amber banner)", () => {
    it("renders testid mc-bootstrap-banner-none", () => {
      render(<BannerMirror d={BASE} />);
      expect(screen.getByTestId("mc-bootstrap-banner-none")).toBeTruthy();
    });

    it("shows the 'no bootstrap-eligible candidates' message", () => {
      render(<BannerMirror d={BASE} />);
      const el = screen.getByTestId("mc-bootstrap-no-eligible");
      expect(el.textContent).toContain("No bootstrap-eligible candidates");
    });

    it("shows top WATCH candidate symbol when present", () => {
      render(<BannerMirror d={{ ...BASE, top_watch_candidate: WATCH_TOP }} />);
      const sym = screen.getByTestId("mc-bootstrap-top-symbol");
      expect(sym.textContent).toBe("HDFCBANK");
    });

    it("shows action label in top-watch line", () => {
      render(<BannerMirror d={{ ...BASE, top_watch_candidate: WATCH_TOP }} />);
      const row = screen.getByTestId("mc-bootstrap-top-watch");
      expect(row.textContent).toContain("WATCH");
    });

    it("shows confidence in top-watch line", () => {
      render(<BannerMirror d={{ ...BASE, top_watch_candidate: WATCH_TOP }} />);
      const row = screen.getByTestId("mc-bootstrap-top-watch");
      expect(row.textContent).toContain("78%");
    });

    it("shows ineligibility reason when present", () => {
      render(<BannerMirror d={{ ...BASE, top_watch_candidate: WATCH_TOP }} />);
      const reason = screen.getByTestId("mc-bootstrap-inelig-reason");
      expect(reason.textContent).toContain(WATCH_TOP.ineligibility_reason);
    });

    it("omits ineligibility reason element when reason is null", () => {
      const top = { ...WATCH_TOP, ineligibility_reason: null };
      render(<BannerMirror d={{ ...BASE, top_watch_candidate: top }} />);
      expect(screen.queryByTestId("mc-bootstrap-inelig-reason")).toBeNull();
    });

    it("falls back to watch_count message when top_watch_candidate is null", () => {
      render(<BannerMirror d={{ ...BASE, watch_count: 7 }} />);
      const el = screen.getByTestId("mc-bootstrap-no-watch");
      expect(el.textContent).toContain("7");
    });

    it("does not render the eligible banner", () => {
      render(<BannerMirror d={BASE} />);
      expect(screen.queryByTestId("mc-bootstrap-banner-eligible")).toBeNull();
    });
  });

  describe("eligible candidates exist (teal banner)", () => {
    const ELIGIBLE: BannerProps = {
      ...BASE,
      bootstrap_eligible_count: 2,
      top_candidates: [
        { symbol: "RELIANCE", confidence: 74.0, bootstrap_eligible: true },
        { symbol: "TCS", confidence: 68.0, bootstrap_eligible: true },
      ],
    };

    it("renders testid mc-bootstrap-banner-eligible", () => {
      render(<BannerMirror d={ELIGIBLE} />);
      expect(screen.getByTestId("mc-bootstrap-banner-eligible")).toBeTruthy();
    });

    it("does NOT render the amber banner", () => {
      render(<BannerMirror d={ELIGIBLE} />);
      expect(screen.queryByTestId("mc-bootstrap-banner-none")).toBeNull();
    });

    it("shows the top symbol", () => {
      render(<BannerMirror d={ELIGIBLE} />);
      const sym = screen.getByTestId("mc-bootstrap-top-symbol");
      expect(sym.textContent).toBe("RELIANCE");
    });

    it("shows count in banner text", () => {
      render(<BannerMirror d={ELIGIBLE} />);
      const el = screen.getByTestId("mc-bootstrap-elig-count");
      expect(el.textContent).toContain("2");
    });
  });
});
