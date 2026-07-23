"""TimeframeAggregator — aggregates 1m CompletedBar events into higher timeframes.

Emit rules (in priority order):
  1. When N bars accumulated (N = bars per target interval).
  2. Session boundary: the new bar is on a different calendar date.
  3. Gap detection: elapsed time since last bar > interval duration.

On rules 2 and 3: emit the accumulated buffer and place the incoming bar into
a fresh buffer (it is NOT included in the emitted aggregate).
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from market_data.contracts import CompletedBar

logger = logging.getLogger(__name__)

# Bars per higher-timeframe interval (all source bars are assumed 1-minute)
_INTERVAL_BARS: dict[str, int] = {
    "5m": 5,
    "15m": 15,
    "1h": 60,
    "daily": 375,  # NSE full session: 9:15 – 15:30
}

# Equivalent duration in minutes (for gap detection threshold)
_INTERVAL_MINUTES: dict[str, int] = {
    "5m": 5,
    "15m": 15,
    "1h": 60,
    "daily": 375,
}


class TimeframeAggregator:
    """Stateful aggregator for a single (instrument_token, target_interval) pair.

    Not coroutine-safe — use one instance per strategy runtime task.
    """

    def __init__(self, instrument_token: str, target_interval: str) -> None:
        if target_interval not in _INTERVAL_BARS:
            raise ValueError(
                f"Unsupported interval {target_interval!r}. "
                f"Choose from: {sorted(_INTERVAL_BARS)}"
            )
        self._instrument_token = instrument_token
        self._target_interval = target_interval
        self._target_bars = _INTERVAL_BARS[target_interval]
        self._interval_minutes = _INTERVAL_MINUTES[target_interval]
        self._buffer: List[CompletedBar] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def on_bar(self, bar: CompletedBar) -> Optional[CompletedBar]:
        """Process one source bar.

        Returns an aggregated bar when a complete higher-timeframe bar is
        ready, else None.
        """
        if bar.instrument_token != self._instrument_token:
            return None

        bar_ts = _parse_ts(bar.timestamp)

        # Check for boundary conditions when we have buffered bars
        if self._buffer:
            last_ts = _parse_ts(self._buffer[-1].timestamp)

            session_boundary = bar_ts.date() != last_ts.date()
            gap_minutes = (bar_ts - last_ts).total_seconds() / 60
            gap_detected = gap_minutes > self._interval_minutes

            if session_boundary or gap_detected:
                # Emit what we have, then start fresh with the incoming bar
                emitted = self._emit()
                self._buffer.append(bar)
                return emitted

        self._buffer.append(bar)

        if len(self._buffer) >= self._target_bars:
            return self._emit()

        return None

    def reset(self) -> None:
        """Discard the current buffer without emitting."""
        self._buffer = []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _emit(self) -> CompletedBar:
        """Build and return an aggregated bar from the current buffer, then clear it."""
        bars = self._buffer
        self._buffer = []

        open_price = bars[0].open
        high_price = max(b.high for b in bars)
        low_price = min(b.low for b in bars)
        close_price = bars[-1].close
        total_volume = sum((b.volume for b in bars), Decimal("0"))

        return CompletedBar(
            instrument_token=self._instrument_token,
            timestamp=bars[-1].timestamp,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=total_volume,
            interval=self._target_interval,
        )


def _parse_ts(ts: str | datetime) -> datetime:
    """Parse an ISO-8601 timestamp string (or pass-through a datetime)."""
    if isinstance(ts, datetime):
        return ts
    return datetime.fromisoformat(ts)
