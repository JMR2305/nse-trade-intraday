"""
strategy_optimizer.py
Tests parameter combinations for 4 strategies and ranks them by composite score.

Parameter grids:
  EMA Cross      : fast (9/10/20) × slow (21/30/50)           →  9 combos
  RSI Mean Rev.  : oversold (25/30/35) × overbought (65/70/75) →  9 combos
  Trend Rider    : fast_ema (9/20) × mid_ema (20/50) [valid only fast<mid]
                   × rsi_range (2) × atr_stop (2) × atr_target (2)  → 24 combos
  Supertrend     : period (7/10/14) × multiplier (2/3/4)       →  9 combos

Total: 51 combinations.

Scoring formula (all components normalised 0-1):
  score = win_rate_norm  * 0.25
        + pf_norm        * 0.25
        + pnl_norm       * 0.20
        + sharpe_norm    * 0.15
        - dd_penalty     * 0.15
  Multiplied by 100 → range roughly 0-85.
"""

import math
from typing import TypedDict

import numpy as np
import pandas as pd

from backtesting_engine import WARMUP_BARS, _period_for_start, _safe_float as _sf
from market_data_engine import fetch_candles_df
from indicator_engine import compute_indicators_df, _ema  # _ema is the internal EMA helper


# ── TypedDicts ────────────────────────────────────────────────────────────────

class OptimizerResult(TypedDict):
    strategy_id:        str
    strategy_name:      str
    parameters_display: str
    parameters:         dict
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
    score:              float
    warning:            str | None


# ── Generic walk-forward simulation ──────────────────────────────────────────

def _walk_fwd(
    rows,
    entry_fn,
    exit_fn,
    stop_fn,
    target_fn,
    risk_pct: float,
    initial_capital: float,
) -> dict:
    """
    Generic bar-by-bar walk-forward simulation.
    entry_fn(row, prev) → bool
    exit_fn(row, prev)  → bool
    stop_fn(row, ep)    → float
    target_fn(ep, sl)   → float
    """
    capital = initial_capital
    in_pos  = False
    ep = sl = tgt = 0.0
    qty = entry_bar = 0

    trades: list  = []
    equity: list  = [capital]
    peak          = capital
    max_dd        = 0.0
    max_dd_pct    = 0.0
    gross_profit  = 0.0
    gross_loss    = 0.0
    best_trade    = 0.0
    worst_trade   = 0.0

    n = len(rows)

    for i in range(WARMUP_BARS, n):
        row  = rows.iloc[i]
        prev = rows.iloc[i - 1]

        close = _sf(row.get("close", 0))
        high  = _sf(row.get("high",  0))
        low   = _sf(row.get("low",   0))
        if close <= 0:
            continue

        if in_pos:
            exit_price = close
            triggered  = False

            if low > 0 and low <= sl:
                exit_price = sl;  triggered = True
            elif high > 0 and high >= tgt:
                exit_price = tgt; triggered = True
            elif exit_fn(row, prev):
                triggered = True

            if triggered:
                pnl     = round((exit_price - ep) * qty, 2)
                capital = round(capital + pnl, 2)
                if pnl >= 0:
                    gross_profit += pnl
                    best_trade    = max(best_trade, pnl)
                else:
                    gross_loss   += abs(pnl)
                    worst_trade   = min(worst_trade, pnl)

                trades.append({"pnl": pnl, "bars": i - entry_bar})
                in_pos = False
                equity.append(capital)

                if capital > peak:
                    peak = capital
                else:
                    dd     = peak - capital
                    dd_pct = dd / peak * 100 if peak > 0 else 0.0
                    max_dd     = max(max_dd, dd)
                    max_dd_pct = max(max_dd_pct, dd_pct)
        else:
            if entry_fn(row, prev):
                new_sl  = stop_fn(row, close)
                new_tgt = target_fn(close, new_sl)
                rps     = close - new_sl
                if rps <= 0 or new_sl <= 0 or new_tgt <= close:
                    continue
                new_qty = int(capital * risk_pct / rps)
                if new_qty < 1:
                    continue
                in_pos    = True
                ep        = close
                sl        = new_sl
                tgt       = new_tgt
                entry_bar = i
                qty       = new_qty

    # Close open position at last bar
    if in_pos and n > WARMUP_BARS:
        lc = _sf(rows.iloc[n - 1].get("close", 0))
        if lc > 0:
            pnl     = round((lc - ep) * qty, 2)
            capital = round(capital + pnl, 2)
            if pnl >= 0:
                gross_profit += pnl
                best_trade    = max(best_trade, pnl)
            else:
                gross_loss   += abs(pnl)
                worst_trade   = min(worst_trade, pnl)
            trades.append({"pnl": pnl, "bars": n - 1 - entry_bar})
            equity.append(capital)

    total  = len(trades)
    wins   = sum(1 for t in trades if t["pnl"] >= 0)
    wr     = round(wins / total * 100, 2) if total else 0.0
    pnl    = round(capital - initial_capital, 2)
    pnl_p  = round(pnl / initial_capital * 100, 2) if initial_capital else 0.0
    pf     = (round(gross_profit / gross_loss, 2) if gross_loss > 0
              else (999.0 if gross_profit > 0 else 0.0))
    avg_d  = round(sum(t["bars"] for t in trades) / total, 1) if total else 0.0

    # Annualised Sharpe from equity steps
    rets = [
        (equity[j] - equity[j - 1]) / equity[j - 1]
        for j in range(1, len(equity))
        if equity[j - 1] > 0
    ]
    sharpe = 0.0
    if len(rets) >= 2:
        mu  = sum(rets) / len(rets)
        sd  = math.sqrt(sum((r - mu) ** 2 for r in rets) / len(rets))
        sharpe = round(mu / sd * math.sqrt(252) if sd > 0 else 0.0, 2)

    return {
        "total_trades":      total,
        "winning_trades":    wins,
        "losing_trades":     total - wins,
        "win_rate":          wr,
        "net_pnl":           pnl,
        "net_pnl_pct":       pnl_p,
        "profit_factor":     pf,
        "max_drawdown":      round(max_dd, 2),
        "max_drawdown_pct":  round(max_dd_pct, 2),
        "sharpe_ratio":      sharpe,
        "avg_duration_bars": avg_d,
    }


