"""
strategy_optimizer.py  v0.8 — Strategy Robustness Analyzer

Changes from v0.7:
  - Reliability scoring (VERY LOW / LOW / MEDIUM / HIGH) based on trade count
  - Final Score = Raw Score × Reliability Multiplier (prevents over-weighting 1-trade wonders)
  - Multi-period testing: 3M / 6M / 1Y / 2Y slices from 2 years of fetched data
  - Stability score and profitable-period count
  - Robustness badge: A / B / C / D
  - Expanded warnings (including "Profit factor inflated due to no losses")
  - Always fetches 2Y of data so all 4 periods can be tested
  - Sorts by Final Score (not Raw Score)

Parameter grids (51 total combos):
  EMA Cross      : fast (9/10/20) × slow (21/30/50)            →  9 combos
  RSI Mean Rev.  : oversold (25/30/35) × overbought (65/70/75) →  9 combos
  Trend Rider    : fast_ema × mid_ema (valid only fast<mid)
                   × rsi_range(2) × atr_stop(2) × atr_target(2) → 24 combos
  Supertrend     : period (7/10/14) × multiplier (2/3/4)        →  9 combos
"""

import datetime
import math
import statistics
from typing import TypedDict

import numpy as np
import pandas as pd

from backtesting_engine import WARMUP_BARS, _period_for_start, _safe_float as _sf
from market_data_engine import fetch_candles_df
from indicator_engine import compute_indicators_df, _ema


# ── Multi-period slice config (approximate trading-day bars) ──────────────────
MULTI_PERIODS = [
    ("3M",   65),   # ~3 calendar months
    ("6M",  130),   # ~6 calendar months
    ("1Y",  260),   # ~1 year
    ("2Y",  520),   # ~2 years
]


# ── TypedDicts ────────────────────────────────────────────────────────────────

class MultiPeriodEntry(TypedDict):
    period:           str
    bars:             int
    trades:           int
    win_rate:         float
    net_pnl_pct:      float
    max_drawdown_pct: float
    profitable:       bool
    skipped:          bool


class OptimizerResult(TypedDict):
    # Identity
    rank:               int
    strategy_id:        str
    strategy_name:      str
    parameters_display: str
    parameters:         dict

    # Core metrics (from full 2Y data)
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

    # v0.8 scoring
    raw_score:              float   # composite score on full data (0-85)
    reliability_label:      str     # VERY LOW / LOW / MEDIUM / HIGH
    reliability_multiplier: float   # 0.10 / 0.40 / 0.70 / 1.00
    final_score:            float   # raw_score × reliability_multiplier

    # v0.8 warnings
    warning:   str | None    # primary (backward-compat)
    warnings:  list           # all active warnings

    # v0.8 multi-period stability
    multi_period:       list         # list of MultiPeriodEntry
    profitable_periods: int
    total_periods:      int
    avg_win_rate_mp:    float
    avg_drawdown_mp:    float
    stability_score:    float        # 0-100

    # v0.8 badge
    badge: str   # A / B / C / D


# ── Reliability scoring ───────────────────────────────────────────────────────

def _reliability(total_trades: int) -> tuple[str, float]:
    """Returns (label, multiplier)."""
    if total_trades < 5:
        return ("VERY LOW", 0.10)
    if total_trades < 20:
        return ("LOW", 0.40)
    if total_trades < 50:
        return ("MEDIUM", 0.70)
    return ("HIGH", 1.00)


# ── Warnings ──────────────────────────────────────────────────────────────────

def _warnings(m: dict) -> list[str]:
    t  = m.get("total_trades", 0)
    pf = m.get("profit_factor", 0.0)
    msgs: list[str] = []
    if t == 0:
        msgs.append("No trades generated")
    elif t < 5:
        msgs.append("Insufficient trade sample. Do not trust this result.")
    elif t < 20:
        msgs.append("Needs more data before live use.")
    if t > 0 and pf >= 999.0:
        msgs.append("Profit factor inflated due to no losses.")
    return msgs


# ── Composite score ───────────────────────────────────────────────────────────

