"""RC-10C1 Portfolio Core — PortfolioSnapshotRepository.

Persistence layer for portfolio snapshots.  This stub stores snapshots
in memory; a database-backed implementation will be provided in a later
RC batch when the DB schema is finalised.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from src.portfolio.contracts import PortfolioSnapshot
from src.portfolio.exceptions import CorruptSnapshotError

logger = logging.getLogger(__name__)


def compute_snapshot_checksum(snapshot: PortfolioSnapshot) -> str:
    """Return the canonical SHA-256 checksum for *snapshot*.

    The checksum covers every field *except* ``checksum`` itself so that
    it can be stored alongside the payload without creating a circular
    dependency.  The JSON serialisation uses sorted keys for determinism.
    """
    data = snapshot.model_dump(exclude={"checksum"})

    def _default(obj: Any) -> Any:
        from decimal import Decimal
        from uuid import UUID
        if isinstance(obj, Decimal):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, UUID):
            return str(obj)
        raise TypeError(f"Object of type {type(obj)} is not JSON serialisable")

    serialised = json.dumps(data, sort_keys=True, default=_default)
    return hashlib.sha256(serialised.encode()).hexdigest()


def validate_snapshot(snapshot: PortfolioSnapshot) -> None:
    """Raise :class:`CorruptSnapshotError` if *snapshot* fails integrity checks.

    Rules
    -----
    * If ``snapshot.checksum`` is **present**, it must match the recomputed
      checksum.  A mismatch means the stored bytes were modified after the
      checksum was written.
    * A ``None`` checksum is accepted (snapshots created before checksumming
      was introduced are treated as valid — this is a forward-compatible
      policy that can be tightened later).
    """
    if snapshot.checksum is None:
        return  # legacy snapshot — no checksum to validate
    expected = compute_snapshot_checksum(snapshot)
    if snapshot.checksum != expected:
        raise CorruptSnapshotError(
            f"Snapshot {snapshot.snapshot_id} for portfolio "
            f"'{snapshot.portfolio_id}' failed checksum validation "
            f"(stored={snapshot.checksum!r}, computed={expected!r})"
        )


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
        """Return the most recent *valid* snapshot for *portfolio_id*.

        "Valid" means the snapshot passes :func:`validate_snapshot`.  Candidates
        are tested newest-first; the first one that passes is returned.

        Raises
        ------
        CorruptSnapshotError
            If **all** candidates for *portfolio_id* exist but none pass
            checksum validation.  This signals that the snapshot store is
            in a corrupt state and a fill-history rebuild is required.
        """
        candidates = sorted(
            [s for s in self._snapshots if s.portfolio_id == portfolio_id],
            key=lambda s: s.snapshotted_at,
            reverse=True,
        )
        if not candidates:
            return None

        last_err: CorruptSnapshotError | None = None
        for candidate in candidates:
            try:
                validate_snapshot(candidate)
                return candidate
            except CorruptSnapshotError as exc:
                logger.warning(
                    "Snapshot failed checksum — trying older candidate",
                    extra={
                        "snapshot_id": str(candidate.snapshot_id),
                        "portfolio_id": portfolio_id,
                        "error": str(exc),
                    },
                )
                last_err = exc

        # Every candidate failed — propagate the most recent error.
        assert last_err is not None
        raise last_err

    async def list_after(
        self, portfolio_id: str, after: datetime
    ) -> list[PortfolioSnapshot]:
        """Return snapshots taken after *after* for *portfolio_id*."""
        return [
            s for s in self._snapshots
            if s.portfolio_id == portfolio_id and s.snapshotted_at > after
        ]