# ── Scoring & warnings ────────────────────────────────────────────────────────

def _score(m: dict) -> float:
    """
    Composite score (0-100 scale, higher is better).
    Components normalised to 0-1:
      win_rate_norm  = win_rate / 100
      pf_norm        = min(profit_factor, 5) / 5
      pnl_norm       = max(0, min(net_pnl_pct, 30)) / 30
      sharpe_norm    = max(0, min(sharpe, 3)) / 3
      dd_penalty     = min(max_drawdown_pct, 30) / 30
    """
    wr_n  = m["win_rate"] / 100.0
    pf_n  = min(m["profit_factor"], 5.0) / 5.0
    pnl_n = max(0.0, min(m["net_pnl_pct"], 30.0)) / 30.0
    sh_n  = max(0.0, min(m["sharpe_ratio"], 3.0)) / 3.0
    dd_p  = min(m["max_drawdown_pct"], 30.0) / 30.0

    raw = (
        wr_n  * 0.25
        + pf_n  * 0.25
        + pnl_n * 0.20
        + sh_n  * 0.15
        - dd_p  * 0.15
    )
    return round(raw * 100, 2)


def _warning(m: dict) -> str | None:
    t  = m["total_trades"]
    wr = m["win_rate"]
    if t == 0:
        return "No trades generated"
    if t < 5 and wr == 100.0:
        return "Not reliable yet"
    if t < 5:
        return "Low sample size"
    return None


# ── Strategy-specific optimized walk functions ────────────────────────────────

def _run_ema_cross(rows, fast_col: str, slow_col: str, initial_capital: float) -> dict:
    def entry(row, prev):
        f   = _sf(row.get(fast_col,  0))
        s   = _sf(row.get(slow_col,  0))
        pf  = _sf(prev.get(fast_col, 0))
        ps  = _sf(prev.get(slow_col, 0))
        rsi = _sf(row.get("rsi",    50))
        return f > 0 and s > 0 and pf <= ps and f > s and rsi < 70

    def exit_(row, prev):
        f  = _sf(row.get(fast_col,  0))
        s  = _sf(row.get(slow_col,  0))
        pf = _sf(prev.get(fast_col, 0))
        ps = _sf(prev.get(slow_col, 0))
        return pf > ps and f < s

    def stop(row, ep):
        atr = _sf(row.get("atr", 0)) or ep * 0.02
        return round(ep - 2.0 * atr, 2)

    def target(ep, sl):
        return round(ep + 2.0 * (ep - sl), 2)

    return _walk_fwd(rows, entry, exit_, stop, target, 0.01, initial_capital)


