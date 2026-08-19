// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  AllocationSummary,
  QualityAllocationPolicyView,
} from "./AIPaperTraderPage";

describe("Allocation components in AIPaperTraderPage", () => {
  it("renders nothing if no allocation tier or multiplier", () => {
    const { container } = render(<AllocationSummary data={{ stock: "TCS" } as any} />);
    expect(container.innerHTML).toBe("");
  });

  it("renders tier and multiplier if present", () => {
    render(<AllocationSummary data={{ 
      allocation_tier: "EXCEPTIONAL_QUALITY_3X",
      allocation_requested_multiplier: 3,
      allocation_effective_multiplier: 2.5
    } as any} />);
    expect(screen.getByTestId("allocation-tier-badge").textContent).toBe("3X QUALITY");
    expect(screen.getByText("2.5x")).not.toBeNull();
    expect(screen.getByText("(3x req)")).not.toBeNull();
  });

  it("renders missing optional data gracefully (just multiplier)", () => {
    render(<AllocationSummary data={{ 
      allocation_effective_multiplier: 1.5,
      allocation_requested_multiplier: 1.5
    } as any} />);
    expect(screen.queryByTestId("allocation-tier-badge")).toBeNull();
    expect(screen.getByText("1.5x")).not.toBeNull();
  });
  
  it("renders limiting caps if present", () => {
    render(<AllocationSummary data={{ 
      allocation_tier: "NORMAL",
      allocation_requested_multiplier: 1,
      allocation_effective_multiplier: 1,
      allocation_limiting_caps: ["PORTFOLIO_MAX_CAP"]
    } as any} />);
    expect(screen.getByText(/Capped by: PORTFOLIO_MAX_CAP/)).not.toBeNull();
  });

  it("labels recommendation sizing as a non-executed current-scan preview", () => {
    render(<AllocationSummary data={{
      allocation_tier: "HIGH_QUALITY_2X",
      allocation_requested_multiplier: 2,
      allocation_effective_multiplier: 2,
      allocation_preview: true,
      allocation_preview_not_executed: true,
      allocation_scan_id: "scan-123",
      allocation_evaluated_at: "2026-08-19T04:00:05Z",
    } as any} />);
    expect(screen.getByTestId("allocation-preview-label").textContent)
      .toContain("PREVIEW · NOT EXECUTED");
    expect(screen.getByText(/Current-scan estimate · Scan scan-123/))
      .not.toBeNull();
  });

  it("renders exact configured quality thresholds and disabled sector override", () => {
    render(<QualityAllocationPolicyView settings={{
      quality_allocation_override_enabled: true,
      quality_allocation_2x_enabled: true,
      quality_allocation_3x_enabled: true,
      quality_allocation_2x_min_confidence: 85,
      quality_allocation_2x_min_opportunity_score: 80,
      quality_allocation_2x_min_trade_quality_score: 80,
      quality_allocation_2x_min_risk_reward: 2.5,
      quality_allocation_2x_risk_budget_pct: 1.5,
      quality_allocation_3x_min_confidence: 90,
      quality_allocation_3x_min_opportunity_score: 85,
      quality_allocation_3x_min_trade_quality_score: 88,
      quality_allocation_3x_min_risk_reward: 3,
      quality_allocation_3x_risk_budget_pct: 2,
      quality_allocation_3x_max_atr_pct: 3,
      quality_allocation_3x_max_stop_distance_pct: 2.5,
      quality_allocation_absolute_cap: 30_000,
      quality_allocation_3x_sector_override_enabled: false,
      quality_allocation_3x_sector_override_cap_pct: 50,
    }} />);
    expect(screen.getByTestId("quality-allocation-policy-state").textContent)
      .toContain("ON");
    expect(screen.getByText(/85\/80\/80/)).not.toBeNull();
    expect(screen.getByText(/90\/85\/88/)).not.toBeNull();
    expect(screen.getByText(/SECTOR OVERRIDE OFF/)).not.toBeNull();
  });

  it("keeps the policy visible when overrides are disabled", () => {
    render(<QualityAllocationPolicyView settings={{
      quality_allocation_override_enabled: false,
      quality_allocation_2x_enabled: true,
      quality_allocation_3x_enabled: true,
    }} />);
    expect(screen.getByTestId("quality-allocation-policy-state").textContent)
      .toContain("OFF");
    expect(screen.getByText("Normal 1x sizing only")).not.toBeNull();
  });
});
