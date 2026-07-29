"""
models.py — Phase 7.2
Data models, enums, and feature flag guard for Event Intelligence.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import List, Optional

# ── Feature flag ──────────────────────────────────────────────────────────────

_FLAG = "EVENT_INTELLIGENCE_ENABLED"


def is_enabled() -> bool:
    return os.environ.get(_FLAG, "false").lower() in ("1", "true", "yes")


def disabled_response() -> dict:
    return {
        "status":       "DISABLED",
        "feature_flag": _FLAG,
        "advisory_only": True,
        "available":    False,
    }


# ── Event types ───────────────────────────────────────────────────────────────

TYPE_CORPORATE   = "CORPORATE"
TYPE_REGULATORY  = "REGULATORY"
TYPE_NEWS        = "NEWS"

# Corporate sub-types
CORP_RESULTS      = "RESULTS"
CORP_DIVIDEND     = "DIVIDEND"
CORP_SPLIT        = "SPLIT"
CORP_BONUS        = "BONUS"
CORP_BUYBACK      = "BUYBACK"
CORP_BOARD        = "BOARD_MEETING"
CORP_RIGHTS       = "RIGHTS"
CORP_BULK_DEAL    = "BULK_DEAL"
CORP_BLOCK_DEAL   = "BLOCK_DEAL"
CORP_MGMT         = "MANAGEMENT_GUIDANCE"
CORP_PROMOTER     = "PROMOTER_HOLDING"

# Regulatory sub-types
REG_ASM           = "ASM"
REG_GSM           = "GSM"
REG_FO_BAN        = "FO_BAN"
REG_NSE           = "NSE_CIRCULAR"
REG_BSE           = "BSE_CIRCULAR"
REG_SEBI          = "SEBI_CIRCULAR"
REG_SUSPENSION    = "SUSPENSION"
REG_MARGIN        = "MARGIN_CHANGE"
REG_INDEX_IN      = "INDEX_INCLUSION"
REG_INDEX_OUT     = "INDEX_EXCLUSION"
REG_COMPLIANCE    = "COMPLIANCE_NOTICE"

# News sub-types
NEWS_COMPANY      = "COMPANY_NEWS"
NEWS_SECTOR       = "SECTOR_NEWS"
NEWS_MARKET       = "MARKET_NEWS"
NEWS_GLOBAL       = "GLOBAL_NEWS"
NEWS_BREAKING     = "BREAKING_NEWS"
NEWS_ECONOMIC     = "ECONOMIC_HEADLINE"

# Impact direction
IMPACT_BULLISH    = "BULLISH"
IMPACT_BEARISH    = "BEARISH"
IMPACT_NEUTRAL    = "NEUTRAL"
IMPACT_VOLATILE   = "VOLATILE"

# Priority
PRIORITY_CRITICAL = "CRITICAL"
PRIORITY_HIGH     = "HIGH"
PRIORITY_MEDIUM   = "MEDIUM"
PRIORITY_LOW      = "LOW"


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class EventRecord:
    event_id:           str
    event_type:         str          # CORPORATE / REGULATORY / NEWS
    sub_type:           str
    title:              str
    description:        str
    symbol:             Optional[str]    = None
    sector:             Optional[str]    = None
    event_date:         Optional[str]    = None   # ISO date YYYY-MM-DD
    discovered_at:      Optional[str]    = None   # ISO datetime
    importance_score:   float           = 50.0    # 0-100
    confidence_score:   float           = 50.0    # 0-100
    impact_direction:   str             = IMPACT_NEUTRAL
    expected_volatility: float          = 0.0     # expected % move
    expected_duration:  str             = "1D"
    priority:           str             = PRIORITY_MEDIUM
    affected_stocks:    List[str]       = field(default_factory=list)
    affected_sectors:   List[str]       = field(default_factory=list)
    trading_risk:       Optional[str]   = None
    opportunity:        Optional[str]   = None
    source:             str             = "INTERNAL"
    is_duplicate:       bool            = False

    def to_dict(self) -> dict:
        return {
            "event_id":           self.event_id,
            "event_type":         self.event_type,
            "sub_type":           self.sub_type,
            "title":              self.title,
            "description":        self.description,
            "symbol":             self.symbol,
            "sector":             self.sector,
            "event_date":         self.event_date,
            "discovered_at":      self.discovered_at,
            "importance_score":   round(self.importance_score, 1),
            "confidence_score":   round(self.confidence_score, 1),
            "impact_direction":   self.impact_direction,
            "expected_volatility": round(self.expected_volatility, 2),
            "expected_duration":  self.expected_duration,
            "priority":           self.priority,
            "affected_stocks":    self.affected_stocks,
            "affected_sectors":   self.affected_sectors,
            "trading_risk":       self.trading_risk,
            "opportunity":        self.opportunity,
            "source":             self.source,
        }


# ── Score helpers ─────────────────────────────────────────────────────────────

def event_grade(score: float) -> str:
    if score >= 90: return "A+"
    if score >= 80: return "A"
    if score >= 70: return "B"
    if score >= 55: return "C"
    return "D"


def priority_from_score(score: float) -> str:
    if score >= 80: return PRIORITY_CRITICAL
    if score >= 65: return PRIORITY_HIGH
    if score >= 45: return PRIORITY_MEDIUM
    return PRIORITY_LOW
