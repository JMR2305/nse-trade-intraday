"""
backtesting_engine.py
Walk-Forward Backtesting Engine with Debug / Validation Mode.

Algorithm:
  1. Fetch OHLCV data for the full period
  2. Compute all indicator series in ONE pass (O(n), no lookahead)
  3. Walk bar-by-bar:
     - Always evaluate entry signal + rule checks (for validation stats)
     - If in position: cache exit signal; check stop/target; apply exit
     - If flat + signal: attempt entry; record rejection if stop/qty invalid
  4. Force-close any open position at end of data
  5. Compute performance metrics + ValidationSummary
  6. Write detailed log file to /tmp/backtest_logs/

Debug mode (debug=True):
  - Populates debug_candles: per-bar indicator snapshot + pass/fail for every rule
  - Still included in response even when debug=False: validation summary, rejected trades

Output: BacktestResult TypedDict.
"""

import math
import os
import textwrap
from datetime import datetime, date
from typing import Optional, TypedDict

import numpy as np
import pandas as pd

from market_data_engine import fetch_candles_df
from indicator_engine import compute_indicators_df
from strategies import get_strategy, StrategyBase
from config import INITIAL_CAPITAL, MAX_RISK_PCT, MAX_CAPITAL_PER_TRADE_PCT
from analytics_engine import compute_trade_analytics


# ── TypedDicts ─────────────────────────────────────────────────────────────────

class RuleCheck(TypedDict):
    rule:           str
    current_value:  str
    required_value: str
    passed:         bool


class DebugCandle(TypedDict):
    date:         str
    close:        float
    ema9:         float
    ema20:        float
    ema50:        float
    rsi:          float
    macd_line:    float
    macd_signal:  float
    vwap:         float
    adx:          float
    bb_upper:     float
    bb_lower:     float
    volume_ratio: float
    in_position:  bool
    buy_signal:   bool
    sell_signal:  bool     # True = signal-based exit fired this bar (while in position)
    failed_rules: list     # list[str] — rule descriptions that failed
    rule_checks:  list     # list[RuleCheck]


class RejectedTrade(TypedDict):
    date:           str
    close:          float
    rejection_type: str    # "bad_stop" | "qty_zero"
    explanation:    str
    rule_checks:    list   # list[RuleCheck] — all rules PASSED for entry (signal fired)


class ValidationSummary(TypedDict):
    total_candles:          int
    warmup_candles:         int
    active_candles:         int
    buy_signals_fired:      int    # check_entry()=True on any bar (in or out of position)
    buy_signals_while_flat: int    # check_entry()=True when flat (no position)
    sell_signals_fired:     int    # total exit events (= executed trades)
    executed_trades:        int
    rejected_trades:        int    # signal fired, flat, but bad_stop or qty_zero
    skipped_while_invested: int    # signal fired but already in a position
    rejection_breakdown:    dict   # {"bad_stop": N, "qty_zero": N}
    rule_failure_counts:    dict   # {"<rule text>": count} — when flat & signal=False
    most_common_failure:    str    # rule name with highest failure count
    zero_trade_diagnosis:   list   # populated when executed_trades == 0
    log_file_path:          str    # absolute path to the .log file on disk


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
    trades:            list     # list[BacktestTrade]
    equity_curve:      list     # portfolio value at each bar (sampled)
    computed_at:       str
    error:             Optional[str]
    # ── Validation / Debug ─────────────────────────────────────────────
    validation:              dict   # ValidationSummary
    debug_candles:           list   # list[DebugCandle], populated when debug=True
    rejected_trades_detail:  list   # list[RejectedTrade], always populated
    # ── Performance Analytics (v0.9) ────────────────────────────────────
    expectancy:              float  # avg ₹ P&L per trade
    max_consecutive_wins:    int
    max_consecutive_losses:  int
    capital_curve:           list   # list[float], capital after each trade


# ── Helpers ───────────────────────────────────────────────────────────────────

WARMUP_BARS       = 55          # bars discarded for indicator warmup
MAX_EQUITY_POINTS = 500         # downsample equity curve
LOG_DIR           = "/tmp/backtest_logs"


def _safe_float(v) -> float:
    try:
        f = float(v)
        return 0.0 if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return 0.0


