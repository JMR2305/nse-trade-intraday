"""
optimisation_models.py — Phase 6.2
Data models, feature flag, scoring helpers.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------

def is_enabled() -> bool:
    return os.environ.get("STRATEGY_OPTIMISATION_ENABLED", "false").lower() == "true"


def disabled_response() -> dict:
    return {
        "status": "DISABLED",
        "message": "Set STRATEGY_OPTIMISATION_ENABLED=true to enable.",
    }


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def grade(score: float) -> str:
    if score >= 90:
        return "A+"
    if score >= 80:
        return "A"
    if score >= 65:
        return "B"
    if score >= 50:
        return "C"
    return "D"


def underperform_action(score: float) -> str:
    """Advisory action for underperforming strategies."""
    if score < 30:
        return "Pause"
    if score < 50:
        return "Retune"
    if score < 65:
        return "Observe"
    return "Continue"


# ---------------------------------------------------------------------------
# Strategy profile
# ---------------------------------------------------------------------------

@dataclass
class StrategyProfile:
    strategy: str
    total_trades: int
    win_rate: float
    avg_return_pct: float
    profit_factor: float
    max_drawdown: float
    sharpe_ratio: float
    avg_holding_time_minutes: float
    avg_confidence: float
    avg_execution_score: float
    avg_risk_score: float
    consistency_score: float
    stability_score: float
    recovery_score: float
    health_score: float
    grade: str
    action: str              # Continue / Observe / Retune / Pause
    is_underperforming: bool
    underperform_reasons: List[str] = field(default_factory=list)
    advisory_only: bool = True

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "total_trades": self.total_trades,
            "win_rate": round(self.win_rate, 4),
            "avg_return_pct": round(self.avg_return_pct, 4),
            "profit_factor": round(self.profit_factor, 3),
            "max_drawdown": round(self.max_drawdown, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 3),
            "avg_holding_time_minutes": round(self.avg_holding_time_minutes, 1),
            "avg_confidence": round(self.avg_confidence, 4),
            "avg_execution_score": round(self.avg_execution_score, 4),
            "avg_risk_score": round(self.avg_risk_score, 4),
            "consistency_score": round(self.consistency_score, 4),
            "stability_score": round(self.stability_score, 4),
            "recovery_score": round(self.recovery_score, 4),
            "health_score": round(self.health_score, 2),
            "grade": self.grade,
            "action": self.action,
            "is_underperforming": self.is_underperforming,
            "underperform_reasons": self.underperform_reasons,
            "advisory_only": True,
        }


# ---------------------------------------------------------------------------
# Regime row
# ---------------------------------------------------------------------------

@dataclass
class RegimeRow:
    regime: str
    trades: int
    win_rate: float
    avg_return_pct: float
    net_pnl: float
    avg_confidence: float
    rank: int = 0

    def to_dict(self) -> dict:
        return {
            "regime": self.regime,
            "trades": self.trades,
            "win_rate": round(self.win_rate, 4),
            "avg_return_pct": round(self.avg_return_pct, 4),
            "net_pnl": round(self.net_pnl, 2),
            "avg_confidence": round(self.avg_confidence, 4),
            "rank": self.rank,
        }


# ---------------------------------------------------------------------------
# Time window row
# ---------------------------------------------------------------------------

@dataclass
class TimeWindowRow:
    window: str           # Opening Hour / Morning / Mid Session / Afternoon / Closing Hour
    start_time: str       # HH:MM
    end_time: str
    trades: int
    win_rate: float
    avg_return_pct: float
    net_pnl: float
    avg_holding_minutes: float
    rank: int = 0

    def to_dict(self) -> dict:
        return {
            "window": self.window,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "trades": self.trades,
            "win_rate": round(self.win_rate, 4),
            "avg_return_pct": round(self.avg_return_pct, 4),
            "net_pnl": round(self.net_pnl, 2),
            "avg_holding_minutes": round(self.avg_holding_minutes, 1),
            "rank": self.rank,
        }


# ---------------------------------------------------------------------------
# Sector row
# ---------------------------------------------------------------------------

@dataclass
class SectorRow:
    sector: str
    trades: int
    win_rate: float
    net_pnl: float
    avg_return_pct: float
    avg_risk_score: float
    consistency_score: float
    rank: int = 0

    def to_dict(self) -> dict:
        return {
            "sector": self.sector,
            "trades": self.trades,
            "win_rate": round(self.win_rate, 4),
            "net_pnl": round(self.net_pnl, 2),
            "avg_return_pct": round(self.avg_return_pct, 4),
            "avg_risk_score": round(self.avg_risk_score, 4),
            "consistency_score": round(self.consistency_score, 4),
            "rank": self.rank,
        }


# ---------------------------------------------------------------------------
# Parameter recommendation
# ---------------------------------------------------------------------------

@dataclass
class ParameterRec:
    strategy: str
    parameter: str
    current_observation: str
    recommended_value: str
    rationale: str
    confidence: str          # HIGH / MEDIUM / LOW
    advisory_only: bool = True

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "parameter": self.parameter,
            "current_observation": self.current_observation,
            "recommended_value": self.recommended_value,
            "rationale": self.rationale,
            "confidence": self.confidence,
            "advisory_only": True,
        }


# ---------------------------------------------------------------------------
# Pattern
# ---------------------------------------------------------------------------

@dataclass
class Pattern:
    pattern_id: str
    pattern_type: str        # WINNING / LOSING / HIGH_CONF / LOW_CONF
    description: str
    conditions: Dict[str, Any]
    trade_count: int
    win_rate: float
    avg_return_pct: float
    examples: List[str] = field(default_factory=list)   # trade_ids

    def to_dict(self) -> dict:
        return {
            "pattern_id": self.pattern_id,
            "pattern_type": self.pattern_type,
            "description": self.description,
            "conditions": self.conditions,
            "trade_count": self.trade_count,
            "win_rate": round(self.win_rate, 4),
            "avg_return_pct": round(self.avg_return_pct, 4),
            "examples": self.examples[:3],
        }