def _raw_score(m: dict) -> float:
    """0-85 composite (all components normalised 0-1)."""
    wr_n  = m.get("win_rate", 0) / 100.0
    pf_n  = min(m.get("profit_factor", 0), 5.0) / 5.0
    pnl_n = max(0.0, min(m.get("net_pnl_pct", 0), 30.0)) / 30.0
    sh_n  = max(0.0, min(m.get("sharpe_ratio", 0), 3.0)) / 3.0
    dd_p  = min(m.get("max_drawdown_pct", 0), 30.0) / 30.0
    raw = (wr_n * 0.25 + pf_n * 0.25 + pnl_n * 0.20 + sh_n * 0.15 - dd_p * 0.15)
    return round(raw * 100, 2)


# ── Multi-period stability ────────────────────────────────────────────────────

def _stability_score(period_results: list) -> float:
    """0-100 score: higher = more consistent across time windows."""
    valid = [p for p in period_results if not p.get("skipped") and p.get("trades", 0) > 0]
    if not valid:
        return 0.0
    profitable_ratio = sum(1 for p in valid if p.get("profitable")) / len(valid)
    avg_wr  = sum(p["win_rate"] for p in valid) / len(valid) / 100.0
    avg_dd  = sum(p["max_drawdown_pct"] for p in valid) / len(valid)
    dd_pen  = min(avg_dd / 30.0, 1.0)
    # Consistency: punish high std-dev of win rates
    if len(valid) >= 2:
        wrs = [p["win_rate"] for p in valid]
        wr_std = statistics.stdev(wrs)
        consistency = max(0.0, 1.0 - wr_std / 50.0)
    else:
        consistency = 0.5
    score = (profitable_ratio * 0.45 + avg_wr * 0.25 + consistency * 0.10 - dd_pen * 0.20)
    return round(max(0.0, score * 100), 1)


# ── Robustness badge ──────────────────────────────────────────────────────────

def _badge(rel_label: str, profitable_periods: int, total_periods: int, final_score: float) -> str:
    if rel_label == "HIGH" and profitable_periods >= 3 and final_score >= 25:
        return "A"
    if rel_label in ("HIGH", "MEDIUM") and profitable_periods >= 2 and final_score >= 10:
        return "B"
    if final_score >= 5 and profitable_periods >= 1:
        return "C"
    return "D"


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
    capital   = initial_capital
    in_pos    = False
    ep = sl   = tgt = 0.0
    qty = entry_bar = 0
    trades: list = []
    equity: list = [capital]
    peak = capital
    max_dd = max_dd_pct = 0.0
    gross_p = gross_l = 0.0
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
                if pnl >= 0: gross_p += pnl
                else:        gross_l += abs(pnl)
                trades.append({"pnl": pnl, "bars": i - entry_bar})
                in_pos = False
                equity.append(capital)
                if capital > peak:
                    peak = capital
                else:
                    dd = peak - capital
                    ddp = dd / peak * 100 if peak > 0 else 0.0
                    max_dd     = max(max_dd, dd)
                    max_dd_pct = max(max_dd_pct, ddp)
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
                in_pos = True; ep = close; sl = new_sl; tgt = new_tgt
                entry_bar = i; qty = new_qty

    if in_pos and n > WARMUP_BARS:
        lc = _sf(rows.iloc[n - 1].get("close", 0))
        if lc > 0:
            pnl     = round((lc - ep) * qty, 2)
            capital = round(capital + pnl, 2)
            if pnl >= 0: gross_p += pnl
            else:        gross_l += abs(pnl)
            trades.append({"pnl": pnl, "bars": n - 1 - entry_bar})
            equity.append(capital)

    total = len(trades)
    wins  = sum(1 for t in trades if t["pnl"] >= 0)
    wr    = round(wins / total * 100, 2) if total else 0.0
    pnl   = round(capital - initial_capital, 2)
    pnl_p = round(pnl / initial_capital * 100, 2) if initial_capital else 0.0
    pf    = (round(gross_p / gross_l, 2) if gross_l > 0 else (999.0 if gross_p > 0 else 0.0))
    avg_d = round(sum(t["bars"] for t in trades) / total, 1) if total else 0.0

    rets = [(equity[j] - equity[j-1]) / equity[j-1]
            for j in range(1, len(equity)) if equity[j-1] > 0]
    sharpe = 0.0
    if len(rets) >= 2:
        mu = sum(rets) / len(rets)
        sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / len(rets))
        sharpe = round(mu / sd * math.sqrt(252) if sd > 0 else 0.0, 2)

    return {
        "total_trades": total, "winning_trades": wins, "losing_trades": total - wins,
        "win_rate": wr, "net_pnl": pnl, "net_pnl_pct": pnl_p,
        "profit_factor": pf, "max_drawdown": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd_pct, 2), "sharpe_ratio": sharpe,
        "avg_duration_bars": avg_d,
    }