def _run_mean_reversion(rows, oversold: int, overbought: int, initial_capital: float) -> dict:
    def entry(row, prev):
        rsi    = _sf(row.get("rsi",      50))
        close  = _sf(row.get("close",     0))
        bb_low = _sf(row.get("bb_lower",  0))
        adx    = _sf(row.get("adx",       0))
        return close > 0 and bb_low > 0 and rsi < oversold and close <= bb_low * 1.01 and adx < 35

    def exit_(row, prev):
        rsi    = _sf(row.get("rsi",      50))
        close  = _sf(row.get("close",     0))
        bb_mid = _sf(row.get("bb_middle", 0))
        return rsi > overbought or (bb_mid > 0 and close > bb_mid)

    def stop(row, ep):
        atr = _sf(row.get("atr", 0)) or ep * 0.015
        return round(ep - 1.5 * atr, 2)

    def target(ep, sl):
        return round(ep + 1.5 * (ep - sl), 2)

    return _walk_fwd(rows, entry, exit_, stop, target, 0.01, initial_capital)


def _run_trend_rider(
    rows,
    fast_col: str, mid_col: str, slow_col: str,
    rsi_min: int, rsi_max: int,
    atr_stop: float, atr_tgt: float,
    initial_capital: float,
) -> dict:
    def entry(row, prev):
        f   = _sf(row.get(fast_col, 0))
        m   = _sf(row.get(mid_col,  0))
        s   = _sf(row.get(slow_col, 0))
        rsi = _sf(row.get("rsi",    50))
        ml  = _sf(row.get("macd_line",   0))
        ms  = _sf(row.get("macd_signal", 0))
        cl  = _sf(row.get("close", 0))
        vw  = _sf(row.get("vwap",  0))
        if not (f > 0 and m > 0):
            return False
        stacked = (f > m > s) if s > 0 else (f > m)
        return stacked and rsi_min <= rsi <= rsi_max and ml > ms and vw > 0 and cl > vw

    def exit_(row, prev):
        f  = _sf(row.get(fast_col,  0))
        m  = _sf(row.get(mid_col,   0))
        pf = _sf(prev.get(fast_col, 0))
        pm = _sf(prev.get(mid_col,  0))
        return pf > pm and f < m

    def stop(row, ep):
        atr = _sf(row.get("atr", 0)) or ep * 0.02
        return round(ep - atr_stop * atr, 2)

    def target(ep, sl):
        return round(ep + atr_tgt * (ep - sl), 2)

    return _walk_fwd(rows, entry, exit_, stop, target, 0.01, initial_capital)


def _run_supertrend(rows, st_line_col: str, st_dir_col: str, initial_capital: float) -> dict:
    def entry(row, prev):
        sd  = str(row.get(st_dir_col,  "DOWN"))
        psd = str(prev.get(st_dir_col, "DOWN"))
        cl  = _sf(row.get("close",       0))
        stl = _sf(row.get(st_line_col,   0))
        return psd == "DOWN" and sd == "UP" and cl > 0 and stl > 0 and cl > stl

    def exit_(row, prev):
        return str(row.get(st_dir_col, "UP")) == "DOWN"

    def stop(row, ep):
        stl = _sf(row.get(st_line_col, 0))
        if 0 < stl < ep:
            return round(stl, 2)
        atr = _sf(row.get("atr", 0)) or ep * 0.02
        return round(ep - 2.0 * atr, 2)

    def target(ep, sl):
        return round(ep + 3.0 * (ep - sl), 2)

    return _walk_fwd(rows, entry, exit_, stop, target, 0.01, initial_capital)


# ── Supertrend computation ────────────────────────────────────────────────────

