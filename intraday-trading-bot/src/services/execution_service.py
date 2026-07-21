"""Execution service — routes orders through RC-8B risk gate then to PaperBroker."""

from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import logger
from src.brokers.paper_broker import PaperBroker
from src.brokers.interface import OrderRequest
from src.services.order_service import OrderService
from src.services.position_service import PositionService
from src.database.repositories.orders import OrderRepository
from src.database.repositories.fills import FillRepository
from src.database.repositories.ledger import LedgerRepository
from src.risk.engine import RiskEngine
from src.risk.integration_layer import RiskIntegrationLayer
from src.risk.execution_adapter import ProjectExecutionAdapter


class ExecutionService:
    """Execution service — the ONLY path for order execution.

    Every order passes through RiskIntegrationLayer (RC-8B) before reaching
    PaperBroker. Risk gating is always enabled; call
    self._risk_integration.disable() in tests to bypass.
    """

    def __init__(self, db_session: AsyncSession) -> None:
        self._db = db_session
        self._broker = PaperBroker()
        self._order_service = OrderService(db_session)
        self._position_service = PositionService(db_session)
        self._order_repo = OrderRepository(db_session)
        self._fill_repo = FillRepository(db_session)
        self._ledger_repo = LedgerRepository(db_session)

        # RC-8B: Risk Integration Layer — always enabled in production.
        # Pass limits via risk_integration.set_limits() or add_limit() after construction.
        _risk_engine = RiskEngine()
        _adapter = ProjectExecutionAdapter(db_session, self)
        self._risk_integration = RiskIntegrationLayer(_risk_engine, _adapter, enabled=True)

    async def execute_order(
        self,
        session_id: str,
        instrument_token: int,
        symbol: str,
        side: str,
        quantity: int,
        order_type: str = "MARKET",
        price: Optional[Decimal] = None,
        trigger_price: Optional[Decimal] = None,
        stop_loss: Optional[Decimal] = None,
        target: Optional[Decimal] = None,
        idempotency_key: str = "",
        created_by: str = "system",
    ) -> Dict[str, Any]:
        """Submit an order through the risk gate and (if approved) to PaperBroker.

        session_id is used as account_id in the risk engine.
        Raises Exception if the risk gate rejects the order.
        """
        order = {
            "instrument_token": str(instrument_token),
            "symbol": symbol,
            "side": side,
            "quantity": Decimal(str(quantity)),
            "price": price,
            "order_type": order_type,
            "trigger_price": trigger_price,
            "stop_loss": stop_loss,
            "target": target,
            "idempotency_key": idempotency_key,
            "created_by": created_by,
        }

        integration_result = await self._risk_integration.submit_order(
            account_id=session_id,
            order=order,
        )

        if integration_result.rejected:
            raise Exception(f"Risk check failed: {integration_result.rejection_reason}")

        if integration_result.error:
            raise Exception(f"Execution error: {integration_result.error}")

        return integration_result.execution_result

    async def _submit_approved_order(
        self,
        account_id: str,
        order: Any,
    ) -> Dict[str, Any]:
        """Execute a risk-approved order via the RC-7 PaperBroker path.

        Called exclusively by ProjectExecutionAdapter.submit_order() after the
        risk gate approves. account_id == session_id for this project.
        """
        session_id = account_id
        if not isinstance(order, dict):
            raise ValueError("Order must be a dict; got %s" % type(order))

        instrument_token = int(order.get("instrument_token", 0))
        symbol = order.get("symbol", "")
        side = order.get("side", "BUY")
        quantity = int(order.get("quantity", 0))
        order_type = order.get("order_type", "MARKET")
        price: Optional[Decimal] = order.get("price")
        trigger_price: Optional[Decimal] = order.get("trigger_price")
        stop_loss: Optional[Decimal] = order.get("stop_loss")
        target: Optional[Decimal] = order.get("target")
        idempotency_key: str = order.get("idempotency_key", "")
        created_by: str = order.get("created_by", "system")

        db_order = await self._order_service.create_order(
            session_id=session_id,
            instrument_token=instrument_token,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            trigger_price=trigger_price,
            stop_loss=stop_loss,
            target=target,
            idempotency_key=idempotency_key,
            created_by=created_by,
        )

        broker_order = OrderRequest(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
            price=price,
            trigger_price=trigger_price,
            stop_loss=stop_loss,
            target=target,
            tag=idempotency_key,
        )

        response = await self._broker.place_order(broker_order)
        await self._order_service.update_order_status(
            order_id=db_order.id,
            status=response.status,
            broker_order_id=response.broker_order_id,
            message=response.message,
        )

        if response.status == "COMPLETE":
            costs = self._broker.get_order_costs(response.broker_order_id) or {}
            await self._fill_repo.create(
                order_id=db_order.id,
                fill_id=response.broker_order_id,
                quantity=response.filled_quantity,
                price=response.average_price or Decimal("0"),
                brokerage=costs.get("brokerage", Decimal("0")),
                stt=costs.get("stt", Decimal("0")),
                exchange_charge=costs.get("exchange_charge", Decimal("0")),
                gst=costs.get("gst", Decimal("0")),
                sebi_charge=costs.get("sebi_charge", Decimal("0")),
                stamp_duty=costs.get("stamp_duty", Decimal("0")),
                total_cost=costs.get("total_cost", Decimal("0")),
            )
            await self._position_service.update_position_from_fill(
                session_id=session_id,
                instrument_token=instrument_token,
                side=side,
                quantity=response.filled_quantity,
                price=response.average_price or Decimal("0"),
            )
            trade_value = response.filled_quantity * (response.average_price or Decimal("0"))
            current_balance = await self._ledger_repo.get_current_balance(session_id)
            total_cost = costs.get("total_cost", Decimal("0"))
            if side == "BUY":
                new_balance = current_balance - trade_value - total_cost
                description = f"Buy {symbol} x{quantity}"
            else:
                new_balance = current_balance + trade_value - total_cost
                description = f"Sell {symbol} x{quantity}"
            await self._ledger_repo.create(
                session_id=session_id,
                transaction_type="COSTS",
                amount=-total_cost,
                balance_after=new_balance,
                description=description,
                related_order_id=db_order.id,
            )
            logger.info(
                f"Order executed and filled: {db_order.id}",
                extra={
                    "event_type": "ORDER_EXECUTED",
                    "order_id": db_order.id,
                    "fill_price": str(response.average_price),
                    "total_cost": str(total_cost),
                },
            )

        return {
            "order_id": db_order.id,
            "broker_order_id": response.broker_order_id,
            "status": response.status,
            "filled_quantity": response.filled_quantity,
            "average_price": float(response.average_price) if response.average_price else None,
            "message": response.message,
            "idempotency_key": idempotency_key,
        }

    async def cancel_order(self, order_id: int) -> bool:
        """Cancel a pending or open order."""
        order = await self._order_repo.get_by_id(order_id)
        if not order:
            return False
        if order.order_id and order.order_id.startswith("PAPER_"):
            result = await self._broker.cancel_order(order.order_id)
            if result:
                await self._order_service.update_order_status(order_id, "CANCELLED")
            return result
        return False
