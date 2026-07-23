"""Domain models for the Market Intelligence Layer.

All types are frozen Pydantic models — immutable snapshots safe to share
across coroutines.  This module has NO external dependencies beyond the
standard library and Pydantic.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class MarketRegime(str, Enum):
    UNKNOWN = "UNKNOWN"
    RANGING = "RANGING"
    UPTREND = "UPTREND"
    DOWNTREND = "DOWNTREND"
    STRONG_UPTREND = "STRONG_UPTREND"
    STRONG_DOWNTREND = "STRONG_DOWNTREND"
    EXPANDING_RANGE = "EXPANDING_RANGE"


class MarketRegimeSnapshot(BaseModel, frozen=True):
    """Frozen regime classification for one instrument at one point in time."""

    model_config = ConfigDict(frozen=True)

    instrument_token: str
    regime: MarketRegime
    confidence: Decimal  # clamped to [0, 1]
    detected_at: datetime


class AnnouncementRecord(BaseModel, frozen=True):
    """Frozen representation of one classified corporate announcement."""

    model_config = ConfigDict(frozen=True)

    announcement_id: str
    instrument_token: str
    exchange: str
    tradingsymbol: str
    classification: str
    headline: str
    body_text: Optional[str] = None
    ai_summary: Optional[str] = None
    model_version: Optional[str] = None
    published_at: datetime
    effective_date: Optional[date] = None
    raw_metadata: Dict[str, Any] = Field(default_factory=dict)


class InstrumentScore(BaseModel, frozen=True):
    """Composite opportunity score for one instrument."""

    model_config = ConfigDict(frozen=True)

    instrument_token: str
    composite_score: Decimal  # [0, 1]
    computed_at: datetime
    factor_scores: Dict[str, Decimal] = Field(default_factory=dict)
    rank: int = 0  # assigned by WatchlistRanker.rank()


class WatchlistRankingSnapshot(BaseModel, frozen=True):
    """Ranked list of instruments by opportunity quality."""

    model_config = ConfigDict(frozen=True)

    scores: List[InstrumentScore] = Field(default_factory=list)
    computed_at: datetime = Field(default_factory=datetime.utcnow)


class StrategyScore(BaseModel, frozen=True):
    """Strategy alignment score with current market conditions."""

    model_config = ConfigDict(frozen=True)

    strategy_id: str = ""
    score: Decimal  # [0, 1]
    regime_alignment: Decimal  # [0, 1]
    instrument_suitability: Decimal  # [0, 1]
    computed_at: datetime = Field(default_factory=datetime.utcnow)


class MultiTimeframeContext(BaseModel, frozen=True):
    """Full per-instrument intelligence snapshot injected into StrategyContext."""

    model_config = ConfigDict(frozen=True)

    instrument_token: str
    snapshot_timestamp: datetime
    timeframes: Dict[str, Dict[str, Decimal]] = Field(default_factory=dict)
    regime: Optional[MarketRegimeSnapshot] = None
    active_announcements: List[AnnouncementRecord] = Field(default_factory=list)
    watchlist_rank: Optional[int] = None
    composite_score: Optional[Decimal] = None
