"""AnnouncementRepository — persistence for corporate announcement records.

All methods are async and work within an externally-supplied AsyncSession.
No commit/rollback/close is called — callers manage the session lifecycle
via SessionContext.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Announcement
from market_intelligence.multi_timeframe_context import AnnouncementRecord

logger = logging.getLogger(__name__)


class AnnouncementRepository:
    """Repository for Announcement ORM model persistence."""

    async def upsert(
        self, session: AsyncSession, record: AnnouncementRecord
    ) -> Announcement:
        """Idempotent upsert by (exchange, announcement_id).

        Returns the existing row if already present, otherwise creates a new one.
        Does NOT flush or commit.
        """
        stmt = select(Announcement).where(
            Announcement.exchange == record.exchange,
            Announcement.announcement_id == record.announcement_id,
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is not None:
            return existing

        orm = Announcement(
            announcement_id=record.announcement_id,
            exchange=record.exchange,
            instrument_token=record.instrument_token,
            tradingsymbol=record.tradingsymbol,
            classification=record.classification,
            headline=record.headline,
            body_text=record.body_text,
            ai_summary=record.ai_summary,
            model_version=record.model_version,
            published_at=record.published_at,
            effective_date=record.effective_date,
            raw_metadata=record.raw_metadata,
        )
        session.add(orm)
        return orm

    async def get_by_instrument(
        self,
        session: AsyncSession,
        instrument_token: str,
        limit: int = 100,
    ) -> List[Announcement]:
        """Return the most recent announcements for an instrument."""
        stmt = (
            select(Announcement)
            .where(Announcement.instrument_token == instrument_token)
            .order_by(Announcement.published_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_classification(
        self,
        session: AsyncSession,
        classification: str,
        limit: int = 100,
    ) -> List[Announcement]:
        """Return announcements filtered by classification."""
        stmt = (
            select(Announcement)
            .where(Announcement.classification == classification)
            .order_by(Announcement.published_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_exchange_and_id(
        self,
        session: AsyncSession,
        exchange: str,
        announcement_id: str,
    ) -> Optional[Announcement]:
        """Fetch one announcement by its unique key."""
        stmt = select(Announcement).where(
            Announcement.exchange == exchange,
            Announcement.announcement_id == announcement_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
