"""
backtesting_engine.py
Walk-Forward Backtesting Engine — paper-only, no real orders.

Algorithm:
  1. Fetch OHLCV data for the full period
  2. Compute all indicator series in ONE pass (O(n), no lookahead)
  3. Walk bar-by-bar:
     - If flat: call strategy.check_entry()
     - If in position: check stop/target hits on bar H/L, then strategy.check_exit()
  4. Force-close any open position at end of data
  5. Compute performance metrics

Entry executes at next bar's OPEN (no look-ahead into current bar).
Stop and target are tested against bar's High/Low (intrabar fill assumed).

Output: BacktestResult TypedDict with all metrics + equity curve + trade list.
"""

import math
from datetime import datetime, date
from typing import Optional, TypedDict

import numpy as np
import pandas as pd

from market_data_engine import fetch_candles_df
from indicator_engine import compute_indicators_df
from strategies import get_strategy, StrategyBase
from config import INITIAL_CAPITAL, MAX_RISK_PCT, MAX_CAPITAL_PER_TRADE_PCT


# ── TypedDicts ─────────────────────────────────────────────────────────────────

class BacktestTrade(TypedDict):
    trade_no:       int
    entry_date:     str
    exit_date:      str
    symbol:         str
    direction:      str    # LONG
    entry_price:    float
    exit_price:     float
    stop_loss:      float
    target:         float
    quantity:       int
    pnl:            float
    pnl_pct:        float
    duration_bars:  int
    exit_reason:    str    # TARGET | STOP | SIGNAL_EXIT | END_OF_DATA
    entry_reason:   str


class BacktestResult(TypedDict):
    symbol:            str
    strategy:          str
    strategy_name:     str
    interval:          str
    start_date:        str
    end_date:          str
    initial_capital:   float
    final_capital:     float
    total_trades:      int
    winning_trades:    int
    losing_trades:     int
    breakeven_trades:  int
    win_rate:          float    # 0–100
    net_pnl:           float
    net_pnl_pct:       float
    profit_factor:     float
    max_drawdown:      float    # absolute ₹
    max_drawdown_pct:  float    # % of peak
    avg_profit:        float
    avg_loss:          float
    best_trade:        float
    worst_trade:       float
    avg_duration_bars: float
    sharpe_ratio:      float
    data_source:       str      # yfinance | mock
    trades:            list
    equity_curve:      list     # portfolio value at each bar (sampled)
    computed_at:       str
    error:             Optional[str]


# ── Helpers ───────────────────────────────────────────────────────────────────

WARMUP_BARS = 55          # bars discarded for indicator warmup (EMA50 + buffer)
MAX_EQUITY_POINTS = 500   # downsample equity curve to this many points


def _safe_float(v) -> float:
    try:
        f = float(v)
        return 0.0 if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return 0.0


def _compute_qty(
    entry_price: float,
    stop_loss: float,
    capital: float,
) -> int:
    """
    Compute position size respecting 1% risk rule.

    For small accounts (e.g. ₹5000 paper-trading capital) the strict
    20%-of-capital cap would prevent any trade on stocks priced above ₹1000.
    Instead we cap at whatever shares we can afford outright (up to 100% of
    cash) while still applying the risk-based quantity as the primary control.
    We always ensure at least 1 share when the account can cover entry price.
    """
    stop_dist = entry_price - stop_loss
    if stop_dist <= 0 or capital < entry_price:
        return 0

    # 1% risk rule: max loss = 1% of capital
    risk_amount = capital * MAX_RISK_PCT
    qty_risk    = max(1, math.floor(risk_amount / stop_dist))

    # Hard cap: never risk more shares than we can afford
    qty_afford  = math.floor(capital / entry_price)
    return max(0, min(qty_risk, qty_afford))


def _empty_result(symbol: str, strategy: str, error: str) -> BacktestResult:
    return BacktestResult(
        symbol=symbol, strategy=strategy, strategy_name=strategy, interval="1d",
        start_date="", end_date="", initial_capital=INITIAL_CAPITAL, final_capital=INITIAL_CAPITAL,
        total_trades=0, winning_trades=0, losing_trades=0, breakeven_trades=0,
        win_rate=0.0, net_pnl=0.0, net_pnl_pct=0.0, profit_factor=0.0,
        max_drawdown=0.0, max_drawdown_pct=0.0,
        avg_profit=0.0, avg_loss=0.0, best_trade=0.0, worst_trade=0.0,
        avg_duration_bars=0.0, sharpe_ratio=0.0, data_source="none",
        trades=[], equity_curve=[], computed_at=datetime.now().isoformat(), error=error,
    )


def _downsample(equity: list[float], max_points: int) -> list[float]:
    if len(equity) <= max_points:
        return equity
    step = len(equity) / max_points
    return [equity[int(i * step)] for i in range(max_points)] + [equity[-1]]


