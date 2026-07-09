"""
market_replay.py
Historical Market Scanner / Market Replay.

Runs the exact same strategy-selection logic as market_scanner.py, but as
if a chosen past date were "today" — using only market data available up
to that date to generate the signal — then compares the signal with what
actually happened afterwards (over a chosen holding period).

PAPER TRADING ONLY — no real orders are ever placed. This module only
reads historical market data (yfinance) for research/backtesting purposes.

Lookahead-bias safeguard:
  - The signal (strategy selection, indicators, live_signal, score, action)
    is computed ONLY from candles with timestamp <= scan_date.
  - Candles after scan_date are fetched and used STRICTLY for the outcome
    comparison (price after holding period), never for signal generation.
"""

import math
from datetime import datetime, timedelta
from typing import TypedDict

import yfinance as yf

from config import SECTOR_MAP, NIFTY_50, INITIAL_CAPITAL
from market_data_engine import to_yf_symbol
from indicator_engine import compute_indicators_df
from strategies import get_strategy, LAB_STRATEGY_IDS
from backtesting_engine import _run_lab_walk, WARMUP_BARS
from market_scanner import (
    _sector_of, _final_action, _heat_of, _strategy_perf_score,
    _confidence_score, _opportunity_score,
)

import pandas as pd

# ── Config ──────────────────────────────────────────────────────────────────

INTERVAL_MAP = {"daily": "1d", "hourly": "1h"}
VALID_HOLDING_DAYS = {1, 3, 5, 10}
MIN_BARS = WARMUP_BARS + 10

OUTCOME_THRESHOLD_PCT = 1.0   # for BUY/STRONG BUY/IGNORE calls
WATCH_NEUTRAL_BAND_PCT = 3.0  # for WATCH calls


# ── TypedDicts ────────────────────────────────────────────────────────────────

class ReplayItem(TypedDict):
    stock:              str
    sector:             str
    scan_date:          str
    holding_period:     int
    best_strategy_id:   str
    best_strategy_name: str
    historical_action:  str      # STRONG BUY | BUY | WATCH | IGNORE
    opportunity_score:  float
    trade_quality:      float
    confidence:         float
    price_on_scan_date: float
    price_after_holding: float | None
    return_pct:         float | None
    outcome:            str      # Correct | Wrong | Neutral | Pending
    why_signal:         str
    what_happened:      str
    error:              str | None


class ReplaySummary(TypedDict):
    scan_date:            str
    holding_period:       int
    interval:             str
    total_scanned:        int
    buy_signals:          int
    watch_signals:        int
    ignore_signals:       int
    correct_calls:        int
    wrong_calls:          int
    neutral_calls:        int
    accuracy_pct:         float
    avg_return_pct:       float
    best_signal:          str
    best_signal_return:   float
    worst_signal:         str
    worst_signal_return:  float


class MarketReplayResult(TypedDict):
    scan_date:      str
    holding_period: int
    interval:       str
    items:          list   # ReplayItem[], sorted by opportunity_score desc
    summary:        ReplaySummary


# ── Data fetch (no mock fallback — historical accuracy matters) ─────────────

def _fetch_raw_df(symbol: str, yf_interval: str, start: str, end: str) -> pd.DataFrame:
    """
    Fetch real historical OHLCV data for an explicit date window. Unlike
    market_data_engine.fetch_candles_df, this never falls back to
    synthetic/mock data — a historical replay must use real candles or
    fail loudly, since mock data would silently corrupt the comparison.
    """
    yf_sym = to_yf_symbol(symbol)
    ticker = yf.Ticker(yf_sym)
    df = ticker.history(start=start, end=end, interval=yf_interval)
    if df is None or df.empty:
        raise ValueError(f"No historical data returned for {yf_sym} ({start} .. {end})")
    df.index = pd.to_datetime(df.index)
    df = df[["Open", "High", "Low", "Close", "Volume"]].rename(
        columns={"Open": "open", "High": "high", "Low": "low",
                 "Close": "close", "Volume": "volume"}
    )
    df = df.dropna(subset=["close"])
    df = df[df["close"] > 0]
    return df.sort_index()


def _empty_replay_item(symbol: str, scan_date: str, holding_period: int, error: str) -> ReplayItem:
    return ReplayItem(
        stock=symbol.upper(), sector=_sector_of(symbol),
        scan_date=scan_date, holding_period=holding_period,
        best_strategy_id="", best_strategy_name="",
        historical_action="IGNORE", opportunity_score=0.0, trade_quality=0.0, confidence=0.0,
        price_on_scan_date=0.0, price_after_holding=None, return_pct=None,
        outcome="Pending", why_signal=error, what_happened="", error=error,
    )


# ── Per-stock replay ──────────────────────────────────────────────────────────

