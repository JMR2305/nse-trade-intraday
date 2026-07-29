"""
global_markets.py — Phase 7.3
Global market intelligence: major indices + global sentiment score.

Fetches via yfinance with a module-level session cache to avoid repeated calls.
Falls back to neutral defaults when yfinance is unavailable.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Optional

# ── Session cache ─────────────────────────────────────────────────────────────
_cache: dict = {}
_CACHE_TTL_S = 300   # 5 minutes

_INDEX_TICKERS = {
    "Dow Jones":     "^DJI",
    "NASDAQ":        "^IXIC",
    "S&P 500":       "^GSPC",
    "FTSE 100":      "^FTSE",
    "DAX":           "^GDAXI",
    "Nikkei 225":    "^N225",
    "Hang Seng":     "^HSI",
    "Shanghai":      "000001.SS",
    "GIFT Nifty":    "^NSEI",       # Nifty 50 as GIFT Nifty proxy
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cache_valid(key: str) -> bool:
    if key not in _cache:
        return False
    return (datetime.now(timezone.utc) - _cache[key]["ts"]).total_seconds() < _CACHE_TTL_S


def _fetch_index(ticker: str) -> dict:
    """Fetch last price + 1-day change % via yfinance fast_info."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        fi = t.fast_info
        price = float(fi.last_price or 0)
        prev  = float(fi.previous_close or price)
        change_pct = round(((price - prev) / prev * 100) if prev else 0.0, 2)
        return {
            "price":      round(price, 2),
            "prev_close": round(prev, 2),
            "change_pct": change_pct,
            "available":  price > 0,
        }
    except Exception:
        return {"price": 0.0, "prev_close": 0.0, "change_pct": 0.0, "available": False}


def _direction(change_pct: float) -> str:
    if change_pct > 0.3:   return "BULLISH"
    if change_pct < -0.3:  return "BEARISH"
    return "NEUTRAL"


def _global_sentiment_from_mi() -> dict:
    """Pull Phase 7.1 regime for richer context."""
    try:
        from market_intelligence_hub.shared_services import get_summary as mi_summary
        s = mi_summary()
        regime = s.get("market_regime", "SIDEWAYS")
        health = float(s.get("market_health_score", 50.0))
        return {"regime": regime, "health": health}
    except Exception:
        return {"regime": "SIDEWAYS", "health": 50.0}


def get_global_markets() -> dict:
    """Returns global index snapshots + composite sentiment score."""
    cache_key = "global_markets"
    if _cache_valid(cache_key):
        return _cache[cache_key]["data"]

    indices = []
    bullish_count = bearish_count = neutral_count = 0

    for name, ticker in _INDEX_TICKERS.items():
        data = _fetch_index(ticker)
        cp   = data["change_pct"]
        direction = _direction(cp)
        if direction == "BULLISH":  bullish_count += 1
        elif direction == "BEARISH": bearish_count += 1
        else:                        neutral_count += 1

        indices.append({
            "name":        name,
            "ticker":      ticker,
            "price":       data["price"],
            "prev_close":  data["prev_close"],
            "change_pct":  cp,
            "direction":   direction,
            "available":   data["available"],
        })

    total = max(1, bullish_count + bearish_count + neutral_count)
    sentiment_raw = (bullish_count - bearish_count) / total   # -1 to +1
    sentiment_score = round(50.0 + sentiment_raw * 35.0, 1)   # 15 to 85

    # Blend with Phase 7.1 regime health
    mi = _global_sentiment_from_mi()
    blended_score = round(sentiment_score * 0.6 + mi["health"] * 0.4, 1)

    if blended_score >= 65:   sentiment_label = "RISK_ON"
    elif blended_score >= 50: sentiment_label = "NEUTRAL"
    elif blended_score >= 35: sentiment_label = "CAUTIOUS"
    else:                     sentiment_label = "RISK_OFF"

    result = {
        "available":       True,
        "advisory_only":   True,
        "generated_at":    _now_iso(),
        "indices":         indices,
        "bullish_count":   bullish_count,
        "bearish_count":   bearish_count,
        "neutral_count":   neutral_count,
        "global_sentiment_score": blended_score,
        "sentiment_label": sentiment_label,
        "regime_context":  mi["regime"],
        "asia_session":    [i for i in indices if i["name"] in ("Nikkei 225", "Hang Seng", "Shanghai", "GIFT Nifty")],
        "europe_session":  [i for i in indices if i["name"] in ("FTSE 100", "DAX")],
        "us_session":      [i for i in indices if i["name"] in ("Dow Jones", "NASDAQ", "S&P 500")],
    }

    _cache[cache_key] = {"data": result, "ts": datetime.now(timezone.utc)}
    return result
