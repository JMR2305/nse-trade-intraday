"""Paper account ledger repository."""

from typing import Optional, List
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc

from src.database.models import PaperAccountLedger


class LedgerRepository:
    """Repository for paper_account_ledger table operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, entry_id: int) -> Optional[PaperAccountLedger]:
        """Get ledger entry by ID."""
        result = await self._session.execute(
            select(PaperAccountLedger).where(PaperAccountLedger.id == entry_id)
        )
        return result.scalar_one_or_none()

    async def get_by_session(self, session_id: str, limit: int = 100) -> List[PaperAccountLedger]:
        """Get ledger entries for a session."""
        result = await self._session.execute(
            select(PaperAccountLedger)
            .where(PaperAccountLedger.session_id == session_id)
            .order_by(desc(PaperAccountLedger.created_at))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_current_balance(self, session_id: str) -> Decimal:
        """Get latest balance for a session."""
        result = await self._session.execute(
            select(PaperAccountLedger.balance_after)
            .where(PaperAccountLedger.session_id == session_id)
            .order_by(desc(PaperAccountLedger.created_at))
            .limit(1)
        )
        balance = result.scalar_one_or_none()
        return balance or Decimal("0")

    async def get_session_pnl(self, session_id: str) -> Decimal:
        """Get realized P&L for a session from ledger."""
        result = await self._session.execute(
            select(func.sum(PaperAccountLedger.amount)).where(
                PaperAccountLedger.session_id == session_id,
                PaperAccountLedger.transaction_type.in_(["TRADE_PROFIT", "TRADE_LOSS"]),
            )
        )
        pnl = result.scalar()
        return pnl or Decimal("0")

    async def create(self, **kwargs) -> PaperAccountLedger:
        """Create a new ledger entry."""
        entry = PaperAccountLedger(**kwargs)
        self._session.add(entry)
        await self._session.flush()
        await self._session.refresh(entry)
        return entry
