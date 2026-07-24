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
from src.brokers.exceptions import BrokerSessionExpiredError
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
        await self._ws_manager.stop()
        logger.info(
            "ZerodhaAdapter closed",
            extra={"event_type": "ZERODHA_ADAPTER_CLOSED"},
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
        """Place an order.  Kill switch enforced in OrderGateway."""
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
