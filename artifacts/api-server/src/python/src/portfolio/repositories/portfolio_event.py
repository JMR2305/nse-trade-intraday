"""RC-10C1 Portfolio Core — PortfolioEventRepository.

Persistence layer for portfolio events.  In-memory implementation;
a database-backed version will be provided in a later RC batch.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from src.portfolio.contracts import PortfolioEvent, PortfolioEventType

logger = logging.getLogger(__name__)


class PortfolioEventRepository:
    """Stores and retrieves PortfolioEvent records.

    In-memory implementation. Replace with a DB-backed version in production.
    """

    def __init__(self) -> None:
        self._events: list[PortfolioEvent] = []

    async def append(self, event: PortfolioEvent) -> None:
        """Persist *event*."""
        self._events.append(event)
        logger.debug(
            "Portfolio event persisted",
            extra={
                "event_id": str(event.event_id),
                "event_type": event.event_type.value,
                "idempotency_key": event.idempotency_key,
            },
        )

    async def append_many(self, events: list[PortfolioEvent]) -> None:
        """Persist multiple events."""
        for event in events:
            await self.append(event)

    async def get_events_after_sequence(
        self, portfolio_id: str, sequence: int
    ) -> list[PortfolioEvent]:
        """Return events with sequence > *sequence* for *portfolio_id*."""
        return [
            e for e in self._events
            if e.portfolio_id == portfolio_id and (e.sequence or 0) > sequence
        ]

    async def get_events_after(
        self, portfolio_id: str, after: datetime
    ) -> list[PortfolioEvent]:
        """Return events occurred after *after* for *portfolio_id*."""
        return [
            e for e in self._events
            if e.portfolio_id == portfolio_id and e.occurred_at > after
        ]

    async def list_all(self, portfolio_id: str = "default") -> list[PortfolioEvent]:
        """Return all events for *portfolio_id*."""
        return [e for e in self._events if e.portfolio_id == portfolio_id]
