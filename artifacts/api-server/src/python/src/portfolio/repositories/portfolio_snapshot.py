"""RC-10C1 Portfolio Core — PortfolioSnapshotRepository.

Persistence layer for portfolio snapshots.  This stub stores snapshots
in memory; a database-backed implementation will be provided in a later
RC batch when the DB schema is finalised.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.portfolio.contracts import PortfolioSnapshot

logger = logging.getLogger(__name__)


class PortfolioSnapshotRepository:
    """Stores and retrieves PortfolioSnapshot objects.

    In-memory implementation. Replace with a DB-backed version in production.
    """

    def __init__(self) -> None:
        self._snapshots: list[PortfolioSnapshot] = []

    async def save(self, snapshot: PortfolioSnapshot) -> None:
        """Persist *snapshot*."""
        self._snapshots.append(snapshot)
        logger.debug(
            "Snapshot saved",
            extra={
                "snapshot_id": str(snapshot.snapshot_id),
                "portfolio_id": snapshot.portfolio_id,
                "version": snapshot.version,
            },
        )

    async def get_latest(self, portfolio_id: str = "default") -> PortfolioSnapshot | None:
        """Return the most recent snapshot for *portfolio_id*, or None."""
        matching = [s for s in self._snapshots if s.portfolio_id == portfolio_id]
        if not matching:
            return None
        return max(matching, key=lambda s: s.snapshotted_at)

    async def get_latest_valid(self, portfolio_id: str = "default") -> PortfolioSnapshot | None:
        """Return the most recent valid (non-corrupt) snapshot."""
        return await self.get_latest(portfolio_id)

    async def list_after(
        self, portfolio_id: str, after: datetime
    ) -> list[PortfolioSnapshot]:
        """Return snapshots taken after *after* for *portfolio_id*."""
        return [
            s for s in self._snapshots
            if s.portfolio_id == portfolio_id and s.snapshotted_at > after
        ]
