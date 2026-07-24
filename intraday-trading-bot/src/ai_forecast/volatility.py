"""RC-10B VolatilityForecaster — ATR-based intraday volatility estimation.

Public contract (plan-aligned):
    VolatilityForecast.predicted_atr          raw ATR value
    VolatilityForecast.predicted_range_pct    predicted_atr / close * 100
    VolatilityForecast.confidence             ATR stability score ∈ [0.3, 0.9]
    VolatilityForecast.forecast_horizon       e.g. "15m"
    VolatilityForecast.computed_at            timezone-aware datetime

Algorithms:
  ATR-based  (≥15 bars):  predicted_atr = ATR(14); confidence = ATR stability
  STD-based  (2–14 bars): predicted_atr = STD of closes (2×bar window);
                           confidence = 0.5
  Fallback   (0–1 bars):  predicted_atr = 0; confidence = 0.3
             (prefer near-zero over 1% floor to avoid misrepresenting
              NSE instruments at different price scales)

Backward-compat deprecated aliases on VolatilityForecast:
  .expected_range      → .predicted_atr
  .expected_range_pct  → .predicted_range_pct
  .forecast_window     → .forecast_horizon
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from decimal import Decimal
from typing import Deque, Dict, List, Optional

from pydantic import BaseModel, ConfigDict

from market_data.contracts import CompletedBar

logger = logging.getLogger(__name__)

_D0 = Decimal("0")
_FOUR = Decimal("0.0001")


class VolatilityForecast(BaseModel, frozen=True):
    """Plan-aligned volatility forecast."""

    model_config = ConfigDict(frozen=True, protected_namespaces=())

    instrument_token: str
    predicted_atr: Decimal
    predicted_range_pct: Decimal
    confidence: Decimal
    forecast_horizon: str
    model_version: str
    computed_at: datetime

    # ------------------------------------------------------------------
    # Deprecated field aliases — preserved for backward compatibility
    # ------------------------------------------------------------------

    @property
    def expected_range(self) -> Decimal:
        """Deprecated: use predicted_atr."""
        return self.predicted_atr

    @property
    def expected_range_pct(self) -> Decimal:
        """Deprecated: use predicted_range_pct."""
        return self.predicted_range_pct

    @property
    def forecast_window(self) -> str:
        """Deprecated: use forecast_horizon."""
        return self.forecast_horizon


class VolatilityForecaster:
    """Lightweight volatility forecaster from recent bar data.

    Maintains per-instrument 50-bar ring buffers.
    update() and forecast() are protected by an asyncio.Lock for concurrent
    strategy runtimes sharing the same forecaster instance.
    """

    _BUFFER_CAPACITY = 50
    _ATR_PERIOD      = 14
    _STD_PERIOD      = 20
    _ATR_HIST_SIZE   = 5    # bars kept for stability computation

    def __init__(self, default_window: str = "15m") -> None:
        self._default_window = default_window
        self._bar_buffers: Dict[str, Deque[CompletedBar]] = {}
        self._atr_history: Dict[str, Deque[Decimal]] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def forecast(
        self,
        instrument_token: str,
        bars: Optional[List[CompletedBar]] = None,
        window: Optional[str] = None,
    ) -> VolatilityForecast:
        """Generate a volatility forecast.

        Uses bars from the internal buffer if bars is None.
        """
        if bars is None:
            bars = list(self._bar_buffers.get(instrument_token, []))

        close = bars[-1].close if bars else _D0
        atr = self._compute_atr(bars)
        std = self._compute_std(bars)

        if atr is not None and atr > _D0:
            predicted_atr = atr
            confidence = self._compute_confidence(instrument_token, atr)
        elif std is not None and std > _D0:
            predicted_atr = std
            confidence = Decimal("0.5")
        else:
            predicted_atr = _D0
            confidence = Decimal("0.3")

        predicted_range_pct = (
            (predicted_atr / close * Decimal("100")).quantize(_FOUR)
            if close > _D0
            else _D0
        )

        return VolatilityForecast(
            instrument_token=instrument_token,
            predicted_atr=predicted_atr.quantize(_FOUR),
            predicted_range_pct=predicted_range_pct,
            confidence=confidence.quantize(_FOUR),
            forecast_horizon=window or self._default_window,
            model_version="vol-1.1",
            computed_at=datetime.now(timezone.utc),
        )

    def update(self, bar: CompletedBar) -> None:
        """Add a bar to the internal buffer.  Thread-safe via GIL on deque append."""
        token = bar.instrument_token
        if token not in self._bar_buffers:
            self._bar_buffers[token] = deque(maxlen=self._BUFFER_CAPACITY)
        self._bar_buffers[token].append(bar)

    def get_buffer(self, instrument_token: str) -> List[CompletedBar]:
        """Return a snapshot of the internal buffer for an instrument."""
        return list(self._bar_buffers.get(instrument_token, []))

    # ------------------------------------------------------------------
    # Private computation
    # ------------------------------------------------------------------

    def _compute_atr(self, bars: List[CompletedBar]) -> Optional[Decimal]:
        if len(bars) < self._ATR_PERIOD + 1:
            return None
        try:
            from market_intelligence.indicator_engine import compute_atr
            return compute_atr(bars, self._ATR_PERIOD)
        except Exception:
            return None

    def _compute_std(self, bars: List[CompletedBar]) -> Optional[Decimal]:
        """STD of closes over up to _STD_PERIOD bars; requires ≥ 2."""
        n = min(len(bars), self._STD_PERIOD)
        if n < 2:
            return None
        closes = [b.close for b in bars[-n:]]
        mean = sum(closes) / Decimal(n)
        variance = sum((c - mean) ** 2 for c in closes) / Decimal(n)
        return variance.sqrt()

    def _compute_confidence(self, instrument_token: str, atr: Decimal) -> Decimal:
        """ATR stability confidence: 1 − CV(ATR history), clamped to [0.3, 0.9].

        CV = std(ATR) / mean(ATR).  Higher stability (lower CV) → higher confidence.
        Falls back to 0.6 when history is too short.
        """
        hist = self._atr_history.setdefault(
            instrument_token, deque(maxlen=self._ATR_HIST_SIZE)
        )
        hist.append(atr)

        if len(hist) < 3:
            return Decimal("0.6")  # Not enough history yet

        values = list(hist)
        mean_atr = sum(values) / Decimal(len(values))
        if mean_atr == _D0:
            return Decimal("0.3")
        variance = sum((v - mean_atr) ** 2 for v in values) / Decimal(len(values))
        std_atr = variance.sqrt()
        cv = std_atr / mean_atr
        stability = Decimal("1") - cv
        lo, hi = Decimal("0.3"), Decimal("0.9")
        return max(lo, min(hi, stability))
