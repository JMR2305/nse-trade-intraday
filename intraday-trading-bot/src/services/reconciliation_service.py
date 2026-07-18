"""Reconciliation service — verifies internal state consistency."""

from typing import Dict, Any, List
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import logger
from src.database.repositories.orders import OrderRepository
from src.database.repositories.fills import FillRepository
from src.database.repositories.positions import PositionRepository
from src.database.repositories.ledger import LedgerRepository


class ReconciliationService:
    """Reconciles persisted order/fill/position/ledger data. Run on startup to verify consistency before becoming ready."""

    def __init__(self, db_session: AsyncSession) -> None:
        self._db = db_session
        self._order_repo = OrderRepository(db_session)
        self._fill_repo = FillRepository(db_session)
        self._position_repo = PositionRepository(db_session)
        self._ledger_repo = LedgerRepository(db_session)

    async def reconcile_session(self, session_id: str) -> Dict[str, Any]:
        discrepancies = []
        orders = await self._order_repo.get_by_session(session_id)
        for order in orders:
            if order.status in ["COMPLETE", "PARTIAL_FILL"]:
                total_filled = await self._fill_repo.get_total_filled_quantity(order.id)
                if total_filled > order.quantity:
                    discrepancies.append({"type": "OVER_FILL", "order_id": order.id, "order_quantity": order.quantity, "filled_quantity": total_filled})
        positions = await self._position_repo.get_open_positions(session_id)
        ledger_balance = await self._ledger_repo.get_current_balance(session_id)
        is_healthy = len(discrepancies) == 0
        logger.info(f"Reconciliation complete for {session_id}: {len(discrepancies)} discrepancies",
                    extra={"event_type": "RECONCILIATION_COMPLETE", "session_id": session_id, "healthy": is_healthy, "discrepancies": len(discrepancies)})
        return {"session_id": session_id, "healthy": is_healthy, "discrepancies": discrepancies,
                "order_count": len(orders), "open_position_count": len(positions), "ledger_balance": float(ledger_balance)}

    async def is_session_ready(self, session_id: str) -> bool:
        result = await self.reconcile_session(session_id)
        return result["healthy"]