def _compute_qty(entry_price: float, stop_loss: float, capital: float) -> int:
    """
    1% risk rule position sizing.
    Guarantees at least 1 share when affordable, caps at affordable quantity.
    """
    stop_dist = entry_price - stop_loss
    if stop_dist <= 0 or capital < entry_price:
        return 0
    risk_amount = capital * MAX_RISK_PCT
    qty_risk    = max(1, math.floor(risk_amount / stop_dist))
    qty_afford  = math.floor(capital / entry_price)
    return max(0, min(qty_risk, qty_afford))


def _empty_result(symbol: str, strategy: str, error: str) -> BacktestResult:
    empty_validation = ValidationSummary(
        total_candles=0, warmup_candles=WARMUP_BARS, active_candles=0,
        buy_signals_fired=0, buy_signals_while_flat=0, sell_signals_fired=0,
        executed_trades=0, rejected_trades=0, skipped_while_invested=0,
        rejection_breakdown={}, rule_failure_counts={}, most_common_failure="",
        zero_trade_diagnosis=[f"Backtest failed: {error}"],
        log_file_path="",
    )
    return BacktestResult(
        symbol=symbol, strategy=strategy, strategy_name=strategy, interval="1d",
        start_date="", end_date="", initial_capital=INITIAL_CAPITAL, final_capital=INITIAL_CAPITAL,
        total_trades=0, winning_trades=0, losing_trades=0, breakeven_trades=0,
        win_rate=0.0, net_pnl=0.0, net_pnl_pct=0.0, profit_factor=0.0,
        max_drawdown=0.0, max_drawdown_pct=0.0,
        avg_profit=0.0, avg_loss=0.0, best_trade=0.0, worst_trade=0.0,
        avg_duration_bars=0.0, sharpe_ratio=0.0, data_source="none",
        trades=[], equity_curve=[], computed_at=datetime.now().isoformat(), error=error,
        validation=empty_validation, debug_candles=[], rejected_trades_detail=[],
        expectancy=0.0, max_consecutive_wins=0, max_consecutive_losses=0, capital_curve=[],
    )


def _downsample(equity: list, max_points: int) -> list:
    if len(equity) <= max_points:
        return equity
    step = len(equity) / max_points
    return [equity[int(i * step)] for i in range(max_points)] + [equity[-1]]


def _period_for_start(start_date: str) -> str:
    try:
        start = date.fromisoformat(start_date)
        days  = (date.today() - start).days
        if days <= 90:  return "3mo"
        if days <= 180: return "6mo"
        if days <= 365: return "1y"
        if days <= 730: return "2y"
        return "5y"
    except Exception:
        return "1y"


# ── Log file generation ────────────────────────────────────────────────────────