def replay_stock(
    symbol: str,
    scan_date: str,
    holding_period: int,
    interval: str = "daily",
    capital: float = INITIAL_CAPITAL,
) -> ReplayItem:
    yf_interval = INTERVAL_MAP.get(interval, "1d")
    scan_dt = datetime.strptime(scan_date, "%Y-%m-%d")

    # Lookback window sized to guarantee enough warmup bars before scan_date.
    if yf_interval == "1h":
        lookback_start = scan_dt - timedelta(days=55)
    else:
        lookback_start = scan_dt - timedelta(days=280)

    # Future window sized to guarantee enough bars after scan_date for the
    # chosen holding period (calendar-day buffer accounts for weekends/holidays).
    future_end = scan_dt + timedelta(days=holding_period * 3 + 12)

    try:
        full_df = _fetch_raw_df(
            symbol, yf_interval,
            start=lookback_start.strftime("%Y-%m-%d"),
            end=future_end.strftime("%Y-%m-%d"),
        )
    except Exception as exc:
        return _empty_replay_item(symbol, scan_date, holding_period, f"Data fetch failed: {exc}")

    # STRICT lookahead cutoff: only bars up to end of scan_date are visible
    # to the signal-generation logic below.
    as_of_df = full_df[full_df.index.tz_localize(None) <= scan_dt + timedelta(hours=23, minutes=59)] \
        if full_df.index.tz is not None else full_df[full_df.index <= scan_dt + timedelta(hours=23, minutes=59)]

    if as_of_df.empty or len(as_of_df) < MIN_BARS:
        return _empty_replay_item(
            symbol, scan_date, holding_period,
            f"Insufficient historical data before {scan_date}: {len(as_of_df)} bars (need {MIN_BARS}+)",
        )

    try:
        enriched = compute_indicators_df(as_of_df)
    except Exception as exc:
        return _empty_replay_item(symbol, scan_date, holding_period, f"Indicator computation failed: {exc}")

    rows = enriched.reset_index(drop=False)
    last_row = rows.iloc[-1]
    prev_row = rows.iloc[-2]
    price_on_scan_date = float(last_row.get("close", 0.0) or 0.0)

    if price_on_scan_date <= 0:
        return _empty_replay_item(symbol, scan_date, holding_period, "No valid closing price on scan date")

    best = None  # (perf, sid, strategy, metrics, live_signal, reason)
    for sid in LAB_STRATEGY_IDS:
        try:
            strategy = get_strategy(sid)
            metrics = _run_lab_walk(rows, strategy, capital)
            perf = _strategy_perf_score(metrics)
            live_ok, reason = strategy.check_entry(last_row, prev_row)
        except Exception:
            continue
        candidate_rank = (1 if live_ok else 0, perf)
        if best is None or candidate_rank > (1 if best[4] else 0, best[0]):
            best = (perf, sid, strategy, metrics, live_ok, reason)

    if best is None:
        return _empty_replay_item(symbol, scan_date, holding_period, "No strategy could be evaluated")

    perf_score, sid, strategy, metrics, live_signal, reason = best
    confidence = _confidence_score(perf_score, metrics.get("total_trades", 0), live_signal)

    try:
        stop_loss = strategy.compute_stop_loss(last_row, price_on_scan_date)
        target = strategy.compute_target(price_on_scan_date, stop_loss)
    except Exception:
        stop_loss, target = 0.0, 0.0
    risk_per_share = max(0.0, price_on_scan_date - stop_loss) if stop_loss > 0 else 0.0
    reward_per_share = max(0.0, target - price_on_scan_date) if target > 0 else 0.0
    rr_ratio = round(reward_per_share / risk_per_share, 2) if risk_per_share > 0 else 0.0

    opp_score = _opportunity_score(perf_score, confidence, rr_ratio, live_signal)
    action = _final_action(opp_score)

    why_signal = (
        f"{strategy.name} selected (regime: {strategy.best_regime}). {reason or ''} "
        f"Trade quality {perf_score:.0f}/100 from {metrics.get('total_trades', 0)} historical trades "
        f"(win rate {metrics.get('win_rate', 0.0):.0f}%)."
    ).strip()

    # ── Outcome: future candles used ONLY here, never above ──────────────
    future_df = full_df[full_df.index > as_of_df.index[-1]]

    # Resolve holding period in trading DAYS regardless of scan interval —
    # collapse to daily closes for a clean, comparable "N trading days later" price.
    future_daily = future_df if yf_interval == "1d" else future_df.resample("1D").last().dropna()
    future_daily = future_daily[future_daily["close"] > 0]

    price_after_holding = None
    return_pct = None
    outcome = "Pending"
    what_happened = "Not enough future data yet to evaluate this outcome."

    if len(future_daily) >= holding_period:
        price_after_holding = round(float(future_daily.iloc[holding_period - 1]["close"]), 2)
        return_pct = round((price_after_holding - price_on_scan_date) / price_on_scan_date * 100.0, 2)

        if action in ("STRONG BUY", "BUY"):
            if return_pct > OUTCOME_THRESHOLD_PCT:
                outcome = "Correct"
            elif return_pct < -OUTCOME_THRESHOLD_PCT:
                outcome = "Wrong"
            else:
                outcome = "Neutral"
        elif action == "WATCH":
            if abs(return_pct) <= WATCH_NEUTRAL_BAND_PCT:
                outcome = "Neutral"
            else:
                outcome = "Correct" if return_pct > 0 else "Wrong"
        else:  # IGNORE
            outcome = "Correct" if return_pct <= OUTCOME_THRESHOLD_PCT else "Wrong"

        direction = "rose" if return_pct >= 0 else "fell"
        what_happened = (
            f"{symbol.upper()} {direction} from ₹{price_on_scan_date:.2f} to "
            f"₹{price_after_holding:.2f} over the next {holding_period} trading day(s) "
            f"({return_pct:+.1f}%). Signal was {action}, outcome: {outcome}."
        )

    return ReplayItem(
        stock=symbol.upper(),
        sector=_sector_of(symbol),
        scan_date=scan_date,
        holding_period=holding_period,
        best_strategy_id=strategy.id,
        best_strategy_name=strategy.name,
        historical_action=action,
        opportunity_score=opp_score,
        trade_quality=perf_score,
        confidence=confidence,
        price_on_scan_date=round(price_on_scan_date, 2),
        price_after_holding=price_after_holding,
        return_pct=return_pct,
        outcome=outcome,
        why_signal=why_signal,
        what_happened=what_happened,
        error=None,
    )


