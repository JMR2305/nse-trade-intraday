"""Minute-bar repository.

Wraps the existing ``minute_bars`` SQLAlchemy model.
Service-level transaction control: do not commit inside every method.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.market_data.contracts import CompletedBar


class MinuteBarRepository:
    """CRUD and gap-finding for minute bars.

    All methods accept an optional ``session`` argument so that the
    caller (service or backfill coordinator) controls transaction
    boundaries.
    """

    def __init__(self, model_class: Any | None = None) -> None:
        # The model class is injected so we avoid import-time DB deps.
        # In production this will be the SQLAlchemy model from models.py.
        self._model = model_class

    # ------------------------------------------------------------------
    # Insert
    # ------------------------------------------------------------------
    async def insert_completed_bar(
        self,
        bar: CompletedBar,
        session: AsyncSession,
    ) -> None:
        """Insert a single completed bar."""
        if self._model is None:
            raise RuntimeError("model_class not injected")
        record = self._model(
            instrument_token=bar.instrument_token,
            timestamp=bar.timestamp,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            oi=bar.oi,
        )
        session.add(record)

    async def insert_many(
        self,
        bars: list[CompletedBar],
        session: AsyncSession,
    ) -> None:
        """Bulk insert completed bars."""
        if self._model is None:
            raise RuntimeError("model_class not injected")
        for bar in bars:
            record = self._model(
                instrument_token=bar.instrument_token,
                timestamp=bar.timestamp,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                oi=bar.oi,
            )
            session.add(record)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------
    async def get_range(
        self,
        instrument_token: int,
        start: datetime,
        end: datetime,
        session: AsyncSession,
    ) -> list[CompletedBar]:
        """Return bars in [start, end) ordered by timestamp ascending."""
        if self._model is None:
            raise RuntimeError("model_class not injected")
        stmt = (
            select(self._model)
            .where(
                and_(
                    self._model.instrument_token == instrument_token,
                    self._model.timestamp >= start,
                    self._model.timestamp < end,
                )
            )
            .order_by(self._model.timestamp.asc())
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_contract(row) for row in rows]

    async def get_latest(
        self,
        instrument_token: int,
        session: AsyncSession,
        before: datetime | None = None,
    ) -> CompletedBar | None:
        """Return the most recent bar for a token.

        Args:
            before: if given, only consider bars with timestamp < before.
        """
        if self._model is None:
            raise RuntimeError("model_class not injected")
        filters = [self._model.instrument_token == instrument_token]
        if before is not None:
            filters.append(self._model.timestamp < before)
        stmt = (
            select(self._model)
            .where(and_(*filters))
            .order_by(self._model.timestamp.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return self._to_contract(row)

    async def find_gaps(
        self,
        instrument_token: int,
        start: datetime,
        end: datetime,
        session: AsyncSession,
    ) -> list[tuple[datetime, datetime]]:
        """Find missing 1-minute intervals between start and end.

        Returns:
            List of (gap_start, gap_end) tuples where gap_end = gap_start + 1min.
        """
        if self._model is None:
            raise RuntimeError("model_class not injected")
        # Fetch all timestamps in range
        stmt = (
            select(self._model.timestamp)
            .where(
                and_(
                    self._model.instrument_token == instrument_token,
                    self._model.timestamp >= start,
                    self._model.timestamp < end,
                )
            )
            .order_by(self._model.timestamp.asc())
        )
        result = await session.execute(stmt)
        timestamps = [row[0] for row in result.all()]

        gaps: list[tuple[datetime, datetime]] = []
        if not timestamps:
            # Entire range is a gap
            current = start
            while current < end:
                gaps.append((current, current + timedelta(minutes=1)))
                current += timedelta(minutes=1)
            return gaps

        # Check gap before first timestamp
        current = start
        while current < timestamps[0]:
            gaps.append((current, current + timedelta(minutes=1)))
            current += timedelta(minutes=1)

        # Check gaps between consecutive timestamps
        for i in range(1, len(timestamps)):
            expected = timestamps[i - 1] + timedelta(minutes=1)
            while expected < timestamps[i]:
                gaps.append((expected, expected + timedelta(minutes=1)))
                expected += timedelta(minutes=1)

        # Check gap after last timestamp
        current = timestamps[-1] + timedelta(minutes=1)
        while current < end:
            gaps.append((current, current + timedelta(minutes=1)))
            current += timedelta(minutes=1)

        return gaps

    # ------------------------------------------------------------------
    # Upsert / backfill
    # ------------------------------------------------------------------
    async def upsert_backfilled_bar(
        self,
        bar: CompletedBar,
        policy: str,
        session: AsyncSession,
    ) -> None:
        """Insert or update a backfilled bar based on conflict policy.

        Args:
            policy: one of "INSERT_ONLY", "OVERWRITE", "SKIP".
            session: caller-controlled AsyncSession.
        """
        if self._model is None:
            raise RuntimeError("model_class not injected")

        existing = await self.get_latest(
            bar.instrument_token,
            session=session,
            before=bar.timestamp + timedelta(minutes=1),
        )
        if existing and existing.timestamp == bar.timestamp:
            if policy == "SKIP":
                return
            if policy == "OVERWRITE":
                # Update existing record
                stmt = (
                    select(self._model)
                    .where(
                        and_(
                            self._model.instrument_token == bar.instrument_token,
                            self._model.timestamp == bar.timestamp,
                        )
                    )
                )
                result = await session.execute(stmt)
                row = result.scalar_one()
                row.open = bar.open
                row.high = bar.high
                row.low = bar.low
                row.close = bar.close
                row.volume = bar.volume
                row.oi = bar.oi
                return
            # INSERT_ONLY falls through to insert below only if no conflict
            if policy == "INSERT_ONLY":
                return

        # Insert new
        record = self._model(
            instrument_token=bar.instrument_token,
            timestamp=bar.timestamp,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            oi=bar.oi,
        )
        session.add(record)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _to_contract(self, row: Any) -> CompletedBar:
        """Map a SQLAlchemy row to a CompletedBar contract."""
        return CompletedBar(
            instrument_token=row.instrument_token,
            timestamp=row.timestamp,
            open=Decimal(str(row.open)),
            high=Decimal(str(row.high)),
            low=Decimal(str(row.low)),
            close=Decimal(str(row.close)),
            volume=int(row.volume),
            oi=int(row.oi) if row.oi is not None else None,
            is_backfilled=False,  # not persisted in this schema version
            source="live",        # not persisted in this schema version
        )
