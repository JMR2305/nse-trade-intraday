"""
paper_analytics/models.py — Phase 8.2
Dataclasses, enums, grade/trend helpers, and feature-flag for the
Advanced Paper Trading Analytics module.

READ-ONLY. ADVISORY-ONLY.
This module NEVER places orders, modifies paper trades, strategies,
portfolio, risk parameters, or AI models.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# ── Feature flag ──────────────────────────────────────────────────────────────
_FLAG = "PAPER_ANALYTICS_ENABLED"


def is_enabled() -> bool:
    return os.environ.get(_FLAG, "false").lower() in ("1", "true", "yes")


def disabled_response() -> dict:
    return {
        "status":        "DISABLED",
        "available":     False,
        "advisory_only": True,
        "message":       f"Set {_FLAG}=true to enable Paper Analytics.",
    }


# ── Grade helpers ─────────────────────────────────────────────────────────────

def analytics_grade(score: float) -> str:
    """A+ / A / B / C / D grading from 0–100 score."""
    if score >= 92: return "A+"
    if score >= 80: return "A"
    if score >= 68: return "B"
    if score >= 50: return "C"
    return "D"


def trend_label(current: float, previous: float, margin: float = 2.0) -> str:
    if current > previous + margin: return "IMPROVING"
    if current < previous - margin: return "DECLINING"
    return "STABLE"


# ── Status constants ──────────────────────────────────────────────────────────
STATUS_ENABLED  = "ENABLED"
STATUS_DISABLED = "DISABLED"
STATUS_ERROR    = "ERROR"

ADVISORY_LABEL = "PAPER TRADING / ADVISORY ONLY"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Snapshot dataclass (for Executive Dashboard integration) ──────────────────

@dataclass
class PaperAnalyticsSnapshot:
    """Flat KPI dict consumed by the Executive Dashboard and future phases."""
    total_trades:       int   = 0
    win_rate:           float = 0.0
    profit_factor:      float = 0.0
    expectancy:         float = 0.0
    total_pnl:          float = 0.0
    max_drawdown:       float = 0.0
    sharpe_ratio:       float = 0.0
    best_strategy:      str   = "N/A"
    best_sector:        str   = "N/A"
    avg_hold_seconds:   float = 0.0
    analytics_score:    float = 0.0
    grade:              str   = "N/A"
    available:          bool  = False
    generated_at:       str   = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return {
            "total_trades":     self.total_trades,
            "win_rate":         self.win_rate,
            "profit_factor":    self.profit_factor,
            "expectancy":       self.expectancy,
            "total_pnl":        self.total_pnl,
            "max_drawdown":     self.max_drawdown,
            "sharpe_ratio":     self.sharpe_ratio,
            "best_strategy":    self.best_strategy,
            "best_sector":      self.best_sector,
            "avg_hold_seconds": self.avg_hold_seconds,
            "analytics_score":  self.analytics_score,
            "grade":            self.grade,
            "available":        self.available,
            "generated_at":     self.generated_at,
            "advisory_only":    True,
        }