def _build_supertrend(df_raw: pd.DataFrame, period: int, multiplier: float):
    """
    Compute Supertrend with custom period/multiplier.
    Returns (line_series, direction_series) aligned to df_raw.index.
    """
    high  = df_raw["high"]
    low   = df_raw["low"]
    close = df_raw["close"]

    # True Range
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()

    hl2   = (high + low) / 2.0
    ub_raw = hl2 + multiplier * atr
    lb_raw = hl2 - multiplier * atr

    # Finalise bands
    ub = ub_raw.copy()
    lb = lb_raw.copy()
    for i in range(1, len(df_raw)):
        ub.iloc[i] = (ub_raw.iloc[i]
                      if ub_raw.iloc[i] < ub.iloc[i - 1] or close.iloc[i - 1] > ub.iloc[i - 1]
                      else ub.iloc[i - 1])
        lb.iloc[i] = (lb_raw.iloc[i]
                      if lb_raw.iloc[i] > lb.iloc[i - 1] or close.iloc[i - 1] < lb.iloc[i - 1]
                      else lb.iloc[i - 1])

    # Direction + line
    st_line = pd.Series(index=df_raw.index, dtype=float)
    st_dir  = pd.Series(index=df_raw.index, dtype=str)
    st_line.iloc[0] = lb.iloc[0]
    st_dir.iloc[0]  = "UP"

    for i in range(1, len(df_raw)):
        prev_line = st_line.iloc[i - 1]
        if prev_line == ub.iloc[i - 1]:
            # Was in DOWN
            if close.iloc[i] > ub.iloc[i]:
                st_dir.iloc[i]  = "UP"
                st_line.iloc[i] = lb.iloc[i]
            else:
                st_dir.iloc[i]  = "DOWN"
                st_line.iloc[i] = ub.iloc[i]
        else:
            # Was in UP
            if close.iloc[i] < lb.iloc[i]:
                st_dir.iloc[i]  = "DOWN"
                st_line.iloc[i] = ub.iloc[i]
            else:
                st_dir.iloc[i]  = "UP"
                st_line.iloc[i] = lb.iloc[i]

    return st_line, st_dir


# ── Main optimizer entry point ────────────────────────────────────────────────

