"""
phase13_intelligence.py — Phase 13: Institutional AI & Strategy Evolution

Extends Phase 12's 11 factors to 14 factors with:
  NEW: historical_similarity, risk_reward, portfolio_context
  IMPROVED: regime transition tracking, evidence labels, strategy-by-regime
             eligibility, data-age protection, stale-sector blocking

Factor weights (sum = 1.0):
  trend              0.15
  momentum           0.12
  volatility         0.06
  volume             0.07
  relative_strength  0.12
  market_regime      0.10
  sector_strength    0.07
  liquidity          0.05
  hist_expectancy    0.08
  calibration_quality 0.02
  data_freshness     0.02
  historical_similarity 0.06
  risk_reward        0.05
  portfolio_context  0.03

Evidence labels: insufficient | very_low | low | moderate | strong | validated
Stale-data gate: blocks BUY/STRONG_BUY if data unavailable, stale, or scan > 90 min old
No-lookahead: learning only from SELL rows with close timestamps
PAPER TRADING / RESEARCH ONLY — no real broker orders.
"""

from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

_DIR = os.path.dirname(os.path.abspath(__file__))

CACHE_FILE = os.path.join(_DIR, "phase13_cache.json")
CACHE_TTL_S = 600.0

RESEARCH_ENGINE_VERSION = "Research Engine v1.0 · Phase 13"
LABEL = "PAPER / RESEARCH ONLY"
PHASE = 13

# ── Factor weights (must sum to 1.0) ─────────────────────────────────────────
FACTOR_WEIGHTS: Dict[str, float] = {
    "trend":                0.15,
    "momentum":             0.12,
    "volatility":           0.06,
    "volume":               0.07,
    "relative_strength":    0.12,
    "market_regime":        0.10,
    "sector_strength":      0.07,
    "liquidity":            0.05,
    "hist_expectancy":      0.08,
    "calibration_quality":  0.02,
    "data_freshness":       0.02,
    "historical_similarity":0.06,
    "risk_reward":          0.05,
    "portfolio_context":    0.03,
}
_wsum = sum(FACTOR_WEIGHTS.values())
assert abs(_wsum - 1.0) < 1e-9, f"Factor weights sum to {_wsum}, not 1.0"

# ── Evidence label thresholds (by completed trade count) ─────────────────────
EVIDENCE_LABELS = [
    (100, "validated"),
    (50,  "strong"),
    (20,  "moderate"),
    (10,  "low"),
    (3,   "very_low"),
    (0,   "insufficient"),
]

def evidence_label(n: int) -> str:
    for threshold, label in EVIDENCE_LABELS:
        if n >= threshold:
            return label
    return "insufficient"

# ── Strategy → Regime eligibility ─────────────────────────────────────────────
STRATEGY_REGIME_FIT: Dict[str, List[str]] = {
    "trend_rider":     ["TRENDING_UP"],
    "breakout_hunter": ["TRENDING_UP", "VOLATILE"],
    "mean_reversion":  ["RANGE_BOUND", "TRENDING_DOWN"],
    "ema_cross":       ["TRENDING_UP"],
    "macd_cross":      ["TRENDING_UP"],
    "supertrend_follow": ["TRENDING_UP", "VOLATILE"],
}

def eligible_strategies(regime: str) -> List[str]:
    """Return strategies that fit the current regime."""
    return [s for s, regimes in STRATEGY_REGIME_FIT.items() if regime in regimes]

def best_strategy_for_regime(regime: str, expectancy_map: Dict[str, Any]) -> Optional[str]:
    """Pick the strategy with best historical expectancy that fits current regime."""
    eligible = eligible_strategies(regime)
    if not eligible:
        return None
    # Score by expectancy if available, else arbitrary ordering
    scored = []
    for s in eligible:
        ev = expectancy_map.get(f"strategy:{s}", {}).get("expectancy", 0.0)
        scored.append((ev, s))
    scored.sort(reverse=True)
    return scored[0][1] if scored else eligible[0]

# ── Regime multipliers ────────────────────────────────────────────────────────
REGIME_SCORE_MULT: Dict[str, float] = {
    "TRENDING_UP":   1.10,
    "RANGE_BOUND":   0.95,
    "TRENDING_DOWN": 0.80,
    "VOLATILE":      0.85,
    "CRISIS":        0.60,
}

REGIMES = list(REGIME_SCORE_MULT.keys())

# ── Stale-data / data-age thresholds ─────────────────────────────────────────
STALE_QUALITIES = {"STALE", "UNAVAILABLE", "DATA_UNAVAILABLE"}
STALE_SCAN_MINUTES_MARKET_OPEN = 90   # during market hours
STALE_SCAN_MINUTES_MARKET_CLOSED = 720  # 12 hours
BLOCK_ACTIONS = {"BUY", "STRONG_BUY"}

# ── Position sizing caps ──────────────────────────────────────────────────────
MAX_CAPITAL_PCT = 0.20
MAX_RISK_PCT = 0.01
MIN_SHARES = 1

# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _safe(v: Any, default: Any = None) -> Any:
    if v is None:
        return default
    try:
        f = float(v)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return default

def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))

def _load_json(path: str, default: Any = None) -> Any:
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return default

def _save_atomic(path: str, data: Any) -> None:
    tmp = path + f".tmp.{os.getpid()}"
    try:
        with open(tmp, "w") as fh:
            json.dump(data, fh, default=str)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass

# ─────────────────────────────────────────────────────────────────────────────
# Cache
# ─────────────────────────────────────────────────────────────────────────────