# ── Strategy-specific runners ─────────────────────────────────────────────────

def _run_ema_cross(rows, fast_col, slow_col, cap):
    def entry(row, prev):
        f, s   = _sf(row.get(fast_col,0)),  _sf(row.get(slow_col,0))
        pf, ps = _sf(prev.get(fast_col,0)), _sf(prev.get(slow_col,0))
        rsi    = _sf(row.get("rsi", 50))
        return f>0 and s>0 and pf<=ps and f>s and rsi<70
    def exit_(row, prev):
        f, s   = _sf(row.get(fast_col,0)),  _sf(row.get(slow_col,0))
        pf, ps = _sf(prev.get(fast_col,0)), _sf(prev.get(slow_col,0))
        return pf>ps and f<s
    def stop(row, ep):
        atr = _sf(row.get("atr",0)) or ep*0.02
        return round(ep - 2.0*atr, 2)
    def target(ep, sl):
        return round(ep + 2.0*(ep-sl), 2)
    return _walk_fwd(rows, entry, exit_, stop, target, 0.01, cap)


def _run_mean_reversion(rows, oversold, overbought, cap):
    def entry(row, prev):
        rsi   = _sf(row.get("rsi",50));   cl = _sf(row.get("close",0))
        bbl   = _sf(row.get("bb_lower",0)); adx = _sf(row.get("adx",0))
        return cl>0 and bbl>0 and rsi<oversold and cl<=bbl*1.01 and adx<35
    def exit_(row, prev):
        rsi   = _sf(row.get("rsi",50));   cl = _sf(row.get("close",0))
        bbm   = _sf(row.get("bb_middle",0))
        return rsi>overbought or (bbm>0 and cl>bbm)
    def stop(row, ep):
        atr = _sf(row.get("atr",0)) or ep*0.015
        return round(ep - 1.5*atr, 2)
    def target(ep, sl):
        return round(ep + 1.5*(ep-sl), 2)
    return _walk_fwd(rows, entry, exit_, stop, target, 0.01, cap)


def _run_trend_rider(rows, fast_col, mid_col, slow_col, rsi_min, rsi_max, atr_stop, atr_tgt, cap):
    def entry(row, prev):
        f  = _sf(row.get(fast_col,0)); m  = _sf(row.get(mid_col,0))
        s  = _sf(row.get(slow_col,0)); rsi = _sf(row.get("rsi",50))
        ml = _sf(row.get("macd_line",0)); ms = _sf(row.get("macd_signal",0))
        cl = _sf(row.get("close",0));  vw = _sf(row.get("vwap",0))
        if not (f>0 and m>0): return False
        stacked = (f>m>s) if s>0 else (f>m)
        return stacked and rsi_min<=rsi<=rsi_max and ml>ms and vw>0 and cl>vw
    def exit_(row, prev):
        f  = _sf(row.get(fast_col,0));  m  = _sf(row.get(mid_col,0))
        pf = _sf(prev.get(fast_col,0)); pm = _sf(prev.get(mid_col,0))
        return pf>pm and f<m
    def stop(row, ep):
        atr = _sf(row.get("atr",0)) or ep*0.02
        return round(ep - atr_stop*atr, 2)
    def target(ep, sl):
        return round(ep + atr_tgt*(ep-sl), 2)
    return _walk_fwd(rows, entry, exit_, stop, target, 0.01, cap)


