"""
Risk Engine — core evaluation engine.

Orchestrates risk rule evaluation across all configured limits.
Manages per-account RiskState in-memory with asyncio locking.
Records throttle counts and fill events after approved checks.

IMPORTANT: The engine is stateful (holds per-account RiskState).
Callers that need recovery should use RiskEnginePersistenceAdapter
from persistence.py.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Set

from .contracts import (
    RiskCheckType,
    RiskConfiguration,
    RiskContext,
    RiskRequest,
    RiskResult,
    RiskSeverity,
    RiskStateSnapshot,
    RiskViolation,
    MaxOrdersPerMinuteLimit,
    KillSwitchLimit,
    EmergencyHaltLimit,
    CircuitBreakerLimit,
)
from .exceptions import (
    KillSwitchActive,
    EmergencyHaltActive,
    RiskStateError,
)
from .rules import get_rule, RULE_REGISTRY
from .state import RiskState

logger = logging.getLogger(__name__)


class RiskEngine:
    """Core risk evaluation engine.

    Manages per-account RiskState in-memory. Evaluates all configured
    risk limits for each incoming order. Records throttle counts after
    evaluation and fill events after execution.

    Thread-safe: per-account asyncio.Lock prevents concurrent evaluation
    for the same account.
    """

    def __init__(self) -> None:
        self._states: Dict[str, RiskState] = {}
        self._account_locks: Dict[str, asyncio.Lock] = {}
        self._processed_fills: Dict[str, Set[str]] = {}  # account_id -> set of fill_ids
        self._global_lock = asyncio.Lock()

    async def _get_state(self, account_id: str) -> RiskState:
        """Get or create a RiskState for the account (thread-safe)."""
        async with self._global_lock:
            if account_id not in self._states:
                self._states[account_id] = RiskState(account_id)
                self._account_locks[account_id] = asyncio.Lock()
                self._processed_fills[account_id] = set()
        return self._states[account_id]

    async def _get_lock(self, account_id: str) -> asyncio.Lock:
        """Get the per-account lock."""
        await self._get_state(account_id)
        return self._account_locks[account_id]

    def _get_throttle_key(self, account_id: str, config: MaxOrdersPerMinuteLimit) -> str:
        """Build the throttle state key for message count tracking."""
        key = f"orders_per_minute:{account_id}"
        if config.scope == "instrument" and config.instrument_token:
            key += f":{config.instrument_token}"
        return key

    async def evaluate(
        self,
        request: RiskRequest,
        context: RiskContext,
        limits: List[RiskConfiguration],
    ) -> RiskResult:
        """Evaluate all configured risk limits for an order.

        Safety rules (KILL_SWITCH, EMERGENCY_HALT, CIRCUIT_BREAKER) are
        evaluated first and short-circuit on the first FATAL violation.

        For non-safety rules, all configured limits are evaluated and all
        violations are collected before returning.

        Throttle counts are recorded AFTER evaluation (so the current
        order counts toward the limit for the NEXT order).

        Args:
            request: The risk check request.
            context: Market and portfolio context.
            limits: List of configured risk limits to evaluate.

        Returns:
            RiskResult with approved=True or approved=False + violations.
        """
        account_id = request.account_id
        state = await self._get_state(account_id)
        check_timestamp = request.check_timestamp

        violations: List[RiskViolation] = []

        # Evaluate all limits in the configured order
        for config in limits:
            if not config.enabled:
                continue

            check_type = config.check_type

            # Re-snapshot state for each rule (captures any in-flight mutations)
            state_snapshot = state.to_snapshot(check_timestamp)

            try:
                rule = get_rule(check_type)
            except KeyError:
                logger.warning(f"No rule registered for check_type={check_type!r}; skipping")
                continue

            violation = rule.evaluate(request, context, config, state_snapshot)

            if violation is not None:
                violations.append(violation)

                # Safety rules short-circuit immediately on FATAL
                if check_type in (
                    RiskCheckType.KILL_SWITCH,
                    RiskCheckType.EMERGENCY_HALT,
                    RiskCheckType.CIRCUIT_BREAKER,
                ) and violation.severity == RiskSeverity.FATAL:
                    return RiskResult(
                        approved=False,
                        violations=violations,
                        check_timestamp=check_timestamp,
                        account_id=account_id,
                    )

        # Determine approval: any FATAL or CRITICAL violation blocks the order
        is_approved = not any(
            v.severity in (RiskSeverity.FATAL, RiskSeverity.CRITICAL)
            for v in violations
        )

        if is_approved:
            # Record throttle counts post-evaluation
            await self._record_message_throttle(state, account_id, limits, check_timestamp)

        return RiskResult(
            approved=is_approved,
            violations=violations,
            check_timestamp=check_timestamp,
            account_id=account_id,
        )

    async def _record_message_throttle(
        self,
        state: RiskState,
        account_id: str,
        limits: List[RiskConfiguration],
        now: datetime,
    ) -> None:
        """Record throttle counts for MaxOrdersPerMinuteLimit rules."""
        for config in limits:
            if not config.enabled:
                continue
            if config.check_type != RiskCheckType.MAX_ORDERS_PER_MINUTE:
                continue
            if not isinstance(config, MaxOrdersPerMinuteLimit):
                continue

            throttle_key = self._get_throttle_key(account_id, config)
            await state.record_message(throttle_key, config.window_seconds, now)

    async def record_fill(
        self,
        account_id: str,
        fill_id: str,
        realized_pnl: Decimal,
        turnover: Decimal,
        current_equity: Decimal,
        fill_timestamp: Optional[datetime] = None,
    ) -> bool:
        """Record a fill event into the account's RiskState.

        Idempotent: duplicate fill_ids are silently ignored.

        Args:
            account_id: The account.
            fill_id: Unique fill identifier for idempotency.
            realized_pnl: Realized P&L from the fill.
            turnover: Turnover value of the fill.
            current_equity: Portfolio equity after the fill.
            fill_timestamp: Timestamp of the fill (defaults to now).

        Returns:
            True if the fill was recorded, False if it was a duplicate.
        """
        state = await self._get_state(account_id)

        async with self._global_lock:
            if fill_id in self._processed_fills[account_id]:
                logger.debug(
                    f"Duplicate fill {fill_id!r} for account {account_id!r}; ignoring"
                )
                return False
            self._processed_fills[account_id].add(fill_id)

        ts = fill_timestamp or datetime.now(timezone.utc)
        await state.record_fill(
            realized_pnl=realized_pnl,
            turnover=turnover,
            current_equity=current_equity,
            fill_timestamp=ts,
        )
        logger.info(
            f"Fill recorded for account {account_id!r}: fill_id={fill_id!r}, "
            f"pnl={realized_pnl}, turnover={turnover}"
        )
        return True

    async def activate_kill_switch(self, account_id: str, reason: str) -> None:
        """Activate the kill switch for an account."""
        state = await self._get_state(account_id)
        await state.activate_kill_switch(reason)

    async def deactivate_kill_switch(self, account_id: str) -> None:
        """Deactivate the kill switch for an account."""
        state = await self._get_state(account_id)
        await state.deactivate_kill_switch()

    async def activate_emergency_halt(self, account_id: str, reason: str) -> None:
        """Activate emergency halt for an account."""
        state = await self._get_state(account_id)
        await state.activate_emergency_halt(reason)

    async def deactivate_emergency_halt(self, account_id: str) -> None:
        """Deactivate emergency halt for an account."""
        state = await self._get_state(account_id)
        await state.deactivate_emergency_halt()

    async def trigger_circuit_breaker(self, account_id: str) -> None:
        """Trigger the circuit breaker for an account."""
        state = await self._get_state(account_id)
        await state.trigger_circuit_breaker()

    async def reset_circuit_breaker(self, account_id: str) -> None:
        """Reset the circuit breaker for an account."""
        state = await self._get_state(account_id)
        await state.reset_circuit_breaker()

    async def get_state_snapshot(
        self, account_id: str, timestamp: Optional[datetime] = None
    ) -> RiskStateSnapshot:
        """Get a snapshot of the current state for an account."""
        state = await self._get_state(account_id)
        ts = timestamp or datetime.now(timezone.utc)
        return await state.to_snapshot_locked(ts)

    async def restore_state(self, snapshot: RiskStateSnapshot) -> None:
        """Restore engine state from a persisted snapshot."""
        async with self._global_lock:
            account_id = snapshot.account_id
            self._states[account_id] = RiskState.from_snapshot(snapshot)
            if account_id not in self._account_locks:
                self._account_locks[account_id] = asyncio.Lock()
            if account_id not in self._processed_fills:
                self._processed_fills[account_id] = set()
        logger.info(f"RiskEngine state restored for account {snapshot.account_id!r}")

    async def reset_daily(self, account_id: str, initial_equity: Decimal = Decimal("0")) -> None:
        """Reset daily counters for an account (call at market open)."""
        state = await self._get_state(account_id)
        await state.reset_daily(initial_equity)
