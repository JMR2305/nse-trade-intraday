"""
models.py — Phase 7.4
Dataclasses, enums, constants and helpers for the Explainable AI Hub.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any

# ── Feature flag ──────────────────────────────────────────────────────────────

_FLAG = "EXPLAINABLE_AI_ENABLED"


def is_enabled() -> bool:
    return os.environ.get(_FLAG, "false").lower() in ("true", "1", "yes")


def disabled_response(_caller: str = "") -> dict:
    return {
        "status":        "DISABLED",
        "feature_flag":  _FLAG,
        "advisory_only": True,
        "available":     False,
    }


# ── Grade / tier helpers ──────────────────────────────────────────────────────

def explainability_grade(score: float) -> str:
    if score >= 90: return "A+"
    if score >= 80: return "A"
    if score >= 70: return "B"
    if score >= 55: return "C"
    return "D"


def confidence_tier(score: float) -> str:
    if score >= 80: return "HIGH"
    if score >= 65: return "MODERATE"
    if score >= 50: return "LOW"
    return "VERY_LOW"


def trend_label(current: float, previous: float, threshold: float = 3.0) -> str:
    if current - previous > threshold:  return "IMPROVING"
    if previous - current > threshold:  return "WEAKENING"
    return "STABLE"


# ── Enums / constants ─────────────────────────────────────────────────────────

SCENARIO_BULLISH  = "BULLISH"
SCENARIO_NEUTRAL  = "NEUTRAL"
SCENARIO_BEARISH  = "BEARISH"

SIGNAL_STRONG_BUY  = "STRONG_BUY"
SIGNAL_BUY         = "BUY"
SIGNAL_WATCH       = "WATCH"
SIGNAL_SELL        = "SELL"
SIGNAL_STRONG_SELL = "STRONG_SELL"
SIGNAL_NO_TRADE    = "NO_TRADE"

BUY_SIGNALS   = {SIGNAL_STRONG_BUY, SIGNAL_BUY}
SELL_SIGNALS  = {SIGNAL_STRONG_SELL, SIGNAL_SELL}
WATCH_SIGNALS = {SIGNAL_WATCH}

RISK_LOW    = "LOW"
RISK_MEDIUM = "MEDIUM"
RISK_HIGH   = "HIGH"


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class IndicatorContribution:
    """One row in the 12-indicator breakdown. All rows sum to 100%."""
    name: str
    indicator_name: str           # alias — same value, used by UI layer
    contribution_pct: float       # 0–100, sums to 100 across all 12
    direction: str                # BULLISH | BEARISH | NEUTRAL
    description: str
    explanation: str              # alias for description (UI compatibility)
    weight_basis: str             # why this weight was assigned

    def __post_init__(self) -> None:
        # Keep aliases consistent
        if not self.indicator_name:
            self.indicator_name = self.name
        if not self.explanation:
            self.explanation = self.description

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DecisionTreeNode:
    label: str
    contribution_score: float  # 0–100
    direction: str
    children: List["DecisionTreeNode"] = field(default_factory=list)
    evidence: str = ""

    def to_dict(self) -> dict:
        return {
            "label":              self.label,
            "contribution_score": self.contribution_score,
            "direction":          self.direction,
            "evidence":           self.evidence,
            "children":           [c.to_dict() for c in self.children],
        }


@dataclass
class ScenarioAnalysis:
    """Phase 7.4 scenario (BULLISH / NEUTRAL / BEARISH)."""
    scenario_type:    str        # BULLISH | NEUTRAL | BEARISH
    probability:      float      # 0–1
    expected_return:  float      # % gain/loss
    key_conditions:   List[str]
    risk_factors:     List[str]
    narrative:        str
    price_target:     float
    advisory_only:    bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class HistoricalMatch:
    """Phase 7.4 historical pattern match."""
    symbol:           str
    date:             str
    signal_type:      str
    regime:           str
    confidence:       float
    outcome:          str
    pnl_pct:          Optional[float]
    similarity_score: float
    match_reasons:    List[str]
    narrative:        str
    advisory_only:    bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ConfidenceDecomposition:
    """Phase 7.4 8-dimension confidence breakdown."""
    symbol:             str
    overall_confidence: float
    reliability_grade:  str
    technical_score:    float
    fundamental_score:  float
    market_score:       float
    event_score:        float
    macro_score:        float
    risk_score:         float
    regime_score:       float
    historical_score:   float
    narrative:          str
    dimension_details:  List[Dict[str, Any]] = field(default_factory=list)
    advisory_only:      bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ExplainableDecision:
    """
    Full explanation for one symbol's latest signal.
    Field naming: primary_reason (singular) for the top reason text;
    primary_reasons (plural) as convenience alias (list form).
    """
    symbol: str
    signal_type: str

    # Reason text
    primary_reason: str
    secondary_reasons: List[str]

    # Supporting evidence groups
    supporting_indicators:         List[str]
    supporting_market_conditions:  List[str]
    supporting_events:             List[str]
    supporting_macro_conditions:   List[str]

    # Scores
    ai_score:            float
    strategy_score:      float
    risk_score:          float
    final_confidence:    float   # canonical; 0–100 or 0–1 depending on source
    explainability_score: float
    grade:               str
    decision_tree:       Dict[str, Any]
    plain_english_summary: str

    # Extended fields (used by operator_summary and UI)
    confidence:          float   = 0.0   # 0–1 representation (filled from final_confidence)
    tier:                str     = ""
    risk_level:          str     = RISK_MEDIUM
    price:               Optional[float] = None
    target:              Optional[float] = None
    stop_loss:           Optional[float] = None
    regime:              str     = "NEUTRAL"

    advisory_only: bool = True

    def __post_init__(self) -> None:
        # Normalise confidence to 0–1
        if self.confidence == 0.0 and self.final_confidence > 0:
            fc = self.final_confidence
            self.confidence = fc / 100.0 if fc > 1.0 else fc
        if not self.tier:
            self.tier = confidence_tier(self.confidence * 100)

    @property
    def primary_reasons(self) -> List[str]:
        """Convenience alias — list form of primary_reason + secondary_reasons."""
        result = []
        if self.primary_reason:
            result.append(self.primary_reason)
        result.extend(self.secondary_reasons or [])
        return result

    def to_dict(self) -> dict:
        d = asdict(self)
        d["primary_reasons"] = self.primary_reasons
        return d
