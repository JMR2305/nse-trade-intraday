"""
Mock ExecutionEnginePort for risk engine unit tests.

Provides configurable in-memory portfolio, positions, and order state.
Records all submitted orders for assertion in tests.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import uuid4

from src.risk.integration_layer import ExecutionEnginePort


class MockExecutionEngine(ExecutionEnginePort):
    """In-memory mock for ExecutionEnginePort.

    Usage in tests:
        engine = MockExecutionEngine()
        engine.set_portfolio(equity=Decimal("100000"), cash=Decimal("100000"))
        engine.add_position("738561", net_quantity=Decimal("0"))
        engine.set_fill_result(status="COMPLETE", filled_quantity=Decimal("10"), average_price=Decimal("100"))
        layer = RiskIntegrationLayer(risk_engine, engine, limits)
        result = await layer.submit_order("test_account", order)
        assert engine.submitted_orders  # was called
    """

    def __init__(self) -> None:
        self._portfolio: Optional[Dict[str, Any]] = None
        self._positions: Dict[str, Any] = {}
        self._open_orders: List[Any] = []
        self._market_prices: Dict[str, Optional[Decimal]] = {}
        self._fill_result: Optional[Dict[str, Any]] = None
        self._raise_on_submit: Optional[Exception] = None
        self.submitted_orders: List[Any] = []
        self.submit_call_count: int = 0

    def set_portfolio(
        self,
        equity: Decimal = Decimal("100000"),
        cash: Decimal = Decimal("100000"),
        buying_power: Decimal = Decimal("100000"),
        available_margin: Decimal = Decimal("100000"),
        total_market_value: Decimal = Decimal("0"),
    ) -> None:
        self._portfolio = {
            "equity": equity,
            "cash": cash,
            "buying_power": buying_power,
            "available_margin": available_margin,
            "total_market_value": total_market_value,
        }

    def add_position(
        self,
        instrument_token: str,
        net_quantity: Decimal = Decimal("0"),
        direction: str = "FLAT",
        market_value: Decimal = Decimal("0"),
    ) -> None:
        self._positions[instrument_token] = {
            "net_quantity": net_quantity,
            "direction": direction,
            "market_value": market_value,
        }

    def add_open_order(self, order: Dict[str, Any]) -> None:
        self._open_orders.append(order)

    def set_market_price(self, instrument_token: str, price: Optional[Decimal]) -> None:
        self._market_prices[instrument_token] = price

    def set_fill_result(
        self,
        status: str = "COMPLETE",
        filled_quantity: Decimal = Decimal("10"),
        average_price: Decimal = Decimal("100"),
        order_id: Optional[str] = None,
        broker_order_id: Optional[str] = None,
    ) -> None:
        oid = order_id or str(uuid4().hex[:8])
        boid = broker_order_id or f"PAPER_{uuid4().hex[:8]}"
        self._fill_result = {
            "order_id": oid,
            "broker_order_id": boid,
            "status": status,
            "filled_quantity": filled_quantity,
            "average_price": float(average_price),
            "message": "Mock execution",
            "idempotency_key": "",
        }

    def set_submit_error(self, exc: Exception) -> None:
        """Make submit_order raise an exception."""
        self._raise_on_submit = exc

    def clear_submit_error(self) -> None:
        self._raise_on_submit = None

    async def get_portfolio_snapshot(self, account_id: str) -> Optional[Dict[str, Any]]:
        return self._portfolio

    async def get_position_snapshots(self, account_id: str) -> Dict[str, Any]:
        return dict(self._positions)

    async def get_open_orders(self, account_id: str) -> List[Any]:
        return list(self._open_orders)

    async def get_market_price(self, instrument_token: str) -> Optional[Decimal]:
        return self._market_prices.get(instrument_token)

    async def submit_order(self, account_id: str, order: Any) -> Dict[str, Any]:
        self.submit_call_count += 1
        self.submitted_orders.append({"account_id": account_id, "order": order})

        if self._raise_on_submit is not None:
            raise self._raise_on_submit

        if self._fill_result is not None:
            return dict(self._fill_result)

        # Default success result
        return {
            "order_id": f"order_{self.submit_call_count}",
            "broker_order_id": f"PAPER_{self.submit_call_count}",
            "status": "COMPLETE",
            "filled_quantity": Decimal("10"),
            "average_price": 100.0,
            "message": "Mock fill",
            "idempotency_key": "",
        }
