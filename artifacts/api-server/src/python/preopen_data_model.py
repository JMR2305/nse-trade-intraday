"""
preopen_data_model.py — Phase 5A Pre-Open Intelligence data models.

PAPER TRADING / ADVISORY ONLY.
Pre-open data cannot generate or execute trades.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, List
import json


# ── Provider state enum ───────────────────────────────────────────────────────

class ProviderState:
    LIVE        = "LIVE"
    DELAYED     = "DELAYED"
    STALE       = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
    PARTIAL     = "PARTIAL"


# ── Classification labels (advisory only) ────────────────────────────────────

class Classification:
    STRONG_GAP_UP      = "STRONG_GAP_UP"
    MODERATE_GAP_UP    = "MODERATE_GAP_UP"
    FLAT_OPEN          = "FLAT_OPEN"
    MODERATE_GAP_DOWN  = "MODERATE_GAP_DOWN"
    STRONG_GAP_DOWN    = "STRONG_GAP_DOWN"
    BUY_IMBALANCE      = "BUY_IMBALANCE"
    SELL_IMBALANCE     = "SELL_IMBALANCE"
    HIGH_PARTICIPATION = "HIGH_PARTICIPATION"
    LOW_LIQUIDITY      = "LOW_LIQUIDITY"
    DATA_INCOMPLETE    = "DATA_INCOMPLETE"
    WATCH_AFTER_OPEN   = "WATCH_AFTER_OPEN"
    AVOID_AT_OPEN      = "AVOID_AT_OPEN"


# ── Core snapshot model ───────────────────────────────────────────────────────

@dataclass
class PreOpenSnapshot:
    """Normalized pre-open market snapshot for one symbol."""
    # Identity
    snapshot_id: str
    trading_date: str                      # YYYY-MM-DD in IST
    timestamp_ist: str                     # ISO timestamp in IST
    symbol: str
    company_name: str
    sector: str

    # Prices (stored as float for JSON-serializability; Decimal used in calcs)
    previous_close: float
    indicative_equilibrium_price: Optional[float] = None
    indicative_open_price: Optional[float] = None
    final_open_price: Optional[float] = None
    price_change: Optional[float] = None
    gap_percent: Optional[float] = None

    # Quantities
    total_buy_quantity: int = 0
    total_sell_quantity: int = 0
    matched_quantity: int = 0
    final_executed_quantity: int = 0
    total_traded_value: float = 0.0

    # Derived metrics
    buy_sell_imbalance: int = 0
    imbalance_percent: float = 0.0
    volume_rank: Optional[int] = None
    gap_rank: Optional[int] = None
    liquidity_score: float = 0.0

    # Classification
    classification: str = Classification.DATA_INCOMPLETE
    opportunity_score: float = 0.0
    factor_scores: dict = field(default_factory=dict)  # individual factor contributions

    # Data quality
    data_source: str = "unknown"
    provider_label: str = "Yahoo Finance (Fallback)"   # human-readable provider name
    data_freshness_seconds: int = 0
    source_status: str = ProviderState.UNAVAILABLE
    is_stale: bool = True
    validation_status: str = "UNVALIDATED"
    raw_payload_reference: Optional[str] = None

    # True when the provider supplied real buy/sell auction quantities.
    # False for Yahoo Finance and Kite (which don't expose the NSE auction book).
    # Downstream code must check this flag before displaying imbalance values.
    order_book_available: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PreOpenSession:
    """One pre-open session (one per trading day)."""
    session_id: str
    trading_date: str
    started_at: str
    status: str = "INITIALISING"   # INITIALISING | COLLECTING | FROZEN | RECONCILED | ERROR
    symbol_count: int = 0
    valid_count: int = 0
    stale_count: int = 0
    provider_status: str = ProviderState.UNAVAILABLE
    frozen_at: Optional[str] = None
    reconciled_at: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WatchlistItem:
    """One ranked item in a pre-open watchlist."""
    rank: int
    symbol: str
    sector: str
    gap_percent: float
    imbalance_percent: float
    executed_quantity: int
    liquidity_score: float
    opportunity_score: float
    classification: str
    risk_flags: List[str] = field(default_factory=list)
    explanation: str = ""
    required_post_open_confirmation: List[str] = field(default_factory=list)
    previous_close: float = 0.0
    indicative_price: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ReconciliationRecord:
    """Post-open reconciliation: indicative vs actual prices."""
    symbol: str
    session_id: str
    trading_date: str
    indicative_equilibrium_price: Optional[float]
    final_pre_open_price: Optional[float]
    actual_open_price: Optional[float]
    price_at_0920: Optional[float]
    price_at_0930: Optional[float]
    indicative_to_open_error: Optional[float]      # abs % error
    opening_continuation: Optional[bool]            # gap held after open
    opening_reversal: Optional[bool]                # gap reversed after open
    watchlist_confirmed: Optional[bool]             # in watchlist AND confirmed
    was_in_watchlist: bool = False
    reconciled_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def decimal_to_float(d: Optional[Decimal]) -> Optional[float]:
    if d is None:
        return None
    return float(d)


def now_ist_str() -> str:
    """Current time as ISO string (UTC for storage, labelled IST for display)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
