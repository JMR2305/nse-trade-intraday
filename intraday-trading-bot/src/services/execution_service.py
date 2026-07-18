"""Execution service — routes orders to PaperBroker only."""

from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.logging import logger
from src.core.exceptions import LiveModeBlockedError
from src.brokers.paper_broker import PaperBroker
from src.brokers.interface import OrderRequest
from src.services.order_service import OrderService
from src.services.position_service import PositionService
from src.services.risk_service import RiskService
from src.database.repositories.orders import OrderRepository
from src.database.repositories.fills import FillRepository
from src.database.repositories.ledger import LedgerRepository


class ExecutionService:
    """Execution service — the ONLY path for order execution. Routes exclusively to PaperBroker."""

    def __init__(self, db_session: AsyncSession) -> None:
        self._db = db_session
        self._broker = PaperBroker()
        self._order_service = OrderService(db_session)
        self._position_service = PositionService(db_session)
        self._risk_service = RiskService(db_session)
        self._order_repo = OrderRepository(db_session)
        self._fill_repo = FillRepository(db_session)
        self._ledger_repo = LedgerRepository(db_session)

    async def execute_order(self, session_id: str, instrument_token: int, symbol: str, side: str,
                            quantity: int, order_type: str = "MARKET", price: Optional[Decimal] = None,
                            trigger_price: Optional[Decimal] = None, stop_loss: Optional[Decimal] = None,
                            target: Optional[Decimal] = None, idempotency_key: str = "",
                            created_by: str = "system") -> Dict[str, Any]:
        entry_price = price or Decimal("100")
        risk_ok, risk_msg = await self._risk_service.check_trade_risk(
            entry_price=entry_price, stop_loss=stop_loss, quantity=quantity, symbol=symbol, session_id=session_id
        )
        if not risk_ok:
            raise Exception(f"Risk check failed: {risk_msg}")

        order = await self._order_service.create_order(
            session_id=session_id, instrument_token=instrument_token, side=side, order_type=order_type,
            quantity=quantity, price=price, trigger_price=trigger_price, stop_loss=stop_loss,
            target=target, idempotency_key=idempotency_key, created_by=created_by
        )

        broker_order = OrderRequest(symbol=symbol, side=side, quantity=quantity, order_type=order_type,
                                    price=price, trigger_price=trigger_price, stop_loss=stop_loss,
                                    target=target, tag=idempotency_key)

        response = await self._broker.place_order(broker_order)
        await self._order_service.update_order_status(order_id=order.id, status=response.status,
                                                        broker_order_id=response.broker_order_id, message=response.message)

        if response.status == "COMPLETE":
            costs = self._broker.get_order_costs(response.broker_order_id) or {}
            fill = await self._fill_repo.create(
                order_id=order.id, fill_id=response.broker_order_id, quantity=response.filled_quantity,
                price=response.average_price or Decimal("0"), brokerage=costs.get("brokerage", Decimal("0")),
                stt=costs.get("stt", Decimal("0")), exchange_charge=costs.get("exchange_charge", Decimal("0")),
                gst=costs.get("gst", Decimal("0")), sebi_charge=costs.get("sebi_charge", Decimal("0")),
                stamp_duty=costs.get("stamp_duty", Decimal("0")), total_cost=costs.get("total_cost", Decimal("0"))
            )
            position = await self._position_service.update_position_from_fill(
                session_id=session_id, instrument_token=instrument_token, side=side,
                quantity=response.filled_quantity, price=response.average_price or Decimal("0")
            )
            trade_value = response.filled_quantity * (response.average_price or Decimal("0"))
            current_balance = await self._ledger_repo.get_current_balance(session_id)
            if side == "BUY":
                new_balance = current_balance - trade_value - costs.get("total_cost", Decimal("0"))
                await self._ledger_repo.create(session_id=session_id, transaction_type="COSTS",
                                               amount=-costs.get("total_cost", Decimal("0")), balance_after=new_balance,
                                               description=f"Buy {symbol} x{quantity}", related_order_id=order.id)
            else:
                new_balance = current_balance + trade_value - costs.get("total_cost", Decimal("0"))
                await self._ledger_repo.create(session_id=session_id, transaction_type="COSTS",
                                               amount=-costs.get("total_cost", Decimal("0")), balance_after=new_balance,
                                               description=f"Sell {symbol} x{quantity}", related_order_id=order.id)
            logger.info(f"Order executed and filled: {order.id}", extra={"event_type": "ORDER_EXECUTED", "order_id": order.id,
                                                                           "fill_price": str(response.average_price), "total_cost": str(costs.get("total_cost", "0"))})
        return {"order_id": order.id, "broker_order_id": response.broker_order_id, "status": response.status,
                "filled_quantity": response.filled_quantity, "average_price": float(response.average_price) if response.average_price else None,
                "message": response.message, "idempotency_key": idempotency_key}

    async def cancel_order(self, order_id: int) -> bool:
        order = await self._order_repo.get_by_id(order_id)
        if not order:
            return False
        if order.order_id and order.order_id.startswith("PAPER_"):
            result = await self._broker.cancel_order(order.order_id)
            if result:
                await self._order_service.update_order_status(order_id, "CANCELLED")
            return result
        return False
