from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict

from market_data.contracts import CompletedBar

logger = logging.getLogger(__name__)


class VolatilityForecast(BaseModel, frozen=True):
    model_config = ConfigDict(frozen=True, protected_namespaces=())

    instrument_token: str
    forecast_window: str
    expected_range: Decimal
    expected_range_pct: Decimal
    confidence: Decimal
    model_version: str
    computed_at: str


class VolatilityForecaster:
    """Lightweight volatility forecasting from recent bar data.

    Uses ATR-based projection with STD fallback.
    """

    def __init__(self, default_window: str = "15m") -> None:
        self._default_window = default_window
        self._bar_buffers: Dict[str, List[CompletedBar]] = {}

    def _get_close(self, bars: List[CompletedBar]) -> Decimal:
        if not bars:
            return Decimal("1")
        return bars[-1].close

    def _compute_atr(self, bars: List[CompletedBar], period: int = 14) -> Optional[Decimal]:
        if len(bars) < period + 1:
            return None
        from market_intelligence.indicator_engine import compute_atr
        return compute_atr(bars, period)

    def _compute_std(self, bars: List[CompletedBar], period: int = 20) -> Optional[Decimal]:
        """Compute standard deviation using up to `period` bars.

        Uses min(len(bars), period) so that short bar sequences still produce
        a result, which is preferable to falling back to the 1% default.
        Requires at least 2 bars.
        """
        n = min(len(bars), period)
        if n < 2:
            return None
        closes = [b.close for b in bars[-n:]]
        mean = sum(closes) / Decimal(n)
        variance = sum((c - mean) ** 2 for c in closes) / Decimal(n)
        return variance.sqrt()

    def forecast(
        self,
        instrument_token: str,
        bars: List[CompletedBar],
        window: Optional[str] = None,
    ) -> VolatilityForecast:
        """Generate volatility forecast from recent bars."""
        close = self._get_close(bars)
        atr = self._compute_atr(bars, 14)
        std = self._compute_std(bars, 20)

        # Use ATR if available, else std, else default to 1% of price
        if atr is not None and atr > 0:
            expected_range = atr * Decimal("2")  # ~2 ATR range
            confidence = Decimal("0.6")
        elif std is not None and std > 0:
            expected_range = std * Decimal("2")
            confidence = Decimal("0.5")
        else:
            expected_range = close * Decimal("0.01")  # 1% default
            confidence = Decimal("0.3")

        expected_range_pct = (expected_range / close * Decimal("100")) if close > 0 else Decimal("0")

        return VolatilityForecast(
            instrument_token=instrument_token,
            forecast_window=window or self._default_window,
            expected_range=expected_range.quantize(Decimal("0.0001")),
            expected_range_pct=expected_range_pct.quantize(Decimal("0.0001")),
            confidence=confidence.quantize(Decimal("0.0001")),
            model_version="vol-1.0",
            computed_at=datetime.now(timezone.utc).isoformat(),
        )

    def update(self, bar: CompletedBar) -> None:
        """Add bar to internal buffer."""
        token = bar.instrument_token
        if token not in self._bar_buffers:
            self._bar_buffers[token] = []
        self._bar_buffers[token].append(bar)
        if len(self._bar_buffers[token]) > 50:
            self._bar_buffers[token] = self._bar_buffers[token][-50:]

    def get_buffer(self, instrument_token: str) -> List[CompletedBar]:
        return self._bar_buffers.get(instrument_token, [])
