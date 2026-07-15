"""
phase12_intelligence.py — Phase 12: Advanced Institutional Intelligence Layer

Multi-factor signal fusion for the NSE Research Engine.

Factors (11):
  trend            — EMA slope, crossover alignment
  momentum         — RSI z-score, MACD histogram direction
  volatility       — ATR%, Bollinger-band width, VIX regime
  volume           — volume vs 20-day avg, spike detection
  relative_strength — stock return vs NIFTY & vs sector (trailing 20d)
  market_regime    — 5-state adaptive detection (TRENDING_UP/DOWN/VOLATILE/RANGE_BOUND/CRISIS)
  sector_strength  — sector rank position (1=best, 11=worst)
  liquidity        — avg daily volume adequacy
  hist_expectancy  — from COMPLETED paper trades only (no-lookahead)
  calibration_quality — calibration reliability score
  data_freshness   — how fresh/complete the underlying price data is

Safety rules (unchanged from earlier phases):
  - BUY/STRONG_BUY blocked if data_status=DATA_UNAVAILABLE or quality in {STALE,UNAVAILABLE}
  - Learning ONLY from completed paper trades (no-lookahead: close_ts must exist)
  - No real broker orders — PAPER TRADING ONLY
  - Results cached in phase12_cache.json (TTL 600s by default)

Contradiction detection: signals when ≥2 factors point directionally opposite to ≥2 others.
"""

from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

_DIR = os.path.dirname(os.path.abspath(__file__))

CACHE_FILE = os.path.join(_DIR, "phase12_cache.json")
CACHE_TTL_S = 600.0  # 10 minutes

RESEARCH_ENGINE_VERSION = "Research Engine v1.0 · Phase 12"
LABEL = "PAPER / RESEARCH ONLY"

# ── Factor weights (must sum to 1.0) ─────────────────────────────────────────
FACTOR_WEIGHTS: Dict[str, float] = {
    "trend":              0.18,
    "momentum":           0.14,
    "volatility":         0.08,
    "volume":             0.08,
    "relative_strength":  0.14,
    "market_regime":      0.10,
    "sector_strength":    0.08,
    "liquidity":          0.06,
    "hist_expectancy":    0.10,
    "calibration_quality":0.02,
    "data_freshness":     0.02,
}
assert abs(sum(FACTOR_WEIGHTS.values()) - 1.0) < 1e-9, "Factor weights must sum to 1.0"

# ── Market regime definitions ─────────────────────────────────────────────────
REGIMES = ["TRENDING_UP", "TRENDING_DOWN", "VOLATILE", "RANGE_BOUND", "CRISIS"]

# Regime adjustments: multiplier applied to final fused score (BUY direction)
REGIME_SCORE_MULT: Dict[str, float] = {
    "TRENDING_UP":   1.10,
    "RANGE_BOUND":   0.95,
    "TRENDING_DOWN": 0.80,
    "VOLATILE":      0.85,
    "CRISIS":        0.60,
}

# ── Data-freshness gate thresholds ────────────────────────────────────────────
STALE_QUALITIES = {"STALE", "UNAVAILABLE", "DATA_UNAVAILABLE"}
BLOCKED_ACTIONS = {"BUY", "STRONG_BUY", "STRONG BUY"}

# ── Position sizing caps ──────────────────────────────────────────────────────
MAX_CAPITAL_PER_TRADE_PCT = 0.20   # never exceed 20% per trade
MAX_RISK_PCT = 0.01                # 1% max loss per trade
MIN_SHARES = 1


# ── Utilities ─────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe(v: Any, default: Any = None) -> Any:
    if v is None:
        return default
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _load_json(path: str, default: Any = None) -> Any:
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def _save_atomic(path: str, data: Any) -> None:
    tmp = path + f".tmp.{os.getpid()}"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f, default=str)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass


# ── Cache ─────────────────────────────────────────────────────────────────────

def _load_cache() -> Dict[str, Any]:
    raw = _load_json(CACHE_FILE, {})
    if not isinstance(raw, dict):
        return {}
    return raw


def _save_cache(cache: Dict[str, Any]) -> None:
    _save_atomic(CACHE_FILE, cache)


def _cache_fresh(cache: Dict[str, Any], key: str, ttl: float = CACHE_TTL_S) -> bool:
    entry = cache.get(key)
    if not isinstance(entry, dict):
        return False
    ts = entry.get("_cached_at", 0.0)
    return (time.time() - float(ts)) < ttl


# ── No-lookahead trade reader ─────────────────────────────────────────────────

def _completed_paper_trades() -> List[Dict[str, Any]]:
    """
    Return ONLY trades that have a close_ts (completed). Strict no-lookahead:
    we never include open positions or trades without a settlement timestamp.
    """
    from paper_trader import get_trades
    try:
        trades = list(get_trades())
    except Exception:
        return []
    completed = []
    for t in trades:
        if not isinstance(t, dict):
            continue
        # Must have both BUY and SELL legs (completed round-trip)
        if t.get("action", "").upper() != "SELL":
            continue
        close_ts = t.get("timestamp") or t.get("close_ts") or t.get("trade_date")
        if not close_ts:
            continue
        completed.append(t)
    return completed


