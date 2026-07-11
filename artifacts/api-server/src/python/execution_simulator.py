"""
execution_simulator.py — v2.4 Realistic Execution Simulator.

Simulates how a paper-trade recommendation would actually have filled and
exited on the NSE, with configurable, fully-visible cost assumptions:

  - Entry at next trading-day open (or next candle open)
  - Slippage: 0% / 0.05% / 0.10% / 0.20% (any value accepted)
  - Brokerage (percent + flat), STT, exchange charges, GST, SEBI charges,
    stamp duty, bid/ask spread
  - Gap openings (entry price is the real gapped open, optionally capped)
  - Partial fills (volume-participation limit)
  - Insufficient capital (skip with reason)
  - Position-size rounding to whole shares

Exit simulation supports: stop-loss hit, target hit, signal exit, time exit,
portfolio exit, end-of-test forced close.  When stop AND target are touched
inside the same candle, the CONSERVATIVE rule (stop first) is applied by
default; an OPTIMISTIC alternate (target first) is available for sensitivity
testing.  The selected rule is labelled on every trade.

PAPER TRADING AND RESEARCH ONLY — no real orders are ever placed.
Pure functions; no network access; fully deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any

import math

import pandas as pd

# ── Intrabar rules ───────────────────────────────────────────────────────────

INTRABAR_CONSERVATIVE = "conservative"   # stop assumed to be hit first
INTRABAR_OPTIMISTIC = "optimistic"       # target assumed to be hit first

INTRABAR_RULE_LABELS = {
    INTRABAR_CONSERVATIVE: "Conservative: if stop and target are touched in the same candle, the stop-loss is assumed to trigger first.",
    INTRABAR_OPTIMISTIC: "Optimistic (sensitivity test): if stop and target are touched in the same candle, the target is assumed to trigger first.",
}

# Exit reasons
EXIT_STOP = "Stop-Loss Hit"
EXIT_TARGET = "Target Hit"
EXIT_SIGNAL = "Signal Exit"
EXIT_TIME = "Time Exit"
EXIT_PORTFOLIO = "Portfolio Exit"
EXIT_FORCED = "End-of-Test Forced Close"


# ── Cost model ───────────────────────────────────────────────────────────────

@dataclass
class CostModel:
    """
    All execution-cost assumptions, visible and editable.
    Percentages are expressed in PERCENT (0.05 == 0.05%), matching how the
    UI presents them. Defaults approximate NSE delivery (CNC) trading with a
    discount broker (zero delivery brokerage).
    """
    slippage_pct: float = 0.05          # adverse price movement per side
    spread_pct: float = 0.05            # full bid/ask spread; half paid per side
    brokerage_pct: float = 0.0          # % of turnover per side
    brokerage_flat: float = 0.0         # ₹ flat per executed side
    brokerage_max: float = 20.0         # ₹ cap per side (0 = no cap)
    stt_pct: float = 0.1                # Securities Transaction Tax, per side (delivery)
    exchange_pct: float = 0.00297       # NSE transaction charge, per side
    sebi_pct: float = 0.0001            # SEBI turnover fee (₹10/crore), per side
    stamp_pct: float = 0.015            # stamp duty, BUY side only
    gst_pct: float = 18.0               # GST on (brokerage + exchange + SEBI)
    # Fill realism
    volume_participation_pct: float = 5.0   # max % of candle volume we may take
    allow_partial_fills: bool = True
    max_entry_gap_pct: float = 3.0      # skip entry if open gaps up more than this vs signal close (0 = disabled)
    # Entry timing: "next_day_open" (daily candles) or "next_candle_open"
    entry_timing: str = "next_day_open"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None) -> "CostModel":
        cm = cls()
        if not d:
            return cm
        for k, v in d.items():
            if hasattr(cm, k) and v is not None:
                cur = getattr(cm, k)
                try:
                    setattr(cm, k, type(cur)(v) if not isinstance(cur, bool) else bool(v))
                except (TypeError, ValueError):
                    pass
        return cm


def side_costs(cost_model: CostModel, turnover: float, side: str) -> dict:
    """
    Statutory + brokerage costs for ONE side (buy or sell) on `turnover` ₹.
    Returns a full breakdown so nothing is hidden.
    """
    cm = cost_model
    brokerage = turnover * cm.brokerage_pct / 100.0 + cm.brokerage_flat
    if cm.brokerage_max > 0:
        brokerage = min(brokerage, cm.brokerage_max)
    stt = turnover * cm.stt_pct / 100.0
    exchange = turnover * cm.exchange_pct / 100.0
    sebi = turnover * cm.sebi_pct / 100.0
    stamp = turnover * cm.stamp_pct / 100.0 if side == "buy" else 0.0
    gst = (brokerage + exchange + sebi) * cm.gst_pct / 100.0
    total = brokerage + stt + exchange + sebi + stamp + gst
    return {
        "side": side,
        "turnover": round(turnover, 2),
        "brokerage": round(brokerage, 4),
        "stt": round(stt, 4),
        "exchange": round(exchange, 4),
        "sebi": round(sebi, 4),
        "stamp_duty": round(stamp, 4),
        "gst": round(gst, 4),
        "total": round(total, 4),
    }


def effective_buy_price(cost_model: CostModel, raw_price: float) -> float:
    """Open price worsened by slippage and half the bid/ask spread."""
    return raw_price * (1.0 + (cost_model.slippage_pct + cost_model.spread_pct / 2.0) / 100.0)


def effective_sell_price(cost_model: CostModel, raw_price: float) -> float:
    return raw_price * (1.0 - (cost_model.slippage_pct + cost_model.spread_pct / 2.0) / 100.0)


# ── Entry simulation ─────────────────────────────────────────────────────────

def simulate_entry(
    cost_model: CostModel,
    entry_candle: dict,
    signal_close: float,
    available_cash: float,
    desired_allocation: float,
) -> dict:
    """
    Try to fill a BUY at the next candle's open.

    entry_candle: {"date": str, "open": float, "high": float, "low": float,
                   "close": float, "volume": float}
    signal_close: close price on the signal day (for gap measurement)
    desired_allocation: ₹ the strategy wants to deploy

    Returns {"filled": bool, ...} — when not filled, `skip_reason` explains why.
    """
    raw_open = float(entry_candle.get("open", 0.0) or 0.0)
    if raw_open <= 0:
        return {"filled": False, "skip_reason": "No valid open price on entry day"}

    gap_pct = ((raw_open - signal_close) / signal_close * 100.0) if signal_close > 0 else 0.0
    if cost_model.max_entry_gap_pct > 0 and gap_pct > cost_model.max_entry_gap_pct:
        return {
            "filled": False,
            "skip_reason": (
                f"Gap opening +{gap_pct:.2f}% exceeds the {cost_model.max_entry_gap_pct:.2f}% "
                f"entry-gap limit — entry skipped"
            ),
            "gap_pct": round(gap_pct, 2),
        }

    fill_price = effective_buy_price(cost_model, raw_open)
    budget = min(available_cash, desired_allocation)

    # Whole-share sizing that leaves room for buy-side costs.
    qty = int(budget // fill_price)
    while qty > 0:
        turnover = qty * fill_price
        costs = side_costs(cost_model, turnover, "buy")
        if turnover + costs["total"] <= available_cash + 1e-9:
            break
        qty -= 1
    if qty <= 0:
        return {
            "filled": False,
            "skip_reason": (
                f"Insufficient capital: 1 share at ₹{fill_price:.2f} plus costs exceeds "
                f"available cash ₹{available_cash:.2f}"
            ),
            "gap_pct": round(gap_pct, 2),
        }

    requested_qty = qty
    fill_note = ""
    if cost_model.allow_partial_fills and cost_model.volume_participation_pct > 0:
        vol = float(entry_candle.get("volume", 0.0) or 0.0)
        max_qty = int(vol * cost_model.volume_participation_pct / 100.0)
        if vol > 0 and qty > max_qty:
            if max_qty <= 0:
                return {
                    "filled": False,
                    "skip_reason": (
                        f"Partial-fill limit: candle volume {vol:.0f} allows 0 shares at "
                        f"{cost_model.volume_participation_pct:.1f}% participation"
                    ),
                    "gap_pct": round(gap_pct, 2),
                }
            qty = max_qty
            fill_note = (
                f"Partial fill: wanted {requested_qty}, filled {qty} "
                f"({cost_model.volume_participation_pct:.1f}% of candle volume)"
            )

    turnover = qty * fill_price
    buy_costs = side_costs(cost_model, turnover, "buy")

    return {
        "filled": True,
        "entry_date": str(entry_candle.get("date", "")),
        "raw_open": round(raw_open, 4),
        "fill_price": round(fill_price, 4),
        "quantity": qty,
        "requested_quantity": requested_qty,
        "partial_fill": qty < requested_qty,
        "fill_note": fill_note,
        "gap_pct": round(gap_pct, 2),
        "turnover": round(turnover, 2),
        "buy_costs": buy_costs,
        "cash_used": round(turnover + buy_costs["total"], 2),
    }


# ── Exit simulation ──────────────────────────────────────────────────────────

def evaluate_exit_candle(
    candle: dict,
    stop_loss: float,
    target: float,
    intrabar_rule: str = INTRABAR_CONSERVATIVE,
) -> tuple[bool, float, str, bool]:
    """
    Check ONE candle for a stop/target exit.
    Returns (exited, raw_exit_price, reason, both_touched).
    Gap-through fills happen at the (worse/better) open, not the level.
    """
    o, h, low = float(candle["open"]), float(candle["high"]), float(candle["low"])
    hit_stop = stop_loss > 0 and low <= stop_loss
    hit_target = target > 0 and h >= target

    if hit_stop and hit_target:
        if intrabar_rule == INTRABAR_OPTIMISTIC:
            raw = target if o <= target else o
            return True, raw, EXIT_TARGET, True
        raw = o if o < stop_loss else stop_loss
        return True, raw, EXIT_STOP, True
    if hit_stop:
        raw = o if o < stop_loss else stop_loss
        return True, raw, EXIT_STOP, False
    if hit_target:
        raw = o if o > target else target
        return True, raw, EXIT_TARGET, False
    return False, 0.0, "", False


def _candle(row: Any) -> dict:
    return {
        "open": float(row["open"]), "high": float(row["high"]),
        "low": float(row["low"]), "close": float(row["close"]),
    }


def simulate_exit(
    cost_model: CostModel,
    candles: pd.DataFrame,
    entry_price: float,
    stop_loss: float,
    target: float,
    quantity: int,
    max_holding_days: int = 30,
    intrabar_rule: str = INTRABAR_CONSERVATIVE,
    signal_exit_dates: set[str] | None = None,
    portfolio_exit_dates: set[str] | None = None,
) -> dict:
    """
    Walk forward candle-by-candle from the entry day (candles must start at
    the entry candle, dates as index or 'date' column, ascending) and find
    the first exit event.

    Priority inside one candle:
      1. Gap open through stop/target (exit at open, not the level)
      2. Stop / target touched intrabar (same-candle rule applies)
      3. Portfolio exit (at close)
      4. Signal exit (at close)
      5. Time exit after max_holding_days trading days (at close)
      6. End-of-data forced close (at last close)

    Also tracks Maximum Adverse / Favourable Excursion (% vs entry).
    Returns dict with exit_date, raw_exit_price, exit_reason, holding_days,
    mae_pct, mfe_pct, intrabar_rule, intrabar_rule_label, both_touched_candles.
    """
    if intrabar_rule not in (INTRABAR_CONSERVATIVE, INTRABAR_OPTIMISTIC):
        intrabar_rule = INTRABAR_CONSERVATIVE
    signal_exit_dates = signal_exit_dates or set()
    portfolio_exit_dates = portfolio_exit_dates or set()

    if "date" in candles.columns:
        dates = [str(d)[:10] for d in candles["date"].tolist()]
    else:
        dates = [str(d)[:10] for d in candles.index.tolist()]

    mae = 0.0   # most negative excursion, %
    mfe = 0.0   # most positive excursion, %
    both_touched = 0

    exit_date = None
    raw_exit = None
    reason = None
    holding = 0

    n = len(candles)
    rows = candles.reset_index(drop=True)

    for i in range(n):
        row = rows.iloc[i]
        c = _candle(row)
        d = dates[i]
        holding = i  # trading days held so far (entry day = 0)

        # Excursions (use full candle range)
        if entry_price > 0:
            mae = min(mae, (c["low"] - entry_price) / entry_price * 100.0)
            mfe = max(mfe, (c["high"] - entry_price) / entry_price * 100.0)

        if i == 0 and stop_loss > 0 and c["open"] <= stop_loss:
            # Entered directly at/below stop (rare) — treat open as exit.
            exit_date, raw_exit, reason = d, c["open"], EXIT_STOP
            break

        exited, raw, why, both = evaluate_exit_candle(c, stop_loss, target, intrabar_rule)
        if both:
            both_touched += 1
        if exited:
            exit_date, raw_exit, reason = d, raw, why
            break
        if d in portfolio_exit_dates:
            exit_date, raw_exit, reason = d, c["close"], EXIT_PORTFOLIO
            break
        if d in signal_exit_dates:
            exit_date, raw_exit, reason = d, c["close"], EXIT_SIGNAL
            break
        if max_holding_days > 0 and i >= max_holding_days:
            exit_date, raw_exit, reason = d, c["close"], EXIT_TIME
            break

    if exit_date is None:
        # Ran out of data inside the test window — forced close on last candle.
        last = rows.iloc[n - 1]
        exit_date, raw_exit, reason = dates[n - 1], float(last["close"]), EXIT_FORCED
        holding = n - 1

    sell_price = effective_sell_price(cost_model, float(raw_exit))
    turnover = sell_price * quantity
    sell_costs = side_costs(cost_model, turnover, "sell")

    return {
        "exit_date": exit_date,
        "raw_exit_price": round(float(raw_exit), 4),
        "sell_price": round(sell_price, 4),
        "exit_reason": reason,
        "holding_days": holding,
        "mae_pct": round(mae, 2),
        "mfe_pct": round(mfe, 2),
        "both_touched_candles": both_touched,
        "intrabar_rule": intrabar_rule,
        "intrabar_rule_label": INTRABAR_RULE_LABELS[intrabar_rule],
        "sell_turnover": round(turnover, 2),
        "sell_costs": sell_costs,
    }


# ── Full round-trip helper ───────────────────────────────────────────────────

def build_trade_record(
    symbol: str,
    entry: dict,
    exit_info: dict,
    meta: dict | None = None,
) -> dict:
    """
    Combine an entry fill and an exit into one net-of-costs trade record.
    `meta` carries recommendation/confidence/strategy/etc straight through.
    """
    qty = int(entry["quantity"])
    buy_total = float(entry["buy_costs"]["total"])
    sell_total = float(exit_info["sell_costs"]["total"])
    gross = (float(exit_info["raw_exit_price"]) - float(entry["raw_open"])) * qty
    # Net uses effective (slippage/spread-adjusted) prices plus explicit costs.
    net = (float(exit_info["sell_price"]) - float(entry["fill_price"])) * qty - buy_total - sell_total
    invested = float(entry["fill_price"]) * qty
    total_costs = buy_total + sell_total + \
        (float(entry["fill_price"]) - float(entry["raw_open"])) * qty + \
        (float(exit_info["raw_exit_price"]) - float(exit_info["sell_price"])) * qty

    rec = {
        "symbol": symbol,
        "entry_date": entry["entry_date"],
        "entry_price": entry["fill_price"],
        "raw_open": entry["raw_open"],
        "quantity": qty,
        "requested_quantity": entry["requested_quantity"],
        "partial_fill": entry["partial_fill"],
        "gap_pct": entry.get("gap_pct", 0.0),
        "invested": round(invested, 2),
        "exit_date": exit_info["exit_date"],
        "exit_price": exit_info["sell_price"],
        "raw_exit_price": exit_info["raw_exit_price"],
        "exit_reason": exit_info["exit_reason"],
        "holding_days": exit_info["holding_days"],
        "mae_pct": exit_info["mae_pct"],
        "mfe_pct": exit_info["mfe_pct"],
        "intrabar_rule": exit_info["intrabar_rule"],
        "gross_pnl": round(gross, 2),
        "net_pnl": round(net, 2),
        "return_pct": round(net / invested * 100.0, 2) if invested > 0 else 0.0,
        "buy_costs": entry["buy_costs"],
        "sell_costs": exit_info["sell_costs"],
        "total_costs": round(total_costs, 2),
        "win": net > 0,
    }
    if meta:
        rec.update(meta)
    return rec
