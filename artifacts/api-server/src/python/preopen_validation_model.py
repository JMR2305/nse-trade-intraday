"""
preopen_validation_model.py — Phase 5B Pre-Open Prediction Validation data models.

PAPER TRADING / ADVISORY ONLY.
No order, execution, or trade-placement function exists in this module.
Pre-open validation data CANNOT submit orders or affect the risk engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, List
import uuid


# ── Outcome classification enum ───────────────────────────────────────────────

class OutcomeClass:
    """Post-open outcome classifications. Advisory labels only."""
    STRONG_CONTINUATION  = "STRONG_CONTINUATION"    # ≥1% return at 09:30 with low MAE
    MODERATE_CONTINUATION = "MODERATE_CONTINUATION"  # positive return at 09:30, below strong
    FLAT                 = "FLAT"                    # return within ±0.25% at 09:30
    EARLY_REVERSAL       = "EARLY_REVERSAL"          # reversal within first 15 min
    LATE_REVERSAL        = "LATE_REVERSAL"           # reversal between 09:30 and 10:30
    FALSE_BREAKOUT       = "FALSE_BREAKOUT"          # gap-up but closes flat or negative
    NO_LIQUIDITY         = "NO_LIQUIDITY"            # insufficient traded volume post-open
    DATA_INCOMPLETE      = "DATA_INCOMPLETE"         # missing required price checkpoints
    INVALID_SIGNAL       = "INVALID_SIGNAL"          # pre-open data was stale/corrupt


class DataQualityStatus:
    COMPLETE   = "COMPLETE"      # all price checkpoints present
    PARTIAL    = "PARTIAL"       # some checkpoints missing (still usable)
    STALE      = "STALE"         # pre-open snapshot was stale
    MISSING    = "MISSING"       # essential prices absent — excluded from metrics
    HOLIDAY    = "HOLIDAY"       # NSE holiday — session skipped
    INVALID    = "INVALID"       # corrupt / out-of-range data


class ValidationStatus:
    PENDING    = "PENDING"       # created, awaiting price collection
    PARTIAL    = "PARTIAL"       # some checkpoints collected
    COMPLETE   = "COMPLETE"      # all checkpoints and classification done
    EXCLUDED   = "EXCLUDED"      # excluded from accuracy metrics (data quality)
    ERROR      = "ERROR"


# ── Core validation record ────────────────────────────────────────────────────

@dataclass
class ValidationRecord:
    """
    One post-open validation record per pre-open candidate.
    All 42 fields from the Phase 5B spec.
    Prices stored as Optional[float] for JSON-serializability.
    """
    # Identity
    validation_id: str = field(default_factory=lambda: f"val-{uuid.uuid4().hex[:12]}")
    trading_date: str = ""
    session_id: str = ""
    symbol: str = ""
    sector: str = ""

    # Pre-open metadata
    preopen_rank: Optional[int] = None
    opportunity_score: float = 0.0
    classification: str = ""          # Phase 5A classification label

    # Pre-open prices
    previous_close: Optional[float] = None
    indicative_price: Optional[float] = None
    final_preopen_price: Optional[float] = None

    # Post-open price checkpoints
    actual_open: Optional[float] = None
    price_0920: Optional[float] = None
    price_0930: Optional[float] = None
    price_1000: Optional[float] = None
    price_1030: Optional[float] = None
    intraday_high: Optional[float] = None
    intraday_low: Optional[float] = None
    closing_price: Optional[float] = None

    # Pre-open quantities
    buy_quantity: int = 0
    sell_quantity: int = 0
    imbalance_percent: float = 0.0
    executed_quantity: int = 0

    # Phase 5A factor scores
    liquidity_score: float = 0.0
    sector_score: float = 0.0
    index_context: Optional[float] = None    # NIFTY gap %
    vix_context: Optional[float] = None      # India VIX
    gap_percent: Optional[float] = None

    # Calculated returns (vs actual_open)
    open_error_percent: Optional[float] = None    # |indicative - actual| / actual × 100
    return_0920: Optional[float] = None
    return_0930: Optional[float] = None
    return_1000: Optional[float] = None
    return_1030: Optional[float] = None
    max_favourable_excursion: Optional[float] = None
    max_adverse_excursion: Optional[float] = None
    closing_return: Optional[float] = None

    # Outcome flags
    continuation_flag: bool = False
    reversal_flag: bool = False
    prediction_result: str = OutcomeClass.DATA_INCOMPLETE

    # Quality
    validation_status: str = ValidationStatus.PENDING
    data_quality_status: str = DataQualityStatus.MISSING

    # Timestamps
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    def to_dict(self) -> dict:
        return asdict(self)

    def update_returns(self) -> None:
        """Recalculate return fields from stored prices."""
        base = self.actual_open
        if base is None or base <= 0:
            return
        if self.indicative_price is not None:
            self.open_error_percent = round(abs(self.indicative_price - base) / base * 100, 4)
        if self.price_0920 is not None:
            self.return_0920 = round((self.price_0920 - base) / base * 100, 4)
        if self.price_0930 is not None:
            self.return_0930 = round((self.price_0930 - base) / base * 100, 4)
        if self.price_1000 is not None:
            self.return_1000 = round((self.price_1000 - base) / base * 100, 4)
        if self.price_1030 is not None:
            self.return_1030 = round((self.price_1030 - base) / base * 100, 4)
        if self.closing_price is not None:
            self.closing_return = round((self.closing_price - base) / base * 100, 4)
        # MFE / MAE (vs open)
        prices = [p for p in [self.price_0920, self.price_0930, self.price_1000,
                               self.price_1030, self.intraday_high, self.intraday_low,
                               self.closing_price] if p is not None]
        if prices:
            high = max(prices)
            low = min(prices)
            if self.gap_percent is not None and self.gap_percent >= 0:
                self.max_favourable_excursion = round((high - base) / base * 100, 4)
                self.max_adverse_excursion = round((low - base) / base * 100, 4)
            else:
                self.max_favourable_excursion = round((base - low) / base * 100, 4)
                self.max_adverse_excursion = round((high - base) / base * 100, 4)
        self.updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Session-level validation record ──────────────────────────────────────────

@dataclass
class ValidationSession:
    """Aggregated validation state for one trading day."""
    session_id: str
    trading_date: str
    phase5a_session_id: Optional[str] = None
    status: str = ValidationStatus.PENDING
    total_candidates: int = 0
    valid_candidates: int = 0
    excluded_candidates: int = 0
    classified_candidates: int = 0
    data_quality_pct: float = 0.0
    metrics_computed: bool = False
    daily_report_path: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    def to_dict(self) -> dict:
        return asdict(self)


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
