"""FaultIsolator — per-strategy error-budget enforcement.

When a strategy's error rate breaches a configured budget, the isolator
returns a FaultAction that tells the coordinator to pause or stop the
strategy automatically.  This prevents a misbehaving strategy from
flooding the execution layer with bad signals or consuming all resources.

Design principles
-----------------
- FaultIsolator is purely in-process state (no DB).
- Each strategy has its own FaultBudget; a default budget covers any
  strategy without a custom one.
- record_error() is async (lock-protected) and returns FaultAction.
- record_success() resets the consecutive-error streak (not the rate-
  window counters — those decay naturally).
- reset_isolation() is an explicit operator action (manual review).
- All public read methods are synchronous and lock-free (snapshot copy).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class FaultAction(str, Enum):
    """Action the coordinator should take after record_error() returns."""

    NONE = "NONE"       # within budget — continue normally
    PAUSE = "PAUSE"     # budget breached; auto-pause signal generation
    STOP = "STOP"       # budget breached; full stop (config opt-in)


@dataclass(frozen=True)
class FaultBudget:
    """Error budget configuration for one strategy."""

    # How many errors in a row before isolation triggers
    max_consecutive_errors: int = 5
    # How many errors in a 60-second window before isolation triggers
    max_errors_per_minute: int = 10
    # If True, FaultAction.PAUSE is returned on breach; else FaultAction.STOP
    auto_pause_on_breach: bool = True


@dataclass(frozen=True)
class FaultIsolationStatus:
    """Point-in-time isolation status for one strategy."""

    strategy_id: str
    is_isolated: bool
    consecutive_errors: int
    errors_last_minute: int
    isolation_reason: str = ""


class FaultIsolator:
    """Enforces per-strategy error budgets and drives isolation actions.

    Parameters
    ----------
    default_budget:
        Budget applied to strategies without a custom one.  If None,
        the library defaults (5 consecutive / 10 per-minute) are used.
    """

    def __init__(self, default_budget: Optional[FaultBudget] = None) -> None:
        self._default_budget: FaultBudget = default_budget or FaultBudget()
        self._budgets: Dict[str, FaultBudget] = {}
        self._consecutive: Dict[str, int] = {}
        self._error_times: Dict[str, List[datetime]] = {}
        self._isolated: Dict[str, str] = {}   # strategy_id → isolation reason
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def configure_budget(self, strategy_id: str, budget: FaultBudget) -> None:
        """Set a custom error budget for *strategy_id*."""
        self._budgets[strategy_id] = budget

    def remove(self, strategy_id: str) -> None:
        """Drop all state for a deregistered strategy."""
        self._budgets.pop(strategy_id, None)
        self._consecutive.pop(strategy_id, None)
        self._error_times.pop(strategy_id, None)
        self._isolated.pop(strategy_id, None)

    # ------------------------------------------------------------------
    # Write methods (async, lock-protected)
    # ------------------------------------------------------------------

    async def record_error(self, strategy_id: str) -> FaultAction:
        """Record an error and return the recommended FaultAction.

        If the strategy is already isolated, PAUSE is returned immediately
        without re-evaluating the budget (isolation is sticky until
        reset_isolation() is called by an operator).
        """
        async with self._lock:
            # Already isolated — return PAUSE immediately
            if strategy_id in self._isolated:
                return FaultAction.PAUSE

            budget = self._budgets.get(strategy_id, self._default_budget)

            # Update consecutive counter
            count = self._consecutive.get(strategy_id, 0) + 1
            self._consecutive[strategy_id] = count

            # Update time-windowed counter (rolling 60 s window)
            now = datetime.now(timezone.utc)
            window_start = now - timedelta(minutes=1)
            times = [t for t in self._error_times.get(strategy_id, []) if t > window_start]
            times.append(now)
            self._error_times[strategy_id] = times

            # Evaluate thresholds
            if count >= budget.max_consecutive_errors:
                reason = (
                    f"{count} consecutive errors "
                    f"(limit={budget.max_consecutive_errors})"
                )
                self._isolated[strategy_id] = reason
                logger.warning(
                    "FaultIsolator: strategy %s isolated — %s", strategy_id, reason
                )
                return (
                    FaultAction.PAUSE if budget.auto_pause_on_breach else FaultAction.STOP
                )

            if len(times) >= budget.max_errors_per_minute:
                reason = (
                    f"{len(times)} errors in last 60 s "
                    f"(limit={budget.max_errors_per_minute})"
                )
                self._isolated[strategy_id] = reason
                logger.warning(
                    "FaultIsolator: strategy %s isolated — %s", strategy_id, reason
                )
                return (
                    FaultAction.PAUSE if budget.auto_pause_on_breach else FaultAction.STOP
                )

            return FaultAction.NONE

    async def record_success(self, strategy_id: str) -> None:
        """Reset the consecutive-error streak after a clean execution."""
        async with self._lock:
            if self._consecutive.get(strategy_id, 0) > 0:
                self._consecutive[strategy_id] = 0

    async def reset_isolation(self, strategy_id: str) -> None:
        """Operator-initiated isolation reset (manual review complete)."""
        async with self._lock:
            self._isolated.pop(strategy_id, None)
            self._consecutive[strategy_id] = 0
            logger.info(
                "FaultIsolator: isolation cleared for strategy %s", strategy_id
            )

    # ------------------------------------------------------------------
    # Read methods (synchronous, lock-free)
    # ------------------------------------------------------------------

    def is_isolated(self, strategy_id: str) -> bool:
        """True iff the strategy is currently isolated."""
        return strategy_id in self._isolated

    def get_isolation_reason(self, strategy_id: str) -> Optional[str]:
        """Return the reason string set when isolation was triggered, or None."""
        return self._isolated.get(strategy_id)

    def get_status(self, strategy_id: str) -> FaultIsolationStatus:
        """Return a frozen status snapshot (lock-free)."""
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(minutes=1)
        recent = [
            t for t in self._error_times.get(strategy_id, []) if t > window_start
        ]
        return FaultIsolationStatus(
            strategy_id=strategy_id,
            is_isolated=strategy_id in self._isolated,
            consecutive_errors=self._consecutive.get(strategy_id, 0),
            errors_last_minute=len(recent),
            isolation_reason=self._isolated.get(strategy_id, ""),
        )