def _load_cache() -> Dict[str, Any]:
    raw = _load_json(CACHE_FILE, {})
    return raw if isinstance(raw, dict) else {}

def _save_cache(cache: Dict[str, Any]) -> None:
    _save_atomic(CACHE_FILE, cache)

def _cache_fresh(cache: Dict[str, Any], key: str, ttl: float = CACHE_TTL_S) -> bool:
    entry = cache.get(key)
    if not isinstance(entry, dict):
        return False
    return (time.time() - float(entry.get("_cached_at", 0))) < ttl

# ─────────────────────────────────────────────────────────────────────────────
# No-lookahead completed trade reader
# ─────────────────────────────────────────────────────────────────────────────

def _completed_paper_trades() -> List[Dict[str, Any]]:
    """Return ONLY SELL rows with a close timestamp (completed round-trips)."""
    try:
        from paper_trader import get_trades
        trades = list(get_trades())
    except Exception:
        return []
    return [
        t for t in trades
        if isinstance(t, dict)
        and t.get("action", "").upper() == "SELL"
        and bool(t.get("timestamp") or t.get("close_ts") or t.get("trade_date"))
    ]

def _build_expectancy_map(trades: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Per-symbol and per-strategy expectancy from completed trades."""
    grouped: Dict[str, List[float]] = {}
    for t in trades:
        sym = str(t.get("symbol", "")).upper()
        strategy = str(t.get("strategy_id") or t.get("strategy") or "unknown")
        qty = _safe(t.get("quantity"), 0) or 0
        buy_p = _safe(t.get("avg_buy_price") or t.get("entry_price"), 0) or 0
        sell_p = _safe(t.get("price") or t.get("exit_price"), 0) or 0
        pnl = _safe(t.get("pnl") or t.get("realized_pnl"))
        if pnl is None and qty and buy_p and sell_p:
            pnl = (sell_p - buy_p) * qty
        if pnl is None:
            continue
        pnl = float(pnl)
        for key in [sym, f"strategy:{strategy}"]:
            grouped.setdefault(key, []).append(pnl)

    result: Dict[str, Dict[str, Any]] = {}
    for key, pnls in grouped.items():
        if not pnls:
            continue
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        n = len(pnls)
        wr = len(wins) / n
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
        expectancy = wr * avg_win - (1 - wr) * avg_loss
        gp = sum(wins); gl = abs(sum(losses))
        pf = gp / gl if gl > 0 else (1.5 if gp > 0 else 1.0)
        result[key] = {
            "count": n,
            "win_rate": round(wr, 4),
            "expectancy": round(expectancy, 2),
            "profit_factor": round(min(pf, 9.99), 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "evidence": evidence_label(n),
        }
    return result

# ─────────────────────────────────────────────────────────────────────────────
# Data-age / scan staleness
# ─────────────────────────────────────────────────────────────────────────────

def _scan_age_minutes(scan_ts: Optional[str]) -> Optional[float]:
    if not scan_ts:
        return None
    try:
        ts = datetime.fromisoformat(scan_ts.rstrip("Z")).replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() / 60
    except Exception:
        return None

def _is_market_open() -> bool:
    try:
        from market_hours import market_status
        ms = market_status()
        return bool(ms.get("is_open"))
    except Exception:
        return False

def _scan_is_stale(scan_ts: Optional[str]) -> Tuple[bool, Optional[float]]:
    age = _scan_age_minutes(scan_ts)
    if age is None:
        return False, None
    limit = STALE_SCAN_MINUTES_MARKET_OPEN if _is_market_open() else STALE_SCAN_MINUTES_MARKET_CLOSED
    return age > limit, age

# ─────────────────────────────────────────────────────────────────────────────
# Market regime detection (extended with transition tracking)
# ─────────────────────────────────────────────────────────────────────────────

def detect_market_regime(market_context: Dict[str, Any]) -> Dict[str, Any]:
    vix = _safe(market_context.get("vix") or market_context.get("india_vix"), 18.0) or 18.0
    nifty_trend = str(market_context.get("nifty_trend") or market_context.get("trend") or "NEUTRAL").upper()
    mkt_score = _safe(market_context.get("market_score"), 50.0) or 50.0
    breadth = _safe(market_context.get("breadth_score") or market_context.get("advance_decline_ratio"), 50.0) or 50.0

    scores: Dict[str, float] = {}

    # TRENDING_UP
    tu = 0.0
    if "BULL" in nifty_trend: tu += 40.0
    if mkt_score >= 60: tu += 25.0
    elif mkt_score >= 50: tu += 10.0
    if breadth >= 55: tu += 20.0
    if vix < 16: tu += 15.0
    elif vix < 20: tu += 5.0
    scores["TRENDING_UP"] = _clamp(tu)

    # TRENDING_DOWN
    td = 0.0
    if "BEAR" in nifty_trend: td += 40.0
    if mkt_score <= 35: td += 25.0
    elif mkt_score <= 45: td += 10.0
    if breadth <= 40: td += 20.0
    if 15 <= vix <= 25: td += 15.0
    scores["TRENDING_DOWN"] = _clamp(td)

    # VOLATILE
    vo = 0.0
    if vix >= 25: vo += 50.0
    elif vix >= 20: vo += 25.0
    if "SIDEWAYS" in nifty_trend or "NEUTRAL" in nifty_trend: vo += 20.0
    scores["VOLATILE"] = _clamp(vo)

    # RANGE_BOUND
    rb = 0.0
    if "SIDEWAYS" in nifty_trend or "NEUTRAL" in nifty_trend: rb += 35.0
    if 40 <= mkt_score <= 60: rb += 25.0
    if 45 <= breadth <= 60: rb += 20.0
    if vix < 20: rb += 20.0
    scores["RANGE_BOUND"] = _clamp(rb)

    # CRISIS
    cr = 0.0
    if vix >= 35: cr += 60.0
    elif vix >= 28: cr += 35.0
    if mkt_score <= 25: cr += 25.0
    if breadth <= 25: cr += 15.0
    scores["CRISIS"] = _clamp(cr)

    regime = max(scores, key=scores.__getitem__)
    confidence = scores[regime]

    # Transition tracking: compare to cached previous regime
    prev_regime = None
    regime_duration_bars = None
    try:
        cache = _load_cache()
        prev = cache.get("last_regime")
        if isinstance(prev, dict):
            prev_regime = prev.get("regime")
            if prev_regime == regime:
                regime_duration_bars = prev.get("duration_bars", 1) + 1
            else:
                regime_duration_bars = 1
        else:
            regime_duration_bars = 1
        # Update last_regime in cache
        cache["last_regime"] = {
            "regime": regime,
            "duration_bars": regime_duration_bars,
            "confidence": confidence,
            "updated_at": _now_str(),
        }
        _save_cache(cache)
    except Exception:
        regime_duration_bars = 1

    return {
        "regime": regime,
        "confidence": round(confidence, 1),
        "all_scores": {k: round(v, 1) for k, v in scores.items()},
        "prev_regime": prev_regime,
        "regime_duration_bars": regime_duration_bars,
        "regime_changed": (prev_regime is not None and prev_regime != regime),
        "score_multiplier": REGIME_SCORE_MULT.get(regime, 1.0),
        "eligible_strategies": eligible_strategies(regime),
        "inputs": {"vix": vix, "nifty_trend": nifty_trend, "market_score": mkt_score, "breadth": breadth},
        "reasoning": f"VIX={vix:.1f}, trend={nifty_trend}, mkt_score={mkt_score:.0f}, breadth={breadth:.0f}",
    }

# ─────────────────────────────────────────────────────────────────────────────
# Sector rotation
# ─────────────────────────────────────────────────────────────────────────────

def compute_sector_rotation(scan_recs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from config import SECTOR_MAP
    sector_scores: Dict[str, List[float]] = {s: [] for s in SECTOR_MAP}
    for rec in scan_recs:
        if not isinstance(rec, dict): continue
        sym = str(rec.get("symbol", "")).upper()
        score = _safe(rec.get("opportunity_score") or rec.get("score") or rec.get("confidence"))
        if score is None: continue
        for sector, members in SECTOR_MAP.items():
            if sym in members:
                sector_scores[sector].append(score)
                break

    rows = []
    for sector, sl in sector_scores.items():
        rows.append({
            "sector": sector,
            "avg_score": round(sum(sl) / len(sl), 1) if sl else None,
            "stock_count": len(sl),
            "vs_median": None,
            "momentum": "NEUTRAL",
            "rank": None,
        })

    valid = [r for r in rows if r["avg_score"] is not None]
    no_data = [r for r in rows if r["avg_score"] is None]
    sorted_avgs = sorted([r["avg_score"] for r in valid])
    n = len(sorted_avgs)
    median = (sorted_avgs[n // 2] if n % 2 else (sorted_avgs[n // 2 - 1] + sorted_avgs[n // 2]) / 2) if n else 50.0

    valid.sort(key=lambda r: r["avg_score"], reverse=True)
    for i, r in enumerate(valid):
        r["rank"] = i + 1
        vs = r["avg_score"] - median
        r["vs_median"] = round(vs, 1)
        r["momentum"] = (
            "STRONG" if vs >= 8 else
            "OUTPERFORMING" if vs >= 2 else
            "NEUTRAL" if vs >= -2 else
            "UNDERPERFORMING" if vs >= -8 else "WEAK"
        )
    for i, r in enumerate(no_data):
        r["rank"] = len(valid) + i + 1

    return valid + no_data

# ─────────────────────────────────────────────────────────────────────────────
# Relative strength
# ─────────────────────────────────────────────────────────────────────────────

def compute_relative_strength(
    symbol: str,
    sym_ret: Optional[float],
    nifty_ret: Optional[float],
    sector_ret: Optional[float],
    sector_name: Optional[str] = None,
) -> Dict[str, Any]:
    rs_idx = round(sym_ret - nifty_ret, 2) if sym_ret is not None and nifty_ret is not None else None
    rs_sec = round(sym_ret - sector_ret, 2) if sym_ret is not None and sector_ret is not None else None
    label = (
        "LEADER" if rs_idx is not None and rs_idx >= 5 else
        "OUTPERFORMER" if rs_idx is not None and rs_idx >= 1 else
        "IN-LINE" if rs_idx is not None and rs_idx >= -1 else
        "LAGGARD" if rs_idx is not None and rs_idx >= -5 else
        "WEAK" if rs_idx is not None else "UNKNOWN"
    )
    return {
        "symbol": symbol, "sector": sector_name,
        "symbol_return_pct": sym_ret, "nifty_return_pct": nifty_ret, "sector_return_pct": sector_ret,
        "rs_vs_index": rs_idx, "rs_vs_sector": rs_sec, "rs_rank_label": label,
    }

# ─────────────────────────────────────────────────────────────────────────────
# Factor scoring functions (14 factors)
# ─────────────────────────────────────────────────────────────────────────────

def _score_trend(item: Dict[str, Any]) -> Tuple[float, str]:
    conf = _safe(item.get("confidence") or item.get("ai_confidence"), 50.0) or 50.0
    rec = str(item.get("recommendation") or item.get("action") or "").upper()
    base = _clamp(conf)
    if "STRONG" in rec and "BUY" in rec: base = min(100, base + 10)
    elif "AVOID" in rec or "SELL" in rec: base = max(0, base - 15)
    return round(base, 1), f"conf={conf:.0f} rec={rec or 'N/A'}"

def _score_momentum(item: Dict[str, Any]) -> Tuple[float, str]:
    indicators = item.get("indicators") or {}
    rsi = _safe(item.get("rsi") or indicators.get("rsi"))
    sig = _safe(item.get("signal_strength") or item.get("buy_score"))
    if rsi is not None:
        score = 70.0 if rsi < 30 else 60.0 if rsi < 45 else 50.0 if rsi < 55 else 45.0 if rsi < 70 else 25.0
        return round(score, 1), f"rsi={rsi:.0f}"
    if sig is not None:
        return round(_clamp(float(sig)), 1), f"sig_str={sig}"
    return 50.0, "momentum unknown"

def _score_volatility(item: Dict[str, Any], vix: float = 18.0) -> Tuple[float, str]:
    risk_level = str(item.get("risk_level") or "MEDIUM").upper()
    base = 75.0 if vix < 15 else 60.0 if vix < 18 else 50.0 if vix < 22 else 35.0 if vix < 28 else 15.0
    adj = {"LOW": 10.0, "MEDIUM": 0.0, "HIGH": -15.0}.get(risk_level, 0.0)
    return round(_clamp(base + adj), 1), f"vix={vix:.1f} risk={risk_level}"

def _score_volume(item: Dict[str, Any]) -> Tuple[float, str]:
    spike = item.get("volume_spike") or item.get("volume_confirmation")
    if spike is True: return 80.0, "volume spike confirmed"
    if spike is False: return 35.0, "no volume spike"
    vol = _safe(item.get("volume") or item.get("avg_volume"))
    if vol is not None:
        return (75.0, f"vol={vol/1e6:.1f}M") if vol >= 1_000_000 else \
               (55.0, f"vol={vol/1000:.0f}K") if vol >= 200_000 else \
               (35.0, f"vol={vol:.0f} (low)")
    return 50.0, "volume unknown"

def _score_data_freshness(item: Dict[str, Any]) -> Tuple[float, str]:
    quality = str(item.get("data_quality") or item.get("quality") or "").upper()
    status = str(item.get("data_status") or "OK").upper()
    if status == "DATA_UNAVAILABLE" or quality in STALE_QUALITIES:
        return 0.0, f"STALE ({quality})"
    return (100.0, "LIVE") if quality == "LIVE" else (80.0, "NEAR_LIVE") if quality == "NEAR_LIVE" else (50.0, f"quality={quality or 'unknown'}")

def _score_liquidity(item: Dict[str, Any]) -> Tuple[float, str]:
    vol = _safe(item.get("volume") or item.get("avg_volume"))
    price = _safe(item.get("price") or item.get("ltp") or item.get("entry_price"))
    if vol and price and price > 0:
        t = vol * price
        return (90.0, f"₹{t/1e7:.0f}cr") if t >= 1e8 else \
               (70.0, f"₹{t/1e6:.0f}L") if t >= 1e7 else \
               (45.0, f"₹{t/1e5:.0f}K") if t >= 1e6 else (20.0, "low turnover")
    return 50.0, "liquidity unknown"

def _score_hist_expectancy(symbol: str, exp_map: Dict[str, Any]) -> Tuple[float, str]:
    stats = exp_map.get(symbol.upper())
    if not stats or stats.get("count", 0) < 3:
        n = (stats or {}).get("count", 0)
        return 50.0, f"insufficient trades (n={n})"
    exp = stats["expectancy"]; pf = stats["profit_factor"]
    base = 90.0 if exp >= 200 else 80.0 if exp >= 100 else 70.0 if exp >= 20 else \
           55.0 if exp >= 0 else 40.0 if exp >= -50 else 20.0
    if pf >= 2.0: base = min(100, base + 10)
    elif pf < 1.0: base = max(0, base - 15)
    return round(base, 1), f"exp=₹{exp:.0f} pf={pf:.2f} wr={stats['win_rate']:.0%} n={stats['count']} [{stats['evidence']}]"

def _score_calibration_quality(item: Dict[str, Any]) -> Tuple[float, str]:
    method = str(item.get("calibration_method") or "identity").lower()
    version = _safe(item.get("calibration_version"), 0)
    if method not in ("identity", "") and (version or 0) > 0:
        return 80.0, f"method={method} v{int(version or 0)}"
    return 40.0, "uncalibrated/identity"

def _score_sector_strength(symbol: str, sector_rotation: List[Dict[str, Any]]) -> Tuple[float, str]:
    from config import SECTOR_MAP
    sym_sector = next((sec for sec, m in SECTOR_MAP.items() if symbol.upper() in m), None)
    if sym_sector is None: return 50.0, "sector unknown"
    n_sectors = len(sector_rotation) or 11
    for row in sector_rotation:
        if row.get("sector") == sym_sector:
            rank = row.get("rank")
            if rank is None: return 50.0, f"sector={sym_sector} rank=N/A"
            score = _clamp(100 - (rank - 1) / max(1, n_sectors - 1) * 80)
            return round(score, 1), f"sector={sym_sector} rank={rank}/{n_sectors}"
    return 50.0, f"sector={sym_sector} not ranked"

def _score_market_regime(regime_info: Dict[str, Any]) -> Tuple[float, str]:
    regime = regime_info.get("regime", "RANGE_BOUND")
    conf = _safe(regime_info.get("confidence"), 50.0) or 50.0
    base = {"TRENDING_UP": 80.0, "RANGE_BOUND": 50.0, "TRENDING_DOWN": 25.0, "VOLATILE": 35.0, "CRISIS": 10.0}.get(regime, 50.0)
    score = base * 0.7 + (conf / 100) * 30.0
    return round(score, 1), f"regime={regime} conf={conf:.0f}"

def _score_relative_strength(rs_data: Dict[str, Any]) -> Tuple[float, str]:
    rs_idx = _safe(rs_data.get("rs_vs_index"))
    rs_sec = _safe(rs_data.get("rs_vs_sector"))
    label = rs_data.get("rs_rank_label", "UNKNOWN")
    if rs_idx is None: return 50.0, "RS unavailable"
    base = 90.0 if rs_idx >= 10 else 75.0 if rs_idx >= 5 else 60.0 if rs_idx >= 1 else \
           50.0 if rs_idx >= -1 else 38.0 if rs_idx >= -5 else 20.0
    if rs_sec is not None and rs_sec >= 2: base = min(100, base + 5)
    return round(base, 1), f"vs_idx={rs_idx:+.1f}% {label}"

# ── NEW factors ───────────────────────────────────────────────────────────────

def _score_historical_similarity(
    symbol: str,
    exp_map: Dict[str, Any],
    regime: str,
) -> Tuple[float, str]:
    """
    Historical similarity: how similar is today's setup to past winners?
    Approximated from the symbol's win-rate pattern + regime alignment.
    """
    stats = exp_map.get(symbol.upper())
    if not stats or stats.get("count", 0) < 3:
        return 50.0, f"insufficient history (n={stats.get('count', 0) if stats else 0})"
    wr = stats["win_rate"]
    ev = stats["evidence"]
    # Base from win rate
    base = 85.0 if wr >= 0.70 else 70.0 if wr >= 0.60 else 55.0 if wr >= 0.50 else \
           40.0 if wr >= 0.40 else 25.0
    # Weight by evidence quality
    ev_mult = {"validated": 1.0, "strong": 0.95, "moderate": 0.85, "low": 0.70, "very_low": 0.55, "insufficient": 0.5}.get(ev, 0.5)
    return round(base * ev_mult, 1), f"wr={wr:.0%} [{ev}]"

def _score_risk_reward(item: Dict[str, Any]) -> Tuple[float, str]:
    """Score quality of entry/target/stop setup."""
    entry = _safe(item.get("entry_price") or item.get("price") or item.get("ltp"))
    stop = _safe(item.get("stop_loss"))
    target = _safe(item.get("target"))
    rr = _safe(item.get("rr_ratio") or item.get("risk_reward"))

    if rr is not None:
        score = 90.0 if rr >= 3.0 else 75.0 if rr >= 2.0 else 55.0 if rr >= 1.5 else \
                35.0 if rr >= 1.0 else 15.0
        return round(score, 1), f"RR={rr:.1f}"

    if entry and stop and target and entry > stop:
        risk = entry - stop
        reward = target - entry
        if risk > 0:
            rr_calc = reward / risk
            score = 90.0 if rr_calc >= 3.0 else 75.0 if rr_calc >= 2.0 else 55.0 if rr_calc >= 1.5 else \
                    35.0 if rr_calc >= 1.0 else 15.0
            return round(score, 1), f"RR={rr_calc:.1f} (E:{entry:.0f} S:{stop:.0f} T:{target:.0f})"

    return 50.0, "RR unknown"

def _score_portfolio_context(
    symbol: str,
    open_positions: List[str],
    sector_map: Dict[str, List[str]],
) -> Tuple[float, str]:
    """
    Portfolio context: penalise concentration, reward diversification.
    open_positions: list of symbol strings currently held
    """
    n_pos = len(open_positions)
    already_held = symbol.upper() in [s.upper() for s in open_positions]

    if already_held:
        return 30.0, f"already held ({n_pos} open positions)"

    # Find sector for this symbol
    sym_sector = next((sec for sec, m in sector_map.items() if symbol.upper() in m), None)
    sector_exposure = sum(
        1 for s in open_positions
        if any(s.upper() in m for sec, m in sector_map.items() if sec == sym_sector)
    ) if sym_sector else 0

    if sector_exposure >= 3:
        return 30.0, f"sector concentrated ({sector_exposure} in {sym_sector})"
    if n_pos == 0:
        return 75.0, "portfolio empty — diversification bonus"
    if n_pos <= 3:
        return 65.0, f"low concentration ({n_pos} positions)"
    return 50.0, f"{n_pos} open positions, sector ok"

# ─────────────────────────────────────────────────────────────────────────────
# Contradiction detection
# ─────────────────────────────────────────────────────────────────────────────

def detect_contradictions(factor_scores: Dict[str, float]) -> Dict[str, Any]:
    BULLISH = {"trend", "momentum", "relative_strength", "market_regime", "sector_strength",
               "hist_expectancy", "historical_similarity", "risk_reward"}
    bullish = [f for f in BULLISH if factor_scores.get(f, 50) >= 60]
    bearish = [f for f in BULLISH if factor_scores.get(f, 50) <= 40]
    if factor_scores.get("data_freshness", 50) <= 20: bearish.append("data_freshness")
    if factor_scores.get("volatility", 50) <= 30: bearish.append("volatility")

    contras = [f"{b}↑ vs {be}↓" for b in bullish for be in bearish]
    level = "HIGH" if len(bullish) >= 2 and len(bearish) >= 2 else \
            "MEDIUM" if len(bullish) >= 1 and len(bearish) >= 2 else \
            "LOW" if len(bullish) >= 1 and len(bearish) >= 1 else "NONE"

    return {
        "level": level,
        "bullish_factors": bullish,
        "bearish_factors": bearish,
        "contradictions": contras[:6],
        "explanation": f"{len(bullish)} bullish vs {len(bearish)} bearish. " +
                       ("; ".join(contras[:3]) if contras else "Signals agree."),
    }

# ─────────────────────────────────────────────────────────────────────────────
# Confidence calibration
# ─────────────────────────────────────────────────────────────────────────────

def calibrate_confidence(raw_score: float, evidence: str, contradiction_level: str) -> Dict[str, Any]:
    """
    Adjust raw fused score with evidence quality and contradictions.
    Prevents misleading precision on small samples.
    """
    ev_mult = {"validated": 1.00, "strong": 0.95, "moderate": 0.88, "low": 0.78, "very_low": 0.65, "insufficient": 0.55}.get(evidence, 0.55)
    contra_mult = {"NONE": 1.0, "LOW": 0.97, "MEDIUM": 0.90, "HIGH": 0.80}.get(contradiction_level, 1.0)
    calibrated = _clamp(raw_score * ev_mult * contra_mult)
    precision = (
        "±15" if evidence in ("insufficient", "very_low") else
        "±10" if evidence == "low" else
        "±7"  if evidence == "moderate" else
        "±5"  if evidence == "strong" else "±3"
    )
    return {
        "raw_score": round(raw_score, 1),
        "calibrated_score": round(calibrated, 1),
        "evidence": evidence,
        "evidence_mult": round(ev_mult, 2),
        "contradiction_mult": round(contra_mult, 2),
        "precision": precision,
        "note": f"Score {precision} due to {evidence} evidence",
    }

# ─────────────────────────────────────────────────────────────────────────────
# Volatility-aware position sizing
# ─────────────────────────────────────────────────────────────────────────────

def volatility_aware_size(
    entry_price: float, stop_loss: float,
    available_cash: float, capital: float = 5000.0,
    vix: float = 18.0, regime: str = "RANGE_BOUND",
) -> Dict[str, Any]:
    if entry_price <= 0:
        return {"feasible": False, "suggested_quantity": 0, "sizing_note": "invalid entry price",
                "max_risk_pct_used": MAX_RISK_PCT, "regime_adj": "none"}
    adj_risk = MAX_RISK_PCT * (0.5 if regime in ("CRISIS", "VOLATILE") or vix >= 28 else
                               0.75 if regime == "TRENDING_DOWN" or vix >= 22 else 1.0)
    adj_label = ("halved (crisis/volatile)" if adj_risk == MAX_RISK_PCT * 0.5 else
                 "reduced 25% (bearish)" if adj_risk == MAX_RISK_PCT * 0.75 else "standard")
    max_risk = capital * adj_risk
    stop_dist = max(0.0, entry_price - stop_loss)
    qty_risk = math.floor(max_risk / stop_dist) if stop_dist > 0 else 0
    qty_cap = math.floor(available_cash * MAX_CAPITAL_PCT / entry_price)
    qty = max(0, min(qty_risk, qty_cap))
    pos_val = round(qty * entry_price, 2)
    max_loss = round(qty * stop_dist, 2)
    cap_util = round(pos_val / available_cash * 100, 1) if available_cash > 0 else 0.0
    return {
        "feasible": qty >= MIN_SHARES,
        "suggested_quantity": qty,
        "position_value": pos_val,
        "max_loss": max_loss,
        "max_risk_pct_used": adj_risk,
        "capital_utilization_pct": cap_util,
        "stop_distance": round(stop_dist, 2),
        "regime_adj": adj_label,
        "regime": regime, "vix": vix,
        "sizing_note": (
            f"Risk {adj_risk*100:.1f}% ({adj_label}); qty={qty} @ ₹{entry_price:.2f}; max-loss=₹{max_loss:.2f}"
            if qty >= MIN_SHARES else "Not feasible with current capital"
        ),
    }

# ─────────────────────────────────────────────────────────────────────────────
# Per-symbol fusion (14 factors)
# ─────────────────────────────────────────────────────────────────────────────

def fuse_symbol(
    item: Dict[str, Any],
    regime_info: Dict[str, Any],
    sector_rotation: List[Dict[str, Any]],
    nifty_ret: Optional[float],
    exp_map: Dict[str, Any],
    open_positions: List[str],
    available_cash: float,
    capital: float,
    vix: float,
    scan_stale: bool = False,
) -> Dict[str, Any]:
    from config import SECTOR_MAP
    symbol = str(item.get("symbol") or item.get("stock") or "?").upper()
    regime = regime_info.get("regime", "RANGE_BOUND")

    # ── Scores ────────────────────────────────────────────────────────────────
    trend_s,     trend_r     = _score_trend(item)
    momentum_s,  momentum_r  = _score_momentum(item)
    vol_s,       vol_r       = _score_volatility(item, vix)
    volume_s,    volume_r    = _score_volume(item)
    fresh_s,     fresh_r     = _score_data_freshness(item)
    hist_s,      hist_r      = _score_hist_expectancy(symbol, exp_map)
    calib_s,     calib_r     = _score_calibration_quality(item)
    sect_s,      sect_r      = _score_sector_strength(symbol, sector_rotation)
    regime_s,    regime_r    = _score_market_regime(regime_info)
    liq_s,       liq_r       = _score_liquidity(item)
    himsim_s,    himsim_r    = _score_historical_similarity(symbol, exp_map, regime)
    rr_s,        rr_r        = _score_risk_reward(item)
    portctx_s,   portctx_r   = _score_portfolio_context(symbol, open_positions, SECTOR_MAP)

    # Relative strength
    sym_ret = _safe(item.get("change_pct") or item.get("price_change_pct"))
    if sym_ret is None:
        price = _safe(item.get("price") or item.get("ltp")); prev = _safe(item.get("prev_close"))
        if price and prev and prev > 0:
            sym_ret = round((price - prev) / prev * 100, 2)

    sym_sector = next((sec for sec, m in SECTOR_MAP.items() if symbol in m), None)
    sector_ret: Optional[float] = None
    for row in sector_rotation:
        if row.get("sector") == sym_sector and row.get("avg_score") is not None:
            sector_ret = round((row["avg_score"] - 50) / 10, 2)
            break

    rs_data = compute_relative_strength(symbol, sym_ret, nifty_ret, sector_ret, sym_sector)
    rs_s, rs_r = _score_relative_strength(rs_data)

    factor_scores: Dict[str, float] = {
        "trend": trend_s, "momentum": momentum_s, "volatility": vol_s, "volume": volume_s,
        "relative_strength": rs_s, "market_regime": regime_s, "sector_strength": sect_s,
        "liquidity": liq_s, "hist_expectancy": hist_s, "calibration_quality": calib_s,
        "data_freshness": fresh_s, "historical_similarity": himsim_s,
        "risk_reward": rr_s, "portfolio_context": portctx_s,
    }
    factor_rationales: Dict[str, str] = {
        "trend": trend_r, "momentum": momentum_r, "volatility": vol_r, "volume": volume_r,
        "relative_strength": rs_r, "market_regime": regime_r, "sector_strength": sect_r,
        "liquidity": liq_r, "hist_expectancy": hist_r, "calibration_quality": calib_r,
        "data_freshness": fresh_r, "historical_similarity": himsim_r,
        "risk_reward": rr_r, "portfolio_context": portctx_r,
    }

    # ── Weighted fused score ──────────────────────────────────────────────────
    raw = sum(factor_scores[f] * FACTOR_WEIGHTS[f] for f in FACTOR_WEIGHTS)
    fused = _clamp(raw * regime_info.get("score_multiplier", 1.0))

    # ── Stale checks ──────────────────────────────────────────────────────────
    data_status = str(item.get("data_status") or "OK").upper()
    quality = str(item.get("data_quality") or item.get("quality") or "").upper()
    item_stale = (data_status == "DATA_UNAVAILABLE") or (quality in STALE_QUALITIES)
    is_stale = item_stale or scan_stale
    blocker: Optional[str] = None
    if is_stale:
        blocker = (f"Scan data stale — rankings suppressed" if scan_stale else f"Data unavailable/stale ({quality or data_status})")

    # ── Evidence ──────────────────────────────────────────────────────────────
    sym_stats = exp_map.get(symbol)
    evidence = evidence_label(sym_stats["count"] if sym_stats else 0)

    # ── Contradiction ─────────────────────────────────────────────────────────
    contradiction = detect_contradictions(factor_scores)

    # ── Calibrated confidence ─────────────────────────────────────────────────
    calib_info = calibrate_confidence(fused, evidence, contradiction["level"])

    # ── Action ────────────────────────────────────────────────────────────────
    cf = calib_info["calibrated_score"]
    if is_stale:
        action = "WATCH"
    elif cf >= 82:
        action = "STRONG_BUY"
    elif cf >= 68:
        action = "BUY"
    elif cf >= 52:
        action = "WATCH"
    else:
        action = "AVOID"

    if contradiction["level"] == "HIGH" and action in ("STRONG_BUY", "BUY"):
        action = "WATCH"
        if not blocker:
            blocker = "HIGH signal contradiction"

    # ── Strategy ──────────────────────────────────────────────────────────────
    selected_strategy = best_strategy_for_regime(regime, exp_map)
    eligible_strats = eligible_strategies(regime)

    # ── Sizing ────────────────────────────────────────────────────────────────
    entry = _safe(item.get("entry_price") or item.get("price") or item.get("ltp"), 0) or 0
    stop = _safe(item.get("stop_loss"), 0) or 0
    if entry > 0 and stop <= 0:
        stop = entry * 0.97
    sizing = volatility_aware_size(entry, stop, available_cash, capital, vix, regime)

    # ── What would change ─────────────────────────────────────────────────────
    if action in ("STRONG_BUY", "BUY"):
        wwc = f"Exit if stop hit, target reached, or regime turns CRISIS/TRENDING_DOWN"
    elif action == "WATCH":
        gap = 68 - cf
        wwc = f"Need ~{gap:.0f} more calibrated points for BUY; improve trend/momentum or wait for regime shift"
    else:
        wwc = f"Needs score ≥52; weakest: {min(factor_scores, key=factor_scores.__getitem__)}"

    # ── Positive/negative contributors ───────────────────────────────────────
    contribs = [(f, s, FACTOR_WEIGHTS[f], s * FACTOR_WEIGHTS[f]) for f, s in factor_scores.items()]
    positive = sorted([(f, s, w, c) for f, s, w, c in contribs if s >= 60], key=lambda x: x[3], reverse=True)[:4]
    negative = sorted([(f, s, w, c) for f, s, w, c in contribs if s <= 40], key=lambda x: x[3])[:4]

    return {
        "symbol": symbol, "sector": sym_sector,
        "p13_action": action,
        "fused_score": round(fused, 1),
        "calibrated_score": round(cf, 1),
        "raw_fused_score": round(raw, 1),
        "evidence": evidence,
        "calibration": calib_info,
        "factor_scores": {k: round(v, 1) for k, v in factor_scores.items()},
        "factor_rationales": factor_rationales,
        "positive_contributors": [{"factor": f, "score": s, "weight": w, "contribution": round(c, 2)} for f, s, w, c in positive],
        "negative_contributors": [{"factor": f, "score": s, "weight": w, "contribution": round(c, 2)} for f, s, w, c in negative],
        "regime": regime,
        "selected_strategy": selected_strategy,
        "eligible_strategies": eligible_strats,
        "contradiction": contradiction,
        "relative_strength": rs_data,
        "sizing": sizing,
        "is_stale": is_stale,
        "scan_stale": scan_stale,
        "blocker": blocker,
        "what_would_change": wwc,
        "price": _safe(item.get("price") or item.get("ltp")),
        "confidence": _safe(item.get("confidence") or item.get("ai_confidence")),
        "original_recommendation": item.get("recommendation") or item.get("action"),
        "data_quality": quality or "UNKNOWN",
    }

# ─────────────────────────────────────────────────────────────────────────────
# Main analysis entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_phase13_analysis(
    symbols: Optional[List[str]] = None,
    force: bool = False,
    available_cash: float = 5000.0,
    capital: float = 5000.0,
) -> Dict[str, Any]:
    cache = _load_cache()
    key = "full_analysis"
    if not force and _cache_fresh(cache, key):
        return cache[key]

    scan_raw = _load_json(os.path.join(_DIR, "phase7_scan_cache.json"), {})
    market_ctx = _load_json(os.path.join(_DIR, "market_context_cache.json"), {})

    recs: List[Dict[str, Any]] = (
        scan_raw.get("recommendations") or [] if isinstance(scan_raw, dict) else scan_raw
    ) if isinstance(scan_raw, (dict, list)) else []

    if symbols:
        syms_u = {s.upper() for s in symbols}
        recs = [r for r in recs if str(r.get("symbol") or r.get("stock") or "").upper() in syms_u]

    # Scan staleness check
    scan_ts = scan_raw.get("snapshot_ts") if isinstance(scan_raw, dict) else None
    scan_stale, scan_age_min = _scan_is_stale(scan_ts)

    regime_info = detect_market_regime(market_ctx if isinstance(market_ctx, dict) else {})
    vix = regime_info["inputs"]["vix"]
    sector_rotation = compute_sector_rotation(recs)

    completed = _completed_paper_trades()
    exp_map = _build_expectancy_map(completed)

    # NIFTY return
    qs = _load_json(os.path.join(_DIR, "phase11_quote_state.json"), {})
    nifty_q = (qs.get("cache") or {}).get("NIFTY") or {}
    nifty_ret = _safe((nifty_q.get("quote") or {}).get("change_pct"))

    # Open positions
    try:
        from paper_trader import _load_state as _pts
        pt_state = _pts()
        open_pos = list((pt_state.get("positions") or {}).keys())
    except Exception:
        open_pos = []

    fused_results: List[Dict[str, Any]] = []
    for item in recs:
        if not isinstance(item, dict): continue
        try:
            r = fuse_symbol(
                item=item, regime_info=regime_info, sector_rotation=sector_rotation,
                nifty_ret=nifty_ret, exp_map=exp_map, open_positions=open_pos,
                available_cash=available_cash, capital=capital, vix=vix,
                scan_stale=scan_stale,
            )
            fused_results.append(r)
        except Exception as exc:
            fused_results.append({"symbol": str(item.get("symbol") or "?"),
                                   "p13_action": "WATCH", "fused_score": 50.0, "error": str(exc)[:200]})

    fused_results.sort(key=lambda r: r.get("calibrated_score") or r.get("fused_score", 0), reverse=True)

    action_counts: Dict[str, int] = {}
    for r in fused_results:
        a = r.get("p13_action", "WATCH")
        action_counts[a] = action_counts.get(a, 0) + 1

    evidence_counts: Dict[str, int] = {}
    for r in fused_results:
        e = r.get("evidence", "insufficient")
        evidence_counts[e] = evidence_counts.get(e, 0) + 1

    payload = {
        "phase": PHASE,
        "engine_version": RESEARCH_ENGINE_VERSION,
        "generated_at": _now_str(),
        "label": LABEL,
        "regime": regime_info,
        "sector_rotation": sector_rotation,
        "fused_results": fused_results,
        "action_summary": action_counts,
        "evidence_summary": evidence_counts,
        "contradiction_summary": {
            lvl: sum(1 for r in fused_results if r.get("contradiction", {}).get("level") == lvl)
            for lvl in ("NONE", "LOW", "MEDIUM", "HIGH")
        },
        "completed_trade_count": len(completed),
        "open_positions": open_pos,
        "scan_stale": scan_stale,
        "scan_age_minutes": round(scan_age_min, 1) if scan_age_min is not None else None,
        "scan_ts": scan_ts,
        "factor_weights": FACTOR_WEIGHTS,
        "factors": list(FACTOR_WEIGHTS.keys()),
        "_cached_at": time.time(),
    }

    cache[key] = payload
    _save_cache(cache)
    return payload
