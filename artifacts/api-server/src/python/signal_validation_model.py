"""
signal_validation_model.py — Phase 5C data model.

SignalValidationRecord: 41 fields tracking a signal from creation to final outcome.
LifecycleState: 15 states with explicit transitions.
OutcomeClass: 18 outcome classifications.
MissedReason: 14 missed-opportunity reasons.

Uses Decimal for all prices, P&L, and financial calculations.

PAPER TRADING / ADVISORY ONLY.
No order submission, no broker call, no strategy modification.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta

_IST = timezone(timedelta(hours=5, minutes=30))


# ── Feature flag ───────────────────────────────────────────────────────────────

import os as _os

_ENABLED_VAR = "SIGNAL_VALIDATION_ENABLED"

def is_enabled() -> bool:
    return _os.environ.get(_ENABLED_VAR, "false").lower() in ("1", "true", "yes")


# ── Lifecycle states ───────────────────────────────────────────────────────────

class LifecycleState:
    GENERATED           = "GENERATED"
    AI_REVIEWED         = "AI_REVIEWED"
    RISK_REVIEWED       = "RISK_REVIEWED"
    RISK_REJECTED       = "RISK_REJECTED"
    APPROVED            = "APPROVED"
    PAPER_ORDER_CREATED = "PAPER_ORDER_CREATED"
    PAPER_ORDER_FILLED  = "PAPER_ORDER_FILLED"
    OPEN_POSITION       = "OPEN_POSITION"
    CLOSED_POSITION     = "CLOSED_POSITION"
    EXPIRED             = "EXPIRED"
    CANCELLED           = "CANCELLED"
    MISSED              = "MISSED"
    INVALID_DATA        = "INVALID_DATA"
    STALE_DATA          = "STALE_DATA"
    NO_TRADE            = "NO_TRADE"

    ALL = {
        GENERATED, AI_REVIEWED, RISK_REVIEWED, RISK_REJECTED, APPROVED,
        PAPER_ORDER_CREATED, PAPER_ORDER_FILLED, OPEN_POSITION, CLOSED_POSITION,
        EXPIRED, CANCELLED, MISSED, INVALID_DATA, STALE_DATA, NO_TRADE,
    }

    # Valid forward transitions
    TRANSITIONS: Dict[str, List[str]] = {
        GENERATED:           [AI_REVIEWED, RISK_REVIEWED, EXPIRED, INVALID_DATA, STALE_DATA],
        AI_REVIEWED:         [RISK_REVIEWED, EXPIRED, INVALID_DATA],
        RISK_REVIEWED:       [RISK_REJECTED, APPROVED, EXPIRED, INVALID_DATA],
        RISK_REJECTED:       [MISSED],
        APPROVED:            [PAPER_ORDER_CREATED, EXPIRED, MISSED, NO_TRADE],
        PAPER_ORDER_CREATED: [PAPER_ORDER_FILLED, CANCELLED, EXPIRED],
        PAPER_ORDER_FILLED:  [OPEN_POSITION, CLOSED_POSITION],  # CLOSED_POSITION for direct EOD close
        OPEN_POSITION:       [CLOSED_POSITION, EXPIRED],
        CLOSED_POSITION:     [],   # terminal
        EXPIRED:             [],   # terminal
        CANCELLED:           [],   # terminal
        MISSED:              [],   # terminal
        INVALID_DATA:        [],   # terminal
        STALE_DATA:          [],   # terminal
        NO_TRADE:            [],   # terminal
    }

    @classmethod
    def is_valid_transition(cls, from_state: str, to_state: str) -> bool:
        return to_state in cls.TRANSITIONS.get(from_state, [])

    @classmethod
    def is_terminal(cls, state: str) -> bool:
        return not cls.TRANSITIONS.get(state)


# ── Outcome classifications ────────────────────────────────────────────────────

class OutcomeClass:
    STRONG_SUCCESS                  = "STRONG_SUCCESS"
    MODERATE_SUCCESS                = "MODERATE_SUCCESS"
    SMALL_SUCCESS                   = "SMALL_SUCCESS"
    FLAT                            = "FLAT"
    SMALL_FAILURE                   = "SMALL_FAILURE"
    MODERATE_FAILURE                = "MODERATE_FAILURE"
    STRONG_FAILURE                  = "STRONG_FAILURE"
    STOPPED_OUT                     = "STOPPED_OUT"
    TARGET_REACHED                  = "TARGET_REACHED"
    TIME_EXIT                       = "TIME_EXIT"
    RISK_REJECTED_VALIDLY           = "RISK_REJECTED_VALIDLY"
    RISK_REJECTED_BUT_SIGNAL_SUCCEEDED = "RISK_REJECTED_BUT_SIGNAL_SUCCEEDED"
    SIGNAL_EXPIRED                  = "SIGNAL_EXPIRED"
    FALSE_BREAKOUT                  = "FALSE_BREAKOUT"
    EARLY_REVERSAL                  = "EARLY_REVERSAL"
    LATE_REVERSAL                   = "LATE_REVERSAL"
    DATA_INCOMPLETE                 = "DATA_INCOMPLETE"
    INVALID_SIGNAL                  = "INVALID_SIGNAL"

    ALL = {
        STRONG_SUCCESS, MODERATE_SUCCESS, SMALL_SUCCESS, FLAT,
        SMALL_FAILURE, MODERATE_FAILURE, STRONG_FAILURE,
        STOPPED_OUT, TARGET_REACHED, TIME_EXIT,
        RISK_REJECTED_VALIDLY, RISK_REJECTED_BUT_SIGNAL_SUCCEEDED,
        SIGNAL_EXPIRED, FALSE_BREAKOUT, EARLY_REVERSAL, LATE_REVERSAL,
        DATA_INCOMPLETE, INVALID_SIGNAL,
    }


# ── Missed-opportunity reasons ─────────────────────────────────────────────────

class MissedReason:
    RISK_REJECTION         = "risk_rejection"
    STALE_DATA             = "stale_data"
    DUPLICATE_PROTECTION   = "duplicate_protection"
    INSUFFICIENT_CONFIDENCE = "insufficient_confidence"
    LOW_LIQUIDITY          = "low_liquidity"
    SECTOR_LIMIT           = "sector_limit"
    CAPITAL_LIMIT          = "capital_limit"
    POSITION_LIMIT         = "position_limit"
    ENTRY_WINDOW_CLOSED    = "entry_window_closed"
    NO_POST_OPEN_CONFIRMATION = "no_post_open_confirmation"
    STRATEGY_CONFLICT      = "strategy_conflict"
    OPERATOR_DECISION      = "operator_decision"
    SYSTEM_FAILURE         = "system_failure"
    PROVIDER_FAILURE       = "provider_failure"
    UNKNOWN                = "unknown"


# ── Lifecycle event ────────────────────────────────────────────────────────────

@dataclass
class LifecycleEvent:
    validation_id:    str
    event_id:         str
    from_state:       str
    to_state:         str
    timestamp_ist:    str
    reason:           str
    source_component: str
    correlation_id:   str
    metadata:         Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "validation_id":    self.validation_id,
            "event_id":         self.event_id,
            "from_state":       self.from_state,
            "to_state":         self.to_state,
            "timestamp_ist":    self.timestamp_ist,
            "reason":           self.reason,
            "source_component": self.source_component,
            "correlation_id":   self.correlation_id,
            "metadata":         self.metadata,
        }


# ── Price checkpoint ───────────────────────────────────────────────────────────

@dataclass
class PriceCheckpoint:
    validation_id:   str
    checkpoint_type: str   # "5m", "15m", "30m", "60m", "entry", "stop", "target", "exit", "close", "eod"
    price:           Optional[Decimal]
    timestamp_ist:   str
    source:          str   # "yfinance" | "live_quote" | "paper_trade"
    is_hypothetical: bool  = False
    return_pct:      Optional[Decimal] = None

    def to_dict(self) -> dict:
        return {
            "validation_id":   self.validation_id,
            "checkpoint_type": self.checkpoint_type,
            "price":           str(self.price) if self.price is not None else None,
            "timestamp_ist":   self.timestamp_ist,
            "source":          self.source,
            "is_hypothetical": self.is_hypothetical,
            "return_pct":      str(self.return_pct) if self.return_pct is not None else None,
        }


# ── Main record ───────────────────────────────────────────────────────────────

def _dec(v) -> Optional[Decimal]:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError):
        return None


# ── DB column name ↔ model field name translation (module-level) ──────────────
# These must live outside the dataclass (mutable dicts cannot be dataclass attrs).
_MODEL_TO_DB: Dict[str, str] = {
    "AI_recommendation":         "ai_recommendation",
    "AI_confidence":             "ai_confidence",
    "AI_agreement":              "ai_agreement",
    "AI_explanation_latency_ms": "ai_explanation_latency_ms",
    "India_VIX_value":           "india_vix_value",
    "R_multiple":                "r_multiple",
    "VWAP":                      "vwap",
    "ATR":                       "atr",
}
_DB_TO_MODEL: Dict[str, str] = {v: k for k, v in _MODEL_TO_DB.items()}


@dataclass
class SignalValidationRecord:
    # Identity
    validation_id:            str = ""
    trading_date:             str = ""
    signal_id:                str = ""
    session_id:               Optional[str] = None
    audit_id:                 Optional[str] = None
    journal_id:               Optional[str] = None

    # Strategy
    strategy_id:              str = ""
    strategy_name:            str = ""
    strategy_version:         str = ""

    # Instrument
    symbol:                   str = ""
    sector:                   str = ""
    exchange:                 str = "NSE"

    # Signal
    signal_direction:         str = ""          # BUY | SELL | WATCH | NO_TRADE
    signal_type:              str = ""          # STRONG_BUY | BUY | WATCH | etc.
    signal_timestamp_ist:     str = ""
    signal_price:             Optional[Decimal] = None
    signal_strength:          Optional[Decimal] = None
    deterministic_score:      Optional[Decimal] = None

    # AI
    AI_recommendation:        Optional[str]     = None
    AI_confidence:            Optional[Decimal] = None
    AI_agreement:             Optional[str]     = None  # AGREE | DISAGREE | WATCH | NONE
    AI_explanation_latency_ms: Optional[int]    = None

    # Pre-open context
    preopen_rank:             Optional[int]     = None
    preopen_opportunity_score: Optional[Decimal] = None
    preopen_classification:   Optional[str]     = None

    # Market context
    market_regime:            Optional[str]     = None
    index_direction:          Optional[str]     = None
    sector_direction:         Optional[str]     = None
    India_VIX_value:          Optional[Decimal] = None

    # Market microstructure
    volume:                   Optional[int]     = None
    relative_volume:          Optional[Decimal] = None
    VWAP:                     Optional[Decimal] = None
    ATR:                      Optional[Decimal] = None
    spread:                   Optional[Decimal] = None
    liquidity_score:          Optional[Decimal] = None
    data_age_seconds:         Optional[int]     = None
    data_quality_status:      str               = "UNKNOWN"

    # Risk decision
    risk_decision:            str               = ""
    risk_rejection_reason:    Optional[str]     = None
    proposed_position_size:   Optional[int]     = None
    approved_position_size:   Optional[int]     = None

    # Paper trade
    paper_order_created:      bool              = False
    paper_order_id:           Optional[str]     = None
    entry_price:              Optional[Decimal] = None
    entry_timestamp:          Optional[str]     = None
    stop_loss:                Optional[Decimal] = None
    target_price:             Optional[Decimal] = None
    exit_price:               Optional[Decimal] = None
    exit_timestamp:           Optional[str]     = None
    exit_reason:              Optional[str]     = None

    # P&L
    realised_pnl:             Optional[Decimal] = None
    unrealised_pnl:           Optional[Decimal] = None
    R_multiple:               Optional[Decimal] = None
    max_favourable_excursion: Optional[Decimal] = None
    max_adverse_excursion:    Optional[Decimal] = None

    # Price checkpoints
    price_5m:                 Optional[Decimal] = None
    price_15m:                Optional[Decimal] = None
    price_30m:                Optional[Decimal] = None
    price_60m:                Optional[Decimal] = None
    end_of_day_price:         Optional[Decimal] = None

    # Classification
    outcome_class:            Optional[str]     = None
    validation_status:        str               = LifecycleState.GENERATED
    missed_reason:            Optional[str]     = None

    # Meta
    created_at:               str               = ""
    updated_at:               str               = ""

    # Hypothetical (missed/rejected signals)
    is_hypothetical:          bool              = False
    hypothetical_label:       str               = ""  # "HYPOTHETICAL — NOT A TRADE"
    hyp_return_5m:            Optional[Decimal] = None
    hyp_return_15m:           Optional[Decimal] = None
    hyp_return_30m:           Optional[Decimal] = None
    hyp_return_60m:           Optional[Decimal] = None
    hyp_mfe:                  Optional[Decimal] = None
    hyp_mae:                  Optional[Decimal] = None
    hyp_rejection_justified:  Optional[bool]    = None

    def to_dict(self) -> dict:
        """Human-readable dict using model field names. Does NOT use DB keys."""
        d = {}
        for k, v in self.__dict__.items():
            if k.startswith("_"):
                continue
            if isinstance(v, Decimal):
                d[k] = str(v)
            else:
                d[k] = v
        return d

    def to_db_dict(self) -> dict:
        """Dict with DB snake_case column names for all SQL operations."""
        d = {}
        for k, v in self.__dict__.items():
            if k.startswith("_"):
                continue
            db_key = _MODEL_TO_DB.get(k, k)
            if isinstance(v, Decimal):
                d[db_key] = str(v)
            else:
                d[db_key] = v
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "SignalValidationRecord":
        """
        Accept either model field names or DB snake_case column names.
        DB rows use snake_case; in-memory dicts may use model field names.
        Both are handled transparently.
        """
        r = cls()
        # Normalize incoming keys: DB snake_case → model field name
        normalized: dict = {}
        for k, v in data.items():
            model_key = _DB_TO_MODEL.get(k, k)
            normalized[model_key] = v

        # Decimal fields (use model field names after normalization)
        decimal_fields = {
            "signal_price", "signal_strength", "deterministic_score",
            "AI_confidence", "preopen_opportunity_score", "India_VIX_value",
            "relative_volume", "VWAP", "ATR", "spread", "liquidity_score",
            "entry_price", "stop_loss", "target_price", "exit_price",
            "realised_pnl", "unrealised_pnl", "R_multiple",
            "max_favourable_excursion", "max_adverse_excursion",
            "price_5m", "price_15m", "price_30m", "price_60m", "end_of_day_price",
            "hyp_return_5m", "hyp_return_15m", "hyp_return_30m", "hyp_return_60m",
            "hyp_mfe", "hyp_mae",
        }
        int_fields = {
            "volume", "data_age_seconds", "proposed_position_size",
            "approved_position_size", "preopen_rank", "AI_explanation_latency_ms",
        }
        bool_fields = {"paper_order_created", "is_hypothetical", "hyp_rejection_justified"}

        for k, v in normalized.items():
            if not hasattr(r, k):
                continue
            if k in decimal_fields:
                setattr(r, k, _dec(v))
            elif k in bool_fields:
                if v is not None:
                    setattr(r, k, bool(v))
            elif k in int_fields:
                if v is not None:
                    try:
                        setattr(r, k, int(v))
                    except (TypeError, ValueError):
                        pass
            else:
                setattr(r, k, v)
        return r

    def compute_r_multiple(self) -> Optional[Decimal]:
        """R = (exit - entry) / (entry - stop_loss) for long; inverted for short."""
        if None in (self.entry_price, self.exit_price, self.stop_loss):
            return None
        risk = self.entry_price - self.stop_loss
        if risk == 0:
            return None
        if self.signal_direction in ("BUY", "STRONG_BUY"):
            return (self.exit_price - self.entry_price) / abs(risk)
        else:
            return (self.entry_price - self.exit_price) / abs(risk)

    def compute_realised_pnl(self) -> Optional[Decimal]:
        if None in (self.entry_price, self.exit_price, self.approved_position_size):
            return None
        direction = 1 if self.signal_direction in ("BUY", "STRONG_BUY") else -1
        return (self.exit_price - self.entry_price) * Decimal(self.approved_position_size) * direction

    def ist_now(self) -> str:
        from datetime import datetime
        return datetime.now(_IST).isoformat()
