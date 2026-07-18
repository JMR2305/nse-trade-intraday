"""Abstract broker interface — all broker implementations must extend this."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional


@dataclass
class OrderRequest:
    """Request to place an order."""
    symbol: str
    side: str  # BUY | SELL
    quantity: int
    order_type: str  # MARKET | LIMIT | SL | SL-M
    product: str = "MIS"
    price: Optional[Decimal] = None
    trigger_price: Optional[Decimal] = None
    stop_loss: Optional[Decimal] = None
    target: Optional[Decimal] = None
    tag: Optional[str] = None


@dataclass
class OrderResponse:
    """Response from placing an order."""
    broker_order_id: str
    status: str  # PENDING | COMPLETE | REJECTED | CANCELLED
    average_price: Optional[Decimal] = None
    filled_quantity: int = 0
    pending_quantity: int = 0
    message: Optional[str] = None


@dataclass
class Position:
    """Current position in a symbol."""
    symbol: str
    instrument_token: int
    quantity: int
    average_price: Decimal
    last_price: Decimal
    pnl: Decimal
    product: str
    side: str


@dataclass
class Margin:
    """Account margin information."""
    available_cash: Decimal
    used_margin: Decimal
    available_margin: Decimal


class BrokerInterface(ABC):
    """Abstract broker interface. All broker implementations must extend this."""

    @abstractmethod
    async def place_order(self, order: OrderRequest) -> OrderResponse:
        """Place a new order with the broker."""
        pass

    @abstractmethod
    async def modify_order(self, order_id: str, **kwargs: Any) -> OrderResponse:
        """Modify an existing order."""
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an existing order."""
        pass

    @abstractmethod
    async def get_positions(self) -> List[Position]:
        """Get all current positions."""
        pass

    @abstractmethod
    async def get_orders(self) -> List[Dict[str, Any]]:
        """Get all orders."""
        pass

    @abstractmethod
    async def get_margins(self) -> Margin:
        """Get current margin information."""
        pass

    @abstractmethod
    async def get_instruments(self, exchange: str) -> List[Dict[str, Any]]:
        """Get instruments for an exchange."""
        pass

    @abstractmethod
    async def get_quote(self, symbols: List[str]) -> Dict[str, Any]:
        """Get quotes for symbols."""
        pass
