"""RC-10C1 Portfolio Core — CapitalAllocationRepository.

Persistence layer for AllocationDecision records.  In-memory implementation;
a database-backed version will be provided in a later RC batch.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.portfolio.contracts import AllocationDecision, AllocationStatus

logger = logging.getLogger(__name__)


class CapitalAllocationRepository:
    """Stores and retrieves AllocationDecision records.

    Tracks capital allocation decisions for strategies to enable
    post-session analysis and audit.

    In-memory implementation. Replace with a DB-backed version in production.
    """

    def __init__(self) -> None:
        self._decisions: list[AllocationDecision] = []

    async def save(self, decision: AllocationDecision) -> None:
        """Persist *decision*.

        Parameters
        ----------
        decision:
            The AllocationDecision to persist.
        """
        self._decisions.append(decision)
        logger.debug(
            "AllocationDecision saved",
            extra={
                "decision_id": str(decision.decision_id),
                "strategy_id": decision.strategy_id,
                "status": decision.status.value,
                "approved_capital": str(decision.approved_capital),
            },
        )

    async def get_active_for_strategy(
        self, strategy_id: str
    ) -> list[AllocationDecision]:
        """Return all non-expired, non-committed allocation decisions for *strategy_id*.

        Parameters
        ----------
        strategy_id:
            The strategy identifier to query.

        Returns
        -------
        list[AllocationDecision]
            Active (APPROVED, not expired) decisions for the strategy.
        """
        now = datetime.now(timezone.utc)
        active: list[AllocationDecision] = []

        for decision in self._decisions:
            if decision.strategy_id != strategy_id:
                continue
            if decision.status not in (AllocationStatus.APPROVED,):
                continue
            if decision.is_expired(now):
                continue
            active.append(decision)

        logger.debug(
            "Active allocations retrieved",
            extra={"strategy_id": strategy_id, "count": len(active)},
        )
        return active

    async def get_by_decision_id(
        self, decision_id: str
    ) -> AllocationDecision | None:
        """Return the decision with matching *decision_id*, or None."""
        for decision in self._decisions:
            if str(decision.decision_id) == decision_id:
                return decision
        return None

    async def list_for_strategy(
        self, strategy_id: str, limit: int = 100
    ) -> list[AllocationDecision]:
        """Return the most recent *limit* decisions for *strategy_id*."""
        matching = [d for d in self._decisions if d.strategy_id == strategy_id]
        return matching[-limit:]
