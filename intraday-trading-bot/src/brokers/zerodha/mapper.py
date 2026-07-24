"""RC-10D: Zerodha status and data mapper.

ZerodhaStatusMapper translates Zerodha raw status strings and order dicts
into broker-neutral contracts from src.brokers.contracts.

Rules:
  - Unknown Zerodha statuses map to BrokerOrderStatus.UNKNOWN (never crash)
  - Unknown statuses must be logged as warnings and persisted to broker_event_inbox
  - Out-of-order updates detected by exchange_timestamp comparison
  - Illegal state transitions (e.g. CANCELLED → COMPLETE) are rejected
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional, Set, Tuple

from src.brokers.contracts import (
    BrokerExchange,
    BrokerOrderStatus,
    BrokerOrderType,
    BrokerOrderUpdate,
    BrokerProduct,
    BrokerSide,
    BrokerTrade,
    BrokerValidity,
)
from src.core.logging import logger


# ---------------------------------------------------------------------------
# Zerodha → canonical status mapping
# Covers all known Zerodha order states as of API v3
# ---------------------------------------------------------------------------

_ZERODHA_STATUS_MAP: Dict[str, BrokerOrderStatus] = {
    # Standard open states
    "OPEN": BrokerOrderStatus.OPEN,
    "OPEN PENDING": BrokerOrderStatus.OPEN,
    # Validation
    "VALIDATION PENDING": BrokerOrderStatus.VALIDATION_PENDING,
    # Trigger
    "TRIGGER PENDING": BrokerOrderStatus.TRIGGER_PENDING,
    # Modification
    "MODIFY PENDING": BrokerOrderStatus.MODIFICATION_PENDING,
    "MODIFY VALIDATION PENDING": BrokerOrderStatus.MODIFICATION_PENDING,
    # Cancellation
    "CANCEL PENDING": BrokerOrderStatus.CANCELLATION_PENDING,
    # Partial fill
    "UPDATE": BrokerOrderStatus.PARTIALLY_FILLED,
    # Terminal states
    "COMPLETE": BrokerOrderStatus.COMPLETE,
    "CANCELLED": BrokerOrderStatus.CANCELLED,
    "REJECTED": BrokerOrderStatus.REJECTED,
    # AMO states
    "AMO REQ RECEIVED": BrokerOrderStatus.PENDING,
}

# Terminal states that cannot transition to anything else
_TERMINAL_STATES: Set[BrokerOrderStatus] = {
    BrokerOrderStatus.COMPLETE,
    BrokerOrderStatus.CANCELLED,
    BrokerOrderStatus.REJECTED,
}

# Allowed forward transitions from each state
# (empty set means no transitions allowed — terminal)
_ALLOWED_TRANSITIONS: Dict[BrokerOrderStatus, Set[BrokerOrderStatus]] = {
    BrokerOrderStatus.PENDING: {
        BrokerOrderStatus.VALIDATION_PENDING,
        BrokerOrderStatus.OPEN,
        BrokerOrderStatus.REJECTED,
        BrokerOrderStatus.CANCELLED,
    },
    BrokerOrderStatus.VALIDATION_PENDING: {
        BrokerOrderStatus.OPEN,
        BrokerOrderStatus.REJECTED,
        BrokerOrderStatus.CANCELLED,
    },
    BrokerOrderStatus.OPEN: {
        BrokerOrderStatus.PARTIALLY_FILLED,
        BrokerOrderStatus.COMPLETE,
        BrokerOrderStatus.CANCELLED,
        BrokerOrderStatus.REJECTED,
        BrokerOrderStatus.TRIGGER_PENDING,
        BrokerOrderStatus.MODIFICATION_PENDING,
        BrokerOrderStatus.CANCELLATION_PENDING,
    },
    BrokerOrderStatus.TRIGGER_PENDING: {
        BrokerOrderStatus.OPEN,
        BrokerOrderStatus.CANCELLED,
        BrokerOrderStatus.REJECTED,
    },
    BrokerOrderStatus.MODIFICATION_PENDING: {
        BrokerOrderStatus.OPEN,
        BrokerOrderStatus.CANCELLED,
        BrokerOrderStatus.REJECTED,
    },
    BrokerOrderStatus.CANCELLATION_PENDING: {
        BrokerOrderStatus.CANCELLED,
        BrokerOrderStatus.OPEN,  # cancellation failed
    },
    BrokerOrderStatus.PARTIALLY_FILLED: {
        BrokerOrderStatus.COMPLETE,
        BrokerOrderStatus.CANCELLED,
    },
    BrokerOrderStatus.COMPLETE: set(),
    BrokerOrderStatus.CANCELLED: set(),
    BrokerOrderStatus.REJECTED: set(),
    BrokerOrderStatus.UNKNOWN: set(),
}


class ZerodhaStatusMapper:
    """Stateless mapper: Zerodha raw API dicts → broker-neutral contracts."""

    # ── Status mapping ─────────────────────────────────────────────────────

    @staticmethod
    def map_status(raw_status: str) -> BrokerOrderStatus:
        """Map a raw Zerodha status string to BrokerOrderStatus.

        Unknown statuses return UNKNOWN (never crash).
        Callers are responsible for logging and persisting unknowns.
        """
        if not raw_status:
            return BrokerOrderStatus.UNKNOWN
        canonical = _ZERODHA_STATUS_MAP.get(raw_status.upper().strip())
        if canonical is None:
            logger.warning(
                "Unknown Zerodha order status encountered",
                extra={
                    "event_type": "BROKER_UNKNOWN_STATUS",
                    "raw_status": raw_status,
                },
            )
            return BrokerOrderStatus.UNKNOWN
        return canonical

    @staticmethod
    def is_terminal(status: BrokerOrderStatus) -> bool:
        """Return True if status is a terminal state."""
        return status in _TERMINAL_STATES

    @staticmethod
    def is_transition_allowed(
        from_status: BrokerOrderStatus,
        to_status: BrokerOrderStatus,
    ) -> bool:
        """Return True if transitioning from → to is a valid state machine move."""
        if from_status == to_status:
            return True  # idempotent update
        allowed = _ALLOWED_TRANSITIONS.get(from_status, set())
        return to_status in allowed

    # ── Order update mapping ───────────────────────────────────────────────

    @staticmethod
    def map_order_update(
        raw: Dict[str, Any],
        *,
        source: str = "websocket",
        paper_mode: bool = True,
    ) -> BrokerOrderUpdate:
        """Convert a raw Zerodha order dict to BrokerOrderUpdate."""

        def _dec(key: str, default: str = "0") -> Decimal:
            try:
                v = raw.get(key)
                if v is None or v == "":
                    return Decimal(default)
                return Decimal(str(v))
            except InvalidOperation:
                return Decimal(default)

        def _dt(key: str) -> Optional[datetime]:
            v = raw.get(key)
            if not v:
                return None
            if isinstance(v, datetime):
                return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
            try:
                # Zerodha typically returns "2026-07-24 09:15:00" strings
                dt = datetime.strptime(str(v), "%Y-%m-%d %H:%M:%S")
                return dt.replace(tzinfo=timezone(  # IST offset
                    __import__("datetime").timedelta(hours=5, minutes=30)
                ))
            except Exception:
                return None

        raw_side = str(raw.get("transaction_type", "BUY")).upper()
        side = BrokerSide.BUY if raw_side == "BUY" else BrokerSide.SELL

        raw_status = str(raw.get("status", ""))
        status = ZerodhaStatusMapper.map_status(raw_status)

        return BrokerOrderUpdate(
            broker_order_id=str(raw.get("order_id", "")),
            internal_order_id=raw.get("tag"),  # we store internal ID in tag
            exchange_order_id=raw.get("exchange_order_id"),
            trading_symbol=str(raw.get("tradingsymbol", "")),
            exchange=str(raw.get("exchange", "NSE")),
            transaction_type=side,
            status=status,
            quantity=_dec("quantity"),
            filled_quantity=_dec("filled_quantity"),
            pending_quantity=_dec("pending_quantity"),
            average_price=_dec("average_price") or None,
            price=_dec("price") or None,
            trigger_price=_dec("trigger_price") or None,
            rejected_reason=raw.get("status_message") or raw.get("rejected_reason"),
            exchange_timestamp=_dt("exchange_timestamp") or _dt("exchange_update_timestamp"),
            received_at=datetime.now(timezone.utc),
            source=source,
            paper_mode=paper_mode,
        )

    @staticmethod
    def map_trade(raw: Dict[str, Any], paper_mode: bool = True) -> BrokerTrade:
        """Convert a raw Zerodha trade dict to BrokerTrade."""
        def _dec(key: str) -> Decimal:
            try:
                v = raw.get(key, "0")
                return Decimal(str(v)) if v else Decimal("0")
            except InvalidOperation:
                return Decimal("0")

        def _dt(key: str) -> datetime:
            v = raw.get(key)
            if isinstance(v, datetime):
                return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
            if v:
                try:
                    dt = datetime.strptime(str(v), "%Y-%m-%d %H:%M:%S")
                    return dt.replace(tzinfo=timezone.utc)
                except Exception:
                    pass
            return datetime.now(timezone.utc)

        raw_side = str(raw.get("transaction_type", "BUY")).upper()
        side = BrokerSide.BUY if raw_side == "BUY" else BrokerSide.SELL

        return BrokerTrade(
            trade_id=str(raw.get("trade_id", "")),
            broker_order_id=str(raw.get("order_id", "")),
            exchange_order_id=raw.get("exchange_order_id"),
            trading_symbol=str(raw.get("tradingsymbol", "")),
            exchange=str(raw.get("exchange", "NSE")),
            transaction_type=side,
            quantity=_dec("quantity"),
            price=_dec("average_price") or _dec("price"),
            fill_timestamp=_dt("fill_timestamp") or _dt("exchange_timestamp"),
            product=str(raw.get("product", "MIS")),
        )

    @staticmethod
    def map_order_type(raw: str) -> BrokerOrderType:
        """Map Zerodha order type string to BrokerOrderType."""
        mapping = {
            "MARKET": BrokerOrderType.MARKET,
            "LIMIT": BrokerOrderType.LIMIT,
            "SL": BrokerOrderType.SL,
            "SL-M": BrokerOrderType.SL_M,
        }
        return mapping.get(raw.upper(), BrokerOrderType.MARKET)

    @staticmethod
    def to_zerodha_order_params(request) -> Dict[str, Any]:
        """Convert a BrokerOrderRequest to Zerodha KiteConnect kwargs.

        Returns a dict safe to pass to kite.place_order(**params).
        """
        from src.brokers.contracts import BrokerOrderRequest

        params: Dict[str, Any] = {
            "variety": request.variety.value,
            "exchange": request.exchange.value,
            "tradingsymbol": request.trading_symbol,
            "transaction_type": request.transaction_type.value,
            "quantity": int(request.quantity),
            "order_type": (
                "SL-M" if request.order_type.value == "SL-M" else request.order_type.value
            ),
            "product": request.product.value,
            "validity": request.validity.value,
            "tag": request.tag or request.internal_order_id[:20],  # Zerodha tag max 20 chars
        }
        if request.price is not None and request.price > 0:
            params["price"] = float(request.price)
        if request.trigger_price is not None and request.trigger_price > 0:
            params["trigger_price"] = float(request.trigger_price)
        if request.disclosed_quantity is not None and request.disclosed_quantity > 0:
            params["disclosed_quantity"] = int(request.disclosed_quantity)
        return params
