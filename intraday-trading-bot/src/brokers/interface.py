"""Broker adapter interface — all broker implementations must extend BrokerAdapter.

RC-10D adds BrokerAdapter as the canonical protocol extending the legacy
BrokerInterface.  Existing code that only depends on BrokerInterface and the
old-style OrderRequest/OrderResponse dataclasses is unaffected.

Hierarchy
---------
    BrokerInterface (legacy, old-style dataclasses)
        └── BrokerAdapter  (RC-10D, new Pydantic contracts + lifecycle methods)
                └── ZerodhaAdapter    (live)
                PaperBroker also implements BrokerInterface for backward compat;
                it does NOT extend BrokerAdapter (the new Pydantic path is only
                used by ZerodhaAdapter and explicit BrokerAdapter callers).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Coroutine, Dict, List, Optional

from src.brokers.contracts import (
    BrokerCapabilities,
    BrokerFunds,
    BrokerHealth,
    BrokerHolding,
    BrokerInstrument,
    BrokerMargins,
    BrokerOrderRequest,
    BrokerOrderResponse,
    BrokerOrderUpdate,
    BrokerPosition,
    BrokerSession,
    BrokerTrade,
)


# ---------------------------------------------------------------------------
# Legacy dataclasses — kept for PaperBroker backward compat
# ---------------------------------------------------------------------------

@dataclass
class OrderRequest:
    """Request to place an order (legacy, used by PaperBroker)."""
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
    """Response from placing an order (legacy, used by PaperBroker)."""
    broker_order_id: str
    status: str  # PENDING | COMPLETE | REJECTED | CANCELLED
    average_price: Optional[Decimal] = None
    filled_quantity: int = 0
    pending_quantity: int = 0
    message: Optional[str] = None


@dataclass
class Position:
    """Current position in a symbol (legacy)."""
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
    """Account margin information (legacy)."""
    available_cash: Decimal
    used_margin: Decimal
    available_margin: Decimal


# ---------------------------------------------------------------------------
# Legacy abstract interface (kept unmodified for PaperBroker compat)
# ---------------------------------------------------------------------------

class BrokerInterface(ABC):
    """Legacy broker interface. PaperBroker continues to implement this."""

    @abstractmethod
    async def place_order(self, order: OrderRequest) -> OrderResponse:
        """Place a new order with the broker."""

    @abstractmethod
    async def modify_order(self, order_id: str, **kwargs: Any) -> OrderResponse:
        """Modify an existing order."""

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an existing order."""

    @abstractmethod
    async def get_positions(self) -> List[Position]:
        """Get all current positions."""

    @abstractmethod
    async def get_orders(self) -> List[Dict[str, Any]]:
        """Get all orders."""

    @abstractmethod
    async def get_margins(self) -> Margin:
        """Get current margin information."""

    @abstractmethod
    async def get_instruments(self, exchange: str) -> List[Dict[str, Any]]:
        """Get instruments for an exchange."""

    @abstractmethod
    async def get_quote(self, symbols: List[str]) -> Dict[str, Any]:
        """Get quotes for symbols."""


# ---------------------------------------------------------------------------
# RC-10D: BrokerAdapter — new canonical protocol
# ---------------------------------------------------------------------------

#: Type alias for the async callback that receives normalised order updates
OrderUpdateCallback = Callable[[BrokerOrderUpdate], Coroutine[Any, Any, None]]


