"""
risk_models.py — Phase 6.4
Feature flag, scoring helpers, and dataclasses.

READ-ONLY. ADVISORY-ONLY.
No orders, portfolio, strategies, signals, risk engine, or position sizes
are ever modified by this module.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------

def is_enabled() -> bool:
    return os.environ.get("RISK_OPTIMISATION_ENABLED", "false").lower() == "true"


def disabled_response() -> dict:
    return {
        "status": "DISABLED",
        "message": "Set RISK_OPTIMISATION_ENABLED=true to enable.",
    }


# ---------------------------------------------------------------------------
# Health score helpers
# ---------------------------------------------------------------------------

def health_grade(score: float) -> str:
    if score >= 90:
        return "A+"
    if score >= 80:
        return "A"
    if score >= 65:
        return "B"
    if score >= 50:
        return "C"
    return "D"


def compute_risk_optimisation_score(
    diversification_score: float,   # 0–1 (higher = better)
    drawdown_severity: float,        # 0–1 (lower = better; 0=no drawdown)
    capital_efficiency: float,       # 0–1 (higher = better)
    position_sizing_score: float,    # 0–1 (higher = better)
    stop_loss_score: float,          # 0–1 (higher = better)
) -> float:
    """
    Weighted Risk Optimisation Score 0–100.
    Diversification 25%, Drawdown resilience 25%, Capital efficiency 20%,
    Position sizing 15%, Stop loss quality 15%.
    """
    drawdown_resilience = max(0.0, 1.0 - drawdown_severity)
    raw = (
        diversification_score * 25.0
        + drawdown_resilience * 25.0
        + capital_efficiency * 20.0
        + position_sizing_score * 15.0
        + stop_loss_score * 15.0
    )
    return round(min(max(raw, 0.0), 100.0), 2)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class DrawdownPeriod:
    start: str
    end: str
    drawdown_pct: float
    recovery_days: Optional[float]
    description: str

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "end": self.end,
            "drawdown_pct": round(self.drawdown_pct, 4),
            "recovery_days": round(self.recovery_days, 2) if self.recovery_days is not None else None,
            "description": self.description,
        }


@dataclass
class StressScenario:
    name: str                     # e.g. "20% Market Correction"
    scenario_type: str            # CORRECTION / GAP_DOWN / GAP_UP / HIGH_VOL / MULTI_LOSS / SECTOR_COLLAPSE / LIQUIDITY
    assumed_impact_pct: float     # e.g. -0.20
    estimated_portfolio_pnl: float
    estimated_portfolio_pnl_pct: float
    positions_affected: int
    severity: str                 # LOW / MEDIUM / HIGH / CRITICAL
    advisory: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "scenario_type": self.scenario_type,
            "assumed_impact_pct": round(self.assumed_impact_pct, 4),
            "estimated_portfolio_pnl": round(self.estimated_portfolio_pnl, 2),
            "estimated_portfolio_pnl_pct": round(self.estimated_portfolio_pnl_pct, 4),
            "positions_affected": self.positions_affected,
            "severity": self.severity,
            "advisory": self.advisory,
        }


@dataclass
class RiskRecommendation:
    category: str            # CapitalAllocation / PositionSizing / Concentration / Drawdown / StopLoss / Target / RiskBudget / Diversification
    recommendation: str
    rationale: str
    current_value: str
    suggested_value: str
    confidence: str          # HIGH / MEDIUM / LOW
    expected_benefit: str
    risk_reduction: str
    priority: str            # HIGH / MEDIUM / LOW
    advisory_only: bool = True

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "recommendation": self.recommendation,
            "rationale": self.rationale,
            "current_value": self.current_value,
            "suggested_value": self.suggested_value,
            "confidence": self.confidence,
            "expected_benefit": self.expected_benefit,
            "risk_reduction": self.risk_reduction,
            "priority": self.priority,
            "advisory_only": True,
        }
