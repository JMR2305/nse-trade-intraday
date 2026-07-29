"""
models.py — Phase 7.5
Dataclasses, enums, constants and helpers for the Research Lab.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any

# ── Feature flag ──────────────────────────────────────────────────────────────

_FLAG = "RESEARCH_LAB_ENABLED"


def is_enabled() -> bool:
    return os.environ.get(_FLAG, "false").lower() in ("true", "1", "yes")


def disabled_response(_caller: str = "") -> dict:
    return {
        "status":        "DISABLED",
        "feature_flag":  _FLAG,
        "advisory_only": True,
        "available":     False,
    }


# ── Grade / trend helpers ─────────────────────────────────────────────────────

def research_grade(score: float) -> str:
    if score >= 90: return "A+"
    if score >= 80: return "A"
    if score >= 70: return "B"
    if score >= 55: return "C"
    return "D"


def trend_label(current: float, previous: float, threshold: float = 3.0) -> str:
    if current - previous > threshold:  return "IMPROVING"
    if previous - current > threshold:  return "WEAKENING"
    return "STABLE"


# ── Strategy types ────────────────────────────────────────────────────────────

STRATEGY_TREND_FOLLOWING  = "TREND_FOLLOWING"
STRATEGY_MEAN_REVERSION   = "MEAN_REVERSION"
STRATEGY_MOMENTUM         = "MOMENTUM"
STRATEGY_BREAKOUT         = "BREAKOUT"
STRATEGY_RANGE_TRADING    = "RANGE_TRADING"
STRATEGY_VOLATILITY_BASED = "VOLATILITY_BASED"
STRATEGY_SECTOR_ROTATION  = "SECTOR_ROTATION"
STRATEGY_CUSTOM           = "CUSTOM_RESEARCH"

ALL_STRATEGIES = [
    STRATEGY_TREND_FOLLOWING,
    STRATEGY_MEAN_REVERSION,
    STRATEGY_MOMENTUM,
    STRATEGY_BREAKOUT,
    STRATEGY_RANGE_TRADING,
    STRATEGY_VOLATILITY_BASED,
    STRATEGY_SECTOR_ROTATION,
]

# ── Scenario types ────────────────────────────────────────────────────────────

SCENARIO_BULL         = "BULL_MARKET"
SCENARIO_BEAR         = "BEAR_MARKET"
SCENARIO_SIDEWAYS     = "SIDEWAYS_MARKET"
SCENARIO_HIGH_VOL     = "HIGH_VOLATILITY"
SCENARIO_LOW_VOL      = "LOW_VOLATILITY"
SCENARIO_GAP_OPEN     = "GAP_OPENING"
SCENARIO_NEWS_DRIVEN  = "NEWS_DRIVEN"
SCENARIO_MACRO_SHOCK  = "MACRO_SHOCK"

ALL_SCENARIOS = [
    SCENARIO_BULL, SCENARIO_BEAR, SCENARIO_SIDEWAYS,
    SCENARIO_HIGH_VOL, SCENARIO_LOW_VOL,
    SCENARIO_GAP_OPEN, SCENARIO_NEWS_DRIVEN, SCENARIO_MACRO_SHOCK,
]

# ── Market regimes ────────────────────────────────────────────────────────────

REGIME_BULL       = "BULL"
REGIME_BEAR       = "BEAR"
REGIME_RANGE      = "RANGE"
REGIME_VOLATILE   = "VOLATILE"
REGIME_LOW_VOL    = "LOW_VOLATILITY"
REGIME_TRANSITION = "TRANSITION"

ALL_REGIMES = [
    REGIME_BULL, REGIME_BEAR, REGIME_RANGE,
    REGIME_VOLATILE, REGIME_LOW_VOL, REGIME_TRANSITION,
]

# ── Experiment status ─────────────────────────────────────────────────────────

STATUS_DRAFT      = "DRAFT"
STATUS_RUNNING    = "RUNNING"
STATUS_COMPLETE   = "COMPLETE"
STATUS_ARCHIVED   = "ARCHIVED"


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class StrategyProfile:
    """Research profile for one strategy type."""
    strategy_type:   str
    label:           str
    description:     str
    signal_count:    int
    win_rate:        float          # 0–1
    avg_confidence:  float          # 0–100
    avg_drawdown:    float          # % (positive number)
    consistency:     float          # 0–100
    risk_score:      float          # 0–100
    performance_score: float        # 0–100
    grade:           str
    best_regime:     str
    worst_regime:    str
    recommendation:  str
    advisory_only:   bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ScenarioResult:
    """Advisory outcome of simulating one market scenario."""
    scenario_type:     str
    label:             str
    description:       str
    market_impact:     str          # POSITIVE / NEGATIVE / NEUTRAL
    expected_signals:  int
    signal_shift:      str          # how signal distribution would shift
    risk_level:        str
    opportunity_score: float        # 0–100
    threat_score:      float        # 0–100
    affected_sectors:  List[str]
    key_risks:         List[str]
    key_opportunities: List[str]
    recommended_actions: List[str]
    advisory_only:     bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ReplayFrame:
    """One historical signal snapshot in the replay timeline."""
    frame_id:    str
    timestamp:   str
    symbol:      str
    signal_type: str
    confidence:  float
    price:       Optional[float]
    regime:      str
    reason:      str
    outcome:     str                # WIN / LOSS / UNKNOWN
    pnl_pct:     Optional[float]
    advisory_only: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ParameterExperiment:
    """Result of testing one parameter variation."""
    experiment_id:   str
    parameter_name:  str
    baseline_value:  float
    test_value:      float
    impact_label:    str            # IMPROVED / NEUTRAL / DEGRADED
    signal_count_delta: int         # relative to baseline
    confidence_delta:   float
    win_rate_delta:     float
    risk_delta:         float
    narrative:          str
    advisory_only:      bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RegimeProfile:
    """Performance profile for one market regime."""
    regime:          str
    signal_count:    int
    win_rate:        float
    avg_confidence:  float
    avg_drawdown:    float
    best_strategy:   str
    worst_strategy:  str
    vix_range:       str
    advisory_only:   bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RiskSimulation:
    """Advisory risk simulation outputs."""
    expected_drawdown:      float
    max_drawdown_estimate:  float
    capital_usage_pct:      float
    risk_distribution:      Dict[str, float]    # LOW/MED/HIGH percentages
    reward_distribution:    Dict[str, float]
    volatility_exposure:    float
    stress_scenarios:       List[Dict[str, Any]]
    monte_carlo_note:       str
    advisory_only:          bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BenchmarkComparison:
    """Performance comparison across research / baseline / market / paper."""
    research_score:     float
    baseline_score:     float
    market_score:       float
    paper_score:        float
    relative_alpha:     float
    risk_adj_return:    float
    consistency:        float
    winner:             str
    narrative:          str
    advisory_only:      bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Experiment:
    """Innovation workspace experiment record."""
    experiment_id:   str
    title:           str
    objective:       str
    tags:            List[str]
    status:          str
    created_at:      str
    notes:           str
    hypothesis:      str
    result_summary:  str
    version:         int
    advisory_only:   bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ResearchReport:
    """Auto-generated research report."""
    report_id:       str
    generated_at:    str
    research_score:  float
    grade:           str
    trend:           str
    executive_summary: str
    objectives:      List[str]
    methodology:     str
    key_findings:    List[str]
    performance_summary: str
    risk_analysis:   str
    limitations:     List[str]
    recommendations: List[str]
    advisory_only:   bool = True

    def to_dict(self) -> dict:
        return asdict(self)