class BrokerAdapter(ABC):
    """Canonical broker adapter protocol for RC-10D.

    All methods use broker-neutral Pydantic contracts from src.brokers.contracts.
    Raw third-party types must never cross this boundary.

    Safety invariants (enforced by every implementation):
      - paper_mode=True by default; live requires ≥5 explicit gates
      - kill switch is checked before any order is placed
      - credentials are never included in logs or exception messages
      - order placement timeouts enter reconciliation, not blind retry
    """

    # ── Lifecycle ─────────────────────────────────────────────────────────

    @abstractmethod
    async def authenticate(self) -> BrokerSession:
        """Exchange credentials for a valid session.

        Must never automate the interactive OAuth browser step.
        Returns a BrokerSession (credentials redacted in repr).
        """

    @abstractmethod
    async def restore_session(self) -> BrokerSession:
        """Restore a persisted session from the broker_sessions DB table.

        Returns a valid BrokerSession or raises BrokerSessionExpiredError.
        """

    @abstractmethod
    async def validate_session(self) -> bool:
        """Probe the broker to verify the session is alive.

        Returns True if the session is valid, False otherwise.
        Raises BrokerConnectionError on network failure.
        """

    @abstractmethod
    async def close(self) -> None:
        """Release all resources: HTTP client, WebSocket, background tasks."""

    # ── Orders ────────────────────────────────────────────────────────────

    @abstractmethod
    async def place_broker_order(self, request: BrokerOrderRequest) -> BrokerOrderResponse:
        """Place an order with the broker (idempotent via correlation table).

        In paper mode, delegates to PaperBroker.
        In live mode, requires all safety gates to pass.
        Timeout → marks correlation as UNCERTAIN → enters reconciliation.
        """

    @abstractmethod
    async def modify_broker_order(
        self,
        broker_order_id: str,
        internal_order_id: str,
        **kwargs: Any,
    ) -> BrokerOrderResponse:
        """Modify an existing order."""

    @abstractmethod
    async def cancel_broker_order(
        self,
        broker_order_id: str,
        internal_order_id: str,
        variety: str = "regular",
    ) -> bool:
        """Cancel a pending or open order.

        Cancellation is allowed even when the kill switch is active.
        """

    @abstractmethod
    async def get_broker_order(self, broker_order_id: str) -> Optional[BrokerOrderUpdate]:
        """Fetch a single order by broker order ID."""

    @abstractmethod
    async def get_order_book(self) -> List[BrokerOrderUpdate]:
        """Fetch the full order book for today."""

    @abstractmethod
    async def get_trades(self) -> List[BrokerTrade]:
        """Fetch today's trade book (executed fills)."""

    # ── Account & market data ─────────────────────────────────────────────

    @abstractmethod
    async def get_broker_positions(self) -> List[BrokerPosition]:
        """Fetch current positions from the broker."""

    @abstractmethod
    async def get_broker_holdings(self) -> List[BrokerHolding]:
        """Fetch delivery holdings from the broker."""

    @abstractmethod
    async def get_broker_margins(self) -> BrokerMargins:
        """Fetch account margin summary."""

    @abstractmethod
    async def get_broker_funds(self) -> BrokerFunds:
        """Fetch full account funds breakdown."""

    @abstractmethod
    async def get_broker_instruments(self, exchange: str) -> List[BrokerInstrument]:
        """Fetch instrument master for an exchange."""

    # ── Updates & health ─────────────────────────────────────────────────

    @abstractmethod
    async def subscribe_order_updates(self, callback: OrderUpdateCallback) -> None:
        """Subscribe to real-time order update feed via WebSocket.

        The callback receives normalised BrokerOrderUpdate objects.
        Duplicate events (same broker_order_id + exchange_timestamp) are
        suppressed before the callback is called.
        """

    @abstractmethod
    async def health_check(self) -> BrokerHealth:
        """Return a point-in-time health snapshot."""

    @abstractmethod
    def get_capabilities(self) -> BrokerCapabilities:
        """Return the static capabilities of this adapter."""

    # ── Optional lifecycle hooks (non-abstract, default no-op) ───────────

    def set_db_session(self, db_session: Any) -> None:
        """Wire a SQLAlchemy async session for DB-backed idempotency persistence.

        Default no-op.  Implementations that support DB-backed correlation
        tracking (e.g. ZerodhaAdapter) override this to pass the session
        through to their order gateway and reconciliation engine.
        """

    async def seed_correlations_from_db(self, db_session: Any = None) -> int:
        """Seed in-memory correlation cache from broker_order_correlations table.

        Called after restore_session() so idempotency survives restarts.
        Default no-op, returns 0.
        """
        return 0
