"""
position_sizer.py
Position Sizing Engine.

Given ₹5,000 capital (configurable via config.py) and a 1% max-risk rule:

  max_risk_amount = capital × MAX_RISK_PCT   (₹50 on ₹5,000)
  stop_distance   = |entry_price - stop_loss|
  qty_from_risk   = floor(max_risk_amount / stop_distance)
  qty_from_cap    = floor(available_cash × MAX_CAPITAL_PER_TRADE_PCT / entry_price)
  suggested_qty   = min(qty_from_risk, qty_from_cap)

Never exceeds available capital or the per-trade capital cap.
Designed so a single stop-out costs at most 1% of total capital.

Future Zerodha integration: swap available_cash with live margin from broker API.
"""

import math
from typing import TypedDict
from config import MAX_RISK_PCT, MAX_CAPITAL_PER_TRADE_PCT, INITIAL_CAPITAL


# ── TypedDict ─────────────────────────────────────────────────────────────────

class PositionSizing(TypedDict):
    capital:                float   # total capital being managed
    available_cash:         float   # current available cash
    max_risk_amount:        float   # capital × MAX_RISK_PCT (e.g. ₹50)
    stop_distance:          float   # |entry - stop_loss| per share
    stop_distance_pct:      float   # stop_distance / entry × 100
    suggested_quantity:     int     # shares to buy
    position_value:         float   # suggested_quantity × entry_price
    expected_profit:        float   # suggested_quantity × |target - entry|
    max_loss:               float   # suggested_quantity × stop_distance
    rr_ratio:               float   # |target - entry| / stop_distance
    capital_utilization_pct: float  # position_value / available_cash × 100
    feasible:               bool    # can afford at least 1 share
    sizing_note:            str     # human-readable sizing rationale


# ── Core function ─────────────────────────────────────────────────────────────

def compute_position(
    entry_price: float,
    stop_loss: float,
    target: float,
    available_cash: float,
    is_long: bool = True,
    capital: float = INITIAL_CAPITAL,
) -> PositionSizing:
    """
    Compute risk-adjusted position size.

    Args:
        entry_price    : planned entry price
        stop_loss      : stop-loss level
        target         : profit target level
        available_cash : current cash in paper portfolio
        is_long        : True for BUY trade, False for SELL/SHORT
        capital        : total capital under management (for risk % calculation)

    Returns:
        PositionSizing TypedDict with all position details.
    """
    max_risk_amount = round(capital * MAX_RISK_PCT, 2)  # e.g. ₹50

    # ── Stop distance ──────────────────────────────────────────────────────────
    if is_long:
        stop_distance = entry_price - stop_loss
        reward_distance = target - entry_price
    else:
        stop_distance = stop_loss - entry_price
        reward_distance = entry_price - target

    stop_distance = max(stop_distance, 0.0)
    reward_distance = max(reward_distance, 0.0)
    stop_distance_pct = (stop_distance / entry_price * 100) if entry_price > 0 else 0.0
    rr_ratio = round(reward_distance / stop_distance, 2) if stop_distance > 0 else 0.0

    # ── Quantity calculation ───────────────────────────────────────────────────
    if stop_distance <= 0 or entry_price <= 0:
        qty = 0
    else:
        qty_from_risk = math.floor(max_risk_amount / stop_distance)
        qty_from_cap  = math.floor(available_cash * MAX_CAPITAL_PER_TRADE_PCT / entry_price)
        qty = max(0, min(qty_from_risk, qty_from_cap))

    # ── Derived metrics ────────────────────────────────────────────────────────
    position_value   = round(qty * entry_price, 2)
    expected_profit  = round(qty * reward_distance, 2)
    max_loss         = round(qty * stop_distance, 2)
    util_pct         = round(position_value / available_cash * 100, 1) if available_cash > 0 else 0.0
    feasible         = qty > 0

    # ── Sizing note ────────────────────────────────────────────────────────────
    if not feasible:
        if entry_price > available_cash:
            note = f"Cannot afford 1 share @ ₹{entry_price:.0f} — need more capital"
        elif stop_distance <= 0:
            note = "Stop loss must be below entry for a long trade"
        else:
            note = f"1% risk (₹{max_risk_amount:.0f}) too small for stop ₹{stop_distance:.2f}/share"
    elif qty == 1:
        note = f"Minimum viable position — 1 share risking ₹{max_loss:.2f}"
    elif stop_distance < 0.5:
        note = f"{qty} shares, but stop is tight ({stop_distance_pct:.1f}%) — whipsaw risk"
    else:
        note = (
            f"{qty} shares @ ₹{entry_price:.2f} | "
            f"Risk: ₹{max_loss:.2f} ({util_pct:.1f}% of cash) | "
            f"Reward: ₹{expected_profit:.2f}"
        )

    return PositionSizing(
        capital                 = round(capital, 2),
        available_cash          = round(available_cash, 2),
        max_risk_amount         = max_risk_amount,
        stop_distance           = round(stop_distance, 2),
        stop_distance_pct       = round(stop_distance_pct, 2),
        suggested_quantity      = qty,
        position_value          = position_value,
        expected_profit         = expected_profit,
        max_loss                = max_loss,
        rr_ratio                = rr_ratio,
        capital_utilization_pct = util_pct,
        feasible                = feasible,
        sizing_note             = note,
    )


def compute_from_signal(signal: dict, available_cash: float, capital: float = INITIAL_CAPITAL) -> PositionSizing:
    """Convenience wrapper that extracts fields from a Signal dict."""
    entry      = signal.get("price", 0.0)
    stop_loss  = signal.get("stop_loss", 0.0)
    target     = signal.get("target", 0.0)
    sig_type   = signal.get("signal", "NO_TRADE")
    is_long    = sig_type in {"STRONG_BUY", "BUY", "WATCH", "NO_TRADE"}

    return compute_position(
        entry_price    = entry,
        stop_loss      = stop_loss,
        target         = target,
        available_cash = available_cash,
        is_long        = is_long,
        capital        = capital,
    )