def _run_supertrend(rows, st_line_col, st_dir_col, cap):
    def entry(row, prev):
        sd  = str(row.get(st_dir_col,"DOWN")); psd = str(prev.get(st_dir_col,"DOWN"))
        cl  = _sf(row.get("close",0));         stl = _sf(row.get(st_line_col,0))
        return psd=="DOWN" and sd=="UP" and cl>0 and stl>0 and cl>stl
    def exit_(row, prev):
        return str(row.get(st_dir_col,"UP")) == "DOWN"
    def stop(row, ep):
        stl = _sf(row.get(st_line_col,0))
        if 0<stl<ep: return round(stl, 2)
        atr = _sf(row.get("atr",0)) or ep*0.02
        return round(ep - 2.0*atr, 2)
    def target(ep, sl):
        return round(ep + 3.0*(ep-sl), 2)
    return _walk_fwd(rows, entry, exit_, stop, target, 0.01, cap)


# ── Custom Supertrend indicator ───────────────────────────────────────────────

def _build_supertrend(df: pd.DataFrame, period: int, multiplier: float):
    high = df["high"]; low = df["low"]; close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high-low, (high-prev_close).abs(), (low-prev_close).abs()], axis=1
    ).max(axis=1)
    atr  = tr.ewm(span=period, adjust=False).mean()
    hl2  = (high + low) / 2.0
    ub_r = hl2 + multiplier * atr
    lb_r = hl2 - multiplier * atr
    ub   = ub_r.copy(); lb = lb_r.copy()
    for i in range(1, len(df)):
        ub.iloc[i] = (ub_r.iloc[i] if ub_r.iloc[i]<ub.iloc[i-1] or close.iloc[i-1]>ub.iloc[i-1] else ub.iloc[i-1])
        lb.iloc[i] = (lb_r.iloc[i] if lb_r.iloc[i]>lb.iloc[i-1] or close.iloc[i-1]<lb.iloc[i-1] else lb.iloc[i-1])
    st_line = pd.Series(index=df.index, dtype=float)
    st_dir  = pd.Series(index=df.index, dtype=str)
    st_line.iloc[0] = lb.iloc[0]; st_dir.iloc[0] = "UP"
    for i in range(1, len(df)):
        pl = st_line.iloc[i-1]
        if pl == ub.iloc[i-1]:
            st_dir.iloc[i]  = "UP"   if close.iloc[i]>ub.iloc[i] else "DOWN"
            st_line.iloc[i] = lb.iloc[i] if close.iloc[i]>ub.iloc[i] else ub.iloc[i]
        else:
            st_dir.iloc[i]  = "DOWN" if close.iloc[i]<lb.iloc[i] else "UP"
            st_line.iloc[i] = ub.iloc[i] if close.iloc[i]<lb.iloc[i] else lb.iloc[i]
    return st_line, st_dir


# ── Build combo list ──────────────────────────────────────────────────────────

