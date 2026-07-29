"""
models.py — Phase 7.3
Data models, enums, and feature flag for the Macro Intelligence Hub.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import List, Optional

# ── Feature flag ──────────────────────────────────────────────────────────────

_FLAG = "MACRO_INTELLIGENCE_ENABLED"


def is_enabled() -> bool:
    return os.environ.get(_FLAG, "false").lower() in ("1", "true", "yes")


def disabled_response() -> dict:
    return {
        "status":        "DISABLED",
        "feature_flag":  _FLAG,
        "advisory_only": True,
        "available":     False,
    }


# ── Category constants ─────────────────────────────────────────────────────────

CAT_ECONOMIC     = "ECONOMIC"
CAT_CENTRAL_BANK = "CENTRAL_BANK"
CAT_GLOBAL       = "GLOBAL_MARKET"
CAT_FLOWS        = "MARKET_FLOWS"
CAT_CURRENCY     = "CURRENCY"
CAT_COMMODITY    = "COMMODITY"
CAT_VOLATILITY   = "VOLATILITY"

# ── Direction constants ────────────────────────────────────────────────────────

DIR_BULLISH  = "BULLISH"
DIR_BEARISH  = "BEARISH"
DIR_NEUTRAL  = "NEUTRAL"
DIR_VOLATILE = "VOLATILE"

# ── Priority constants ─────────────────────────────────────────────────────────

PRI_CRITICAL = "CRITICAL"
PRI_HIGH     = "HIGH"
PRI_MEDIUM   = "MEDIUM"
PRI_LOW      = "LOW"

# ── Economic sub-types ─────────────────────────────────────────────────────────

ECO_RBI_POLICY     = "RBI_POLICY"
ECO_REPO_RATE      = "REPO_RATE"
ECO_CPI            = "CPI"
ECO_WPI            = "WPI"
ECO_GDP            = "GDP"
ECO_IIP            = "IIP"
ECO_PMI            = "PMI"
ECO_TRADE_BALANCE  = "TRADE_BALANCE"
ECO_FISCAL_DEFICIT = "FISCAL_DEFICIT"
ECO_BUDGET         = "GOVT_BUDGET"
ECO_EMPLOYMENT     = "EMPLOYMENT"
ECO_GLOBAL_EVENT   = "GLOBAL_EVENT"

# ── Flow sub-types ─────────────────────────────────────────────────────────────

FLOW_FII       = "FII_ACTIVITY"
FLOW_DII       = "DII_ACTIVITY"
FLOW_INST_BUY  = "INSTITUTIONAL_BUY"
FLOW_INST_SELL = "INSTITUTIONAL_SELL"
FLOW_SECTOR    = "SECTOR_ROTATION"
FLOW_LIQUIDITY = "LIQUIDITY_TREND"

# ── Volatility regime ─────────────────────────────────────────────────────────

VIX_EXPANSION   = "EXPANSION"
VIX_CONTRACTION = "CONTRACTION"
VIX_STABLE      = "STABLE"

# ── Risk levels ───────────────────────────────────────────────────────────────

RISK_LOW     = "LOW"
RISK_MEDIUM  = "MEDIUM"
RISK_HIGH    = "HIGH"
RISK_EXTREME = "EXTREME"


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class MacroEvent:
    event_id:            str
    category:            str            # CAT_*
    sub_type:            str
    title:               str
    description:         str
    event_date:          Optional[str]   = None     # ISO date YYYY-MM-DD
    discovered_at:       Optional[str]   = None     # ISO datetime
    importance_score:    float           = 50.0     # 0-100
    confidence_score:    float           = 50.0     # 0-100
    direction:           str             = DIR_NEUTRAL
    expected_volatility: str             = RISK_MEDIUM
    expected_duration:   str             = "1D"
    priority:            str             = PRI_MEDIUM
    affected_sectors:    List[str]       = field(default_factory=list)
    affected_industries: List[str]       = field(default_factory=list)
    historical_context:  Optional[str]   = None
    trading_risk:        Optional[str]   = None
    opportunity:         Optional[str]   = None
    source:              str             = "INTERNAL"
    is_upcoming:         bool            = False

    def to_dict(self) -> dict:
        return {
            "event_id":            self.event_id,
            "category":            self.category,
            "sub_type":            self.sub_type,
            "title":               self.title,
            "description":         self.description,
            "event_date":          self.event_date,
            "discovered_at":       self.discovered_at,
            "importance_score":    round(self.importance_score, 1),
            "confidence_score":    round(self.confidence_score, 1),
            "direction":           self.direction,
            "expected_volatility": self.expected_volatility,
            "expected_duration":   self.expected_duration,
            "priority":            self.priority,
            "affected_sectors":    self.affected_sectors,
            "affected_industries": self.affected_industries,
            "historical_context":  self.historical_context,
            "trading_risk":        self.trading_risk,
            "opportunity":         self.opportunity,
            "source":              self.source,
            "is_upcoming":         self.is_upcoming,
        }


# ── Score / grade helpers ─────────────────────────────────────────────────────

def macro_grade(score: float) -> str:
    if score >= 90: return "A+"
    if score >= 80: return "A"
    if score >= 70: return "B"
    if score >= 55: return "C"
    return "D"


def priority_from_score(score: float) -> str:
    if score >= 80: return PRI_CRITICAL
    if score >= 65: return PRI_HIGH
    if score >= 45: return PRI_MEDIUM
    return PRI_LOW


def trend_label(current: float, previous: float) -> str:
    if current > previous + 2:  return "IMPROVING"
    if current < previous - 2:  return "WEAKENING"
    return "STABLE"
