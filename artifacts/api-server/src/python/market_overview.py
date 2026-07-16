"""
market_overview.py
Generates a market intelligence overview for the dashboard.

Data:
  - NIFTY 50 / BANK NIFTY price and trend
  - India VIX status
  - Market regime classification
  - Overall market score (0–100)
  - Top 5 strongest / weakest stocks from the watchlist
  - Scanned at timestamp
"""

import os
import json
from datetime import datetime, timezone
from typing import TypedDict

from market_regime import get_regime, RegimeResult
from signal_engine import generate_signal


class StockSnapshot(TypedDict):
    symbol: str
    price: float
    signal: str
    confidence: float
    change_pct: float


class MarketOverview(TypedDict):
    nifty_price: float
    nifty_change_pct: float
    nifty_trend: str
    banknifty_price: float
    banknifty_change_pct: float
    banknifty_trend: str
    regime: str
    regime_description: str
    vix_value: float
    vix_status: str
    market_score: float
    top_strong: list[StockSnapshot]
    top_weak: list[StockSnapshot]
    scanned_at: str


WATCHLIST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlist.json")
DEFAULT_WATCHLIST = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
    "SBIN", "WIPRO", "LT", "BAJFINANCE", "MARUTI",
]


def _load_watchlist() -> list[str]:
    if os.path.exists(WATCHLIST_FILE):
        try:
            with open(WATCHLIST_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return list(DEFAULT_WATCHLIST)


def _market_score(regime: RegimeResult, signals: list[dict]) -> float:
    """
    Compute an overall market score 0–100.

    Formula:
      - Base: 50 (neutral)
      - NIFTY trend contribution: ±15
      - Breadth: % of bullish signals × 20
      - VIX penalty: deduct up to 15 for high volatility
    """
    score = 50.0

    # NIFTY trend
    nifty_trend = regime.get("nifty_trend", "SIDEWAYS")
    if nifty_trend == "UP":
        score += 15
    elif nifty_trend == "DOWN":
        score -= 15

    # Breadth: fraction of BUY/STRONG_BUY signals
    actionable = [s for s in signals if s.get("signal") not in ("NO_TRADE", "WATCH")]
    if actionable:
        bulls = sum(1 for s in actionable if s.get("signal") in ("BUY", "STRONG_BUY"))
        breadth = bulls / len(actionable)
        score += (breadth - 0.5) * 20  # -10 to +10

    # VIX contribution
    vix = regime.get("vix_value", 16.0)
    if vix >= 28:
        score -= 15
    elif vix >= 20:
        score -= 8
    elif vix < 13:
        score += 5

    return round(max(0.0, min(100.0, score)), 1)


def get_market_overview(available_cash: float = 5000.0) -> MarketOverview:
    """
    Compute a full market overview snapshot.
    Scans the watchlist with the signal engine to rank stocks.
    """
    # Market regime (fetches NIFTY + VIX data)
    regime = get_regime()

    # Quick signal scan on watchlist for breadth + ranking
    watchlist = _load_watchlist()
    signals: list[dict] = []
    for sym in watchlist:
        try:
            # skip_mtf=True for speed — market overview is for ranking only,
            # not for generating trade signals (RUN SCAN does that with full MTF)
            sig = generate_signal(sym, available_cash, regime=regime, skip_mtf=True)
            signals.append(sig)
        except Exception:
            pass

    # Rank stocks: signed confidence (+= bullish, -= bearish)
    def signed_conf(s: dict) -> float:
        direction = 1 if s.get("signal") in ("BUY", "STRONG_BUY") else -1
        return direction * s.get("confidence", 0.0)

    ranked = sorted(signals, key=signed_conf, reverse=True)

    def to_snapshot(s: dict) -> StockSnapshot:
        return StockSnapshot(
            symbol=s.get("stock", ""),
            price=s.get("price", 0.0),
            signal=s.get("signal", "NO_TRADE"),
            confidence=s.get("confidence", 0.0),
            change_pct=0.0,  # change_pct not in signal — set via market_data if needed
        )

    top_strong = [to_snapshot(s) for s in ranked[:5]]
    top_weak = [to_snapshot(s) for s in ranked[-5:]][::-1]  # weakest first

    market_score = _market_score(regime, signals)

    return MarketOverview(
        nifty_price=regime["nifty_price"],
        nifty_change_pct=regime["nifty_change_pct"],
        nifty_trend=regime["nifty_trend"],
        banknifty_price=regime["banknifty_price"],
        banknifty_change_pct=regime["banknifty_change_pct"],
        banknifty_trend=regime["banknifty_trend"],
        regime=regime["regime"],
        regime_description=regime["description"],
        vix_value=regime["vix_value"],
        vix_status=regime["vix_status"],
        market_score=market_score,
        top_strong=top_strong,
        top_weak=top_weak,
        scanned_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