def _write_log(
    symbol: str,
    strategy_obj: StrategyBase,
    interval: str,
    initial_capital: float,
    start_str: str,
    end_str: str,
    active_candles: int,
    debug_candles: list,
    rejected_trades_detail: list,
    trades: list,
    validation: "ValidationSummary",
    result_metrics: dict,
) -> str:
    """Write a detailed backtest log file. Returns the file path."""
    os.makedirs(LOG_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{symbol.upper()}_{strategy_obj.id}_{ts}.log"
    filepath = os.path.join(LOG_DIR, filename)

    lines = []
    sep = "=" * 72

    lines.append(sep)
    lines.append(f"  BACKTEST LOG — {symbol.upper()}  ({strategy_obj.name})")
    lines.append(sep)
    lines.append(f"  Generated : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"  Symbol    : {symbol.upper()}")
    lines.append(f"  Strategy  : {strategy_obj.name} ({strategy_obj.id})")
    lines.append(f"  Type      : {strategy_obj.type}")
    lines.append(f"  Period    : {start_str} → {end_str}")
    lines.append(f"  Interval  : {interval}")
    lines.append(f"  Capital   : ₹{initial_capital:,.2f}")
    lines.append("")

    lines.append("ENTRY RULES:")
    for i, r in enumerate(strategy_obj.entry_rules, 1):
        lines.append(f"  [{i}] {r}")
    lines.append("")
    lines.append("EXIT RULES:")
    for i, r in enumerate(strategy_obj.exit_rules, 1):
        lines.append(f"  [{i}] {r}")
    lines.append("")

    # Per-candle log
    lines.append(sep)
    lines.append(f"PER-CANDLE DEBUG LOG  (active bars: {active_candles})")
    lines.append(sep)
    hdr = (f"{'DATE':<12} {'CLOSE':>8} {'EMA9':>8} {'EMA20':>8} {'EMA50':>8} "
           f"{'RSI':>6} {'MACD':>8} {'VWAP':>8} {'ADX':>6} "
           f"{'POS':>4} {'BUY':>4} {'SELL':>5}  FAILED RULES")
    lines.append(hdr)
    lines.append("-" * len(hdr))

    for c in debug_candles:
        date_s  = str(c["date"])[:10]
        pos_s   = "YES" if c["in_position"] else "-"
        buy_s   = "BUY" if c["buy_signal"] else "-"
        sell_s  = "SELL" if c["sell_signal"] else "-"
        failed  = ", ".join(c["failed_rules"]) if c["failed_rules"] else "—"
        lines.append(
            f"{date_s:<12} {c['close']:>8.1f} {c['ema9']:>8.1f} {c['ema20']:>8.1f} "
            f"{c['ema50']:>8.1f} {c['rsi']:>6.1f} {c['macd_line']:>8.3f} "
            f"{c['vwap']:>8.1f} {c['adx']:>6.1f} "
            f"{pos_s:>4} {buy_s:>4} {sell_s:>5}  {failed}"
        )
    if not debug_candles:
        lines.append("  (debug_candles not collected — pass debug=true to populate)")
    lines.append("")

    # Rejected trades
    lines.append(sep)
    lines.append(f"REJECTED TRADES  ({len(rejected_trades_detail)})")
    lines.append(sep)
    for i, rt in enumerate(rejected_trades_detail, 1):
        lines.append(f"  #{i}  {str(rt['date'])[:10]}  close=₹{rt['close']:.1f}")
        lines.append(f"       Type: {rt['rejection_type']}")
        lines.append(f"       Reason: {rt['explanation']}")
    if not rejected_trades_detail:
        lines.append("  (none)")
    lines.append("")

    # Executed trades
    lines.append(sep)
    lines.append(f"EXECUTED TRADES  ({len(trades)})")
    lines.append(sep)
    for t in trades:
        pnl_sign = "+" if t["pnl"] >= 0 else ""
        lines.append(
            f"  #{t['trade_no']:>2}  "
            f"ENTRY {str(t['entry_date'])[:10]} @ ₹{t['entry_price']:.1f}  "
            f"EXIT {str(t['exit_date'])[:10]} @ ₹{t['exit_price']:.1f}  "
            f"QTY={t['quantity']}  "
            f"PnL={pnl_sign}₹{t['pnl']:.2f} ({pnl_sign}{t['pnl_pct']:.1f}%)  "
            f"[{t['exit_reason']}]"
        )
        lines.append(f"       Stop=₹{t['stop_loss']:.1f}  Target=₹{t['target']:.1f}  "
                     f"Bars held={t['duration_bars']}")
        lines.append(f"       Entry reason: {t['entry_reason']}")
    if not trades:
        lines.append("  (none)")
    lines.append("")

    # Summary
    lines.append(sep)
    lines.append("VALIDATION SUMMARY")
    lines.append(sep)
    v = validation
    lines.append(f"  Total candles         : {v['total_candles']}")
    lines.append(f"  Warmup (discarded)    : {v['warmup_candles']}")
    lines.append(f"  Active bars           : {v['active_candles']}")
    lines.append(f"  Buy signals fired     : {v['buy_signals_fired']}")
    lines.append(f"    ↳ while flat        : {v['buy_signals_while_flat']}")
    lines.append(f"    ↳ while invested    : {v['skipped_while_invested']}")
    lines.append(f"  Executed trades       : {v['executed_trades']}")
    lines.append(f"  Rejected trades       : {v['rejected_trades']}")
    if v["rejection_breakdown"]:
        for k, cnt in v["rejection_breakdown"].items():
            lines.append(f"    ↳ {k}: {cnt}")
    lines.append(f"  Exit events           : {v['sell_signals_fired']}")
    lines.append("")
    lines.append(f"  Net P&L               : ₹{result_metrics['net_pnl']:.2f} ({result_metrics['net_pnl_pct']:.2f}%)")
    lines.append(f"  Win rate              : {result_metrics['win_rate']:.1f}%")
    lines.append(f"  Profit factor         : {result_metrics['profit_factor']:.2f}")
    lines.append(f"  Max drawdown          : ₹{result_metrics['max_drawdown']:.2f} ({result_metrics['max_drawdown_pct']:.2f}%)")
    lines.append(f"  Sharpe ratio          : {result_metrics['sharpe']:.2f}")
    lines.append("")

    lines.append("RULE FAILURE BREAKDOWN (when flat, signal not fired):")
    if v["rule_failure_counts"]:
        active = v["active_candles"] or 1
        sorted_failures = sorted(v["rule_failure_counts"].items(), key=lambda x: -x[1])
        for rule, count in sorted_failures:
            pct = round(count / active * 100, 1)
            lines.append(f"  {count:>5}x ({pct:>5.1f}%)  {rule}")
    else:
        lines.append("  (no data — all signals fired or no active bars)")
    lines.append("")

    if v["zero_trade_diagnosis"]:
        lines.append("ZERO-TRADE DIAGNOSIS:")
        for d in v["zero_trade_diagnosis"]:
            lines.append(f"  ⚠ {d}")
        lines.append("")

    lines.append(sep)

    content = "\n".join(lines)
    try:
        with open(filepath, "w") as f:
            f.write(content)
    except Exception:
        filepath = ""

    return filepath


# ── Core engine ───────────────────────────────────────────────────────────────

def run_backtest(
    symbol:          str,
    strategy_name:   str,
    start_date:      str,
    end_date:        str,
    initial_capital: float = INITIAL_CAPITAL,
    interval:        str   = "1d",
    debug:           bool  = False,
) -> BacktestResult:
    """
    Run a walk-forward paper backtest with optional debug / validation output.

    Args:
        symbol          : NSE symbol (RELIANCE, TCS, etc.)
        strategy_name   : strategy id (trend_rider, breakout_hunter, mean_reversion)
        start_date      : ISO date "YYYY-MM-DD"
        end_date        : ISO date "YYYY-MM-DD"
        initial_capital : starting capital in INR
        interval        : bar interval (1d, 1h)
        debug           : if True, populate debug_candles in the response

    Returns:
        BacktestResult TypedDict (always includes validation + rejected_trades_detail)
    """
    # 1. Load strategy
    try:
        strategy: StrategyBase = get_strategy(strategy_name)
    except ValueError as e:
        return _empty_result(symbol, strategy_name, str(e))

    # 2. Fetch OHLCV
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

    data_source = "yfinance"

    # 3. Compute ALL indicators in ONE pass
    try:
        enriched = compute_indicators_df(df)
    except Exception as e:
        return _empty_result(symbol, strategy_name, f"Indicator computation failed: {e}")

    # 4. Walk-forward simulation
    capital          = float(initial_capital)
    peak_capital     = capital
    max_drawdown_abs = 0.0
    max_drawdown_pct = 0.0
    equity_curve: list = [capital]
    trades: list     = []
    position: Optional[dict] = None
    trade_no         = 0

    # Validation tracking
    buy_signals_fired       = 0
    buy_signals_while_flat  = 0
    skipped_while_invested  = 0
    rule_failure_counts: dict = {}
    rejected_trades_detail: list = []
    debug_candles_list: list = []
    rejection_breakdown: dict = {}

    rows = enriched.reset_index()
    n    = len(rows)

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

        # ── Always evaluate entry signal + rule inspector ─────────────────
        entry_signal, entry_reason_str = strategy.check_entry(row, prev)
        rule_checks: list = strategy.inspect_entry_rules(row, prev)

        # Buy-signal statistics
        if entry_signal:
            buy_signals_fired += 1
            if position is None:
                buy_signals_while_flat += 1
            else:
                skipped_while_invested += 1
        elif position is None:
            # Track per-rule failures only when flat and signal not fired
            for rc in rule_checks:
                if not rc["passed"]:
                    rule_failure_counts[rc["rule"]] = (
                        rule_failure_counts.get(rc["rule"], 0) + 1
                    )

        # ── Cache exit signal (avoids double-calling check_exit) ──────────
        sig_exit_cached   = False
        sig_reason_cached = ""
        if position is not None:
            sig_exit_cached, sig_reason_cached = strategy.check_exit(
                row, prev,
                position["entry_price"],
                position["stop"],
                position["target"],
            )

        # ── Build debug candle (every active bar) ─────────────────────────
        if debug:
            failed_rules = [rc["rule"] for rc in rule_checks if not rc["passed"]]
            debug_candles_list.append(DebugCandle(
                date         = cur_time,
                close        = cur_close,
                ema9         = _safe_float(row.get("ema9",         0)),
                ema20        = _safe_float(row.get("ema20",        0)),
                ema50        = _safe_float(row.get("ema50",        0)),
                rsi          = _safe_float(row.get("rsi",          0)),
                macd_line    = _safe_float(row.get("macd_line",    0)),
                macd_signal  = _safe_float(row.get("macd_signal",  0)),
                vwap         = _safe_float(row.get("vwap",         0)),
                adx          = _safe_float(row.get("adx",          0)),
                bb_upper     = _safe_float(row.get("bb_upper",     0)),
                bb_lower     = _safe_float(row.get("bb_lower",     0)),
                volume_ratio = _safe_float(row.get("volume_ratio", 0)),
                in_position  = position is not None,
                buy_signal   = entry_signal,
                sell_signal  = sig_exit_cached,
                failed_rules = failed_rules,
                rule_checks  = rule_checks,
            ))

        # ── In a position — check exits ───────────────────────────────────
        if position is not None:
            exit_price  = None
            exit_reason = None

            if cur_low <= position["stop"]:
                exit_price  = position["stop"]
                exit_reason = "STOP"
            elif cur_high >= position["target"]:
                exit_price  = position["target"]
                exit_reason = "TARGET"
            elif sig_exit_cached:
                exit_price  = cur_close
                exit_reason = "SIGNAL_EXIT"

            if exit_price is not None and exit_reason is not None:
                qty     = position["quantity"]
                pnl     = round((exit_price - position["entry_price"]) * qty, 2)
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

                peak_capital     = max(peak_capital, capital)
                dd_abs           = peak_capital - capital
                dd_pct           = dd_abs / peak_capital * 100 if peak_capital > 0 else 0
                max_drawdown_abs = max(max_drawdown_abs, dd_abs)
                max_drawdown_pct = max(max_drawdown_pct, dd_pct)

        # ── Flat — attempt entry if signal fired ──────────────────────────
        if position is None and capital > 0 and entry_signal:
            entry_price = cur_close
            stop_loss   = strategy.compute_stop_loss(row, entry_price)
            target      = strategy.compute_target(entry_price, stop_loss)

            if stop_loss <= 0 or stop_loss >= entry_price:
                rej = RejectedTrade(
                    date           = cur_time,
                    close          = cur_close,
                    rejection_type = "bad_stop",
                    explanation    = (
                        f"Stop loss ₹{stop_loss:.2f} is invalid for entry at "
                        f"₹{entry_price:.2f} (must be < entry and > 0)"
                    ),
                    rule_checks    = rule_checks,
                )
                rejected_trades_detail.append(rej)
                rejection_breakdown["bad_stop"] = rejection_breakdown.get("bad_stop", 0) + 1
                equity_curve.append(capital)
                continue

            qty = _compute_qty(entry_price, stop_loss, capital)
            if qty <= 0:
                rej = RejectedTrade(
                    date           = cur_time,
                    close          = cur_close,
                    rejection_type = "qty_zero",
                    explanation    = (
                        f"Cannot afford 1 share at ₹{entry_price:.0f} "
                        f"with ₹{capital:.0f} available capital"
                    ),
                    rule_checks    = rule_checks,
                )
                rejected_trades_detail.append(rej)
                rejection_breakdown["qty_zero"] = rejection_breakdown.get("qty_zero", 0) + 1
                equity_curve.append(capital)
                continue

            position = {
                "entry_time":  cur_time,
                "entry_price": entry_price,
                "stop":        stop_loss,
                "target":      target,
                "quantity":    qty,
                "entry_bar":   i,
                "reason":      entry_reason_str,
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

    # 6. Performance metrics
    winners    = [t for t in trades if t["pnl"] > 0]
    losers     = [t for t in trades if t["pnl"] < 0]
    breakevens = [t for t in trades if t["pnl"] == 0]

    gross_profit  = sum(t["pnl"] for t in winners)
    gross_loss    = abs(sum(t["pnl"] for t in losers))
    profit_factor = (round(gross_profit / gross_loss, 2) if gross_loss > 0
                     else 99.0 if gross_profit > 0 else 0.0)

    win_rate    = round(len(winners) / len(trades) * 100, 1) if trades else 0.0
    net_pnl     = round(capital - initial_capital, 2)
    net_pnl_pct = round(net_pnl / initial_capital * 100, 2)
    avg_profit  = round(gross_profit / len(winners), 2) if winners else 0.0
    avg_loss    = round(-gross_loss  / len(losers),  2) if losers  else 0.0
    best_trade  = max((t["pnl"] for t in trades), default=0.0)
    worst_trade = min((t["pnl"] for t in trades), default=0.0)
    avg_dur     = round(sum(t["duration_bars"] for t in trades) / len(trades), 1) if trades else 0.0

    pnls   = [t["pnl"] for t in trades]
    sharpe = 0.0
    if len(pnls) > 1:
        mu     = np.mean(pnls)
        sd     = np.std(pnls)
        sharpe = round(float(mu / sd) if sd > 0 else 0.0, 2)

    start_str = str(rows.iloc[0].get("time",  "")) if len(rows) > 0 else start_date
    end_str   = str(rows.iloc[-1].get("time", "")) if len(rows) > 0 else end_date

    # 7. Build ValidationSummary
    active_candles = n - WARMUP_BARS
    sell_signals_fired = len(trades)

    most_common_failure = (
        max(rule_failure_counts, key=lambda k: rule_failure_counts[k])
        if rule_failure_counts else ""
    )

    # Zero-trade diagnosis
    zero_trade_diagnosis: list = []
    if len(trades) == 0:
        if rejected_trades_detail:
            for rtype, cnt in rejection_breakdown.items():
                if rtype == "bad_stop":
                    zero_trade_diagnosis.append(
                        f"Entry signal fired {cnt}× but stop loss was invalid each time "
                        f"(computed stop ≥ entry price or ≤ 0)"
                    )
                elif rtype == "qty_zero":
                    zero_trade_diagnosis.append(
                        f"Entry signal fired {cnt}× but capital was insufficient "
                        f"to purchase even 1 share at the entry price"
                    )
        else:
            sorted_fails = sorted(rule_failure_counts.items(), key=lambda x: -x[1])
            for rule, count in sorted_fails[:4]:
                pct = round(count / active_candles * 100, 1) if active_candles > 0 else 0
                zero_trade_diagnosis.append(
                    f"'{rule}' failed on {count}/{active_candles} bars ({pct}%)"
                )
            if not sorted_fails:
                zero_trade_diagnosis.append(
                    "No active bars had valid indicator data (insufficient data for warmup)"
                )

    validation = ValidationSummary(
        total_candles          = n,
        warmup_candles         = WARMUP_BARS,
        active_candles         = active_candles,
        buy_signals_fired      = buy_signals_fired,
        buy_signals_while_flat = buy_signals_while_flat,
        sell_signals_fired     = sell_signals_fired,
        executed_trades        = len(trades),
        rejected_trades        = len(rejected_trades_detail),
        skipped_while_invested = skipped_while_invested,
        rejection_breakdown    = rejection_breakdown,
        rule_failure_counts    = rule_failure_counts,
        most_common_failure    = most_common_failure,
        zero_trade_diagnosis   = zero_trade_diagnosis,
        log_file_path          = "",   # filled in after _write_log()
    )

    # 8. Write log file (always)
    result_metrics = {
        "net_pnl": net_pnl, "net_pnl_pct": net_pnl_pct,
        "win_rate": win_rate, "profit_factor": profit_factor,
        "max_drawdown": round(max_drawdown_abs, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "sharpe": sharpe,
    }
    log_path = _write_log(
        symbol           = symbol,
        strategy_obj     = strategy,
        interval         = interval,
        initial_capital  = initial_capital,
        start_str        = start_str,
        end_str          = end_str,
        active_candles   = active_candles,
        debug_candles    = debug_candles_list,
        rejected_trades_detail = rejected_trades_detail,
        trades           = trades,
        validation       = validation,
        result_metrics   = result_metrics,
    )
    validation["log_file_path"] = log_path

    analytics = compute_trade_analytics(trades, initial_capital)

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
        validation        = validation,
        debug_candles     = debug_candles_list,
        rejected_trades_detail = rejected_trades_detail,
        expectancy              = analytics["expectancy"],
        max_consecutive_wins    = analytics["max_consecutive_wins"],
        max_consecutive_losses  = analytics["max_consecutive_losses"],
        capital_curve           = analytics["capital_curve"],
    )


# ══════════════════════════════════════════════════════════════════════════════
# STRATEGY LAB  — compare multiple strategies on the same data
# ══════════════════════════════════════════════════════════════════════════════

class StrategyLabEntry(TypedDict):
    strategy_id:        str
    strategy_name:      str
    strategy_type:      str
    best_regime:        str
    total_trades:       int
    winning_trades:     int
    losing_trades:      int
    win_rate:           float
    net_pnl:            float
    net_pnl_pct:        float
    profit_factor:      float
    max_drawdown:       float
    max_drawdown_pct:   float
    sharpe_ratio:       float
    avg_duration_bars:  float
    best_trade:         float
    worst_trade:        float
    error:              str | None


def _empty_lab_entry(strategy_id: str, error: str) -> dict:
    from strategies import STRATEGY_REGISTRY
    s = STRATEGY_REGISTRY.get(strategy_id)
    return {
        "strategy_id": strategy_id,
        "strategy_name": s.name if s else strategy_id,
        "strategy_type": s.type if s else "UNKNOWN",
        "best_regime": s.best_regime if s else "",
        "total_trades": 0, "winning_trades": 0, "losing_trades": 0,
        "win_rate": 0.0, "net_pnl": 0.0, "net_pnl_pct": 0.0,
        "profit_factor": 0.0, "max_drawdown": 0.0, "max_drawdown_pct": 0.0,
        "sharpe_ratio": 0.0, "avg_duration_bars": 0.0,
        "best_trade": 0.0, "worst_trade": 0.0,
        "error": error,
    }


def _run_lab_walk(rows, strategy, initial_capital: float) -> dict:
    """
    Simplified walk-forward loop for one strategy.
    Uses same position-sizing and bar logic as run_backtest() — no debug overhead.
    """
    capital     = initial_capital
    in_position = False
    entry_price = 0.0
    stop_loss   = 0.0
    target      = 0.0
    entry_bar   = 0
    entry_qty   = 1

    trades:       list = []
    equity:       list = [capital]
    peak          = capital
    max_dd_abs    = 0.0
    max_dd_pct    = 0.0
    gross_profit  = 0.0
    gross_loss    = 0.0
    best_trade    = 0.0
    worst_trade   = 0.0

    n = len(rows)

    for i in range(WARMUP_BARS, n):
        row  = rows.iloc[i]
        prev = rows.iloc[i - 1]

        close = _safe_float(row.get("close", 0))
        high  = _safe_float(row.get("high",  0))
        low   = _safe_float(row.get("low",   0))
        if close <= 0:
            continue

        if in_position:
            exit_triggered = False
            exit_price     = close

            # Stop hit (intrabar low)
            if low > 0 and low <= stop_loss:
                exit_triggered = True
                exit_price     = stop_loss
            # Target hit (intrabar high)
            elif high > 0 and high >= target:
                exit_triggered = True
                exit_price     = target
            else:
                should_exit, _ = strategy.check_exit(
                    row, prev, entry_price, stop_loss, target
                )
                if should_exit:
                    exit_triggered = True
                    exit_price     = close

            if exit_triggered:
                pnl      = round((exit_price - entry_price) * entry_qty, 2)
                duration = i - entry_bar
                capital  = round(capital + pnl, 2)

                if pnl >= 0:
                    gross_profit += pnl
                    best_trade    = max(best_trade, pnl)
                else:
                    gross_loss   += abs(pnl)
                    worst_trade   = min(worst_trade, pnl)

                trades.append({"pnl": pnl, "bars": duration})
                in_position = False
                equity.append(capital)

                if capital > peak:
                    peak = capital
                else:
                    dd_abs     = peak - capital
                    dd_pct     = dd_abs / peak * 100 if peak > 0 else 0.0
                    max_dd_abs = max(max_dd_abs, dd_abs)
                    max_dd_pct = max(max_dd_pct, dd_pct)
        else:
            should_enter, _ = strategy.check_entry(row, prev)
            if should_enter:
                sl  = strategy.compute_stop_loss(row, close)
                tgt = strategy.compute_target(close, sl)
                rps = close - sl
                if rps <= 0 or sl <= 0 or tgt <= close:
                    continue
                qty = int(capital * strategy.risk_pct / rps)
                if qty < 1:
                    continue
                in_position = True
                entry_price = close
                stop_loss   = sl
                target      = tgt
                entry_bar   = i
                entry_qty   = qty

    # Close any open position at last bar
    if in_position and n > WARMUP_BARS:
        last_close = _safe_float(rows.iloc[n - 1].get("close", 0))
        if last_close > 0:
            pnl     = round((last_close - entry_price) * entry_qty, 2)
            capital = round(capital + pnl, 2)
            if pnl >= 0:
                gross_profit += pnl
                best_trade    = max(best_trade, pnl)
            else:
                gross_loss   += abs(pnl)
                worst_trade   = min(worst_trade, pnl)
            trades.append({"pnl": pnl, "bars": n - 1 - entry_bar})
            equity.append(capital)

    # Aggregate metrics
    total_trades   = len(trades)
    winning_trades = sum(1 for t in trades if t["pnl"] >= 0)
    losing_trades  = total_trades - winning_trades
    win_rate       = round(winning_trades / total_trades * 100, 2) if total_trades else 0.0
    net_pnl        = round(capital - initial_capital, 2)
    net_pnl_pct    = round(net_pnl / initial_capital * 100, 2) if initial_capital else 0.0
    profit_factor  = (
        round(gross_profit / gross_loss, 2) if gross_loss > 0
        else (999.0 if gross_profit > 0 else 0.0)
    )
    avg_dur = (
        round(sum(t["bars"] for t in trades) / total_trades, 1)
        if total_trades else 0.0
    )

    # Annualised Sharpe from trade-level returns
    returns = []
    for j in range(1, len(equity)):
        if equity[j - 1] > 0:
            returns.append((equity[j] - equity[j - 1]) / equity[j - 1])
    sharpe = 0.0
    if len(returns) >= 2:
        mu  = sum(returns) / len(returns)
        sd  = math.sqrt(sum((r - mu) ** 2 for r in returns) / len(returns))
        sharpe = round(mu / sd * math.sqrt(252) if sd > 0 else 0.0, 2)

    return {
        "total_trades":     total_trades,
        "winning_trades":   winning_trades,
        "losing_trades":    losing_trades,
        "win_rate":         win_rate,
        "net_pnl":          net_pnl,
        "net_pnl_pct":      net_pnl_pct,
        "profit_factor":    profit_factor,
        "max_drawdown":     round(max_dd_abs, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "sharpe_ratio":     sharpe,
        "avg_duration_bars": avg_dur,
        "best_trade":       round(best_trade, 2),
        "worst_trade":      round(worst_trade, 2),
    }


def run_strategy_lab(
    symbol:          str,
    start_date:      str,
    end_date:        str,
    initial_capital: float = 5000.0,
    interval:        str   = "1d",
    strategy_ids:    list  | None = None,
) -> list:
    """
    Run all Lab strategies on the same OHLCV data (fetched & indicator-computed once).
    Returns list of StrategyLabEntry dicts — one per strategy.
    """
    from strategies import get_strategy, LAB_STRATEGY_IDS

    if strategy_ids is None:
        strategy_ids = LAB_STRATEGY_IDS

    # 1. Fetch data once
    try:
        period = _period_for_start(start_date)
        df = fetch_candles_df(
            symbol, interval=interval, period=period,
            start=start_date, end=end_date,
        )
    except Exception as exc:
        return [_empty_lab_entry(sid, str(exc)) for sid in strategy_ids]

    if df.empty or len(df) < WARMUP_BARS + 5:
        msg = f"Insufficient data: {len(df)} bars (need {WARMUP_BARS + 5}+)"
        return [_empty_lab_entry(sid, msg) for sid in strategy_ids]

    # 2. Compute indicators once
    try:
        enriched = compute_indicators_df(df)
    except Exception as exc:
        return [_empty_lab_entry(sid, f"Indicator error: {exc}") for sid in strategy_ids]

    rows = enriched.reset_index(drop=False)

    # 3. Run each strategy sequentially on shared enriched data
    results: list = []
    for sid in strategy_ids:
        try:
            strategy = get_strategy(sid)
            metrics  = _run_lab_walk(rows, strategy, initial_capital)
            results.append(StrategyLabEntry(
                strategy_id       = strategy.id,
                strategy_name     = strategy.name,
                strategy_type     = strategy.type,
                best_regime       = strategy.best_regime,
                total_trades      = metrics["total_trades"],
                winning_trades    = metrics["winning_trades"],
                losing_trades     = metrics["losing_trades"],
                win_rate          = metrics["win_rate"],
                net_pnl           = metrics["net_pnl"],
                net_pnl_pct       = metrics["net_pnl_pct"],
                profit_factor     = metrics["profit_factor"],
                max_drawdown      = metrics["max_drawdown"],
                max_drawdown_pct  = metrics["max_drawdown_pct"],
                sharpe_ratio      = metrics["sharpe_ratio"],
                avg_duration_bars = metrics["avg_duration_bars"],
                best_trade        = metrics["best_trade"],
                worst_trade       = metrics["worst_trade"],
                error             = None,
            ))
        except Exception as exc:
            results.append(_empty_lab_entry(sid, str(exc)))

    return results