def _build_combos(enriched: pd.DataFrame, initial_capital: float) -> list:
    """
    Returns a list of (strategy_id, strategy_name, parameters_display, parameters, runner_fn).
    runner_fn(rows) → metrics_dict
    Each combo is set up with pre-bound parameters via default-arg capture.
    """
    combos = []
    cap = initial_capital

    # ── EMA Cross
    for fast in [9, 10, 20]:
        for slow in [21, 30, 50]:
            if fast >= slow: continue
            fc, sc = f"ema{fast}", f"ema{slow}"
            combos.append((
                "ema_cross", "EMA Cross",
                f"EMA {fast}/{slow}",
                {"fast_ema": fast, "slow_ema": slow},
                lambda rows, fc=fc, sc=sc: _run_ema_cross(rows, fc, sc, cap),
            ))

    # ── RSI Mean Reversion
    for os_ in [25, 30, 35]:
        for ob in [65, 70, 75]:
            combos.append((
                "mean_reversion", "RSI Mean Rev.",
                f"OS={os_}  OB={ob}",
                {"oversold": os_, "overbought": ob},
                lambda rows, os_=os_, ob=ob: _run_mean_reversion(rows, os_, ob, cap),
            ))

    # ── Trend Rider
    for fast in [9, 20]:
        for mid in [20, 50]:
            if fast >= mid: continue
            sl_ema   = "ema50"  if mid == 20 else "ema200"
            sl_label = 50       if mid == 20 else 200
            fc, mc   = f"ema{fast}", f"ema{mid}"
            for (rsi_min, rsi_max) in [(40, 68), (45, 65)]:
                for atr_stop in [1.5, 2.0]:
                    for atr_tgt in [2.0, 3.0]:
                        disp = (f"EMA {fast}/{mid}/{sl_label} · "
                                f"RSI {rsi_min}–{rsi_max} · "
                                f"ATR ×{atr_stop}/×{atr_tgt}")
                        params = {
                            "fast_ema": fast, "mid_ema": mid, "slow_ema": sl_label,
                            "rsi_min": rsi_min, "rsi_max": rsi_max,
                            "atr_stop": atr_stop, "atr_target": atr_tgt,
                        }
                        combos.append((
                            "trend_rider", "Trend Rider", disp, params,
                            lambda rows, fc=fc, mc=mc, sl=sl_ema, mn=rsi_min, mx=rsi_max,
                                   ast=atr_stop, at=atr_tgt:
                                _run_trend_rider(rows, fc, mc, sl, mn, mx, ast, at, cap),
                        ))

    # ── Supertrend
    st_variants: dict = {}
    for p in [7, 10, 14]:
        for m in [2.0, 3.0, 4.0]:
            lc = f"_st_line_{p}_{int(m*10)}"
            dc = f"_st_dir_{p}_{int(m*10)}"
            if lc in enriched.columns:
                st_variants[(p, m)] = (lc, dc)

    for p in [7, 10, 14]:
        for m in [2.0, 3.0, 4.0]:
            if (p, m) not in st_variants: continue
            lc, dc = st_variants[(p, m)]
            combos.append((
                "supertrend_follow", "Supertrend",
                f"P={p} × M={m}",
                {"period": p, "multiplier": m},
                lambda rows, lc=lc, dc=dc: _run_supertrend(rows, lc, dc, cap),
            ))

    return combos


# ── Run multi-period for one combo ────────────────────────────────────────────

