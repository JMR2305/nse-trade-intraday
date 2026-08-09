"""Execution service — routes orders through RC-8B risk gate then to the broker adapter."""

from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import logger
from src.core.exceptions import IdempotencyError, OrderValidationError
from src.brokers.paper_broker import PaperBroker
from src.brokers.interface import BrokerAdapter, OrderRequest
from src.brokers.contracts import (
    BrokerExchange,
    BrokerOrderRequest,
    BrokerOrderStatus,
    BrokerOrderType,
    BrokerProduct,
    BrokerSide,
    BrokerValidity,
    BrokerVariety,
)
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
    the broker adapter. Risk gating is always enabled; call
    self._risk_integration.disable() in tests to bypass.

    RC-10D: accepts an optional ``broker`` parameter.  When omitted,
    ``PaperBroker()`` is constructed as the default — preserving full
    backward compatibility with all existing call sites and tests.
    """

    def __init__(self, db_session: AsyncSession, broker=None) -> None:
        self._db = db_session
        self._broker = broker if broker is not None else PaperBroker()
        self._order_service = OrderService(db_session)
        self._position_service = PositionService(db_session)
        self._order_repo = OrderRepository(db_session)
        self._fill_repo = FillRepository(db_session)
        self._ledger_repo = LedgerRepository(db_session)

        # RC-10D: wire DB session into BrokerAdapter for correlation persistence.
        # This enables the order gateway to persist idempotency records to
        # broker_order_correlations and recover them on restart.
        if isinstance(self._broker, BrokerAdapter):
            self._broker.set_db_session(db_session)

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
            # Re-raise typed errors so the API layer can map them to proper
            # status codes (409 idempotency conflict, 400 validation).
            exc = integration_result.exception
            if isinstance(exc, (IdempotencyError, OrderValidationError)):
                raise exc
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

        # ── Route to broker: adapter-aware dispatch ───────────────────────────
        # If the injected broker implements BrokerAdapter (RC-10D), build a
        # BrokerOrderRequest and call place_broker_order().  Otherwise fall back
        # to the legacy OrderRequest path (PaperBroker compatibility).
        response_status: str
        response_broker_order_id: str
        response_message: str = ""
        response_filled_quantity: Decimal = Decimal("0")
        response_average_price: Optional[Decimal] = None
        costs: dict = {}

        if isinstance(self._broker, BrokerAdapter):
            _side = BrokerSide.BUY if side.upper() == "BUY" else BrokerSide.SELL
            _order_type_map = {
                "MARKET": BrokerOrderType.MARKET,
                "LIMIT": BrokerOrderType.LIMIT,
                "SL": BrokerOrderType.SL,
                "SL-M": BrokerOrderType.SL_M,
            }
            broker_request = BrokerOrderRequest(
                internal_order_id=str(db_order.id),
                idempotency_key=idempotency_key or str(db_order.id),
                trading_symbol=symbol,
                transaction_type=_side,
                quantity=Decimal(str(quantity)),
                order_type=_order_type_map.get(order_type.upper(), BrokerOrderType.MARKET),
                exchange=BrokerExchange.NSE,
                product=BrokerProduct.MIS,
                validity=BrokerValidity.DAY,
                variety=BrokerVariety.REGULAR,
                price=price,
                trigger_price=trigger_price,
                tag=idempotency_key,
                paper_mode=not self._broker.get_capabilities().supports_live_orders,
            )
            broker_resp = await self._broker.place_broker_order(broker_request)
            # Normalise BrokerOrderResponse → execution_service fields
            response_status = broker_resp.status.value if hasattr(broker_resp.status, "value") else str(broker_resp.status)
            response_broker_order_id = broker_resp.broker_order_id or ""
            response_message = broker_resp.message or ""
            response_filled_quantity = broker_resp.filled_quantity or Decimal("0")
            response_average_price = broker_resp.average_price
        else:
            # Legacy path — PaperBroker and any BrokerInterface implementor
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
            legacy_resp = await self._broker.place_order(broker_order)
            response_status = legacy_resp.status
            response_broker_order_id = legacy_resp.broker_order_id or ""
            response_message = legacy_resp.message or ""
            response_filled_quantity = Decimal(str(legacy_resp.filled_quantity or 0))
            response_average_price = legacy_resp.average_price
            # costs from legacy broker (PaperBroker.get_order_costs)
            if response_status == "COMPLETE":
                costs = (
                    getattr(self._broker, "get_order_costs", lambda _: {})(response_broker_order_id)
                    or {}
                )

        await self._order_service.update_order_status(
            order_id=db_order.id,
            status=response_status,
            broker_order_id=response_broker_order_id,
            message=response_message,
        )

        if response_status in ("COMPLETE", BrokerOrderStatus.COMPLETE.value):
            await self._fill_repo.create(
                order_id=db_order.id,
                fill_id=response_broker_order_id,
                quantity=response_filled_quantity,
                price=response_average_price or Decimal("0"),
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
                quantity=response_filled_quantity,
                price=response_average_price or Decimal("0"),
            )
            trade_value = response_filled_quantity * (response_average_price or Decimal("0"))
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
                    "fill_price": str(response_average_price),
                    "total_cost": str(total_cost),
                },
            )

        return {
            "order_id": db_order.id,
            "broker_order_id": response_broker_order_id,
            "status": response_status,
            "filled_quantity": response_filled_quantity,
            "average_price": float(response_average_price) if response_average_price else None,
            "message": response_message,
            "idempotency_key": idempotency_key,
        }

    async def cancel_order(self, order_id: int) -> bool:
        """Cancel a pending or open order.

        Routes through BrokerAdapter.cancel_broker_order() when a
        BrokerAdapter is injected; falls back to legacy cancel_order()
        for PaperBroker and other BrokerInterface implementors.
        """
        order = await self._order_repo.get_by_id(order_id)
        if not order or not order.order_id:
            return False

        broker_order_id = order.order_id

        if isinstance(self._broker, BrokerAdapter):
            result = await self._broker.cancel_broker_order(
                broker_order_id=broker_order_id,
                internal_order_id=str(order_id),
            )
        else:
            # Legacy path — PaperBroker and BrokerInterface implementors
            result = await self._broker.cancel_order(broker_order_id)

        if result:
            await self._order_service.update_order_status(order_id, "CANCELLED")
        return result
