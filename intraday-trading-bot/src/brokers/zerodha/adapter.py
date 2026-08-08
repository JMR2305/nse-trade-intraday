"""RC-10D: Full Zerodha adapter implementing BrokerAdapter.

ZerodhaAdapter composes all sub-components:
  - ZerodhaSessionManager   (authentication)
  - ZerodhaHttpClient       (REST with rate limiting)
  - ZerodhaOrderGateway     (orders)
  - ZerodhaAccountGateway   (account data)
  - ZerodhaMarketGateway    (market data)
  - ZerodhaWebSocketManager (real-time updates)
  - InstrumentSyncEngine    (master download)
  - ReconciliationEngine    (reconciliation)
  - BrokerHealthTracker     (health)
  - BrokerRateLimiter       (rate limits)

Paper mode (default): delegates to PaperBroker.  No Zerodha calls.
Live mode: active when all 5 gates in is_live_order_allowed() pass.  The startup
lifespan in main.py validates the session before accepting requests.  The order
router (_create_broker) injects this adapter when live gates are satisfied.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, List, Optional

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
from src.brokers.exceptions import BrokerLiveModeError, BrokerSessionExpiredError
from src.brokers.interface import BrokerAdapter, OrderUpdateCallback
from src.brokers.paper_broker import PaperBroker
from src.brokers.zerodha.account_gateway import ZerodhaAccountGateway
from src.brokers.zerodha.authentication import ZerodhaSessionManager
from src.brokers.zerodha.client import ZerodhaHttpClient
from src.brokers.zerodha.config import ZerodhaBrokerConfig
from src.brokers.zerodha.health import BrokerHealthTracker
from src.brokers.zerodha.instrument_sync import InstrumentSyncEngine
from src.brokers.zerodha.market_gateway import ZerodhaMarketGateway
from src.brokers.zerodha.order_gateway import ZerodhaOrderGateway
from src.brokers.zerodha.rate_limiter import BrokerRateLimiter
from src.brokers.zerodha.reconciliation import ReconciliationEngine
from src.brokers.zerodha.websocket import ZerodhaWebSocketManager
from src.core.logging import logger


class ZerodhaAdapter(BrokerAdapter):
    """Full Zerodha adapter implementing the BrokerAdapter protocol.

    In paper mode (default): all order operations route to PaperBroker.
    In live mode: routes to Zerodha API with all safety gates enforced.
    """

    def __init__(self, config: ZerodhaBrokerConfig) -> None:
        self._config = config
        self._paper_broker = PaperBroker()

        # When True, all new order placements are forced to paper mode because
        # the Zerodha access token has expired or is about to expire.  Set by
        # check_token_expiry(); cleared when a fresh session is established.
        self._session_expired_paper_fallback: bool = False

        # Background expiry monitor — created in initialize_live_session()
        self._expiry_monitor: Optional[Any] = None

        # ── Core components ────────────────────────────────────────────────
        self._health_tracker = BrokerHealthTracker(paper_mode=config.paper_trading)
        self._rate_limiter = BrokerRateLimiter(
            order_rps=config.rate_limits.order_api_rps,
            quote_rps=config.rate_limits.quote_api_rps,
            account_rps=config.rate_limits.account_api_rps,
            historical_rps=config.rate_limits.historical_api_rps,
        )
        self._session_manager = ZerodhaSessionManager(config)

        # HTTP client — populated after authenticate()
        self._http_client: Optional[ZerodhaHttpClient] = None

        # ── Gateways (constructed lazily after auth in live mode) ──────────
        self._order_gateway = ZerodhaOrderGateway(
            config=config,
            health_tracker=self._health_tracker,
            paper_broker=self._paper_broker,
            client=None,  # set after auth
        )
        self._account_gateway = ZerodhaAccountGateway(
            config=config,
            health_tracker=self._health_tracker,
            paper_broker=self._paper_broker,
            client=None,
        )
        self._market_gateway = ZerodhaMarketGateway(
            config=config,
            health_tracker=self._health_tracker,
            paper_broker=self._paper_broker,
            client=None,
        )

        self._ws_manager = ZerodhaWebSocketManager(
            config=config,
            health_tracker=self._health_tracker,
            on_reconcile=self._trigger_reconciliation,
        )

        self._reconciler = ReconciliationEngine(
            config=config,
            health_tracker=self._health_tracker,
            order_gateway=self._order_gateway,
        )

        self._instrument_sync = InstrumentSyncEngine(
            config=config,
            market_gateway=self._market_gateway,
        )

        logger.info(
            "ZerodhaAdapter initialised",
            extra={
                "event_type": "ZERODHA_ADAPTER_INIT",
                **config.log_safe(),
            },
        )

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def authenticate(self) -> BrokerSession:
        """Authenticate with Zerodha.  In paper mode, returns a mock session."""
        if self._config.paper_trading:
            session = BrokerSession(
                user_id="paper_user",
                broker_name="zerodha_paper",
                created_at=datetime.now(timezone.utc),
                is_valid=True,
                paper_mode=True,
            )
            await self._health_tracker.mark_authenticated()
            return session

        session = self._session_manager.exchange_request_token()
        await self._health_tracker.mark_authenticated()
        await self._health_tracker.clear_token_expiry_warning()
        self._session_expired_paper_fallback = False
        self._wire_live_client()
        return session

    async def initialize_live_session(self) -> BrokerSession:
        """Restore the access token, probe Zerodha, and mark the adapter ready.

        Call once at startup (in the FastAPI lifespan) before registering the
        adapter for request handling.  After this call:
          - kite HTTP client is wired into all gateways
          - health tracker reports authenticated + session_valid + rest_reachable
          - ``is_ready()`` returns True

        Raises
        ------
        BrokerSessionExpiredError
            If ZERODHA_ACCESS_TOKEN is missing or expired.
        ConfigurationError
            If the live probe (validate_session) returns False.
        """
        from src.core.exceptions import ConfigurationError

        session = await self.restore_session()  # wires kite, marks authenticated
        if not await self.validate_session():
            raise ConfigurationError(
                "LIVE mode: Zerodha session probe failed after restore — "
                "access token may be expired. Re-run the OAuth flow."
            )
        await self._health_tracker.mark_rest_success()  # REST confirmed reachable

        # Start the background expiry monitor so operators get proactive warnings
        from src.brokers.zerodha.expiry_monitor import TokenExpiryMonitor
        if self._expiry_monitor is None:
            self._expiry_monitor = TokenExpiryMonitor(
                self,
                warning_lead_minutes=self._config.token_expiry_warning_lead_minutes,
            )
        self._expiry_monitor.start()

        logger.info(
            "LIVE mode: adapter initialised and session validated",
            extra={"event_type": "LIVE_MODE_ADAPTER_READY", **self._config.log_safe()},
        )
        return session

    async def restore_session(self) -> BrokerSession:
        """Restore from persisted access token.  In paper mode: mock session."""
        if self._config.paper_trading:
            return await self.authenticate()

        try:
            session = self._session_manager.restore_session()
            await self._health_tracker.mark_authenticated()
            await self._health_tracker.clear_token_expiry_warning()
            self._session_expired_paper_fallback = False
            self._wire_live_client()
            return session
        except BrokerSessionExpiredError:
            await self._health_tracker.mark_session_invalid("Token expired or not set")
            raise

    async def validate_session(self) -> bool:
        """Validate the current session.  Paper mode: always True."""
        if self._config.paper_trading:
            return True
        return self._session_manager.validate_session()

    async def close(self) -> None:
        """Release all resources."""
        if self._expiry_monitor is not None:
            await self._expiry_monitor.stop()
        await self._ws_manager.stop()
        logger.info(
            "ZerodhaAdapter closed",
            extra={"event_type": "ZERODHA_ADAPTER_CLOSED"},
        )

    # ── Token expiry ───────────────────────────────────────────────────────

    async def check_token_expiry(
        self,
        warning_lead_minutes: int = 30,
    ) -> dict:
        """Proactively check Zerodha token expiry and degrade gracefully.

        Call this periodically (e.g. from TokenExpiryMonitor every 60 s) or
        ad-hoc before placing a batch of orders.

        Behaviour
        ---------
        - **Paper mode**: returns immediately with ``{"action": "none"}``.
        - **Expiring soon** (within ``warning_lead_minutes``): logs CRITICAL,
          sends a best-effort alert, sets ``_session_expired_paper_fallback``
          so new orders route to the paper broker, marks health tracker
          session invalid.
        - **Already expired**: same as *expiring soon* plus marks as expired.
        - **Healthy**: updates ``token_expiry_minutes`` in the health tracker
          and returns ``{"action": "none"}``.

        Returns
        -------
        dict with keys:
          - ``action``: ``"none"`` | ``"warning_alert"`` | ``"expired_degraded"``
          - ``minutes_remaining``: float | None
        """
        if self._config.paper_trading:
            return {"action": "none", "minutes_remaining": None}

        is_expiring_soon, is_expired, mins = (
            self._session_manager.check_expiry_warning(warning_lead_minutes)
        )

        if not (is_expiring_soon or is_expired):
            # Healthy session: only update the countdown, never set warning flag
            if mins is not None:
                await self._health_tracker.update_token_expiry_minutes(mins)
            return {"action": "none", "minutes_remaining": mins}

        # Token is expiring soon or already expired — set warning state
        if mins is not None:
            await self._health_tracker.mark_token_expiry_warning(
                mins, is_expired=is_expired
            )

        action = "expired_degraded" if is_expired else "warning_alert"
        self._session_expired_paper_fallback = True

        mins_label = f"{mins:.1f}" if mins is not None else "unknown"
        if is_expired:
            msg = (
                "CRITICAL: Zerodha access token has EXPIRED. "
                "New orders are being routed to paper mode. "
                "Re-authenticate immediately via the daily OAuth flow."
            )
        else:
            msg = (
                f"WARNING: Zerodha access token expires in {mins_label} minutes "
                f"(threshold: {warning_lead_minutes} min). "
                "New orders will be routed to paper mode at expiry. "
                "Re-authenticate before the token expires."
            )

        logger.critical(
            msg,
            extra={
                "event_type": "BROKER_TOKEN_EXPIRY_WARNING",
                "action": action,
                "minutes_remaining": mins,
                "warning_lead_minutes": warning_lead_minutes,
                **self._config.log_safe(),
            },
        )

        # Best-effort alert — must never raise
        await self._send_expiry_alert(
            is_expired=is_expired,
            minutes_remaining=mins,
            warning_lead_minutes=warning_lead_minutes,
        )

        return {"action": action, "minutes_remaining": mins}

    async def _send_expiry_alert(
        self,
        *,
        is_expired: bool,
        minutes_remaining: Optional[float],
        warning_lead_minutes: int,
    ) -> None:
        """Send a best-effort email/push notification on token expiry. Never raises."""
        try:
            import sys
            import os
            # Locate email_alerts module — path differs by execution environment
            _python_src = os.path.join(
                os.path.dirname(__file__), "..", "..", "..", "src", "python"
            )
            if _python_src not in sys.path:
                sys.path.insert(0, _python_src)

            from email_alerts import _log, _deliver, _from_address  # type: ignore[import]

            mins_label = (
                f"{minutes_remaining:.0f}" if minutes_remaining is not None else "?"
            )
            if is_expired:
                subject = "[NSE Trading] CRITICAL: Zerodha token EXPIRED — orders in paper mode"
                text = (
                    "The Zerodha access token has expired.\n\n"
                    "All new order placements have been automatically switched to paper mode "
                    "to prevent silent order loss.\n\n"
                    "ACTION REQUIRED: Complete the daily OAuth2 re-authentication:\n"
                    "  1. Call GET /broker/auth/login-url to get the login URL\n"
                    "  2. Complete the browser login\n"
                    "  3. POST /broker/auth/exchange with the request_token\n"
                    "  4. Set ZERODHA_ACCESS_TOKEN to the returned access token\n\n"
                    "See docs/RC10D_Zerodha_Authentication.md for the full recovery runbook."
                )
            else:
                subject = (
                    f"[NSE Trading] WARNING: Zerodha token expires in {mins_label} min"
                )
                text = (
                    f"The Zerodha access token expires in approximately {mins_label} minutes.\n\n"
                    f"When expiry occurs (threshold: {warning_lead_minutes} min), "
                    "new orders will automatically switch to paper mode.\n\n"
                    "ACTION REQUIRED: Re-authenticate before the token expires.\n"
                    "See docs/RC10D_Zerodha_Authentication.md for the recovery runbook."
                )

            try:
                import phase20_store as store  # type: ignore[import]
                settings = store.get_settings()
                to = str(settings.get("email_alert_address") or "").strip()
                if to and "@" in to:
                    _deliver(to, subject, text)
            except Exception as mail_exc:
                _log(f"token expiry email failed: {type(mail_exc).__name__}: {mail_exc}")

        except Exception as exc:  # noqa: BLE001
            logger.debug(
                f"_send_expiry_alert: non-critical failure ({type(exc).__name__}): {exc}",
                extra={"event_type": "BROKER_EXPIRY_ALERT_FAILED"},
            )

    # ── DB session lifecycle ───────────────────────────────────────────────

    def set_db_session(self, db_session) -> None:
        """Wire a SQLAlchemy async session into all components that need it.

        Called by ExecutionService.__init__() immediately after injection.
        """
        self._order_gateway.set_db_session(db_session)
        self._reconciler.set_db_session(db_session)

    async def seed_correlations_from_db(self, db_session=None) -> int:
        """Seed in-memory correlation cache from broker_order_correlations.

        Called after restore_session() so idempotency survives restarts.
        """
        return await self._order_gateway.seed_from_db(db_session)

    # ── Orders ─────────────────────────────────────────────────────────────

    async def place_broker_order(self, request: BrokerOrderRequest) -> BrokerOrderResponse:
        """Place an order.  Kill switch enforced in OrderGateway.

        When the session has been degraded to paper mode due to token expiry,
        the order is routed directly to ``_place_paper_order()`` inside the
        order gateway, bypassing the live-mode config gates entirely.  This
        guarantees a deterministic paper fill regardless of how
        ``_config.paper_trading`` or ``is_live_order_allowed()`` are set.
        """
        if self._session_expired_paper_fallback and not self._config.paper_trading:
            logger.warning(
                "Order routed to paper broker: session expired paper fallback is active. "
                "Re-authenticate to restore live order routing.",
                extra={
                    "event_type": "BROKER_ORDER_PAPER_FALLBACK",
                    "internal_order_id": request.internal_order_id,
                },
            )
            # Call the public fallback path — kill-switch and idempotency guards
            # still run; only live-mode config gates are bypassed.
            return await self._order_gateway.place_order_paper_fallback(
                request, reason="token_expired"
            )
        return await self._order_gateway.place_order(request)

    async def modify_broker_order(
        self,
        broker_order_id: str,
        internal_order_id: str,
        **kwargs: Any,
    ) -> BrokerOrderResponse:
        return await self._order_gateway.modify_order(
            broker_order_id, internal_order_id, **kwargs
        )

    async def cancel_broker_order(
        self,
        broker_order_id: str,
        internal_order_id: str,
        variety: str = "regular",
    ) -> bool:
        return await self._order_gateway.cancel_order(
            broker_order_id, internal_order_id, variety
        )

    async def get_broker_order(self, broker_order_id: str) -> Optional[BrokerOrderUpdate]:
        return await self._order_gateway.get_order(broker_order_id)

    async def get_order_book(self) -> List[BrokerOrderUpdate]:
        return await self._order_gateway.get_order_book()

    async def get_trades(self) -> List[BrokerTrade]:
        return await self._order_gateway.get_trades()

    # ── Account / market ───────────────────────────────────────────────────

    async def get_broker_positions(self) -> List[BrokerPosition]:
        return await self._account_gateway.get_positions()

    async def get_broker_holdings(self) -> List[BrokerHolding]:
        return await self._account_gateway.get_holdings()

    async def get_broker_margins(self) -> BrokerMargins:
        return await self._account_gateway.get_margins()

    async def get_broker_funds(self) -> BrokerFunds:
        return await self._account_gateway.get_funds()

    async def get_broker_instruments(self, exchange: str) -> List[BrokerInstrument]:
        return await self._market_gateway.get_instruments(exchange)

    # ── Updates & health ───────────────────────────────────────────────────

    async def subscribe_order_updates(self, callback: OrderUpdateCallback) -> None:
        """Register a callback for real-time order updates."""
        self._ws_manager.subscribe(callback)
        if self._config.paper_trading:
            return  # WebSocket not started in paper mode
        # Source the access_token from the live Kite client (set after auth),
        # not from config (which never stores the token value).
        access_token = ""
        kite = self._session_manager.get_kite()
        if kite is not None:
            # kiteconnect.KiteConnect stores the token on the instance after
            # set_access_token() is called during exchange_request_token()
            access_token = getattr(kite, "access_token", "") or ""
        if not access_token:
            logger.warning(
                "subscribe_order_updates called without a valid access_token — "
                "WebSocket will not connect.  Authenticate first.",
                extra={"event_type": "BROKER_WS_NO_TOKEN"},
            )
            return
        await self._ws_manager.start(access_token)

    async def health_check(self) -> BrokerHealth:
        """Return the current health snapshot."""
        return self._health_tracker.get_health()

    def get_capabilities(self) -> BrokerCapabilities:
        """Return adapter capabilities."""
        return BrokerCapabilities(
            broker_name="zerodha",
            supports_live_orders=not self._config.paper_trading,
            supports_websocket=True,
            supports_historical_data=False,
            supports_options=True,
            supports_futures=True,
            paper_mode_only=self._config.paper_trading,
            max_orders_per_second=self._config.rate_limits.order_api_rps,
            supported_exchanges=["NSE", "BSE", "NFO"],
            supported_products=["MIS", "CNC", "NRML"],
            supported_order_types=["MARKET", "LIMIT", "SL", "SL-M"],
        )

    # ── Private helpers ────────────────────────────────────────────────────

    def _wire_live_client(self) -> None:
        """Wire the HTTP client into all gateways after successful auth."""
        kite = self._session_manager.get_kite()
        if kite is None:
            return

        self._http_client = ZerodhaHttpClient(
            kite,
            self._rate_limiter,
            timeout_seconds=self._config.timeout_seconds,
            maximum_retries=self._config.maximum_retries,
            retry_backoff_seconds=self._config.retry_backoff_seconds,
        )
        # Re-wire gateways
        self._order_gateway._client = self._http_client
        self._account_gateway._client = self._http_client
        self._market_gateway._client = self._http_client

    async def _trigger_reconciliation(self) -> None:
        """Trigger a post-reconnect reconciliation run."""
        try:
            await self._reconciler.run(trigger="post_reconnect")
        except Exception as exc:
            logger.warning(
                f"Reconciliation trigger failed: {type(exc).__name__}"
            )
