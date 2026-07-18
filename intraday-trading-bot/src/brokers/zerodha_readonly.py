"""Zerodha read-only skeleton — no order execution ever."""

from decimal import Decimal
from typing import Any, Dict, List, Optional

from src.brokers.interface import BrokerInterface, OrderRequest, OrderResponse, Position, Margin
from src.core.exceptions import LiveModeBlockedError
from src.core.logging import logger


class ZerodhaReadOnly(BrokerInterface):
    """
    Read-only Zerodha connection skeleton.
    NEVER used for order placement, modification, or cancellation.
    Only implements read operations (positions, margins, quotes, instruments).
    """

    def __init__(self, api_key: Optional[str] = None, access_token: Optional[str] = None) -> None:
        self._api_key = api_key
        self._access_token = access_token
        logger.info(
            "ZerodhaReadOnly initialized",
            extra={"event_type": "ZERODHA_READONLY_INIT", "api_key_present": bool(api_key)},
        )

    async def place_order(self, order: OrderRequest) -> OrderResponse:
        """BLOCKED: Live execution structurally unavailable."""
        raise LiveModeBlockedError(
            "Zerodha order placement is permanently blocked. Use PaperBroker."
        )

    async def modify_order(self, order_id: str, **kwargs: Any) -> OrderResponse:
        """BLOCKED: Live execution structurally unavailable."""
        raise LiveModeBlockedError(
            "Zerodha order modification is permanently blocked. Use PaperBroker."
        )

    async def cancel_order(self, order_id: str) -> bool:
        """BLOCKED: Live execution structurally unavailable."""
        raise LiveModeBlockedError(
            "Zerodha order cancellation is permanently blocked. Use PaperBroker."
        )

    async def get_positions(self) -> List[Position]:
        """Read-only: Get positions from Zerodha (placeholder)."""
        logger.info("ZerodhaReadOnly.get_positions called (placeholder)")
        return []

    async def get_orders(self) -> List[Dict[str, Any]]:
        """Read-only: Get orders from Zerodha (placeholder)."""
        logger.info("ZerodhaReadOnly.get_orders called (placeholder)")
        return []

    async def get_margins(self) -> Margin:
        """Read-only: Get margins from Zerodha (placeholder)."""
        logger.info("ZerodhaReadOnly.get_margins called (placeholder)")
        return Margin(
            available_cash=Decimal("0"),
            used_margin=Decimal("0"),
            available_margin=Decimal("0"),
        )

    async def get_instruments(self, exchange: str) -> List[Dict[str, Any]]:
        """Read-only: Get instrument list (placeholder)."""
        logger.info(f"ZerodhaReadOnly.get_instruments called for {exchange} (placeholder)")
        return []

    async def get_quote(self, symbols: List[str]) -> Dict[str, Any]:
        """Read-only: Get quotes (placeholder)."""
        logger.info(f"ZerodhaReadOnly.get_quote called for {symbols} (placeholder)")
        return {}
