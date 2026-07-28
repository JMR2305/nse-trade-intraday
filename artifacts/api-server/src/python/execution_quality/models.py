"""
execution_quality/models.py — Phase 5D.1 data models.

PAPER TRADING / ADVISORY ONLY.
No order submission, no broker call, no strategy modification.
"""
from __future__ import annotations

import os as _os
from dataclasses import dataclass
from typing import Optional

_ENABLED_VAR = "EXECUTION_QUALITY_ENABLED"


def is_enabled() -> bool:
    return _os.environ.get(_ENABLED_VAR, "false").lower() in ("1", "true", "yes")


def disabled_response() -> dict:
    return {
        "status":       "DISABLED",
        "feature_flag": _ENABLED_VAR,
        "message":      f"Set {_ENABLED_VAR}=true to enable Phase 5D.1 execution quality analytics.",
        "label":        "PAPER TRADING / ADVISORY ONLY",
    }


@dataclass
class ExecutionRecord:
    """Per-trade execution quality record (read-only, derived from paper trades)."""

    trade_id:   str = ""
    symbol:     str = ""
    strategy_id:   str = ""
    strategy_name: str = ""
    sector:  str = ""
    regime:  str = ""

    # ── Entry ────────────────────────────────────────────────────────────────
    signal_ts:             Optional[str] = None
    entry_ts:              Optional[str] = None
    intended_entry_price:  float = 0.0
    actual_entry_price:    float = 0.0
    entry_slippage_rs:     float = 0.0   # ₹
    entry_slippage_pct:    float = 0.0   # %
    fill_delay_seconds:    float = 0.0

    # ── Exit ─────────────────────────────────────────────────────────────────
    exit_ts:               Optional[str] = None
    intended_exit_price:   float = 0.0
    actual_exit_price:     float = 0.0
    exit_slippage_rs:      float = 0.0
    exit_slippage_pct:     float = 0.0
    exit_delay_seconds:    float = 0.0
    exit_type:             str   = ""

    # ── Position ─────────────────────────────────────────────────────────────
    quantity:    int   = 0
    entry_total: float = 0.0
    pnl:         float = 0.0
    pnl_pct:     float = 0.0

    # ── Execution meta (from BUY trade) ──────────────────────────────────────
    stop_loss_set: bool  = False
    target_set:    bool  = False
    stop_loss:     float = 0.0
    target:        float = 0.0

    # ── Quality ──────────────────────────────────────────────────────────────
    quality_score: int = 0
    quality_grade: str = ""
    is_complete:   bool = False   # True = BUY + SELL round-trip present

    def to_dict(self) -> dict:
        return {
            "trade_id":             self.trade_id,
            "symbol":               self.symbol,
            "strategy_id":          self.strategy_id,
            "strategy_name":        self.strategy_name,
            "sector":               self.sector,
            "regime":               self.regime,
            "signal_ts":            self.signal_ts,
            "entry_ts":             self.entry_ts,
            "intended_entry_price": round(self.intended_entry_price, 2),
            "actual_entry_price":   round(self.actual_entry_price, 2),
            "entry_slippage_rs":    round(self.entry_slippage_rs, 2),
            "entry_slippage_pct":   round(self.entry_slippage_pct, 4),
            "fill_delay_seconds":   round(self.fill_delay_seconds, 1),
            "exit_ts":              self.exit_ts,
            "intended_exit_price":  round(self.intended_exit_price, 2),
            "actual_exit_price":    round(self.actual_exit_price, 2),
            "exit_slippage_rs":     round(self.exit_slippage_rs, 2),
            "exit_slippage_pct":    round(self.exit_slippage_pct, 4),
            "exit_delay_seconds":   round(self.exit_delay_seconds, 1),
            "exit_type":            self.exit_type,
            "quantity":             self.quantity,
            "entry_total":          round(self.entry_total, 2),
            "pnl":                  round(self.pnl, 2),
            "pnl_pct":              round(self.pnl_pct, 2),
            "stop_loss_set":        self.stop_loss_set,
            "target_set":           self.target_set,
            "stop_loss":            round(self.stop_loss, 2),
            "target":               round(self.target, 2),
            "quality_score":        self.quality_score,
            "quality_grade":        self.quality_grade,
            "is_complete":          self.is_complete,
        }
