"""
market_regime.py
Classifies the NSE market regime using NIFTY 50 price data.

Regime types: BULLISH | BEARISH | SIDEWAYS | HIGH_VOLATILITY | LOW_VOLATILITY

Confidence adjustments applied to signal scoring:
  BEARISH       → buy_score  -= 20
  BULLISH       → sell_score -= 20
  SIDEWAYS      → buy_score  -= 10, sell_score -= 10
  HIGH_VOLATILITY → risk level upgraded

Falls back to simulated / neutral data if index fetch fails.
"""

import numpy as np
import pandas as pd
from typing import TypedDict, Optional

NIFTY_SYMBOL = "^NSEI"
BANKNIFTY_SYMBOL = "^NSEBANK"
VIX_SYMBOL = "^INDIAVIX"


class RegimeResult(TypedDict):
    regime: str                        # BULLISH | BEARISH | SIDEWAYS | HIGH_VOLATILITY | LOW_VOLATILITY
    nifty_price: float
    nifty_change_pct: float
    nifty_trend: str                   # UP | DOWN | SIDEWAYS
    banknifty_price: float
    banknifty_change_pct: float
    banknifty_trend: str
    vix_value: float
    vix_status: str                    # LOW | MODERATE | HIGH | EXTREME
    adj_buy: float                     # confidence points to subtract from buy score
    adj_sell: float                    # confidence points to subtract from sell score
    high_volatility: bool
    description: str


def _fetch_index(symbol: str, period: str = "3mo") -> Optional[pd.DataFrame]:
    """Fetch OHLCV for an index symbol (no .NS suffix)."""
    try:
        import yfinance as yf
        df = yf.download(symbol, period=period, interval="1d", progress=False, auto_adjust=True)
        if df.empty:
            return None
        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.columns = ["open", "high", "low", "close", "volume"]
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.index = pd.to_datetime(df.index)
        df = df.dropna()
        return df if len(df) >= 20 else None
    except Exception:
        return None


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _atr_pct(df: pd.DataFrame, period: int = 14) -> float:
    """Compute ATR as % of current price (realized volatility proxy)."""
    h, l, c = df["high"], df["low"], df["close"]
    prev_c = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    atr = float(tr.ewm(com=period - 1, min_periods=period).mean().iloc[-1])
    price = float(c.iloc[-1])
    return (atr / price * 100) if price > 0 else 2.0


def _classify_trend(df: pd.DataFrame) -> tuple[str, float, float]:
    """Return (trend, price, change_pct) from daily OHLCV."""
    close = df["close"]
    price = float(close.iloc[-1])
    ema20 = float(_ema(close, 20).iloc[-1])
    ema50 = float(_ema(close, 50).iloc[-1])

    # 5-day return
    prev_price = float(close.iloc[-6]) if len(close) >= 6 else float(close.iloc[0])
    change_pct = ((price - prev_price) / prev_price * 100) if prev_price > 0 else 0.0

    if ema20 > ema50 * 1.005 and change_pct > 0.5:
        trend = "UP"
    elif ema20 < ema50 * 0.995 and change_pct < -0.5:
        trend = "DOWN"
    else:
        trend = "SIDEWAYS"

    return trend, price, change_pct


def _vix_status(vix: float) -> str:
    if vix < 13:
        return "LOW"
    elif vix < 20:
        return "MODERATE"
    elif vix < 28:
        return "HIGH"
    else:
        return "EXTREME"


def _simulate_regime() -> RegimeResult:
    """Fallback neutral regime when index data is unavailable."""
    return RegimeResult(
        regime="SIDEWAYS",
        nifty_price=0.0,
        nifty_change_pct=0.0,
        nifty_trend="SIDEWAYS",
        banknifty_price=0.0,
        banknifty_change_pct=0.0,
        banknifty_trend="SIDEWAYS",
        vix_value=16.0,
        vix_status="MODERATE",
        adj_buy=10.0,
        adj_sell=10.0,
        high_volatility=False,
        description="Market regime: SIDEWAYS (simulated — index data unavailable)",
    )


