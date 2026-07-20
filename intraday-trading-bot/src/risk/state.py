"""
Risk state management.

RiskState tracks mutable running state for risk checks: daily P&L, message counts,
throttle windows, peak equity, and kill switch status. It is async-safe with
per-account locking.

All monetary values use Decimal. State is deterministic and idempotent.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Dict, Optional, Any
from datetime import datetime, timedelta
import asyncio

from .contracts import RiskStateSnapshot, RiskAction


class RiskState:
    """Mutable running state for risk checks on a single account.

    Thread-safe via per-account asyncio.Lock. All monetary arithmetic uses Decimal.

    Attributes:
        account_id: The account this state belongs to.
        daily_realized_pnl: Cumulative realized P&L for the current trading day.
        daily_turnover: Cumulative turnover for the current trading day.
        peak_equity: Highest equity value seen today.
        message_counts: Dict of throttle_key -> (count, window_start).
        kill_switch_active: Whether the kill switch is currently engaged.
        kill_switch_reason: Reason for kill switch activation.
        _lock: Per-account asyncio.Lock for thread safety.
    """

    def __init__(self, account_id: str, initial_equity: Decimal = Decimal("0")):
        self.account_id: str = account_id
        self.daily_realized_pnl: Decimal = Decimal("0")
        self.daily_turnover: Decimal = Decimal("0")
        self.peak_equity: Decimal = initial_equity
        self.message_counts: Dict[str, tuple] = {}  # key -> (count, window_start)
        self.kill_switch_active: bool = False
        self.kill_switch_reason: Optional[str] = None
        self._lock: asyncio.Lock = asyncio.Lock()

    async def record_fill(
        self,
        realized_pnl: Decimal,
        turnover: Decimal,
        current_equity: Decimal,
        fill_timestamp: datetime,
    ) -> None:
        """Update state after a fill event."""
        async with self._lock:
            if not isinstance(realized_pnl, Decimal):
                realized_pnl = Decimal(str(realized_pnl))
            if not isinstance(turnover, Decimal):
                turnover = Decimal(str(turnover))
            if not isinstance(current_equity, Decimal):
                current_equity = Decimal(str(current_equity))

            self.daily_realized_pnl += realized_pnl
            self.daily_turnover += turnover

            if current_equity > self.peak_equity:
                self.peak_equity = current_equity

    async def record_message(
        self,
        throttle_key: str,
        window_seconds: int,
        now: datetime,
    ) -> int:
        """Record a message (order submission) for throttling.

        Returns:
            Current count for this throttle key in the active window.
        """
        async with self._lock:
            window = timedelta(seconds=window_seconds)

            if throttle_key in self.message_counts:
                count, window_start = self.message_counts[throttle_key]
                if now - window_start > window:
                    # Window expired, reset
                    self.message_counts[throttle_key] = (1, now)
                    return 1
                else:
                    # Increment within window
                    self.message_counts[throttle_key] = (count + 1, window_start)
                    return count + 1
            else:
                self.message_counts[throttle_key] = (1, now)
                return 1

    async def get_message_count(self, throttle_key: str, window_seconds: int, now: datetime) -> int:
        """Get current message count for a throttle key without incrementing."""
        async with self._lock:
            window = timedelta(seconds=window_seconds)

            if throttle_key not in self.message_counts:
                return 0

            count, window_start = self.message_counts[throttle_key]
            if now - window_start > window:
                return 0
            return count

    async def activate_kill_switch(self, reason: str) -> None:
        """Activate the kill switch, preventing all new orders."""
        async with self._lock:
            self.kill_switch_active = True
            self.kill_switch_reason = reason

    async def deactivate_kill_switch(self) -> None:
        """Deactivate the kill switch."""
        async with self._lock:
            self.kill_switch_active = False
            self.kill_switch_reason = None

    async def reset_daily(self, initial_equity: Decimal = Decimal("0")) -> None:
        """Reset daily counters (e.g., at start of new trading day).

        Note: the kill switch is NOT reset here — it is an independent safety
        mechanism that must be explicitly deactivated.
        """
        async with self._lock:
            self.daily_realized_pnl = Decimal("0")
            self.daily_turnover = Decimal("0")
            self.peak_equity = initial_equity
            self.message_counts.clear()

    def to_snapshot(self, snapshot_timestamp: datetime) -> RiskStateSnapshot:
        """Create an immutable snapshot of current state."""
        simple_counts = {k: v[0] for k, v in self.message_counts.items()}

        return RiskStateSnapshot(
            account_id=self.account_id,
            snapshot_timestamp=snapshot_timestamp,
            daily_realized_pnl=self.daily_realized_pnl,
            daily_turnover=self.daily_turnover,
            peak_equity=self.peak_equity,
            message_counts=simple_counts,
            kill_switch_active=self.kill_switch_active,
            kill_switch_reason=self.kill_switch_reason,
        )

    async def to_snapshot_locked(self, snapshot_timestamp: datetime) -> RiskStateSnapshot:
        """Create an immutable snapshot under lock."""
        async with self._lock:
            return self.to_snapshot(snapshot_timestamp)

    @classmethod
    def from_snapshot(cls, snapshot: RiskStateSnapshot) -> "RiskState":
        """Restore a RiskState from an immutable snapshot."""
        state = cls(snapshot.account_id, snapshot.peak_equity)
        state.daily_realized_pnl = snapshot.daily_realized_pnl
        state.daily_turnover = snapshot.daily_turnover
        state.peak_equity = snapshot.peak_equity
        state.kill_switch_active = snapshot.kill_switch_active
        state.kill_switch_reason = snapshot.kill_switch_reason

        # Restore message counts with snapshot timestamp as window start
        now = snapshot.snapshot_timestamp
        for key, count in snapshot.message_counts.items():
            state.message_counts[key] = (count, now)

        return state