def run_optimizer(
    symbol:          str,
    start_date:      str,
    end_date:        str,
    initial_capital: float = 5000.0,
    interval:        str   = "1d",
    top_n:           int   = 10,
) -> list:
    """
    Run all parameter combinations and return the top_n by score.
    Data loaded and indicators computed once for efficiency.
    """
    # 1. Fetch data
    try:
        period = _period_for_start(start_date)
        df_raw = fetch_candles_df(
            symbol, interval=interval, period=period,
            start=start_date, end=end_date,
        )
    except Exception as exc:
        return [{"error": str(exc)}]

    if df_raw.empty or len(df_raw) < WARMUP_BARS + 5:
        return [{"error": f"Insufficient data: {len(df_raw)} bars"}]

    # 2. Compute base indicators (ema9/20/50/200, rsi, macd, bb, atr, adx, vwap, supertrend@10×3)
    try:
        enriched = compute_indicators_df(df_raw.copy())
    except Exception as exc:
        return [{"error": f"Indicator error: {exc}"}]

    # 3. Add extra EMA columns needed by the optimizer
    close = enriched["close"]
    for period_val in [10, 21, 30]:
        col = f"ema{period_val}"
        if col not in enriched.columns:
            enriched[col] = _ema(close, period_val)

    # 4. Compute custom Supertrend variants and attach to enriched
    st_variants: dict = {}   # (period, mult) → (line_col, dir_col)
    for st_period in [7, 10, 14]:
        for st_mult in [2.0, 3.0, 4.0]:
            key      = (st_period, st_mult)
            line_col = f"_st_line_{st_period}_{int(st_mult * 10)}"
            dir_col  = f"_st_dir_{st_period}_{int(st_mult * 10)}"
            try:
                st_line, st_dir_s = _build_supertrend(df_raw, st_period, st_mult)
                enriched[line_col] = st_line.values
                enriched[dir_col]  = st_dir_s.values
                st_variants[key]   = (line_col, dir_col)
            except Exception:
                pass

    rows = enriched.reset_index(drop=False)
    results: list = []

    # ── EMA Cross ──────────────────────────────────────────────────────────────
    for fast in [9, 10, 20]:
        for slow in [21, 30, 50]:
            if fast >= slow:
                continue
            fast_col = f"ema{fast}"
            slow_col = f"ema{slow}"
            try:
                m = _run_ema_cross(rows, fast_col, slow_col, initial_capital)
            except Exception as exc:
                m = {"total_trades": 0, "winning_trades": 0, "losing_trades": 0,
                     "win_rate": 0.0, "net_pnl": 0.0, "net_pnl_pct": 0.0,
                     "profit_factor": 0.0, "max_drawdown": 0.0, "max_drawdown_pct": 0.0,
                     "sharpe_ratio": 0.0, "avg_duration_bars": 0.0}
            params = {"fast_ema": fast, "slow_ema": slow}
            results.append(OptimizerResult(
                strategy_id="ema_cross", strategy_name="EMA Cross",
                parameters_display=f"EMA {fast}/{slow}",
                parameters=params, **m,
                score=_score(m), warning=_warning(m),
            ))

    # ── RSI Mean Reversion ─────────────────────────────────────────────────────
    for oversold in [25, 30, 35]:
        for overbought in [65, 70, 75]:
            try:
                m = _run_mean_reversion(rows, oversold, overbought, initial_capital)
            except Exception:
                m = {"total_trades": 0, "winning_trades": 0, "losing_trades": 0,
                     "win_rate": 0.0, "net_pnl": 0.0, "net_pnl_pct": 0.0,
                     "profit_factor": 0.0, "max_drawdown": 0.0, "max_drawdown_pct": 0.0,
                     "sharpe_ratio": 0.0, "avg_duration_bars": 0.0}
            params = {"oversold": oversold, "overbought": overbought}
            results.append(OptimizerResult(
                strategy_id="mean_reversion", strategy_name="RSI Mean Reversion",
                parameters_display=f"OS={oversold} OB={overbought}",
                parameters=params, **m,
                score=_score(m), warning=_warning(m),
            ))

    # ── Trend Rider ────────────────────────────────────────────────────────────
    for fast in [9, 20]:
        for mid in [20, 50]:
            if fast >= mid:
                continue
            slow     = "ema50"  if mid == 20 else "ema200"
            fast_col = f"ema{fast}"
            mid_col  = f"ema{mid}"
            slow_label = 50 if mid == 20 else 200
            for (rsi_min, rsi_max) in [(40, 68), (45, 65)]:
                for atr_stop in [1.5, 2.0]:
                    for atr_tgt in [2.0, 3.0]:
                        try:
                            m = _run_trend_rider(
                                rows, fast_col, mid_col, slow,
                                rsi_min, rsi_max, atr_stop, atr_tgt,
                                initial_capital,
                            )
                        except Exception:
                            m = {"total_trades": 0, "winning_trades": 0, "losing_trades": 0,
                                 "win_rate": 0.0, "net_pnl": 0.0, "net_pnl_pct": 0.0,
                                 "profit_factor": 0.0, "max_drawdown": 0.0, "max_drawdown_pct": 0.0,
                                 "sharpe_ratio": 0.0, "avg_duration_bars": 0.0}
                        params = {
                            "fast_ema": fast, "mid_ema": mid, "slow_ema": slow_label,
                            "rsi_min": rsi_min, "rsi_max": rsi_max,
                            "atr_stop": atr_stop, "atr_target": atr_tgt,
                        }
                        disp = (f"EMA {fast}/{mid}/{slow_label} · "
                                f"RSI {rsi_min}–{rsi_max} · "
                                f"ATR ×{atr_stop}/×{atr_tgt}")
                        results.append(OptimizerResult(
                            strategy_id="trend_rider", strategy_name="Trend Rider",
                            parameters_display=disp, parameters=params, **m,
                            score=_score(m), warning=_warning(m),
                        ))

    # ── Supertrend ─────────────────────────────────────────────────────────────
    for st_period in [7, 10, 14]:
        for st_mult in [2.0, 3.0, 4.0]:
            key = (st_period, st_mult)
            if key not in st_variants:
                continue
            line_col, dir_col = st_variants[key]
            try:
                m = _run_supertrend(rows, line_col, dir_col, initial_capital)
            except Exception:
                m = {"total_trades": 0, "winning_trades": 0, "losing_trades": 0,
                     "win_rate": 0.0, "net_pnl": 0.0, "net_pnl_pct": 0.0,
                     "profit_factor": 0.0, "max_drawdown": 0.0, "max_drawdown_pct": 0.0,
                     "sharpe_ratio": 0.0, "avg_duration_bars": 0.0}
            params = {"period": st_period, "multiplier": st_mult}
            results.append(OptimizerResult(
                strategy_id="supertrend_follow", strategy_name="Supertrend",
                parameters_display=f"P={st_period} × M={st_mult}",
                parameters=params, **m,
                score=_score(m), warning=_warning(m),
            ))

    # 5. Sort by score descending, assign ranks, return top_n
    results.sort(key=lambda r: r["score"], reverse=True)
    top = results[:top_n]
    for rank, r in enumerate(top, start=1):
        r["rank"] = rank  # type: ignore[typeddict-item]

    return top
