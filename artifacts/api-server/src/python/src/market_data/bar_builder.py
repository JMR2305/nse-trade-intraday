"""Tick-to-1-minute-bar aggregation engine.

Exchange-timestamp driven.  NSE session: 09:15–15:30 Asia/Kolkata.
Deterministic.  No fabricated bars for gaps.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Awaitable

from src.market_data.contracts import CompletedBar, DataGap, Tick
from src.market_data.provider import TickHandler

# NSE regular session in IST
NSE_OPEN = time(9, 15)
NSE_CLOSE = time(15, 30)

# Asia/Kolkata timezone
from zoneinfo import ZoneInfo
IST = ZoneInfo("Asia/Kolkata")


BarHandler = Callable[[CompletedBar], Awaitable[None] | None]
GapHandler = Callable[[DataGap], Awaitable[None] | None]


class BarBuilder:
    """Builds completed 1-minute bars from a stream of Ticks.

    Usage:
        builder = BarBuilder()
        builder.on_bar(my_bar_handler)
        builder.on_gap(my_gap_handler)
        builder.on_out_of_session(my_ooo_handler)
        for tick in ticks:
            builder.process(tick)
        builder.flush_session_close()  # at 15:30 or shutdown

    All timestamps are interpreted in IST (Asia/Kolkata).  The builder
    floors exchange timestamps to the minute boundary to determine bar
    placement.
    """

    def __init__(self) -> None:
        # instrument_token -> _BarState
        self._state: dict[int, _BarState] = {}
        # last seen fingerprint per token (for duplicate detection)
        self._last_fingerprint: dict[int, tuple] = {}
        # callbacks
        self._bar_callbacks: list[BarHandler] = []
        self._gap_callbacks: list[GapHandler] = []
        self._out_of_session_callbacks: list[TickHandler] = []
        self._out_of_order_callbacks: list[TickHandler] = []

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------
    def on_bar(self, callback: BarHandler) -> None:
        """Register a handler that receives each completed bar."""
        self._bar_callbacks.append(callback)

    def on_gap(self, callback: GapHandler) -> None:
        """Register a handler that receives each detected gap."""
        self._gap_callbacks.append(callback)

    def on_out_of_session(self, callback: TickHandler) -> None:
        """Register a handler for ticks outside NSE regular hours."""
        self._out_of_session_callbacks.append(callback)

    def on_out_of_order(self, callback: TickHandler) -> None:
        """Register a handler for out-of-order ticks."""
        self._out_of_order_callbacks.append(callback)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def process(self, tick: Tick) -> None:
        """Process a single tick.

        1. Duplicate detection (exact fingerprint match → drop).
        2. Session boundary check (outside 09:15–15:30 IST → out-of-session).
        3. Determine target minute (floor exchange_timestamp).
        4. If target == current_bar.minute → update current bar.
        5. If target > current_bar.minute → finalize current, emit gaps, start new.
        6. If target < current_bar.minute → out-of-order.
        """
        token = tick.instrument_token

        # 1. Duplicate detection
        fp = tick.fingerprint()
        if self._last_fingerprint.get(token) == fp:
            return
        self._last_fingerprint[token] = fp

        # 2. Session check
        if not self._is_within_session(tick.exchange_timestamp):
            self._notify_out_of_session(tick)
            return

        target_minute = self._floor_minute(tick.exchange_timestamp)
        state = self._state.get(token)

        if state is None:
            # First tick for this instrument today
            self._start_new_bar(token, target_minute, tick)
            return

        current_minute = state.minute

        if target_minute == current_minute:
            self._update_current_bar(state, tick)
        elif target_minute > current_minute:
            self._finalize_and_emit(state)
            self._emit_gaps(token, current_minute, target_minute)
            self._start_new_bar(token, target_minute, tick)
        else:
            # target_minute < current_minute
            self._notify_out_of_order(tick)

    def flush_session_close(self, instrument_token: int | None = None) -> None:
        """Finalize the open bar for one or all instruments.

        Call this deterministically at 15:30 IST or on graceful shutdown.
        """
        if instrument_token is not None:
            state = self._state.get(instrument_token)
            if state:
                self._finalize_and_emit(state)
                del self._state[instrument_token]
            return

        # Flush all
        for token, state in list(self._state.items()):
            self._finalize_and_emit(state)
        self._state.clear()

    def reset(self, instrument_token: int | None = None) -> None:
        """Reset state for one or all instruments (e.g. new trading day)."""
        if instrument_token is not None:
            self._state.pop(instrument_token, None)
            self._last_fingerprint.pop(instrument_token, None)
            return
        self._state.clear()
        self._last_fingerprint.clear()

    def current_bar(self, instrument_token: int) -> CompletedBar | None:
        """Return the in-progress (not yet finalized) bar for a token."""
        state = self._state.get(instrument_token)
        if state is None:
            return None
        return state.to_bar()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _is_within_session(self, dt: datetime) -> bool:
        """Return True if dt falls within NSE regular hours (Mon–Fri, 09:15–15:30 IST)."""
        # Convert to IST if needed
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            raise ValueError("timestamp must be timezone-aware")
        ist = dt.astimezone(IST)
        if ist.weekday() >= 5:  # Saturday or Sunday
            return False
        t = ist.time()
        return NSE_OPEN <= t <= NSE_CLOSE

    @staticmethod
    def _floor_minute(dt: datetime) -> datetime:
        """Floor a datetime to the minute boundary, preserving tzinfo."""
        return dt.replace(second=0, microsecond=0)

    def _start_new_bar(self, token: int, minute: datetime, tick: Tick) -> None:
        state = _BarState(
            instrument_token=token,
            minute=minute,
            open_price=tick.last_price,
            high_price=tick.last_price,
            low_price=tick.last_price,
            close_price=tick.last_price,
            volume=self._compute_volume_delta(token, tick.cumulative_volume),
            oi=tick.open_interest,
            prev_cumulative_volume=tick.cumulative_volume,
        )
        self._state[token] = state

    def _update_current_bar(self, state: _BarState, tick: Tick) -> None:
        # Update OHLC
        if tick.last_price > state.high_price:
            state.high_price = tick.last_price
        if tick.last_price < state.low_price:
            state.low_price = tick.last_price
        state.close_price = tick.last_price

        # Volume delta
        delta = self._compute_volume_delta_for_state(state, tick.cumulative_volume)
        state.volume += delta
        state.prev_cumulative_volume = tick.cumulative_volume

        # OI
        if tick.open_interest is not None:
            state.oi = tick.open_interest

    def _finalize_and_emit(self, state: _BarState) -> None:
        bar = state.to_bar()
        self._notify_bar(bar)

    def _emit_gaps(
        self,
        token: int,
        previous_minute: datetime,
        next_minute: datetime,
    ) -> None:
        """Emit DataGap records for every missing minute between previous and next."""
        gap_start = previous_minute + timedelta(minutes=1)
        while gap_start < next_minute:
            gap = DataGap(
                instrument_token=token,
                start=gap_start,
                end=gap_start + timedelta(minutes=1),
                gap_type="MISSING",
            )
            self._notify_gap(gap)
            gap_start += timedelta(minutes=1)

    def _compute_volume_delta(self, token: int, cumulative_volume: int) -> int:
        """Compute volume delta for the first bar of a session."""
        # No previous state → use cumulative directly (it is the session-start volume)
        return cumulative_volume

    def _compute_volume_delta_for_state(self, state: _BarState, cumulative_volume: int) -> int:
        """Compute volume delta, handling daily reset."""
        if cumulative_volume >= state.prev_cumulative_volume:
            return cumulative_volume - state.prev_cumulative_volume
        # Reset detected (cumulative volume rolled over or new day)
        return cumulative_volume

    # ------------------------------------------------------------------
    # Notification helpers
    # ------------------------------------------------------------------
    def _notify_bar(self, bar: CompletedBar) -> None:
        for cb in self._bar_callbacks:
            try:
                result = cb(bar)
                if hasattr(result, "__await__"):
                    import asyncio
                    try:
                        loop = asyncio.get_running_loop()
                        loop.call_soon(asyncio.create_task, result)
                    except RuntimeError:
                        pass
            except Exception:
                pass

    def _notify_gap(self, gap: DataGap) -> None:
        for cb in self._gap_callbacks:
            try:
                result = cb(gap)
                if hasattr(result, "__await__"):
                    import asyncio
                    try:
                        loop = asyncio.get_running_loop()
                        loop.call_soon(asyncio.create_task, result)
                    except RuntimeError:
                        pass
            except Exception:
                pass

    def _notify_out_of_session(self, tick: Tick) -> None:
        for cb in self._out_of_session_callbacks:
            try:
                result = cb(tick)
                if hasattr(result, "__await__"):
                    import asyncio
                    try:
                        loop = asyncio.get_running_loop()
                        loop.call_soon(asyncio.create_task, result)
                    except RuntimeError:
                        pass
            except Exception:
                pass

    def _notify_out_of_order(self, tick: Tick) -> None:
        for cb in self._out_of_order_callbacks:
            try:
                result = cb(tick)
                if hasattr(result, "__await__"):
                    import asyncio
                    try:
                        loop = asyncio.get_running_loop()
                        loop.call_soon(asyncio.create_task, result)
                    except RuntimeError:
                        pass
            except Exception:
                pass


class _BarState:
    """Mutable internal state for a single in-progress bar."""

    def __init__(
        self,
        instrument_token: int,
        minute: datetime,
        open_price: Decimal,
        high_price: Decimal,
        low_price: Decimal,
        close_price: Decimal,
        volume: int,
        oi: int | None,
        prev_cumulative_volume: int,
    ) -> None:
        self.instrument_token = instrument_token
        self.minute = minute
        self.open_price = open_price
        self.high_price = high_price
        self.low_price = low_price
        self.close_price = close_price
        self.volume = volume
        self.oi = oi
        self.prev_cumulative_volume = prev_cumulative_volume

    def to_bar(self) -> CompletedBar:
        return CompletedBar(
            instrument_token=self.instrument_token,
            timestamp=self.minute,
            open=self.open_price,
            high=self.high_price,
            low=self.low_price,
            close=self.close_price,
            volume=self.volume,
            oi=self.oi,
            is_backfilled=False,
            source="live",
        )
