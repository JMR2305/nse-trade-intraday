"""MarketRegimeDetector — classifies market regime from indicator snapshots.

Algorithm (priority order):
  1. ADX > 40 and +DI > -DI  → STRONG_UPTREND
  2. ADX > 25 and +DI > -DI  → UPTREND
  3. ADX > 40 and -DI > +DI  → STRONG_DOWNTREND
  4. ADX > 25 and -DI > +DI  → DOWNTREND
  5. ATR / close > 0.02       → EXPANDING_RANGE
  6. ADX < 20 and ATR/close < 0.005 → RANGING
  7. Otherwise                → UNKNOWN

Confidence = ADX / 50, clamped to [0, 1].
When ADX is unavailable, confidence = 0.
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict

from market_intelligence.multi_timeframe_context import MarketRegime, MarketRegimeSnapshot

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")
_ONE = Decimal("1")
_FIFTY = Decimal("50")

_ADX_STRONG = Decimal("40")
_ADX_TREND = Decimal("25")
_ADX_WEAK = Decimal("20")
_ATR_EXPAND_RATIO = Decimal("0.02")
_ATR_RANGE_RATIO = Decimal("0.005")


class MarketRegimeDetector:
    """Stateless classifier.  Thread-safe (no mutable state)."""

    def detect(
        self,
        instrument_token: str,
        indicators: Dict[str, Decimal],
    ) -> MarketRegimeSnapshot:
        """Classify the market regime for the given indicator snapshot.

        Returns a MarketRegimeSnapshot with confidence in [0, 1].
        """
        if not indicators:
            return MarketRegimeSnapshot(
                instrument_token=instrument_token,
                regime=MarketRegime.UNKNOWN,
                confidence=_ZERO,
                detected_at=datetime.utcnow(),
            )

        adx = indicators.get("adx_14")
        plus_di = indicators.get("plus_di_14")
        minus_di = indicators.get("minus_di_14")
        atr = indicators.get("atr_14")
        close = indicators.get("close")

        regime = _classify(adx, plus_di, minus_di, atr, close)
        confidence = _compute_confidence(adx)

        return MarketRegimeSnapshot(
            instrument_token=instrument_token,
            regime=regime,
            confidence=confidence,
            detected_at=datetime.utcnow(),
        )


def _classify(
    adx: "Decimal | None",
    plus_di: "Decimal | None",
    minus_di: "Decimal | None",
    atr: "Decimal | None",
    close: "Decimal | None",
) -> MarketRegime:
    # Trend-based classification (requires ADX and both DI lines)
    if adx is not None and plus_di is not None and minus_di is not None:
        if adx > _ADX_STRONG and plus_di > minus_di:
            return MarketRegime.STRONG_UPTREND
        if adx > _ADX_TREND and plus_di > minus_di:
            return MarketRegime.UPTREND
        if adx > _ADX_STRONG and minus_di > plus_di:
            return MarketRegime.STRONG_DOWNTREND
        if adx > _ADX_TREND and minus_di > plus_di:
            return MarketRegime.DOWNTREND

    # Volatility-based classification (requires ATR and close)
    if atr is not None and close is not None and close > _ZERO:
        atr_ratio = atr / close
        if atr_ratio > _ATR_EXPAND_RATIO:
            return MarketRegime.EXPANDING_RANGE
        if adx is not None and adx < _ADX_WEAK and atr_ratio < _ATR_RANGE_RATIO:
            return MarketRegime.RANGING

    # ADX only: weak trend → ranging
    if adx is not None and adx < _ADX_WEAK:
        return MarketRegime.RANGING

    return MarketRegime.UNKNOWN


def _compute_confidence(adx: "Decimal | None") -> Decimal:
    if adx is None or adx <= _ZERO:
        return _ZERO
    raw = adx / _FIFTY
    return min(raw, _ONE)