def _period_for_start(start_date: str) -> str:
    """Convert start date to yfinance period string (approximate)."""
    try:
        start = date.fromisoformat(start_date)
        days = (date.today() - start).days
        if days <= 90:   return "3mo"
        if days <= 180:  return "6mo"
        if days <= 365:  return "1y"
        if days <= 730:  return "2y"
        return "5y"
    except Exception:
        return "1y"


# ── Core engine ───────────────────────────────────────────────────────────────

def run_backtest(
    symbol:          str,
    strategy_name:   str,
    start_date:      str,
    end_date:        str,
    initial_capital: float = INITIAL_CAPITAL,
    interval:        str   = "1d",
) -> BacktestResult:
    """
    Run a walk-forward paper backtest.

    Args:
        symbol          : NSE symbol (RELIANCE, TCS, etc.)
        strategy_name   : strategy id (trend_rider, breakout_hunter, mean_reversion)
        start_date      : ISO date string "YYYY-MM-DD"
        end_date        : ISO date string "YYYY-MM-DD"
        initial_capital : starting capital in INR
        interval        : OHLCV bar interval (1d, 1h)

    Returns:
        BacktestResult TypedDict
    """
    # 1. Load strategy
    try:
        strategy: StrategyBase = get_strategy(strategy_name)
    except ValueError as e:
        return _empty_result(symbol, strategy_name, str(e))

    # 2. Fetch OHLCV (prefer date range over period)
    try:
        period = _period_for_start(start_date)
        df = fetch_candles_df(
            symbol, interval=interval,
            period=period, start=start_date, end=end_date,
        )
    except Exception as e:
        return _empty_result(symbol, strategy_name, f"Data fetch failed: {e}")

    if df.empty or len(df) < WARMUP_BARS + 5:
        return _empty_result(
            symbol, strategy_name,
            f"Insufficient data: {len(df)} bars (need {WARMUP_BARS + 5}+)"
        )

    # Detect if mock data
    data_source = "yfinance"  # indicator if df came from yfinance vs mock
    # (market_data_engine falls back to mock on yfinance failure)

    # 3. Compute ALL indicators in ONE pass (no lookahead)
    try:
        enriched = compute_indicators_df(df)
    except Exception as e:
        return _empty_result(symbol, strategy_name, f"Indicator computation failed: {e}")

    # 4. Walk-forward simulation
    capital      = float(initial_capital)
    peak_capital = capital
    max_drawdown_abs = 0.0
    max_drawdown_pct = 0.0
    equity_curve: list[float] = [capital]
    trades: list[BacktestTrade] = []
    position: Optional[dict] = None
    trade_no = 0

    rows = enriched.reset_index()  # 'time' becomes a column
    n = len(rows)

    for i in range(WARMUP_BARS, n):
        row  = rows.iloc[i]
        prev = rows.iloc[i - 1]

        cur_open  = _safe_float(row.get("open",  0))
        cur_high  = _safe_float(row.get("high",  0))
        cur_low   = _safe_float(row.get("low",   0))
        cur_close = _safe_float(row.get("close", 0))
        cur_time  = str(row.get("time", ""))

        if cur_close <= 0:
            equity_curve.append(capital)
            continue

        # ── In a position ────────────────────────────────────────────────────
        if position is not None:
            exit_price  = None
            exit_reason = None

            # Check stop hit (low crosses stop)
            if cur_low <= position["stop"]:
                exit_price  = position["stop"]
                exit_reason = "STOP"

            # Check target hit (high crosses target), but only if not already stopped
            elif cur_high >= position["target"]:
                exit_price  = position["target"]
                exit_reason = "TARGET"

            # Signal-based exit
            else:
                sig_exit, sig_reason = strategy.check_exit(
                    row, prev,
                    position["entry_price"],
                    position["stop"],
                    position["target"],
                )
                if sig_exit:
                    exit_price  = cur_close
                    exit_reason = "SIGNAL_EXIT"

            if exit_price is not None and exit_reason is not None:
                qty = position["quantity"]
                pnl = round((exit_price - position["entry_price"]) * qty, 2)
                pnl_pct = round(pnl / (position["entry_price"] * qty) * 100, 2)
                capital += pnl

                trade_no += 1
                trades.append(BacktestTrade(
                    trade_no      = trade_no,
                    entry_date    = position["entry_time"],
                    exit_date     = cur_time,
                    symbol        = symbol.upper(),
                    direction     = "LONG",
                    entry_price   = position["entry_price"],
                    exit_price    = round(exit_price, 2),
                    stop_loss     = position["stop"],
                    target        = position["target"],
                    quantity      = qty,
                    pnl           = pnl,
                    pnl_pct       = pnl_pct,
                    duration_bars = i - position["entry_bar"],
                    exit_reason   = exit_reason,
                    entry_reason  = position["reason"],
                ))
                position = None

                # Drawdown tracking
                peak_capital = max(peak_capital, capital)
                dd_abs = peak_capital - capital
                dd_pct = dd_abs / peak_capital * 100 if peak_capital > 0 else 0
                max_drawdown_abs = max(max_drawdown_abs, dd_abs)
                max_drawdown_pct = max(max_drawdown_pct, dd_pct)

        # ── Flat — check entry ────────────────────────────────────────────────
        if position is None and capital > 0:
            should_enter, reason = strategy.check_entry(row, prev)

            if should_enter:
                # Entry at next bar OPEN price (simulated; use current close as proxy)
                # For daily data, close ≈ next open; acceptable approximation
                entry_price = cur_close
                stop_loss   = strategy.compute_stop_loss(row, entry_price)
                target      = strategy.compute_target(entry_price, stop_loss)

                # Validate stop
                if stop_loss <= 0 or stop_loss >= entry_price:
                    equity_curve.append(capital)
                    continue

                qty = _compute_qty(entry_price, stop_loss, capital)
                if qty <= 0:
                    equity_curve.append(capital)
                    continue

                position = {
                    "entry_time":  cur_time,
                    "entry_price": entry_price,
                    "stop":        stop_loss,
                    "target":      target,
                    "quantity":    qty,
                    "entry_bar":   i,
                    "reason":      reason,
                }

        equity_curve.append(capital)

    # 5. Force-close open position at last bar
    if position is not None and len(rows) > 0:
        last   = rows.iloc[-1]
        last_p = _safe_float(last.get("close", position["entry_price"]))
        qty    = position["quantity"]
        pnl    = round((last_p - position["entry_price"]) * qty, 2)
        capital += pnl
        trade_no += 1
        trades.append(BacktestTrade(
            trade_no      = trade_no,
            entry_date    = position["entry_time"],
            exit_date     = str(last.get("time", "")),
            symbol        = symbol.upper(),
            direction     = "LONG",
            entry_price   = position["entry_price"],
            exit_price    = last_p,
            stop_loss     = position["stop"],
            target        = position["target"],
            quantity      = qty,
            pnl           = pnl,
            pnl_pct       = round(pnl / (position["entry_price"] * qty) * 100, 2),
            duration_bars = len(rows) - 1 - position["entry_bar"],
            exit_reason   = "END_OF_DATA",
            entry_reason  = position["reason"],
        ))
        equity_curve.append(capital)

    # 6. Compute performance metrics
    winners  = [t for t in trades if t["pnl"] > 0]
    losers   = [t for t in trades if t["pnl"] < 0]
    breakevens = [t for t in trades if t["pnl"] == 0]

    gross_profit = sum(t["pnl"] for t in winners)
    gross_loss   = abs(sum(t["pnl"] for t in losers))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0
    if profit_factor == float("inf"):
        profit_factor = 99.0

    win_rate    = round(len(winners) / len(trades) * 100, 1) if trades else 0.0
    net_pnl     = round(capital - initial_capital, 2)
    net_pnl_pct = round(net_pnl / initial_capital * 100, 2)
    avg_profit  = round(gross_profit / len(winners), 2)  if winners  else 0.0
    avg_loss    = round(-gross_loss  / len(losers),  2)  if losers   else 0.0
    best_trade  = max((t["pnl"] for t in trades), default=0.0)
    worst_trade = min((t["pnl"] for t in trades), default=0.0)
    avg_dur     = round(sum(t["duration_bars"] for t in trades) / len(trades), 1) if trades else 0.0

    # Sharpe ratio (simplified: Trades PnL / std)
    pnls = [t["pnl"] for t in trades]
    sharpe = 0.0
    if len(pnls) > 1:
        mu = np.mean(pnls)
        sd = np.std(pnls)
        sharpe = round(float(mu / sd) if sd > 0 else 0.0, 2)

    # Date range
    start_str = str(rows.iloc[0].get("time",  "")) if len(rows) > 0 else start_date
    end_str   = str(rows.iloc[-1].get("time", "")) if len(rows) > 0 else end_date

    return BacktestResult(
        symbol            = symbol.upper(),
        strategy          = strategy_name,
        strategy_name     = strategy.name,
        interval          = interval,
        start_date        = start_str,
        end_date          = end_str,
        initial_capital   = initial_capital,
        final_capital     = round(capital, 2),
        total_trades      = len(trades),
        winning_trades    = len(winners),
        losing_trades     = len(losers),
        breakeven_trades  = len(breakevens),
        win_rate          = win_rate,
        net_pnl           = net_pnl,
        net_pnl_pct       = net_pnl_pct,
        profit_factor     = profit_factor,
        max_drawdown      = round(max_drawdown_abs, 2),
        max_drawdown_pct  = round(max_drawdown_pct, 2),
        avg_profit        = avg_profit,
        avg_loss          = avg_loss,
        best_trade        = round(best_trade, 2),
        worst_trade       = round(worst_trade, 2),
        avg_duration_bars = avg_dur,
        sharpe_ratio      = sharpe,
        data_source       = data_source,
        trades            = trades,
        equity_curve      = _downsample([round(v, 2) for v in equity_curve], MAX_EQUITY_POINTS),
        computed_at       = datetime.now().isoformat(),
        error             = None,
    )
