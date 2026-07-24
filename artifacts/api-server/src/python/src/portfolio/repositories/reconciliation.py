"""RC-10C1 Portfolio Core — ReconciliationRepository.

Persistence layer for reconciliation reports.  In-memory implementation;
a database-backed version will be provided in a later RC batch.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from src.portfolio.contracts import PortfolioReconciliationReport

logger = logging.getLogger(__name__)


class ReconciliationRepository:
    """Stores and retrieves PortfolioReconciliationReport objects.

    In-memory implementation. Replace with a DB-backed version in production.
    """

    def __init__(self) -> None:
        self._reports: list[PortfolioReconciliationReport] = []

    async def save(self, report: PortfolioReconciliationReport) -> None:
        """Persist *report*."""
        self._reports.append(report)
        logger.debug(
            "Reconciliation report saved",
            extra={
                "run_id": str(report.run_id),
                "portfolio_id": report.portfolio_id,
                "critical_count": report.critical_count,
                "portfolio_ready": report.portfolio_ready,
            },
        )

    async def get_latest(
        self, portfolio_id: str = "default"
    ) -> PortfolioReconciliationReport | None:
        """Return the most recent reconciliation report for *portfolio_id*."""
        matching = [r for r in self._reports if r.portfolio_id == portfolio_id]
        if not matching:
            return None
        return max(
            matching,
            key=lambda r: r.completed_at or r.started_at,
        )

    async def list_after(
        self, portfolio_id: str, after: datetime
    ) -> list[PortfolioReconciliationReport]:
        """Return reports started after *after* for *portfolio_id*."""
        return [
            r for r in self._reports
            if r.portfolio_id == portfolio_id and r.started_at > after
        ]

    async def count_unresolved(self, portfolio_id: str = "default") -> int:
        """Return the total unresolved critical discrepancy count from the latest report."""
        latest = await self.get_latest(portfolio_id)
        if latest is None:
            return 0
        return latest.critical_count
