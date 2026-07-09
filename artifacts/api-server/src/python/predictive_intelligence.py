"""
Predictive Intelligence Engine — Sprint 3 Module 3.

Evidence layer on top of existing signals: for a candidate trade setup,
find similar historical trades in the Trade Intelligence database and
summarise how they performed. Does NOT replace scanner/AI logic and never
places orders — it only annotates candidates with historical evidence.
"""

from __future__ import annotations

import sqlite3

from trade_intelligence import DB_PATH, classify_regime

# ── Bucketing helpers ─────────────────────────────────────────────────────────

def rsi_bucket(v) -> str:
    if v is None:
        return "unknown"
    if v < 30:  return "oversold"
    if v < 45:  return "weak"
    if v < 55:  return "neutral"
    if v <= 70: return "strong"
    return "overbought"


def adx_bucket(v) -> str:
    if v is None:
        return "unknown"
    if v < 20:  return "no_trend"
    if v < 25:  return "emerging"
    if v <= 40: return "trending"
    return "strong_trend"


def volume_bucket(v) -> str:
    if v is None:
        return "unknown"
    if v < 0.8:  return "low"
    if v <= 1.2: return "normal"
    if v <= 2.0: return "elevated"
    return "surge"


def score_bucket(v) -> str:
    """20-point buckets for 0–100 scores (opportunity / confidence)."""
    if v is None:
        return "unknown"
    return str(int(min(max(v, 0), 99.999) // 20))


def rr_bucket(v) -> str:
    if v is None:
        return "unknown"
    if v < 1:  return "poor"
    if v < 2:  return "fair"
    if v < 3:  return "good"
    return "excellent"


def macd_direction(macd, macd_signal) -> str:
    if macd is None or macd_signal is None:
        return "unknown"
    return "bullish" if macd > macd_signal else "bearish"


def ema_alignment(ema9, ema20, ema50) -> str:
    if None in (ema9, ema20, ema50):
        return "unknown"
    if ema9 > ema20 > ema50:
        return "bullish"
    if ema9 < ema20 < ema50:
        return "bearish"
    return "mixed"


# ── Similarity scoring ────────────────────────────────────────────────────────

# Weights sum to 100. A historical trade counts as "similar" when its
# similarity score reaches MATCH_THRESHOLD.
WEIGHTS = {
    "symbol":       15,
    "sector":       10,
    "strategy":     15,
    "regime":       10,
    "rsi":          10,
    "macd_dir":      8,
    "ema_align":     8,
    "adx":           6,
    "volume":        6,
    "opportunity":   4,
    "confidence":    4,
    "risk_reward":   4,
}
MATCH_THRESHOLD = 45.0


def _features(row: dict) -> dict:
    return {
        "symbol":      str(row.get("symbol") or "").upper(),
        "sector":      str(row.get("sector") or "").upper(),
        "strategy":    str(row.get("entry_strategy") or "").strip().lower(),
        "regime":      str(row.get("market_regime") or ""),
        "rsi":         rsi_bucket(row.get("rsi")),
        "macd_dir":    macd_direction(row.get("macd"), row.get("macd_signal")),
        "ema_align":   ema_alignment(row.get("ema9"), row.get("ema20"), row.get("ema50")),
        "adx":         adx_bucket(row.get("adx")),
        "volume":      volume_bucket(row.get("volume_ratio")),
        "opportunity": score_bucket(row.get("opportunity_score")),
        "confidence":  score_bucket(row.get("confidence")),
        "risk_reward": rr_bucket(row.get("risk_reward")),
    }


def similarity(candidate_f: dict, hist_f: dict) -> float:
    score = 0.0
    for key, weight in WEIGHTS.items():
        c, h = candidate_f[key], hist_f[key]
        if c in ("", "unknown") or h in ("", "unknown"):
            continue
        if c == h:
            score += weight
    return score


def match_type(candidate_f: dict, hist_f: dict) -> str:
    exact_keys = ("symbol", "sector", "strategy", "regime")
    if all(candidate_f[k] == hist_f[k] and candidate_f[k] not in ("", "unknown")
           for k in exact_keys):
        return "exact"
    return "near"


# ── Evidence engine ───────────────────────────────────────────────────────────

def _load_history() -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT symbol, sector, entry_strategy, market_regime, rsi, macd, "
            "macd_signal, ema9, ema20, ema50, adx, volume_ratio, "
            "opportunity_score, confidence, risk_reward, "
            "return_percent, profit_loss, outcome_classification "
            "FROM trade_intelligence "
            "WHERE return_percent IS NOT NULL"
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def _confidence_level(matches: int) -> str:
    if matches >= 50: return "HIGH"
    if matches >= 20: return "MEDIUM"
    if matches >= 5:  return "LOW"
    return "INSUFFICIENT"


def evaluate_candidate(candidate: dict) -> dict:
    """
    Compare a candidate trade setup with historical trades and return an
    evidence summary plus a suggested confidence adjustment.

    candidate keys (all optional except symbol):
      symbol, sector, entry_strategy, market_regime, rsi, macd, macd_signal,
      ema9, ema20, ema50, adx, volume_ratio, opportunity_score, confidence,
      risk_reward
    """
    cf = _features(candidate)
    history = _load_history()

    similar: list[tuple[float, str, dict]] = []
    for h in history:
        hf = _features(h)
        s = similarity(cf, hf)
        if s >= MATCH_THRESHOLD:
            similar.append((s, match_type(cf, hf), h))

    matches = len(similar)
    exact_matches = sum(1 for _, mt, _ in similar if mt == "exact")
    level = _confidence_level(matches)

    returns = [float(h["return_percent"]) for _, _, h in similar]
    wins    = [r for r in returns if r > 0]
    losses  = [r for r in returns if r <= 0]

    win_rate    = round(len(wins) / matches * 100, 1) if matches else None
    avg_return  = round(sum(returns) / matches, 2) if matches else None
    avg_win     = round(sum(wins) / len(wins), 2) if wins else None
    avg_loss    = round(sum(losses) / len(losses), 2) if losses else None
    gross_win   = sum(wins)
    gross_loss  = abs(sum(losses))
    profit_factor = (
        round(gross_win / gross_loss, 2) if gross_loss > 0
        else (None if not wins else float("inf"))
    )
    if profit_factor == float("inf"):
        profit_factor = 99.99  # JSON-safe "all winners" marker
    expected_value = None
    if matches:
        p = len(wins) / matches
        expected_value = round(p * (avg_win or 0.0) + (1 - p) * (avg_loss or 0.0), 2)

    # ── Confidence adjustment per spec ────────────────────────────────────
    adjustment = 0
    warnings: list[str] = []
    if level == "INSUFFICIENT":
        warnings.append("Not enough historical examples yet.")
    else:
        if (win_rate or 0) > 60 and (expected_value or 0) > 0:
            adjustment = {"HIGH": 10, "MEDIUM": 7, "LOW": 5}[level]
        elif (win_rate or 0) < 45 or (expected_value or 0) < 0:
            adjustment = -{"HIGH": 20, "MEDIUM": 15, "LOW": 10}[level]
            warnings.append("Similar setups have historically underperformed.")

    base_conf = candidate.get("confidence")
    adjusted_confidence = None
    if base_conf is not None:
        adjusted_confidence = round(
            min(100.0, max(0.0, float(base_conf) + adjustment)), 1
        )

    return {
        "symbol": str(candidate.get("symbol", "")).upper(),
        "candidate_features": cf,
        "evidence": {
            "matches": matches,
            "exact_matches": exact_matches,
            "win_rate": win_rate,
            "average_return": avg_return,
            "average_win": avg_win,
            "average_loss": avg_loss,
            "profit_factor": profit_factor,
            "expected_value": expected_value,
            "confidence_level": level,
        },
        "adjustment": adjustment,
        "base_confidence": base_conf,
        "adjusted_confidence": adjusted_confidence,
        "warnings": warnings,
    }


# ── Live-candidate builder (GET /predictive-intelligence/{symbol}) ──────────

def evaluate_symbol(symbol: str) -> dict:
    """
    Build a candidate setup for `symbol` from live data (indicators, sector,
    current market regime, cached opportunity metrics) and evaluate it.
    """
    sym = str(symbol).upper()
    candidate: dict = {"symbol": sym}

    try:
        from market_scanner import _sector_of
        candidate["sector"] = _sector_of(sym) or ""
    except Exception:
        candidate["sector"] = ""

    try:
        from market_data import fetch_ohlcv
        from indicator_engine import compute_indicators_df
        df = compute_indicators_df(fetch_ohlcv(sym, period="1y", interval="1d"))
        last = df.iloc[-1]

        def _v(col):
            try:
                v = float(last[col])
                return None if v != v else v  # NaN guard
            except (KeyError, TypeError, ValueError):
                return None

        candidate.update({
            "rsi": _v("rsi"), "macd": _v("macd_line"),
            "macd_signal": _v("macd_signal"),
            "ema9": _v("ema9"), "ema20": _v("ema20"), "ema50": _v("ema50"),
            "adx": _v("adx"), "volume_ratio": _v("volume_ratio"),
        })
    except Exception:
        pass  # evidence still works on categorical features

    try:
        regime = classify_regime()
        candidate["market_regime"] = regime["regime"]
    except Exception:
        candidate["market_regime"] = "Neutral"

    # Cached AI metrics from the latest opportunity scan, if present
    try:
        import json
        with open("opportunity_cache.json") as f:
            for item in json.load(f):
                if str(item.get("stock", "")).upper() == sym:
                    candidate["opportunity_score"] = item.get("opportunity_score")
                    candidate["confidence"] = item.get("confidence")
                    candidate["risk_reward"] = item.get("rr_ratio")
                    break
    except Exception:
        pass

    candidate.setdefault("entry_strategy", "AI Scan")
    return evaluate_candidate(candidate)
