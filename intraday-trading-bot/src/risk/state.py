"""
Risk state management.

RiskState tracks mutable running state for risk checks: daily P&L, trade counts,
order counts, throttle windows, peak equity, and safety mechanisms (kill switch,
emergency halt, circuit breaker). It is async-safe with per-account locking.

All monetary values use Decimal. State is deterministic and idempotent.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Dict, Optional
from datetime import datetime, timedelta, timezone
import asyncio
import logging

from .contracts import RiskStateSnapshot

logger = logging.getLogger(__name__)


class RiskState:
    """Mutable running state for risk checks on a single account.

    Thread-safe via per-account asyncio.Lock. All monetary arithmetic uses Decimal.

    Attributes:
        account_id: The account this state belongs to.
        daily_realized_pnl: Cumulative realized P&L for the current trading day.
        daily_turnover: Cumulative turnover for the current trading day.
        trade_count: Number of completed trades today.
        order_count: Number of orders submitted today.
        peak_equity: Highest equity value seen today.
        message_counts: Dict of throttle_key -> (count, window_start).
        kill_switch_active: Whether the kill switch is currently engaged.
        kill_switch_reason: Reason for kill switch activation.
        emergency_halt_active: Whether emergency halt is active.
        circuit_breaker_triggered: Whether circuit breaker has fired.
        _lock: Per-account asyncio.Lock for thread safety.
    """

    def __init__(self, account_id: str, initial_equity: Decimal = Decimal("0")):
        self.account_id: str = account_id
        self.daily_realized_pnl: Decimal = Decimal("0")
        self.daily_turnover: Decimal = Decimal("0")
        self.trade_count: int = 0
        self.order_count: int = 0
        self.peak_equity: Decimal = initial_equity
        self.message_counts: Dict[str, tuple] = {}  # key -> (count, window_start)
        self.kill_switch_active: bool = False
        self.kill_switch_reason: Optional[str] = None
        self.emergency_halt_active: bool = False
        self.circuit_breaker_triggered: bool = False
        self._lock: asyncio.Lock = asyncio.Lock()

    async def record_fill(
        self,
        realized_pnl: Decimal,
        turnover: Decimal,
        current_equity: Decimal,
        fill_timestamp: datetime,
    ) -> None:
        """Update state after a fill event (trade completed).

        Args:
            realized_pnl: Realized P&L from this fill (can be negative).
            turnover: Turnover value of this fill.
            current_equity: Current portfolio equity after the fill.
            fill_timestamp: Timestamp of the fill.
        """
        async with self._lock:
            if not isinstance(realized_pnl, Decimal):
                realized_pnl = Decimal(str(realized_pnl))
            if not isinstance(turnover, Decimal):
                turnover = Decimal(str(turnover))
            if not isinstance(current_equity, Decimal):
                current_equity = Decimal(str(current_equity))

            self.daily_realized_pnl += realized_pnl
            self.daily_turnover += turnover
            self.trade_count += 1

            if current_equity > self.peak_equity:
                self.peak_equity = current_equity

    async def record_order(self, now: datetime) -> None:
        """Record an order submission (for daily order count tracking).

        Args:
            now: Timestamp of the order submission.
        """
        async with self._lock:
            self.order_count += 1

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
            logger.critical(f"Kill switch state activated for {self.account_id}: {reason}")

    async def deactivate_kill_switch(self) -> None:
        """Deactivate the kill switch."""
        async with self._lock:
            self.kill_switch_active = False
            self.kill_switch_reason = None
            logger.info(f"Kill switch state deactivated for {self.account_id}")

    async def activate_emergency_halt(self, reason: str) -> None:
        """Activate emergency halt, suspending all trading activity."""
        async with self._lock:
            self.emergency_halt_active = True
            logger.critical(f"Emergency halt activated for {self.account_id}: {reason}")

    async def deactivate_emergency_halt(self) -> None:
        """Deactivate emergency halt."""
        async with self._lock:
            self.emergency_halt_active = False
            logger.info(f"Emergency halt deactivated for {self.account_id}")

    async def trigger_circuit_breaker(self) -> None:
        """Trigger the circuit breaker due to rapid portfolio decline."""
        async with self._lock:
            self.circuit_breaker_triggered = True
            logger.critical(f"Circuit breaker triggered for {self.account_id}")

    async def reset_circuit_breaker(self) -> None:
        """Reset the circuit breaker (typically at start of new trading day)."""
        async with self._lock:
            self.circuit_breaker_triggered = False
            logger.info(f"Circuit breaker reset for {self.account_id}")

    async def reset_daily(self, initial_equity: Decimal = Decimal("0")) -> None:
        """Reset daily counters (e.g., at start of new trading day).

        Note: Kill switch, emergency halt, and circuit breaker are NOT reset
        by this method — they are safety mechanisms that must be explicitly
        managed.
        """
        async with self._lock:
            self.daily_realized_pnl = Decimal("0")
            self.daily_turnover = Decimal("0")
            self.trade_count = 0
            self.order_count = 0
            self.peak_equity = initial_equity
            self.message_counts.clear()
            logger.info(f"Daily counters reset for {self.account_id}")

    def to_snapshot(self, snapshot_timestamp: datetime) -> RiskStateSnapshot:
        """Create an immutable snapshot of current state.

        Note: This is a synchronous read. Callers should hold the lock
        or accept a slightly stale read. For critical paths, use the lock.
        """
        # Convert message_counts to simple counts for the snapshot
        simple_counts = {k: v[0] for k, v in self.message_counts.items()}

        return RiskStateSnapshot(
            account_id=self.account_id,
            snapshot_timestamp=snapshot_timestamp,
            daily_realized_pnl=self.daily_realized_pnl,
            daily_turnover=self.daily_turnover,
            trade_count=self.trade_count,
            order_count=self.order_count,
            peak_equity=self.peak_equity,
            message_counts=simple_counts,
            kill_switch_active=self.kill_switch_active,
            kill_switch_reason=self.kill_switch_reason,
            emergency_halt_active=self.emergency_halt_active,
            circuit_breaker_triggered=self.circuit_breaker_triggered,
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
        state.trade_count = snapshot.trade_count
        state.order_count = snapshot.order_count
        state.peak_equity = snapshot.peak_equity
        state.kill_switch_active = snapshot.kill_switch_active
        state.kill_switch_reason = snapshot.kill_switch_reason
        state.emergency_halt_active = snapshot.emergency_halt_active
        state.circuit_breaker_triggered = snapshot.circuit_breaker_triggered

        # Restore message counts with current timestamp as window start
        now = snapshot.snapshot_timestamp
        for key, count in snapshot.message_counts.items():
            state.message_counts[key] = (count, now)

        logger.info(f"RiskState restored from snapshot for {snapshot.account_id}")
        return state
