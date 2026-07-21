"""
Project-specific adapter implementing ExecutionEnginePort.

Bridges the RC-8B RiskIntegrationLayer to the project's existing
service/repository layer. session_id is used as account_id throughout.

get_market_price() returns None (paper mode; PriceBandRule skips None LTP).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.repositories.orders import OrderRepository
from src.database.repositories.positions import PositionRepository
from src.database.repositories.ledger import LedgerRepository
from src.risk.integration_layer import ExecutionEnginePort

if TYPE_CHECKING:
    from src.services.execution_service import ExecutionService


class ProjectExecutionAdapter(ExecutionEnginePort):
    """Implements ExecutionEnginePort over the project's repository layer.

    session_id == account_id in this project (each trading session
    has an isolated account namespace).

    get_market_price() always returns None — this is a paper trading
    system with no real-time LTP feed. PriceBandRule handles None LTP
    gracefully by skipping the check.
    """

    def __init__(
        self,
        db_session: AsyncSession,
        execution_service: "ExecutionService",
    ) -> None:
        self._db = db_session
        self._execution = execution_service
        self._position_repo = PositionRepository(db_session)
        self._ledger_repo = LedgerRepository(db_session)
        self._order_repo = OrderRepository(db_session)

    async def get_portfolio_snapshot(self, account_id: str) -> Optional[Dict[str, Any]]:
        """Build a portfolio snapshot from ledger balance and open positions."""
        try:
            balance = await self._ledger_repo.get_current_balance(account_id)
            positions = await self._position_repo.get_open_positions(account_id)

            balance_dec = Decimal(str(balance)) if balance is not None else Decimal("0")
            exposure = sum(
                Decimal(str(p.quantity)) * Decimal(str(p.average_price))
                for p in positions
            )

            return {
                "equity": balance_dec,
                "cash": balance_dec,
                "buying_power": balance_dec,
                "available_margin": balance_dec,
                "total_market_value": exposure,
            }
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                f"Could not build portfolio snapshot for {account_id}: {exc}"
            )
            return None

    async def get_position_snapshots(self, account_id: str) -> Dict[str, Any]:
        """Return position snapshots keyed by instrument_token string."""
        try:
            positions = await self._position_repo.get_open_positions(account_id)
            result: Dict[str, Any] = {}
            for p in positions:
                qty = p.quantity
                direction = "LONG" if qty > 0 else ("SHORT" if qty < 0 else "FLAT")
                result[str(p.instrument_token)] = {
                    "net_quantity": Decimal(str(qty)),
                    "direction": direction,
                    "market_value": Decimal(str(qty)) * Decimal(str(p.average_price)),
                }
            return result
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                f"Could not build position snapshots for {account_id}: {exc}"
            )
            return {}

    async def get_open_orders(self, account_id: str) -> List[Any]:
        """Return open orders for the account."""
        try:
            orders = await self._order_repo.get_open_orders(account_id)
            return [
                {
                    "instrument_token": str(o.instrument_token),
                    "side": o.side,
                    "price": o.price,
                }
                for o in orders
            ]
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                f"Could not fetch open orders for {account_id}: {exc}"
            )
            return []

    async def get_market_price(self, instrument_token: str) -> Optional[Decimal]:
        """Paper mode: no real-time LTP. PriceBandRule skips None gracefully."""
        return None

    async def submit_order(self, account_id: str, order: Any) -> Dict[str, Any]:
        """Forward a risk-approved order to the RC-7 broker execution path."""
        return await self._execution._submit_approved_order(account_id, order)