def _run_multi_period(runner_fn, period_slices: dict, initial_capital: float) -> list:
    results = []
    for label, (bars, slice_df) in period_slices.items():
        if slice_df is None or len(slice_df) < WARMUP_BARS + 5:
            results.append(MultiPeriodEntry(
                period=label, bars=bars, trades=0, win_rate=0.0,
                net_pnl_pct=0.0, max_drawdown_pct=0.0,
                profitable=False, skipped=True,
            ))
            continue
        try:
            m = runner_fn(slice_df)
            results.append(MultiPeriodEntry(
                period=label, bars=bars,
                trades=m["total_trades"],
                win_rate=m["win_rate"],
                net_pnl_pct=m["net_pnl_pct"],
                max_drawdown_pct=m["max_drawdown_pct"],
                profitable=m["net_pnl"] > 0,
                skipped=False,
            ))
        except Exception:
            results.append(MultiPeriodEntry(
                period=label, bars=bars, trades=0, win_rate=0.0,
                net_pnl_pct=0.0, max_drawdown_pct=0.0,
                profitable=False, skipped=True,
            ))
    return results


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
    Run all 51 parameter combinations with 4-period stability testing.
    Returns the top_n setups sorted by final_score (raw_score × reliability_multiplier).
    """
    # Always fetch 2 years for multi-period testing
    try:
        end_dt    = datetime.date.fromisoformat(end_date)
        start_2y  = (end_dt - datetime.timedelta(days=730)).isoformat()
        fetch_start = min(start_date, start_2y)
        period_str  = _period_for_start(fetch_start)
        df_raw = fetch_candles_df(
            symbol, interval=interval, period=period_str,
            start=fetch_start, end=end_date,
        )
    except Exception as exc:
        return [{"error": str(exc)}]

    if df_raw.empty or len(df_raw) < WARMUP_BARS + 5:
        return [{"error": f"Insufficient data: {len(df_raw)} bars fetched"}]

    # Compute indicators on full data
    try:
        enriched = compute_indicators_df(df_raw.copy())
    except Exception as exc:
        return [{"error": f"Indicator error: {exc}"}]

    # Add extra EMA columns
    close = enriched["close"]
    for p in [10, 21, 30]:
        col = f"ema{p}"
        if col not in enriched.columns:
            enriched[col] = _ema(close, p)

    # Build custom Supertrend variants
    for sp in [7, 10, 14]:
        for sm in [2.0, 3.0, 4.0]:
            lc = f"_st_line_{sp}_{int(sm*10)}"
            dc = f"_st_dir_{sp}_{int(sm*10)}"
            if lc not in enriched.columns:
                try:
                    st_l, st_d = _build_supertrend(df_raw, sp, sm)
                    enriched[lc] = st_l.values
                    enriched[dc] = st_d.values
                except Exception:
                    pass

    # Build period slices (last N bars, indexed as rows DataFrame)
    # Keys: "3M", "6M", "1Y", "2Y"
    period_slices: dict = {}
    n_total = len(enriched)
    for label, bars in MULTI_PERIODS:
        needed = bars + WARMUP_BARS
        if n_total >= needed:
            sl = enriched.iloc[-needed:].copy().reset_index(drop=False)
            period_slices[label] = (bars, sl)
        else:
            # Use whatever is available
            sl = enriched.reset_index(drop=False)
            period_slices[label] = (bars, sl if n_total >= WARMUP_BARS + 5 else None)

    # Full data as rows (main metrics)
    full_rows = enriched.reset_index(drop=False)

    # Build all 51 combos
    combos = _build_combos(enriched, initial_capital)

    results: list = []
    for (strat_id, strat_name, params_display, params, runner_fn) in combos:
        # Main metrics on full data
        try:
            m = runner_fn(full_rows)
        except Exception:
            m = {"total_trades":0,"winning_trades":0,"losing_trades":0,"win_rate":0.0,
                 "net_pnl":0.0,"net_pnl_pct":0.0,"profit_factor":0.0,"max_drawdown":0.0,
                 "max_drawdown_pct":0.0,"sharpe_ratio":0.0,"avg_duration_bars":0.0}

        # Reliability & scoring
        rel_label, rel_mult = _reliability(m["total_trades"])
        raw_sc    = _raw_score(m)
        final_sc  = round(raw_sc * rel_mult, 2)
        warns     = _warnings(m)
        primary_w = warns[0] if warns else None

        # Multi-period stability
        mp_results = _run_multi_period(runner_fn, period_slices, initial_capital)
        valid_mp   = [p for p in mp_results if not p.get("skipped") and p.get("trades",0)>0]
        prof_per   = sum(1 for p in valid_mp if p.get("profitable"))
        total_per  = sum(1 for p in mp_results if not p.get("skipped"))
        avg_wr_mp  = round(sum(p["win_rate"] for p in valid_mp)/len(valid_mp),1) if valid_mp else 0.0
        avg_dd_mp  = round(sum(p["max_drawdown_pct"] for p in valid_mp)/len(valid_mp),1) if valid_mp else 0.0
        stab_sc    = _stability_score(mp_results)

        # Robustness badge
        bdg = _badge(rel_label, prof_per, total_per, final_sc)

        results.append({
            "strategy_id":        strat_id,
            "strategy_name":      strat_name,
            "parameters_display": params_display,
            "parameters":         params,
            **m,
            "raw_score":              raw_sc,
            "reliability_label":      rel_label,
            "reliability_multiplier": rel_mult,
            "final_score":            final_sc,
            "warning":                primary_w,
            "warnings":               warns,
            "multi_period":           mp_results,
            "profitable_periods":     prof_per,
            "total_periods":          total_per,
            "avg_win_rate_mp":        avg_wr_mp,
            "avg_drawdown_mp":        avg_dd_mp,
            "stability_score":        stab_sc,
            "badge":                  bdg,
        })

    # Sort by final_score DESC, then raw_score DESC
    results.sort(key=lambda r: (r["final_score"], r["raw_score"]), reverse=True)
    for rank, r in enumerate(results[:top_n], start=1):
        r["rank"] = rank
    return results[:top_n]
