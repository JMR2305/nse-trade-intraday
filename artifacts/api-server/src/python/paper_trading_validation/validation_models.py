"""
validation_models.py — Phase 6.1
Data models, feature flag, and constants.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------

def is_enabled() -> bool:
    return os.environ.get("PAPER_VALIDATION_ENABLED", "false").lower() == "true"


def disabled_response() -> dict:
    return {
        "status": "DISABLED",
        "message": "Set PAPER_VALIDATION_ENABLED=true to enable.",
    }


# ---------------------------------------------------------------------------
# Trade record — one per completed paper trade (BUY → SELL matched pair)
# ---------------------------------------------------------------------------

@dataclass
class TradeRecord:
    trade_id: str               # sell record id
    timestamp: str              # ISO8601 exit timestamp
    symbol: str
    strategy: str
    market_regime: str
    sector: str
    entry_price: float
    exit_price: float
    quantity: int
    holding_time_minutes: float
    pnl: float
    pnl_pct: float
    execution_quality_score: Optional[float]
    ai_confidence: Optional[float]
    ai_recommendation: Optional[str]
    signal_validation_status: Optional[str]
    risk_score: Optional[float]
    portfolio_value_at_entry: Optional[float]
    executive_score_snapshot: Optional[float]
    exit_reason: str            # Target / Stop Loss / Time Exit / Manual / Risk Rule

    def to_dict(self) -> dict:
        return {
            "trade_id": self.trade_id,
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "strategy": self.strategy,
            "market_regime": self.market_regime,
            "sector": self.sector,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "quantity": self.quantity,
            "holding_time_minutes": round(self.holding_time_minutes, 1),
            "pnl": round(self.pnl, 2),
            "pnl_pct": round(self.pnl_pct, 4),
            "execution_quality_score": self.execution_quality_score,
            "ai_confidence": self.ai_confidence,
            "ai_recommendation": self.ai_recommendation,
            "signal_validation_status": self.signal_validation_status,
            "risk_score": self.risk_score,
            "portfolio_value_at_entry": self.portfolio_value_at_entry,
            "executive_score_snapshot": self.executive_score_snapshot,
            "exit_reason": self.exit_reason,
        }


# ---------------------------------------------------------------------------
# Session metadata
# ---------------------------------------------------------------------------

@dataclass
class SessionMetadata:
    trading_date: str
    session_start: Optional[str]
    session_end: Optional[str]
    market_status: str
    pre_open_summary: str
    market_breadth: str
    nifty: Optional[float]
    bank_nifty: Optional[float]
    india_vix: Optional[float]
    leading_sector: str
    top_gap: str

    def to_dict(self) -> dict:
        return {
            "trading_date": self.trading_date,
            "session_start": self.session_start,
            "session_end": self.session_end,
            "market_status": self.market_status,
            "pre_open_summary": self.pre_open_summary,
            "market_breadth": self.market_breadth,
            "nifty": self.nifty,
            "bank_nifty": self.bank_nifty,
            "india_vix": self.india_vix,
            "leading_sector": self.leading_sector,
            "top_gap": self.top_gap,
        }


# ---------------------------------------------------------------------------
# Daily metrics
# ---------------------------------------------------------------------------

@dataclass
class DailyMetrics:
    date: str
    trade_count: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    net_pnl: float
    gross_pnl: float
    drawdown: float
    avg_holding_time_minutes: float
    avg_slippage: float
    avg_ai_confidence: float
    avg_execution_score: float
    avg_executive_score: float

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "trade_count": self.trade_count,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": round(self.win_rate, 4),
            "net_pnl": round(self.net_pnl, 2),
            "gross_pnl": round(self.gross_pnl, 2),
            "drawdown": round(self.drawdown, 4),
            "avg_holding_time_minutes": round(self.avg_holding_time_minutes, 1),
            "avg_slippage": round(self.avg_slippage, 4),
            "avg_ai_confidence": round(self.avg_ai_confidence, 4),
            "avg_execution_score": round(self.avg_execution_score, 4),
            "avg_executive_score": round(self.avg_executive_score, 4),
        }


# ---------------------------------------------------------------------------
# Data quality report
# ---------------------------------------------------------------------------

@dataclass
class DataQualityReport:
    total_records: int
    missing_values: List[Dict[str, Any]] = field(default_factory=list)
    duplicate_trades: List[str] = field(default_factory=list)
    invalid_timestamps: List[str] = field(default_factory=list)
    negative_quantities: List[str] = field(default_factory=list)
    impossible_prices: List[str] = field(default_factory=list)
    incomplete_ai_data: List[str] = field(default_factory=list)
    corrupted_records: List[str] = field(default_factory=list)
    quality_score: float = 100.0
    verdict: str = "CLEAN"   # CLEAN / WARNINGS / ISSUES

    def to_dict(self) -> dict:
        total_issues = (
            len(self.missing_values)
            + len(self.duplicate_trades)
            + len(self.invalid_timestamps)
            + len(self.negative_quantities)
            + len(self.impossible_prices)
            + len(self.incomplete_ai_data)
            + len(self.corrupted_records)
        )
        return {
            "total_records": self.total_records,
            "total_issues": total_issues,
            "missing_values": self.missing_values,
            "duplicate_trades": self.duplicate_trades,
            "invalid_timestamps": self.invalid_timestamps,
            "negative_quantities": self.negative_quantities,
            "impossible_prices": self.impossible_prices,
            "incomplete_ai_data": self.incomplete_ai_data,
            "corrupted_records": self.corrupted_records,
            "quality_score": round(self.quality_score, 2),
            "verdict": self.verdict,
        }