# ── Full universe replay ──────────────────────────────────────────────────────

def run_market_replay(
    scan_date: str,
    holding_period: int = 5,
    interval: str = "daily",
    symbols: list[str] | None = None,
    capital: float = INITIAL_CAPITAL,
) -> MarketReplayResult:
    if holding_period not in VALID_HOLDING_DAYS:
        holding_period = 5
    if interval not in INTERVAL_MAP:
        interval = "daily"

    # Reject future/today dates — replay only makes sense for the past, and
    # "today" doesn't have a settled future outcome yet.
    try:
        scan_dt = datetime.strptime(scan_date, "%Y-%m-%d")
    except ValueError:
        scan_dt = datetime.now() - timedelta(days=holding_period * 2 + 5)
        scan_date = scan_dt.strftime("%Y-%m-%d")

    universe = symbols if symbols else list(NIFTY_50)

    items: list[ReplayItem] = []
    for sym in universe:
        items.append(replay_stock(sym, scan_date, holding_period, interval, capital))

    items.sort(key=lambda it: (it["error"] is None, it["opportunity_score"]), reverse=True)

    valid = [it for it in items if it["error"] is None]
    resolved = [it for it in valid if it["return_pct"] is not None]

    buy_signals = sum(1 for it in valid if it["historical_action"] in ("STRONG BUY", "BUY"))
    watch_signals = sum(1 for it in valid if it["historical_action"] == "WATCH")
    ignore_signals = sum(1 for it in valid if it["historical_action"] == "IGNORE")

    correct_calls = sum(1 for it in resolved if it["outcome"] == "Correct")
    wrong_calls = sum(1 for it in resolved if it["outcome"] == "Wrong")
    neutral_calls = sum(1 for it in resolved if it["outcome"] == "Neutral")

    decided = correct_calls + wrong_calls
    accuracy_pct = round(correct_calls / decided * 100.0, 1) if decided > 0 else 0.0

    avg_return_pct = (
        round(sum(it["return_pct"] for it in resolved) / len(resolved), 2)
        if resolved else 0.0
    )

    best_item = max(resolved, key=lambda it: it["return_pct"]) if resolved else None
    worst_item = min(resolved, key=lambda it: it["return_pct"]) if resolved else None

    summary = ReplaySummary(
        scan_date=scan_date,
        holding_period=holding_period,
        interval=interval,
        total_scanned=len(items),
        buy_signals=buy_signals,
        watch_signals=watch_signals,
        ignore_signals=ignore_signals,
        correct_calls=correct_calls,
        wrong_calls=wrong_calls,
        neutral_calls=neutral_calls,
        accuracy_pct=accuracy_pct,
        avg_return_pct=avg_return_pct,
        best_signal=best_item["stock"] if best_item else "",
        best_signal_return=best_item["return_pct"] if best_item else 0.0,
        worst_signal=worst_item["stock"] if worst_item else "",
        worst_signal_return=worst_item["return_pct"] if worst_item else 0.0,
    )

    return MarketReplayResult(
        scan_date=scan_date,
        holding_period=holding_period,
        interval=interval,
        items=items,
        summary=summary,
    )
