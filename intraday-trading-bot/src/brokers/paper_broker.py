"""Paper broker implementation — the ONLY execution adapter."""

import random
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.brokers.interface import (
    BrokerInterface,
    OrderRequest,
    OrderResponse,
    Position,
    Margin,
)
from src.core.config import settings
from src.core.logging import logger
from src.core.exceptions import LiveModeBlockedError, OrderValidationError


class PaperBroker(BrokerInterface):
    """
    Paper trading broker. Simulates execution without external calls.
    This is the ONLY registered execution adapter in the system.
    No live orders are ever sent to any external broker.
    """

    def __init__(self) -> None:
        self._orders: Dict[str, Dict[str, Any]] = {}
        self._positions: Dict[str, Position] = {}
        self._order_counter = 0
        self._slippage_models = {
            "realistic": {"mean": Decimal("0.0005"), "std": Decimal("0.001")},
            "optimistic": {"mean": Decimal("0.0001"), "std": Decimal("0.0003")},
            "pessimistic": {"mean": Decimal("0.001"), "std": Decimal("0.002")},
        }

    def _generate_order_id(self) -> str:
        """Generate a unique paper order ID."""
        self._order_counter += 1
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return f"PAPER_{timestamp}_{self._order_counter:06d}"

    def _apply_slippage(self, price: Decimal, side: str) -> Decimal:
        """Apply realistic slippage to fill price."""
        model = self._slippage_models.get(
            settings.paper.slippage_model,
            self._slippage_models["realistic"],
        )
        slippage = model["mean"]
        if side == "BUY":
            fill_price = price * (Decimal("1") + slippage)
        else:
            fill_price = price * (Decimal("1") - slippage)
        return fill_price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def _calculate_costs(self, quantity: int, price: Decimal) -> Dict[str, Decimal]:
        """Calculate trading costs for a fill."""
        turnover = quantity * price
        brokerage = min(
            Decimal(str(settings.broker.brokerage_per_order)),
            turnover * Decimal("0.0003")
        )
        stt = turnover * Decimal("0.00025")
        exchange_charge = turnover * Decimal("0.0000325")
        gst = (brokerage + exchange_charge) * Decimal("0.18")
        sebi_charge = turnover * Decimal("0.000001")
        stamp_duty = turnover * Decimal("0.00003")
        total_cost = brokerage + stt + exchange_charge + gst + sebi_charge + stamp_duty

        return {
            "brokerage": brokerage.quantize(Decimal("0.01")),
            "stt": stt.quantize(Decimal("0.01")),
            "exchange_charge": exchange_charge.quantize(Decimal("0.01")),
            "gst": gst.quantize(Decimal("0.01")),
            "sebi_charge": sebi_charge.quantize(Decimal("0.01")),
            "stamp_duty": stamp_duty.quantize(Decimal("0.01")),
            "total_cost": total_cost.quantize(Decimal("0.01")),
        }

    async def place_order(self, order: OrderRequest) -> OrderResponse:
        """Simulate order placement in paper mode."""
        order_id = self._generate_order_id()

        if order.quantity <= 0:
            return OrderResponse(
                broker_order_id="",
                status="REJECTED",
                message="Quantity must be positive",
            )

        if order.order_type != "MARKET" and order.price is None:
            return OrderResponse(
                broker_order_id="",
                status="REJECTED",
                message="Price required for non-market orders",
            )

        base_price = order.price or Decimal("100")
        fill_price = self._apply_slippage(base_price, order.side)
        costs = self._calculate_costs(order.quantity, fill_price)

        self._orders[order_id] = {
            "order": order,
            "fill_price": fill_price,
            "filled_quantity": order.quantity,
            "status": "COMPLETE",
            "costs": costs,
        }

        await self._update_position(order, fill_price, order.quantity)

        logger.info(
            f"Paper order placed and filled: {order_id}",
            extra={
                "event_type": "PAPER_ORDER_FILLED",
                "order_id": order_id,
                "symbol": order.symbol,
                "side": order.side,
                "quantity": order.quantity,
                "fill_price": str(fill_price),
                "total_cost": str(costs["total_cost"]),
            },
        )

        return OrderResponse(
            broker_order_id=order_id,
            status="COMPLETE",
            average_price=fill_price,
            filled_quantity=order.quantity,
            pending_quantity=0,
        )

    async def _update_position(
        self, order: OrderRequest, fill_price: Decimal, quantity: int
    ) -> None:
        """Update internal position tracking."""
        key = f"{order.symbol}_{order.side}"
        existing = self._positions.get(key)

        if existing:
            total_value = (existing.quantity * existing.average_price) + (quantity * fill_price)
            new_quantity = existing.quantity + quantity
            new_avg = total_value / new_quantity
            self._positions[key] = Position(
                symbol=order.symbol,
                instrument_token=0,
                quantity=new_quantity,
                average_price=new_avg,
                last_price=fill_price,
                pnl=Decimal("0"),
                product=order.product,
                side=order.side,
            )
        else:
            self._positions[key] = Position(
                symbol=order.symbol,
                instrument_token=0,
                quantity=quantity,
                average_price=fill_price,
                last_price=fill_price,
                pnl=Decimal("0"),
                product=order.product,
                side=order.side,
            )

    async def modify_order(self, order_id: str, **kwargs: Any) -> OrderResponse:
        """Paper modification — no-op or create new."""
        if order_id not in self._orders:
            return OrderResponse(
                broker_order_id=order_id,
                status="REJECTED",
                message="Order not found",
            )
        return OrderResponse(
            broker_order_id=order_id,
            status="MODIFIED",
            message="Paper modification accepted",
        )

    async def cancel_order(self, order_id: str) -> bool:
        """Paper cancellation."""
        if order_id in self._orders:
            self._orders[order_id]["status"] = "CANCELLED"
            logger.info(
                f"Paper order cancelled: {order_id}",
                extra={"event_type": "PAPER_ORDER_CANCELLED", "order_id": order_id},
            )
            return True
        return False

    async def get_positions(self) -> List[Position]:
        """Return current paper positions."""
        return list(self._positions.values())

    async def get_orders(self) -> List[Dict[str, Any]]:
        """Return all paper orders."""
        return [
            {
                "order_id": oid,
                "status": data["status"],
                "symbol": data["order"].symbol,
                "side": data["order"].side,
                "quantity": data["order"].quantity,
                "filled_quantity": data["filled_quantity"],
                "average_price": str(data["fill_price"]),
                "total_cost": str(data["costs"]["total_cost"]),
            }
            for oid, data in self._orders.items()
        ]

    async def get_margins(self) -> Margin:
        """Return paper margins."""
        return Margin(
            available_cash=settings.paper.initial_capital,
            used_margin=Decimal("0"),
            available_margin=settings.paper.initial_capital,
        )

    async def get_instruments(self, exchange: str) -> List[Dict[str, Any]]:
        """Return empty list — no real instruments in paper."""
        return []

    async def get_quote(self, symbols: List[str]) -> Dict[str, Any]:
        """Return mock quotes."""
        return {
            sym: {"last_price": Decimal("100"), "volume": 0, "oi": 0}
            for sym in symbols
        }

    def get_order_costs(self, order_id: str) -> Optional[Dict[str, Decimal]]:
        """Get cost breakdown for a paper order."""
        order_data = self._orders.get(order_id)
        if order_data:
            return order_data.get("costs")
        return None