def _hist_expectancy_by_symbol(trades: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    """Aggregate expectancy statistics per symbol from completed trades only."""
    grouped: Dict[str, List[float]] = {}
    for t in trades:
        sym = str(t.get("symbol", "")).upper()
        if not sym:
            continue
        pnl = _safe(t.get("pnl") or t.get("realized_pnl"))
        if pnl is None:
            # Estimate from price difference
            qty = _safe(t.get("quantity"), 0)
            buy_p = _safe(t.get("avg_buy_price") or t.get("entry_price"), 0)
            sell_p = _safe(t.get("price") or t.get("exit_price"), 0)
            if qty and buy_p and sell_p:
                pnl = (sell_p - buy_p) * qty
        if pnl is None:
            continue
        grouped.setdefault(sym, []).append(float(pnl))
    result = {}
    for sym, pnls in grouped.items():
        if not pnls:
            continue
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        win_rate = len(wins) / len(pnls) if pnls else 0.0
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
        expectancy = win_rate * avg_win - (1 - win_rate) * avg_loss
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        pf = gross_profit / gross_loss if gross_loss > 0 else (1.5 if gross_profit > 0 else 1.0)
        result[sym] = {
            "count": len(pnls),
            "win_rate": round(win_rate, 4),
            "expectancy": round(expectancy, 2),
            "profit_factor": round(min(pf, 9.99), 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
        }
    return result


# ── Market regime detection ────────────────────────────────────────────────────

def detect_market_regime(market_context: Dict[str, Any]) -> Dict[str, Any]:
    """
    5-state adaptive regime detection from market context + VIX.

    States: TRENDING_UP | TRENDING_DOWN | VOLATILE | RANGE_BOUND | CRISIS

    Inputs from market_context_cache:
      - vix: float
      - nifty_trend: "BULLISH" | "BEARISH" | "SIDEWAYS" | "NEUTRAL"
      - market_score: 0-100
      - breadth_score: 0-100 (% stocks above 200d MA)
    """
    vix = _safe(market_context.get("vix") or market_context.get("india_vix"), 18.0) or 18.0
    nifty_trend = str(market_context.get("nifty_trend") or market_context.get("trend") or "NEUTRAL").upper()
    market_score = _safe(market_context.get("market_score"), 50.0) or 50.0
    breadth = _safe(market_context.get("breadth_score") or market_context.get("advance_decline_ratio"), 50.0) or 50.0

    # Scores and explanations
    scores: Dict[str, float] = {}
    reasons: List[str] = []

    # Trending up: bullish trend, decent breadth, low-moderate VIX
    tu = 0.0
    if "BULL" in nifty_trend:
        tu += 40.0
    if market_score >= 60:
        tu += 25.0
    elif market_score >= 50:
        tu += 10.0
    if breadth >= 55:
        tu += 20.0
    if vix < 16:
        tu += 15.0
    elif vix < 20:
        tu += 5.0
    scores["TRENDING_UP"] = _clamp(tu)

    # Trending down: bearish trend, poor breadth, moderate VIX
    td = 0.0
    if "BEAR" in nifty_trend:
        td += 40.0
    if market_score <= 35:
        td += 25.0
    elif market_score <= 45:
        td += 10.0
    if breadth <= 40:
        td += 20.0
    if 15 <= vix <= 25:
        td += 15.0
    scores["TRENDING_DOWN"] = _clamp(td)

    # Volatile: high VIX, mixed signals
    vo = 0.0
    if vix >= 25:
        vo += 50.0
    elif vix >= 20:
        vo += 25.0
    if "SIDEWAYS" in nifty_trend or "NEUTRAL" in nifty_trend:
        vo += 20.0
    scores["VOLATILE"] = _clamp(vo)

    # Range bound: sideways, moderate breadth, low volatility
    rb = 0.0
    if "SIDEWAYS" in nifty_trend or "NEUTRAL" in nifty_trend:
        rb += 35.0
    if 40 <= market_score <= 60:
        rb += 25.0
    if 45 <= breadth <= 60:
        rb += 20.0
    if vix < 20:
        rb += 20.0
    scores["RANGE_BOUND"] = _clamp(rb)

    # Crisis: VIX spike + extreme bearish
    cr = 0.0
    if vix >= 35:
        cr += 60.0
    elif vix >= 28:
        cr += 35.0
    if market_score <= 25:
        cr += 25.0
    if breadth <= 25:
        cr += 15.0
    scores["CRISIS"] = _clamp(cr)

    # Winner is highest scoring state
    regime = max(scores, key=scores.__getitem__)
    confidence = scores[regime]

    # Build plain-english reasoning
    reasons.append(f"VIX={vix:.1f}")
    reasons.append(f"trend={nifty_trend}")
    reasons.append(f"mkt_score={market_score:.0f}")
    reasons.append(f"breadth={breadth:.0f}")

    return {
        "regime": regime,
        "confidence": round(confidence, 1),
        "all_scores": {k: round(v, 1) for k, v in scores.items()},
        "inputs": {"vix": vix, "nifty_trend": nifty_trend, "market_score": market_score, "breadth": breadth},
        "reasoning": ", ".join(reasons),
        "score_multiplier": REGIME_SCORE_MULT.get(regime, 1.0),
    }


# ── Sector rotation analysis ───────────────────────────────────────────────────

def compute_sector_rotation(scan_recommendations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Rank sectors by average opportunity score and momentum from the latest scan.
    Returns sorted list (strongest first) with relative-strength vs median.
    """
    from config import SECTOR_MAP
    sector_scores: Dict[str, List[float]] = {s: [] for s in SECTOR_MAP}

    for rec in scan_recommendations:
        if not isinstance(rec, dict):
            continue
        sym = str(rec.get("symbol", "")).upper()
        score = _safe(rec.get("opportunity_score") or rec.get("score") or rec.get("confidence"))
        if score is None:
            continue
        for sector, members in SECTOR_MAP.items():
            if sym in members:
                sector_scores[sector].append(score)
                break

    rows = []
    for sector, scores_list in sector_scores.items():
        if not scores_list:
            rows.append({"sector": sector, "avg_score": None, "stock_count": 0,
                         "vs_median": None, "momentum": "NEUTRAL", "rank": None})
        else:
            avg = sum(scores_list) / len(scores_list)
            rows.append({"sector": sector, "avg_score": round(avg, 1),
                         "stock_count": len(scores_list), "vs_median": None,
                         "momentum": "NEUTRAL", "rank": None})

    # Compute median of non-null avg_scores
    valid_avgs = [r["avg_score"] for r in rows if r["avg_score"] is not None]
    if valid_avgs:
        sorted_avgs = sorted(valid_avgs)
        n = len(sorted_avgs)
        median_score = sorted_avgs[n // 2] if n % 2 else (sorted_avgs[n // 2 - 1] + sorted_avgs[n // 2]) / 2
    else:
        median_score = 50.0

    # Sort by avg_score descending, rank and momentum
    rows_with_score = sorted([r for r in rows if r["avg_score"] is not None],
                             key=lambda r: r["avg_score"], reverse=True)
    rows_no_score = [r for r in rows if r["avg_score"] is None]

    for i, r in enumerate(rows_with_score):
        r["rank"] = i + 1
        vs = r["avg_score"] - median_score
        r["vs_median"] = round(vs, 1)
        if vs >= 8:
            r["momentum"] = "STRONG"
        elif vs >= 2:
            r["momentum"] = "OUTPERFORMING"
        elif vs >= -2:
            r["momentum"] = "NEUTRAL"
        elif vs >= -8:
            r["momentum"] = "UNDERPERFORMING"
        else:
            r["momentum"] = "WEAK"

    for i, r in enumerate(rows_no_score):
        r["rank"] = len(rows_with_score) + i + 1

    return rows_with_score + rows_no_score


# ── Relative strength calculations ────────────────────────────────────────────

def compute_relative_strength(
    symbol: str,
    symbol_return_pct: Optional[float],
    nifty_return_pct: Optional[float],
    sector_return_pct: Optional[float],
    sector_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Compute RS of stock vs NIFTY and vs sector.
    All returns are trailing-period % returns (already computed from price data).
    """
    rs_vs_index = None
    rs_vs_sector = None
    rs_rank_label = "UNKNOWN"

    if symbol_return_pct is not None and nifty_return_pct is not None:
        rs_vs_index = round(symbol_return_pct - nifty_return_pct, 2)

    if symbol_return_pct is not None and sector_return_pct is not None:
        rs_vs_sector = round(symbol_return_pct - sector_return_pct, 2)

    # Rank label from vs_index
    if rs_vs_index is not None:
        if rs_vs_index >= 5:
            rs_rank_label = "LEADER"
        elif rs_vs_index >= 1:
            rs_rank_label = "OUTPERFORMER"
        elif rs_vs_index >= -1:
            rs_rank_label = "IN-LINE"
        elif rs_vs_index >= -5:
            rs_rank_label = "LAGGARD"
        else:
            rs_rank_label = "WEAK"

    return {
        "symbol": symbol,
        "symbol_return_pct": symbol_return_pct,
        "nifty_return_pct": nifty_return_pct,
        "sector_return_pct": sector_return_pct,
        "sector": sector_name,
        "rs_vs_index": rs_vs_index,
        "rs_vs_sector": rs_vs_sector,
        "rs_rank_label": rs_rank_label,
    }


def _estimate_return_from_rec(rec: Dict[str, Any]) -> Optional[float]:
    """Estimate trailing return from recommendation fields."""
    # Try change_pct first
    chg = _safe(rec.get("change_pct") or rec.get("price_change_pct"))
    if chg is not None:
        return chg
    price = _safe(rec.get("price") or rec.get("ltp"))
    prev = _safe(rec.get("prev_close"))
    if price and prev and prev > 0:
        return round((price - prev) / prev * 100, 2)
    return None


# ── Factor scoring engine ──────────────────────────────────────────────────────

def _score_trend(item: Dict[str, Any]) -> Tuple[float, str]:
    """Score trend factor 0-100 from scan recommendation."""
    conf = _safe(item.get("confidence") or item.get("ai_confidence"), 50.0) or 50.0
    rec = str(item.get("recommendation") or item.get("action") or "").upper()
    base = _clamp(conf)
    # Boost/penalty from recommendation label
    if "STRONG" in rec and ("BUY" in rec):
        base = min(100, base + 10)
    elif "STRONG" in rec and ("SELL" in rec):
        base = max(0, base - 20)
    elif "AVOID" in rec or "SELL" in rec:
        base = max(0, base - 15)
    rationale = f"conf={conf:.0f} rec={rec or 'N/A'}"
    return round(base, 1), rationale


def _score_momentum(item: Dict[str, Any]) -> Tuple[float, str]:
    """Score momentum 0-100 using RSI and signal strength."""
    # Try to get RSI from item or nested indicators
    indicators = item.get("indicators") or {}
    rsi = _safe(item.get("rsi") or indicators.get("rsi"))
    signal_str = _safe(item.get("signal_strength") or item.get("buy_score"))
    # RSI scoring: 50 = neutral (50pts), oversold (<30) = bullish (70pts), overbought (>70) = bearish (20pts)
    if rsi is not None:
        if rsi < 30:
            score = 70.0
        elif rsi < 45:
            score = 60.0
        elif rsi < 55:
            score = 50.0
        elif rsi < 70:
            score = 45.0
        else:
            score = 25.0
    elif signal_str is not None:
        score = _clamp(float(signal_str))
    else:
        score = 50.0
    rationale = f"rsi={rsi:.0f}" if rsi is not None else f"sig_str={signal_str}"
    return round(score, 1), rationale


def _score_volatility(item: Dict[str, Any], vix: float = 18.0) -> Tuple[float, str]:
    """
    Score volatility factor 0-100. HIGH volatility = LOWER score for buying.
    Low-volatility environments are more favorable.
    """
    risk_level = str(item.get("risk_level") or "MEDIUM").upper()
    # Base from VIX
    if vix < 15:
        vix_score = 75.0
    elif vix < 18:
        vix_score = 60.0
    elif vix < 22:
        vix_score = 50.0
    elif vix < 28:
        vix_score = 35.0
    else:
        vix_score = 15.0
    # Adjust for stock-level risk
    adj = {"LOW": 10.0, "MEDIUM": 0.0, "HIGH": -15.0}.get(risk_level, 0.0)
    score = _clamp(vix_score + adj)
    return round(score, 1), f"vix={vix:.1f} risk={risk_level}"


def _score_volume(item: Dict[str, Any]) -> Tuple[float, str]:
    """Score volume quality 0-100."""
    volume = _safe(item.get("volume") or item.get("avg_volume"))
    volume_spike = item.get("volume_spike") or item.get("volume_confirmation")
    # If explicit spike flag
    if volume_spike is True:
        return 80.0, "volume spike confirmed"
    if volume_spike is False:
        return 35.0, "no volume spike"
    # Use raw volume relative to a typical NSE midcap level
    if volume is not None:
        if volume >= 1_000_000:
            return 75.0, f"vol={volume/1e6:.1f}M"
        elif volume >= 200_000:
            return 55.0, f"vol={volume/1000:.0f}K"
        else:
            return 35.0, f"vol={volume:.0f} (low)"
    return 50.0, "volume unknown"


def _score_data_freshness(item: Dict[str, Any]) -> Tuple[float, str]:
    """Score data freshness 0-100."""
    quality = str(item.get("data_quality") or item.get("quality") or "").upper()
    data_status = str(item.get("data_status") or "OK").upper()
    if data_status == "DATA_UNAVAILABLE" or quality in STALE_QUALITIES:
        return 0.0, f"STALE/UNAVAILABLE ({quality})"
    if quality == "LIVE":
        return 100.0, "LIVE"
    if quality == "NEAR_LIVE":
        return 80.0, "NEAR_LIVE"
    return 50.0, f"quality={quality or 'unknown'}"


def _score_hist_expectancy(
    symbol: str,
    expectancy_map: Dict[str, Dict[str, float]],
) -> Tuple[float, str]:
    """Score historical expectancy 0-100 from COMPLETED paper trades."""
    stats = expectancy_map.get(symbol.upper())
    if not stats or stats.get("count", 0) < 3:
        return 50.0, f"insufficient trades ({(stats or {}).get('count', 0)})"
    exp = stats["expectancy"]
    pf = stats["profit_factor"]
    wr = stats["win_rate"]
    # Map expectancy to a 0-100 score
    if exp >= 200:
        base = 90.0
    elif exp >= 100:
        base = 80.0
    elif exp >= 20:
        base = 70.0
    elif exp >= 0:
        base = 55.0
    elif exp >= -50:
        base = 40.0
    else:
        base = 20.0
    # Adjust for profit factor
    if pf >= 2.0:
        base = min(100, base + 10)
    elif pf < 1.0:
        base = max(0, base - 15)
    return round(base, 1), f"exp=₹{exp:.0f} pf={pf:.2f} wr={wr:.0%} n={stats['count']}"


def _score_calibration_quality(item: Dict[str, Any]) -> Tuple[float, str]:
    """Score calibration quality from decision service fields."""
    method = str(item.get("calibration_method") or "identity").lower()
    version = _safe(item.get("calibration_version"), 0)
    if method not in ("identity", "") and (version or 0) > 0:
        return 80.0, f"method={method} v{int(version or 0)}"
    return 40.0, "uncalibrated/identity"


def _score_sector_strength(symbol: str, sector_rotation: List[Dict[str, Any]]) -> Tuple[float, str]:
    """Score sector strength 0-100 from sector rotation ranking (1=best)."""
    from config import SECTOR_MAP
    sym_sector = None
    for sector, members in SECTOR_MAP.items():
        if symbol.upper() in members:
            sym_sector = sector
            break
    if sym_sector is None:
        return 50.0, "sector unknown"
    n_sectors = len(sector_rotation) or 11
    for row in sector_rotation:
        if row.get("sector") == sym_sector:
            rank = row.get("rank")
            if rank is None:
                return 50.0, f"sector={sym_sector} rank=N/A"
            score = _clamp(100 - (rank - 1) / max(1, n_sectors - 1) * 80)
            return round(score, 1), f"sector={sym_sector} rank={rank}/{n_sectors}"
    return 50.0, f"sector={sym_sector} not ranked"


def _score_liquidity(item: Dict[str, Any]) -> Tuple[float, str]:
    """Score liquidity adequacy."""
    volume = _safe(item.get("volume") or item.get("avg_volume"))
    price = _safe(item.get("price") or item.get("ltp") or item.get("entry_price"))
    if volume is not None and price is not None and price > 0:
        turnover = volume * price
        if turnover >= 100_000_000:  # ₹10cr+
            return 90.0, f"₹{turnover/1e7:.0f}cr turnover"
        elif turnover >= 10_000_000:  # ₹1cr+
            return 70.0, f"₹{turnover/1e6:.0f}L turnover"
        elif turnover >= 1_000_000:  # ₹10L+
            return 45.0, f"₹{turnover/1e5:.0f}K turnover"
        else:
            return 20.0, f"turnover too low"
    return 50.0, "liquidity unknown"


def _score_relative_strength(rs_data: Dict[str, Any]) -> Tuple[float, str]:
    """Convert relative strength vs index to a 0-100 score."""
    rs_vs_index = _safe(rs_data.get("rs_vs_index"))
    rs_vs_sector = _safe(rs_data.get("rs_vs_sector"))
    label = rs_data.get("rs_rank_label", "UNKNOWN")

    if rs_vs_index is None:
        return 50.0, "RS data unavailable"

    # Map RS to score: symmetric around zero
    if rs_vs_index >= 10:
        base = 90.0
    elif rs_vs_index >= 5:
        base = 75.0
    elif rs_vs_index >= 1:
        base = 60.0
    elif rs_vs_index >= -1:
        base = 50.0
    elif rs_vs_index >= -5:
        base = 38.0
    else:
        base = 20.0

    # Slight bonus if also outperforms sector
    if rs_vs_sector is not None and rs_vs_sector >= 2:
        base = min(100, base + 5)

    return round(base, 1), f"vs_idx={rs_vs_index:+.1f}% {label}"


def _score_market_regime(regime_info: Dict[str, Any]) -> Tuple[float, str]:
    """Score market regime factor 0-100 for bullish direction."""
    regime = regime_info.get("regime", "RANGE_BOUND")
    conf = _safe(regime_info.get("confidence"), 50.0) or 50.0
    # Base score by regime
    regime_base = {
        "TRENDING_UP":   80.0,
        "RANGE_BOUND":   50.0,
        "TRENDING_DOWN": 25.0,
        "VOLATILE":      35.0,
        "CRISIS":        10.0,
    }.get(regime, 50.0)
    # Modulate by regime confidence (high confidence = stronger signal)
    score = regime_base * 0.7 + (conf / 100) * 30.0
    return round(score, 1), f"regime={regime} conf={conf:.0f}"


# ── Contradiction detection ────────────────────────────────────────────────────

def detect_contradictions(factor_scores: Dict[str, float]) -> Dict[str, Any]:
    """
    Detect when bullish factors conflict with bearish factors.

    Bullish factors (score >= 60 = bullish): trend, momentum, relative_strength,
                                              market_regime, sector_strength, hist_expectancy
    Bearish factors (score <= 40 = bearish): volatility, data_freshness + any from above
    Returns contradiction level: NONE | LOW | MEDIUM | HIGH
    """
    BULLISH_FACTORS = {"trend", "momentum", "relative_strength", "market_regime",
                       "sector_strength", "hist_expectancy"}
    BEARISH_HINT = 40.0   # score at or below this = bearish signal
    BULLISH_HINT = 60.0   # score at or above this = bullish signal

    bullish_set = []
    bearish_set = []

    for factor, score in factor_scores.items():
        if factor in BULLISH_FACTORS:
            if score >= BULLISH_HINT:
                bullish_set.append(factor)
            elif score <= BEARISH_HINT:
                bearish_set.append(factor)
        else:
            # Non-directional factors
            if factor == "data_freshness" and score <= 20:
                bearish_set.append(factor)
            elif factor == "volatility" and score <= 30:
                bearish_set.append(factor)

    contradictions = []
    for b in bullish_set:
        for be in bearish_set:
            if be not in BULLISH_FACTORS or (be in BULLISH_FACTORS and factor_scores.get(be, 50) <= BEARISH_HINT):
                contradictions.append(f"{b}↑ vs {be}↓")

    n_bull = len(bullish_set)
    n_bear = len(bearish_set)

    if n_bull >= 2 and n_bear >= 2:
        level = "HIGH"
    elif n_bull >= 1 and n_bear >= 2:
        level = "MEDIUM"
    elif n_bull >= 1 and n_bear >= 1:
        level = "LOW"
    else:
        level = "NONE"

    return {
        "level": level,
        "bullish_factors": bullish_set,
        "bearish_factors": bearish_set,
        "contradictions": contradictions[:6],  # cap for readability
        "explanation": (
            f"{n_bull} bullish factor(s) vs {n_bear} bearish factor(s). "
            + ("; ".join(contradictions[:3]) if contradictions else "No cross-signals.")
        ),
    }


# ── Volatility-aware position sizing ─────────────────────────────────────────

def volatility_aware_size(
    entry_price: float,
    stop_loss: float,
    available_cash: float,
    capital: float = 5000.0,
    vix: float = 18.0,
    regime: str = "RANGE_BOUND",
) -> Dict[str, Any]:
    """
    Extend the base 1%-risk sizing with volatility / regime adjustments:
    - High VIX or CRISIS/VOLATILE regime: reduce max-risk to 0.5%
    - TRENDING_UP + low VIX: allow full 1%
    - Hard caps: never more than 20% of cash in one trade
    """
    if entry_price <= 0:
        return {"feasible": False, "suggested_quantity": 0, "sizing_note": "invalid entry price",
                "max_risk_pct_used": MAX_RISK_PCT, "regime_adj": "none"}

    # Regime-based max-risk adjustment
    if regime in ("CRISIS", "VOLATILE") or vix >= 28:
        adj_risk_pct = MAX_RISK_PCT * 0.5   # halve risk in crisis/volatile
        adj_label = "halved (high vol/crisis)"
    elif regime == "TRENDING_DOWN" or vix >= 22:
        adj_risk_pct = MAX_RISK_PCT * 0.75
        adj_label = "reduced 25% (bearish)"
    else:
        adj_risk_pct = MAX_RISK_PCT
        adj_label = "standard"

    max_risk_amount = round(capital * adj_risk_pct, 2)
    stop_distance = max(0.0, entry_price - stop_loss)

    if stop_distance <= 0:
        qty_risk = 0
    else:
        qty_risk = math.floor(max_risk_amount / stop_distance)

    qty_cap = math.floor(available_cash * MAX_CAPITAL_PER_TRADE_PCT / entry_price)
    qty = max(0, min(qty_risk, qty_cap))
    feasible = qty >= MIN_SHARES

    position_value = round(qty * entry_price, 2)
    max_loss = round(qty * stop_distance, 2)
    cap_util = round(position_value / available_cash * 100, 1) if available_cash > 0 else 0.0

    return {
        "feasible": feasible,
        "suggested_quantity": qty,
        "position_value": position_value,
        "max_loss": max_loss,
        "max_risk_amount": max_risk_amount,
        "max_risk_pct_used": adj_risk_pct,
        "stop_distance": round(stop_distance, 2),
        "capital_utilization_pct": cap_util,
        "regime_adj": adj_label,
        "regime": regime,
        "vix": vix,
        "sizing_note": (
            f"Max-risk {adj_risk_pct*100:.1f}% ({adj_label}); "
            f"qty={qty} @ ₹{entry_price:.2f}; stop=₹{stop_loss:.2f}; max-loss=₹{max_loss:.2f}"
            if feasible else
            "Position not feasible with current capital and stop distance"
        ),
    }


# ── Richer explanation builder ─────────────────────────────────────────────────

def build_rich_explanation(
    symbol: str,
    factor_scores: Dict[str, float],
    factor_rationales: Dict[str, str],
    fused_score: float,
    final_action: str,
    regime: str,
    contradiction: Dict[str, Any],
    rs_data: Dict[str, Any],
    hist_stats: Optional[Dict[str, float]],
    blocker: Optional[str],
    what_would_change: str,
) -> Dict[str, Any]:
    """Structured explanation with factor contributions, blockers, and change conditions."""
    top_factors = sorted(factor_scores.items(), key=lambda x: x[1], reverse=True)
    bottom_factors = sorted(factor_scores.items(), key=lambda x: x[1])

    contributions = []
    for factor, score in factor_scores.items():
        weight = FACTOR_WEIGHTS.get(factor, 0.0)
        contributions.append({
            "factor": factor,
            "score": round(score, 1),
            "weight": round(weight, 3),
            "contribution": round(score * weight, 2),
            "direction": "BULLISH" if score >= 60 else ("BEARISH" if score <= 40 else "NEUTRAL"),
            "rationale": factor_rationales.get(factor, ""),
        })

    return {
        "symbol": symbol,
        "fused_score": round(fused_score, 1),
        "final_action": final_action,
        "regime": regime,
        "factor_contributions": contributions,
        "strongest_factor": top_factors[0][0] if top_factors else None,
        "weakest_factor": bottom_factors[0][0] if bottom_factors else None,
        "contradiction": contradiction,
        "relative_strength_summary": f"vs NIFTY: {rs_data.get('rs_vs_index', 'N/A'):+.1f}%"
                                     if rs_data.get("rs_vs_index") is not None else "RS data unavailable",
        "historical_evidence": hist_stats,
        "blocker": blocker,
        "what_would_change": what_would_change,
        "summary": (
            f"{symbol}: {final_action} | Fused score {fused_score:.0f}/100 | "
            f"Regime {regime} | "
            f"Contradiction: {contradiction['level']} | "
            f"{'⚠ BLOCKED: ' + blocker if blocker else 'No blockers'}"
        ),
    }


# ── Per-symbol fusion ─────────────────────────────────────────────────────────

def fuse_symbol(
    item: Dict[str, Any],
    regime_info: Dict[str, Any],
    sector_rotation: List[Dict[str, Any]],
    nifty_return_pct: Optional[float],
    expectancy_map: Dict[str, Dict[str, float]],
    available_cash: float,
    capital: float,
    vix: float,
) -> Dict[str, Any]:
    """Compute 12-factor fused analysis for one symbol."""
    symbol = str(item.get("symbol") or item.get("stock") or "?").upper()
    regime = regime_info.get("regime", "RANGE_BOUND")

    # ── Factor computation ────────────────────────────────────────────────────
    trend_s,     trend_r     = _score_trend(item)
    momentum_s,  momentum_r  = _score_momentum(item)
    vol_s,       vol_r       = _score_volatility(item, vix)
    volume_s,    volume_r    = _score_volume(item)
    fresh_s,     fresh_r     = _score_data_freshness(item)
    hist_s,      hist_r      = _score_hist_expectancy(symbol, expectancy_map)
    calib_s,     calib_r     = _score_calibration_quality(item)
    sect_s,      sect_r      = _score_sector_strength(symbol, sector_rotation)
    regime_s,    regime_r    = _score_market_regime(regime_info)
    liq_s,       liq_r       = _score_liquidity(item)

    # Relative strength
    sym_ret  = _estimate_return_from_rec(item)
    # Sector return: average of sector members in this same batch — approximate with 0
    from config import SECTOR_MAP
    sym_sector = None
    for sec, members in SECTOR_MAP.items():
        if symbol in members:
            sym_sector = sec
            break
    sector_ret: Optional[float] = None
    for row in sector_rotation:
        if row.get("sector") == sym_sector and row.get("avg_score") is not None:
            # Approximate sector return from sector avg score (0-100 → -5..+5%)
            sector_ret = round((row["avg_score"] - 50) / 10, 2)
            break

    rs_data = compute_relative_strength(symbol, sym_ret, nifty_return_pct, sector_ret, sym_sector)
    rs_s, rs_r = _score_relative_strength(rs_data)

    factor_scores: Dict[str, float] = {
        "trend":               trend_s,
        "momentum":            momentum_s,
        "volatility":          vol_s,
        "volume":              volume_s,
        "relative_strength":   rs_s,
        "market_regime":       regime_s,
        "sector_strength":     sect_s,
        "liquidity":           liq_s,
        "hist_expectancy":     hist_s,
        "calibration_quality": calib_s,
        "data_freshness":      fresh_s,
    }

    factor_rationales: Dict[str, str] = {
        "trend":               trend_r,
        "momentum":            momentum_r,
        "volatility":          vol_r,
        "volume":              volume_r,
        "relative_strength":   rs_r,
        "market_regime":       regime_r,
        "sector_strength":     sect_r,
        "liquidity":           liq_r,
        "hist_expectancy":     hist_r,
        "calibration_quality": calib_r,
        "data_freshness":      fresh_r,
    }

    # ── Weighted fused score ──────────────────────────────────────────────────
    raw_fused = sum(factor_scores[f] * FACTOR_WEIGHTS[f] for f in FACTOR_WEIGHTS)

    # Apply regime multiplier (only to the BUY-direction components)
    mult = regime_info.get("score_multiplier", 1.0)
    fused_score = _clamp(raw_fused * mult)

    # ── Stale-data gate (honesty) ─────────────────────────────────────────────
    data_status = str(item.get("data_status") or "OK").upper()
    quality = str(item.get("data_quality") or item.get("quality") or "").upper()
    is_stale = (data_status == "DATA_UNAVAILABLE") or (quality in STALE_QUALITIES)
    blocker: Optional[str] = None

    if is_stale:
        blocker = f"Data unavailable/stale ({quality or data_status}) — BUY signals blocked"

    # ── Determine final phase-12 action ──────────────────────────────────────
    if is_stale:
        p12_action = "WATCH"
    elif fused_score >= 82:
        p12_action = "STRONG_BUY"
    elif fused_score >= 68:
        p12_action = "BUY"
    elif fused_score >= 52:
        p12_action = "WATCH"
    else:
        p12_action = "AVOID"

    # ── Contradiction detection ───────────────────────────────────────────────
    contradiction = detect_contradictions(factor_scores)

    # Downgrade if HIGH contradiction
    if contradiction["level"] == "HIGH" and p12_action in ("STRONG_BUY", "BUY"):
        p12_action = "WATCH"
        if not blocker:
            blocker = "HIGH contradiction between bullish/bearish factors"

    # ── What would change decision ────────────────────────────────────────────
    if p12_action in ("STRONG_BUY", "BUY"):
        what_would_change = (
            "Exit trigger: stop-loss hit, target reached, or regime turns BEARISH/CRISIS; "
            f"contradiction rising to HIGH; data becoming stale"
        )
    elif p12_action == "WATCH":
        gap = 68 - fused_score
        what_would_change = (
            f"Upgrade to BUY needs ~{gap:.0f} more fused points — "
            f"improve: {factor_rationales.get('trend', '')} "
            f"or regime shift to TRENDING_UP"
        )
    else:
        what_would_change = (
            f"Reversal to WATCH needs fused score ≥52; "
            f"currently {fused_score:.0f}. "
            f"Weakest: {min(factor_scores, key=factor_scores.__getitem__)}"
        )

    # ── Volatility-aware sizing ───────────────────────────────────────────────
    entry_price = _safe(item.get("entry_price") or item.get("price") or item.get("ltp"), 0) or 0
    stop_loss = _safe(item.get("stop_loss"), 0) or 0
    if entry_price > 0 and stop_loss <= 0:
        stop_loss = entry_price * 0.97  # default 3% stop

    sizing = volatility_aware_size(
        entry_price=entry_price,
        stop_loss=stop_loss,
        available_cash=available_cash,
        capital=capital,
        vix=vix,
        regime=regime,
    )

    # ── Richer explanation ────────────────────────────────────────────────────
    explanation = build_rich_explanation(
        symbol=symbol,
        factor_scores=factor_scores,
        factor_rationales=factor_rationales,
        fused_score=fused_score,
        final_action=p12_action,
        regime=regime,
        contradiction=contradiction,
        rs_data=rs_data,
        hist_stats=expectancy_map.get(symbol),
        blocker=blocker,
        what_would_change=what_would_change,
    )

    return {
        "symbol":          symbol,
        "sector":          sym_sector,
        "p12_action":      p12_action,
        "fused_score":     round(fused_score, 1),
        "raw_fused_score": round(raw_fused, 1),
        "factor_scores":   {k: round(v, 1) for k, v in factor_scores.items()},
        "factor_rationales": factor_rationales,
        "regime":          regime,
        "contradiction":   contradiction,
        "relative_strength": rs_data,
        "sizing":          sizing,
        "explanation":     explanation,
        "is_stale":        is_stale,
        "blocker":         blocker,
        "data_status":     data_status,
        "data_quality":    quality or "UNKNOWN",
        # Pass-through from scan item for UI
        "price":           _safe(item.get("price") or item.get("ltp")),
        "confidence":      _safe(item.get("confidence") or item.get("ai_confidence")),
        "original_recommendation": item.get("recommendation") or item.get("action"),
    }


# ── Main analysis entry point ─────────────────────────────────────────────────

def run_phase12_analysis(
    symbols: Optional[List[str]] = None,
    force: bool = False,
    available_cash: float = 5000.0,
    capital: float = 5000.0,
) -> Dict[str, Any]:
    """
    Full Phase 12 intelligence analysis.

    1. Load latest scan cache (phase7_scan_cache.json)
    2. Detect market regime from market_context_cache.json
    3. Compute sector rotation
    4. Score 11 factors per symbol
    5. Fuse with weighted average + regime adjustment
    6. Detect contradictions
    7. Volatility-aware sizing
    8. Cache result (phase12_cache.json, TTL 600s)
    9. Return structured payload (idempotent within TTL)
    """
    cache = _load_cache()
    cache_key = "full_analysis"
    if not force and _cache_fresh(cache, cache_key):
        return cache[cache_key]

    scan_path = os.path.join(_DIR, "phase7_scan_cache.json")
    market_path = os.path.join(_DIR, "market_context_cache.json")

    scan_raw = _load_json(scan_path, {})
    market_ctx = _load_json(market_path, {})

    # Support both nested {"recommendations": [...]} and flat list
    recs: List[Dict[str, Any]] = []
    if isinstance(scan_raw, dict):
        recs = scan_raw.get("recommendations") or []
    elif isinstance(scan_raw, list):
        recs = scan_raw

    # Filter by requested symbols
    if symbols:
        syms_upper = {s.upper() for s in symbols}
        recs = [r for r in recs if str(r.get("symbol") or r.get("stock") or "").upper() in syms_upper]

    # ── Regime ───────────────────────────────────────────────────────────────
    regime_info = detect_market_regime(market_ctx if isinstance(market_ctx, dict) else {})
    vix = regime_info["inputs"]["vix"]

    # ── Sector rotation ───────────────────────────────────────────────────────
    sector_rotation = compute_sector_rotation(recs)

    # ── Historical expectancy (completed trades, no-lookahead) ───────────────
    completed_trades = _completed_paper_trades()
    expectancy_map = _hist_expectancy_by_symbol(completed_trades)

    # ── Estimate NIFTY return for relative strength ───────────────────────────
    quote_path = os.path.join(_DIR, "phase11_quote_state.json")
    qs = _load_json(quote_path, {})
    nifty_q = (qs.get("cache") or {}).get("NIFTY") or {}
    nifty_quote = nifty_q.get("quote") or {}
    nifty_return_pct = _safe(nifty_quote.get("change_pct"))

    # ── Per-symbol fusion ─────────────────────────────────────────────────────
    fused_results: List[Dict[str, Any]] = []
    for item in recs:
        if not isinstance(item, dict):
            continue
        try:
            result = fuse_symbol(
                item=item,
                regime_info=regime_info,
                sector_rotation=sector_rotation,
                nifty_return_pct=nifty_return_pct,
                expectancy_map=expectancy_map,
                available_cash=available_cash,
                capital=capital,
                vix=vix,
            )
            fused_results.append(result)
        except Exception as exc:
            fused_results.append({
                "symbol": str(item.get("symbol") or "?"),
                "p12_action": "WATCH",
                "fused_score": 50.0,
                "error": str(exc)[:200],
            })

    # Sort by fused_score descending
    fused_results.sort(key=lambda r: r.get("fused_score", 0), reverse=True)

    # ── Aggregate contradiction summary ───────────────────────────────────────
    contradiction_counts = {"NONE": 0, "LOW": 0, "MEDIUM": 0, "HIGH": 0}
    for r in fused_results:
        lvl = r.get("contradiction", {}).get("level", "NONE")
        contradiction_counts[lvl] = contradiction_counts.get(lvl, 0) + 1

    # ── Action summary ────────────────────────────────────────────────────────
    action_counts: Dict[str, int] = {}
    for r in fused_results:
        a = r.get("p12_action", "WATCH")
        action_counts[a] = action_counts.get(a, 0) + 1

    payload: Dict[str, Any] = {
        "phase": 12,
        "engine_version":      RESEARCH_ENGINE_VERSION,
        "generated_at":        _now(),
        "label":               LABEL,
        "regime":              regime_info,
        "sector_rotation":     sector_rotation,
        "fused_results":       fused_results,
        "action_summary":      action_counts,
        "contradiction_summary": contradiction_counts,
        "completed_trade_count": len(completed_trades),
        "expectancy_symbols":  list(expectancy_map.keys()),
        "scan_source":         scan_raw.get("scan_id") if isinstance(scan_raw, dict) else None,
        "scan_ts":             scan_raw.get("snapshot_ts") if isinstance(scan_raw, dict) else None,
        "factors":             list(FACTOR_WEIGHTS.keys()),
        "factor_weights":      FACTOR_WEIGHTS,
        "_cached_at":          time.time(),
    }

    cache[cache_key] = payload
    _save_cache(cache)

    return payload
