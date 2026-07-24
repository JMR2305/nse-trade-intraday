"""RC-10D: Zerodha WebSocket order update manager.

ZerodhaWebSocketManager subscribes to the Zerodha Kite WebSocket (KiteTicker)
for real-time order status updates.

Design rules:
  - Normalises raw ticks to BrokerOrderUpdate via ZerodhaStatusMapper
  - Deduplicates by (broker_order_id, exchange_timestamp)
  - Detects out-of-order updates; rejects illegal state transitions
  - Reconnects with back-off via ReconnectManager
  - Triggers reconciliation after each reconnect
  - Updates BrokerHealthTracker on connect/disconnect
  - All Zerodha exceptions wrapped in domain exceptions

In paper mode: no-op (returns immediately, callback never called).
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, Optional, Set, Tuple

from src.brokers.contracts import BrokerOrderStatus, BrokerOrderUpdate
from src.brokers.exceptions import BrokerConnectionError
from src.brokers.zerodha.config import ZerodhaBrokerConfig
from src.brokers.zerodha.health import BrokerHealthTracker
from src.brokers.zerodha.mapper import ZerodhaStatusMapper
from src.brokers.zerodha.reconnect import ReconnectManager
from src.core.logging import logger


OrderUpdateCallback = Callable[[BrokerOrderUpdate], Coroutine[Any, Any, None]]


class ZerodhaWebSocketManager:
    """Manages the KiteTicker WebSocket connection for order feed.

    Parameters
    ----------
    config:
        ZerodhaBrokerConfig — WebSocket only starts in live mode.
    api_key:
        Zerodha API key (read from config; not stored separately).
    access_token:
        Current session access token (may change on re-auth).
    health_tracker:
        BrokerHealthTracker — updated on connect/disconnect.
    on_reconcile:
        Async callback invoked after each reconnect to trigger reconciliation.
    """

    def __init__(
        self,
        config: ZerodhaBrokerConfig,
        health_tracker: BrokerHealthTracker,
        *,
        on_reconcile: Optional[Callable[[], Coroutine[Any, Any, None]]] = None,
    ) -> None:
        self._config = config
        self._health = health_tracker
        self._on_reconcile = on_reconcile
        self._mapper = ZerodhaStatusMapper()

        # Active callbacks registered by subscribers
        self._callbacks: list[OrderUpdateCallback] = []

        # Deduplication: (broker_order_id, exchange_timestamp_iso) → True
        self._seen: Set[Tuple[str, str]] = set()
        # Last known status per broker_order_id for transition validation
        self._last_status: Dict[str, BrokerOrderStatus] = {}

        self._ticker = None  # KiteTicker instance
        self._reconnect_manager: Optional[ReconnectManager] = None
        self._running = False

    # ── Public API ─────────────────────────────────────────────────────────

    async def start(self, access_token: str) -> None:
        """Start the WebSocket connection.

        In paper mode: no-op.
        """
        if self._config.paper_trading:
            logger.debug("WebSocket: paper mode — skipping KiteTicker start")
            return

        if not self._config.api_key or not access_token:
            logger.warning(
                "WebSocket: missing api_key or access_token — skipping",
                extra={"event_type": "BROKER_WS_NO_CREDENTIALS"},
            )
            return

        self._running = True
        self._reconnect_manager = ReconnectManager(
            name="zerodha_websocket",
            reconnect_fn=lambda: self._connect(access_token),
            on_reconnect_success=self._on_reconnect_success,
            max_attempts=self._config.websocket_reconnect_max_attempts,
            base_backoff=self._config.websocket_reconnect_backoff_seconds,
        )

        # Initial connect attempt
        try:
            await self._connect(access_token)
        except Exception as exc:
            logger.warning(
                f"WebSocket: initial connect failed — starting reconnect manager: {type(exc).__name__}",
                extra={"event_type": "BROKER_WS_INITIAL_CONNECT_FAILED"},
            )
            self._reconnect_manager.start()

    async def stop(self) -> None:
        """Disconnect and stop the WebSocket."""
        self._running = False
        if self._reconnect_manager:
            await self._reconnect_manager.stop()
        if self._ticker:
            try:
                self._ticker.stop()
            except Exception:
                pass
            self._ticker = None
        await self._health.mark_websocket_disconnected()
        logger.info(
            "WebSocket: stopped",
            extra={"event_type": "BROKER_WS_STOPPED"},
        )

    def subscribe(self, callback: OrderUpdateCallback) -> None:
        """Register an async callback for order updates."""
        self._callbacks.append(callback)

    # ── Private helpers ────────────────────────────────────────────────────

    async def _connect(self, access_token: str) -> None:
        """Open the KiteTicker WebSocket and register handlers."""
        try:
            from kiteconnect import KiteTicker
        except ImportError:
            raise BrokerConnectionError(
                "kiteconnect not installed — cannot start WebSocket"
            )

        ticker = KiteTicker(
            api_key=self._config.api_key,
            access_token=access_token,
        )
        self._ticker = ticker

        def _on_connect(ws, response):
            asyncio.get_event_loop().call_soon_threadsafe(
                asyncio.ensure_future,
                self._handle_connect(),
            )

        def _on_close(ws, code, reason):
            asyncio.get_event_loop().call_soon_threadsafe(
                asyncio.ensure_future,
                self._handle_close(code, str(reason)),
            )

        def _on_message(ws, payload, is_binary):
            if not is_binary:
                asyncio.get_event_loop().call_soon_threadsafe(
                    asyncio.ensure_future,
                    self._handle_message(payload),
                )

        def _on_error(ws, code, reason):
            logger.warning(
                f"WebSocket error: {code} — {reason}",
                extra={"event_type": "BROKER_WS_ERROR", "code": code},
            )

        ticker.on_connect = _on_connect
        ticker.on_close = _on_close
        ticker.on_message = _on_message
        ticker.on_error = _on_error

        # KiteTicker.connect() is synchronous; run in thread pool
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: ticker.connect(threaded=True))

        logger.info(
            "WebSocket: connected",
            extra={"event_type": "BROKER_WS_CONNECTED"},
        )

    async def _handle_connect(self) -> None:
        await self._health.mark_websocket_connected()
        logger.info("WebSocket: on_connect", extra={"event_type": "BROKER_WS_ON_CONNECT"})

    async def _handle_close(self, code: Any, reason: str) -> None:
        await self._health.mark_websocket_disconnected()
        logger.warning(
            f"WebSocket: closed (code={code}, reason={reason!r})",
            extra={"event_type": "BROKER_WS_CLOSED", "code": code},
        )
        if self._running and self._reconnect_manager:
            self._reconnect_manager.start()

    async def _handle_message(self, payload: Any) -> None:
        """Process an incoming order update message."""
        await self._health.mark_broker_event()

        try:
            if isinstance(payload, (bytes, bytearray)):
                payload = payload.decode("utf-8")
            raw = json.loads(payload) if isinstance(payload, str) else payload
        except Exception:
            return

        # Zerodha sends order updates as JSON with "type": "order"
        if isinstance(raw, dict) and raw.get("type") == "order":
            order_data = raw.get("data", raw)
            await self._dispatch_update(order_data)

    async def _dispatch_update(self, raw: dict) -> None:
        """Normalise, deduplicate, validate, and dispatch one order update."""
        try:
            update = self._mapper.map_order_update(
                raw, source="websocket", paper_mode=False
            )
        except Exception as exc:
            logger.warning(
                f"Failed to map WebSocket order update: {exc}",
                extra={"event_type": "BROKER_WS_MAP_ERROR"},
            )
            return

        # ── Deduplication ──────────────────────────────────────────────────
        ts_key = (
            update.exchange_timestamp.isoformat()
            if update.exchange_timestamp
            else datetime.now(timezone.utc).isoformat()
        )
        dedup_key = (update.broker_order_id, ts_key)
        if dedup_key in self._seen:
            logger.debug(
                f"WebSocket: duplicate update suppressed for {update.broker_order_id}",
                extra={"event_type": "BROKER_WS_DUPLICATE"},
            )
            return
        self._seen.add(dedup_key)

        # Prevent unbounded growth
        if len(self._seen) > 10000:
            self._seen = set(list(self._seen)[-5000:])

        # ── State transition validation ────────────────────────────────────
        prev_status = self._last_status.get(update.broker_order_id)
        if prev_status is not None:
            if not self._mapper.is_transition_allowed(prev_status, update.status):
                logger.warning(
                    f"Illegal state transition {prev_status} → {update.status} "
                    f"for {update.broker_order_id} — rejected",
                    extra={
                        "event_type": "BROKER_WS_ILLEGAL_TRANSITION",
                        "broker_order_id": update.broker_order_id,
                        "from_status": prev_status.value,
                        "to_status": update.status.value,
                    },
                )
                return

        self._last_status[update.broker_order_id] = update.status

        # ── Dispatch ───────────────────────────────────────────────────────
        for callback in self._callbacks:
            try:
                await callback(update)
            except Exception as exc:
                logger.error(
                    f"WebSocket callback error: {type(exc).__name__}",
                    extra={"event_type": "BROKER_WS_CALLBACK_ERROR"},
                )

    async def _on_reconnect_success(self) -> None:
        """Trigger reconciliation after a successful reconnect."""
        logger.info(
            "WebSocket: post-reconnect reconciliation triggered",
            extra={"event_type": "BROKER_WS_POST_RECONNECT_RECON"},
        )
        if self._on_reconcile:
            try:
                await self._on_reconcile()
            except Exception as exc:
                logger.warning(
                    f"Post-reconnect reconciliation failed: {type(exc).__name__}"
                )
