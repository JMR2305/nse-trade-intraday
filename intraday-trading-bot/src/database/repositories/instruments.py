"""Instrument master repository."""

from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from src.database.models import InstrumentMaster


class InstrumentRepository:
    """Repository for instrument_master table operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_token(self, instrument_token: int) -> Optional[InstrumentMaster]:
        """Get instrument by token."""
        result = await self._session.execute(
            select(InstrumentMaster).where(InstrumentMaster.instrument_token == instrument_token)
        )
        return result.scalar_one_or_none()

    async def get_by_symbol(self, tradingsymbol: str, exchange: str = "NSE") -> Optional[InstrumentMaster]:
        """Get instrument by trading symbol and exchange."""
        result = await self._session.execute(
            select(InstrumentMaster).where(
                InstrumentMaster.tradingsymbol == tradingsymbol,
                InstrumentMaster.exchange == exchange,
            )
        )
        return result.scalar_one_or_none()

    async def get_tradable(self, limit: int = 1000) -> List[InstrumentMaster]:
        """Get all tradable instruments."""
        result = await self._session.execute(
            select(InstrumentMaster)
            .where(InstrumentMaster.is_tradable == True)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def create(self, **kwargs) -> InstrumentMaster:
        """Create a new instrument."""
        instrument = InstrumentMaster(**kwargs)
        self._session.add(instrument)
        await self._session.flush()
        await self._session.refresh(instrument)
        return instrument

    async def update(self, instrument_token: int, **kwargs) -> Optional[InstrumentMaster]:
        """Update instrument fields."""
        await self._session.execute(
            update(InstrumentMaster)
            .where(InstrumentMaster.instrument_token == instrument_token)
            .values(**kwargs)
        )
        return await self.get_by_token(instrument_token)

    async def upsert(self, **kwargs) -> InstrumentMaster:
        """Create or update instrument."""
        existing = await self.get_by_token(kwargs.get("instrument_token"))
        if existing:
            return await self.update(existing.instrument_token, **kwargs)
        return await self.create(**kwargs)