def get_regime() -> RegimeResult:
    """
    Classify the current NSE market regime.

    Returns a RegimeResult with confidence adjustments ready to be applied
    to individual stock signal scores.
    """
    nifty_df = _fetch_index(NIFTY_SYMBOL)
    if nifty_df is None:
        return _simulate_regime()

    nifty_trend, nifty_price, nifty_chg = _classify_trend(nifty_df)

    # Bank NIFTY — graceful fallback
    bnk_df = _fetch_index(BANKNIFTY_SYMBOL)
    if bnk_df is not None:
        bnk_trend, bnk_price, bnk_chg = _classify_trend(bnk_df)
    else:
        bnk_trend, bnk_price, bnk_chg = nifty_trend, 0.0, 0.0

    # Volatility from NIFTY realized vol
    atr_pct = _atr_pct(nifty_df)
    high_vol = atr_pct > 3.5

    # VIX — try live first, fall back to ATR-based estimate
    vix_df = _fetch_index(VIX_SYMBOL)
    if vix_df is not None:
        vix_value = float(vix_df["close"].iloc[-1])
        high_vol = high_vol or vix_value >= 20
    else:
        # Estimate VIX from NIFTY realized vol (rough proxy: annualize 14-day ATR%)
        vix_value = round(atr_pct * 10, 1)  # crude but functional

    vix_status = _vix_status(vix_value)

    # ── Regime classification ────────────────────────────────────────────────
    # Primary: volatility check overrides directional classification
    if high_vol or vix_status in ("HIGH", "EXTREME"):
        regime = "HIGH_VOLATILITY"
        adj_buy = 0.0
        adj_sell = 0.0
        desc = (
            f"HIGH VOLATILITY regime — NIFTY ATR {atr_pct:.1f}%, VIX {vix_value:.1f}. "
            "Risk elevated; position sizes reduced. All signals valid but risk level raised."
        )
    elif atr_pct < 1.5 and vix_status == "LOW":
        regime = "LOW_VOLATILITY"
        adj_buy = 0.0
        adj_sell = 0.0
        desc = (
            f"LOW VOLATILITY regime — VIX {vix_value:.1f}, compressed ranges. "
            "Breakout signals preferred; avoid mean-reversion trades."
        )
    elif nifty_trend == "UP" and bnk_trend != "DOWN":
        regime = "BULLISH"
        adj_buy = 0.0
        adj_sell = 20.0
        desc = (
            f"BULLISH regime — NIFTY trending up ({nifty_chg:+.1f}% 5-day). "
            "SELL signal confidence reduced by 20 points. Favour longs."
        )
    elif nifty_trend == "DOWN" and bnk_trend != "UP":
        regime = "BEARISH"
        adj_buy = 20.0
        adj_sell = 0.0
        desc = (
            f"BEARISH regime — NIFTY trending down ({nifty_chg:+.1f}% 5-day). "
            "BUY signal confidence reduced by 20 points. Favour shorts/cash."
        )
    else:
        regime = "SIDEWAYS"
        adj_buy = 10.0
        adj_sell = 10.0
        desc = (
            f"SIDEWAYS regime — NIFTY consolidating ({nifty_chg:+.1f}% 5-day). "
            "Both BUY and SELL confidence reduced by 10. Range-bound conditions."
        )

    return RegimeResult(
        regime=regime,
        nifty_price=round(nifty_price, 2),
        nifty_change_pct=round(nifty_chg, 2),
        nifty_trend=nifty_trend,
        banknifty_price=round(bnk_price, 2),
        banknifty_change_pct=round(bnk_chg, 2),
        banknifty_trend=bnk_trend,
        vix_value=round(vix_value, 2),
        vix_status=vix_status,
        adj_buy=adj_buy,
        adj_sell=adj_sell,
        high_volatility=high_vol,
        description=desc,
    )
