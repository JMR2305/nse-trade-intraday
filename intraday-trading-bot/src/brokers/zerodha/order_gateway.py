"""RC-10D: Zerodha order gateway.

ZerodhaOrderGateway provides idempotent order placement, modification,
and cancellation.  It enforces all safety gates before touching Zerodha.

Safety gates before any live order:
  1. kill_switch_manager.state.can_place_orders() is True
  2. config.paper_trading is False
  3. config.live_trading_enabled is True
  4. config.enabled is True
  5. Health tracker reports session_valid and rest_reachable

Paper mode routes to PaperBroker.
All placement timeouts mark the correlation UNCERTAIN and enter reconciliation.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from src.brokers.contracts import (
    BrokerOrderRequest,
    BrokerOrderResponse,
    BrokerOrderStatus,
    BrokerOrderUpdate,
    BrokerTrade,
    CorrelationStatus,
)
from src.brokers.exceptions import (
    BrokerDuplicateOrderError,
    BrokerKillSwitchError,
    BrokerLiveModeError,
    BrokerOrderNotFoundError,
    BrokerTimeoutError,
)
from src.brokers.zerodha.config import ZerodhaBrokerConfig
from src.brokers.zerodha.health import BrokerHealthTracker
from src.brokers.zerodha.mapper import ZerodhaStatusMapper
from src.core.logging import logger

# Lazy import of ORM model to avoid circular imports at module level
_BrokerOrderCorrelation = None


def _get_correlation_model():
    global _BrokerOrderCorrelation
    if _BrokerOrderCorrelation is None:
        from src.database.broker_models import BrokerOrderCorrelation
        _BrokerOrderCorrelation = BrokerOrderCorrelation
    return _BrokerOrderCorrelation


class ZerodhaOrderGateway:
    """Zerodha order gateway — routes to paper or live depending on config.

    Parameters
    ----------
    config:
        ZerodhaBrokerConfig (paper_trading=True by default).
    client:
        ZerodhaHttpClient for live REST calls (may be None in paper mode).
    health_tracker:
        BrokerHealthTracker — checked before every live order.
    paper_broker:
        PaperBroker instance — used in paper mode and as final fallback.
    correlation_store:
        Optional in-memory dict for correlation tracking (DB is source of truth).
    """

    def __init__(
        self,
        config: ZerodhaBrokerConfig,
        health_tracker: BrokerHealthTracker,
        paper_broker,
        client=None,
    ) -> None:
        self._config = config
        self._health = health_tracker
        self._paper_broker = paper_broker
        self._client = client
        self._mapper = ZerodhaStatusMapper()
        # In-memory correlation cache: idempotency_key → status
        # This is seeded from DB on startup via seed_from_db().
        self._correlations: Dict[str, str] = {}
        # Optional DB session — set via set_db_session() after gateway creation
        self._db_session = None

    # ── DB-backed idempotency ──────────────────────────────────────────────

    def set_db_session(self, db_session) -> None:
        """Wire a SQLAlchemy async session for correlation persistence."""
        self._db_session = db_session

    async def seed_from_db(self, db_session=None) -> int:
        """Load non-terminal correlations from broker_order_correlations table.

        Call on startup / session restore so in-memory cache survives restarts.
        Returns the number of rows loaded.
        """
        session = db_session or self._db_session
        if session is None:
            return 0
        try:
            from sqlalchemy import select, text
            Model = _get_correlation_model()
            # Load all non-terminal rows from the last 7 days
            stmt = select(Model.idempotency_key, Model.status).where(
                Model.status.in_(["PENDING", "SUBMITTED", "UNCERTAIN", "CONFIRMED"])
            )
            result = await session.execute(stmt)
            rows = result.fetchall()
            for row in rows:
                self._correlations[row.idempotency_key] = row.status
            logger.info(
                f"Seeded {len(rows)} correlations from DB",
                extra={
                    "event_type": "BROKER_CORRELATIONS_SEEDED",
                    "count": len(rows),
                },
            )
            return len(rows)
        except Exception as exc:
            logger.warning(
                f"Failed to seed correlations from DB: {type(exc).__name__}",
                extra={"event_type": "BROKER_CORRELATIONS_SEED_FAILED"},
            )
            return 0

    async def _persist_correlation(
        self,
        *,
        idempotency_key: str,
        internal_order_id: str,
        status: str,
        broker_order_id: Optional[str] = None,
        trading_symbol: Optional[str] = None,
        exchange: Optional[str] = None,
        paper_mode: bool = True,
        error_message: Optional[str] = None,
    ) -> None:
        """Upsert a correlation row in broker_order_correlations.

        Uses PostgreSQL INSERT … ON CONFLICT DO UPDATE for idempotency.
        Silently no-ops if no DB session is available.
        """
        session = self._db_session
        if session is None:
            return
        try:
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            Model = _get_correlation_model()
            now = datetime.now(timezone.utc)
            stmt = pg_insert(Model.__table__).values(
                idempotency_key=idempotency_key,
                internal_order_id=internal_order_id,
                broker_order_id=broker_order_id,
                status=status,
                trading_symbol=trading_symbol,
                exchange=exchange,
                paper_mode=paper_mode,
                error_message=error_message,
                created_at=now,
                updated_at=now,
            ).on_conflict_do_update(
                index_elements=["idempotency_key"],
                set_={
                    "status": status,
                    "broker_order_id": broker_order_id,
                    "error_message": error_message,
                    "updated_at": now,
                },
            )
            await session.execute(stmt)
            await session.flush()
        except Exception as exc:
            logger.warning(
                f"Correlation persistence failed: {type(exc).__name__}",
                extra={
                    "event_type": "BROKER_CORRELATION_PERSIST_FAILED",
                    "idempotency_key": idempotency_key,
                },
            )

    # ── Order placement ────────────────────────────────────────────────────

    async def place_order_paper_fallback(
        self, request: BrokerOrderRequest
    ) -> BrokerOrderResponse:
        """Place an order through the paper path while retaining all safety guards.

        Used by ZerodhaAdapter when ``_session_expired_paper_fallback`` is active
        (token expired or approaching expiry).  The execution is forced to paper
        mode regardless of live-mode configuration, but the kill-switch and
        idempotency checks run identically to ``place_order()``.

        Raises
        ------
        BrokerKillSwitchError
            If the kill switch is engaged (same as in the normal path).
        BrokerDuplicateOrderError
            If the idempotency key has already been processed.
        """
        # ── Kill switch check (identical to place_order) ───────────────────
        from src.core.kill_switch import kill_switch_manager
        if not kill_switch_manager.state.can_place_orders():
            ks = kill_switch_manager.state
            logger.critical(
                "Order blocked by kill switch (paper fallback path)",
                extra={
                    "event_type": "BROKER_ORDER_BLOCKED_KILL_SWITCH",
                    "kill_switch_level": ks.level.value,
                    "internal_order_id": request.internal_order_id,
                    "symbol": request.trading_symbol,
                },
            )
            raise BrokerKillSwitchError(
                f"Kill switch at {ks.level.value} — order blocked"
            )

        # ── Duplicate / idempotency check (identical to place_order) ───────
        if request.idempotency_key in self._correlations:
            existing = self._correlations[request.idempotency_key]
            if existing not in (
                CorrelationStatus.UNCERTAIN.value,
                CorrelationStatus.FAILED.value,
            ):
                raise BrokerDuplicateOrderError(
                    f"Idempotency key already processed: {request.idempotency_key!r}"
                )

        # ── Force paper execution ──────────────────────────────────────────
        return await self._place_paper_order(request)

    async def place_order(self, request: BrokerOrderRequest) -> BrokerOrderResponse:
        """Place an order.  Idempotent via idempotency_key check.

        Kill switch is checked first.  Paper mode bypasses all live gates.
        """
        # ── Kill switch check (always, before any mode check) ──────────────
        from src.core.kill_switch import kill_switch_manager
        if not kill_switch_manager.state.can_place_orders():
            ks = kill_switch_manager.state
            logger.critical(
                "Order blocked by kill switch",
                extra={
                    "event_type": "BROKER_ORDER_BLOCKED_KILL_SWITCH",
                    "kill_switch_level": ks.level.value,
                    "internal_order_id": request.internal_order_id,
                    "symbol": request.trading_symbol,
                },
            )
            raise BrokerKillSwitchError(
                f"Kill switch at {ks.level.value} — order blocked"
            )

        # ── Duplicate check ────────────────────────────────────────────────
        if request.idempotency_key in self._correlations:
            existing = self._correlations[request.idempotency_key]
            if existing not in (CorrelationStatus.UNCERTAIN.value, CorrelationStatus.FAILED.value):
                raise BrokerDuplicateOrderError(
                    f"Idempotency key already processed: {request.idempotency_key!r}"
                )

        # ── Paper mode ─────────────────────────────────────────────────────
        if self._config.paper_trading or not self._config.is_live_order_allowed():
            return await self._place_paper_order(request)

        # ── Live mode (all 5+ safety gates already checked by is_live_order_allowed) ──
        return await self._place_live_order(request)

    async def modify_order(
        self,
        broker_order_id: str,
        internal_order_id: str,
        **kwargs: Any,
    ) -> BrokerOrderResponse:
        """Modify an existing order."""
        if self._config.paper_trading:
            from src.brokers.interface import OrderRequest
            resp = await self._paper_broker.modify_order(broker_order_id)
            return BrokerOrderResponse(
                internal_order_id=internal_order_id,
                broker_order_id=broker_order_id,
                status=BrokerOrderStatus.OPEN,
                paper_mode=True,
                message=resp.message,
            )

        if not self._config.is_live_order_allowed():
            raise BrokerLiveModeError("Live modification requires all safety gates")

        await self._assert_health()
        try:
            order_id = await self._client.modify_order(
                variety=kwargs.get("variety", "regular"),
                order_id=broker_order_id,
                **{k: v for k, v in kwargs.items() if k != "variety"},
            )
            return BrokerOrderResponse(
                internal_order_id=internal_order_id,
                broker_order_id=str(order_id),
                status=BrokerOrderStatus.MODIFICATION_PENDING,
                paper_mode=False,
            )
        except BrokerTimeoutError:
            logger.warning(
                "Order modification timed out",
                extra={
                    "event_type": "BROKER_MODIFY_TIMEOUT",
                    "broker_order_id": broker_order_id,
                    "internal_order_id": internal_order_id,
                },
            )
            raise

    async def cancel_order(
        self,
        broker_order_id: str,
        internal_order_id: str,
        variety: str = "regular",
    ) -> bool:
        """Cancel an order.  Allowed even when kill switch is active."""
        if self._config.paper_trading:
            return await self._paper_broker.cancel_order(broker_order_id)

        if not self._config.is_live_order_allowed():
            raise BrokerLiveModeError("Live cancellation requires all safety gates")

        try:
            await self._client.cancel_order(variety=variety, order_id=broker_order_id)
            logger.info(
                "Order cancelled",
                extra={
                    "event_type": "BROKER_ORDER_CANCELLED",
                    "broker_order_id": broker_order_id,
                    "internal_order_id": internal_order_id,
                },
            )
            return True
        except Exception as exc:
            logger.error(
                f"Cancel failed: {type(exc).__name__}",
                extra={
                    "event_type": "BROKER_CANCEL_FAILED",
                    "broker_order_id": broker_order_id,
                },
            )
            raise

    # ── Order book / trades ────────────────────────────────────────────────

    async def get_order_book(self) -> List[BrokerOrderUpdate]:
        """Fetch the full order book for today."""
        if self._config.paper_trading or self._client is None:
            return []

        raw_orders = await self._client.get_orders()
        return [
            self._mapper.map_order_update(o, source="rest", paper_mode=False)
            for o in (raw_orders or [])
        ]

    async def get_trades(self) -> List[BrokerTrade]:
        """Fetch today's trade book."""
        if self._config.paper_trading or self._client is None:
            return []

        raw_trades = await self._client.get_trades()
        return [self._mapper.map_trade(t) for t in (raw_trades or [])]

    async def get_order(self, broker_order_id: str) -> Optional[BrokerOrderUpdate]:
        """Fetch a single order by broker ID."""
        if self._config.paper_trading or self._client is None:
            return None

        try:
            history = await self._client.get_order_history(broker_order_id)
            if not history:
                return None
            # Most recent entry
            latest = sorted(
                history,
                key=lambda x: x.get("exchange_update_timestamp", ""),
                reverse=True,
            )[0]
            return self._mapper.map_order_update(latest, source="rest", paper_mode=False)
        except Exception:
            return None

    # ── Private helpers ────────────────────────────────────────────────────

    async def _place_paper_order(self, request: BrokerOrderRequest) -> BrokerOrderResponse:
        """Route order to PaperBroker and normalise response."""
        from src.brokers.interface import OrderRequest as LegacyRequest

        legacy = LegacyRequest(
            symbol=request.trading_symbol,
            side=request.transaction_type.value,
            quantity=int(request.quantity),
            order_type=request.order_type.value,
            product=request.product.value,
            price=request.price,
            trigger_price=request.trigger_price,
            tag=request.tag or request.internal_order_id,
        )
        resp = await self._paper_broker.place_order(legacy)

        self._correlations[request.idempotency_key] = CorrelationStatus.CONFIRMED.value
        await self._persist_correlation(
            idempotency_key=request.idempotency_key,
            internal_order_id=request.internal_order_id,
            status=CorrelationStatus.CONFIRMED.value,
            broker_order_id=resp.broker_order_id,
            trading_symbol=request.trading_symbol,
            exchange=request.exchange.value if hasattr(request.exchange, "value") else str(request.exchange),
            paper_mode=True,
        )

        status_map = {
            "COMPLETE": BrokerOrderStatus.COMPLETE,
            "REJECTED": BrokerOrderStatus.REJECTED,
            "CANCELLED": BrokerOrderStatus.CANCELLED,
            "PENDING": BrokerOrderStatus.PENDING,
        }
        status = status_map.get(resp.status, BrokerOrderStatus.UNKNOWN)

        logger.info(
            "Paper order routed",
            extra={
                "event_type": "BROKER_ORDER_PAPER",
                "internal_order_id": request.internal_order_id,
                "broker_order_id": resp.broker_order_id,
                "symbol": request.trading_symbol,
                "side": request.transaction_type.value,
                "quantity": str(request.quantity),
                "status": status.value,
            },
        )
        # Populate fill fields from the paper broker's synchronous response
        filled_qty = Decimal(str(resp.filled_quantity or 0))
        avg_price = resp.average_price if resp.average_price is not None else None

        return BrokerOrderResponse(
            internal_order_id=request.internal_order_id,
            broker_order_id=resp.broker_order_id,
            status=status,
            paper_mode=True,
            message=resp.message,
            placed_at=datetime.now(timezone.utc),
            filled_quantity=filled_qty,
            average_price=avg_price,
        )

    async def _place_live_order(self, request: BrokerOrderRequest) -> BrokerOrderResponse:
        """Place a live order via the Zerodha API.

        Timeout → UNCERTAIN (never blindly retried).
        """
        await self._assert_health()

        params = self._mapper.to_zerodha_order_params(request)

        # Record pending correlation (in-memory + DB)
        self._correlations[request.idempotency_key] = CorrelationStatus.PENDING.value
        await self._persist_correlation(
            idempotency_key=request.idempotency_key,
            internal_order_id=request.internal_order_id,
            status=CorrelationStatus.PENDING.value,
            trading_symbol=request.trading_symbol,
            exchange=request.exchange.value if hasattr(request.exchange, "value") else str(request.exchange),
            paper_mode=False,
        )

        try:
            broker_order_id = await self._client.place_order(**params)
            self._correlations[request.idempotency_key] = CorrelationStatus.SUBMITTED.value
            await self._persist_correlation(
                idempotency_key=request.idempotency_key,
                internal_order_id=request.internal_order_id,
                status=CorrelationStatus.SUBMITTED.value,
                broker_order_id=broker_order_id,
                trading_symbol=request.trading_symbol,
                exchange=request.exchange.value if hasattr(request.exchange, "value") else str(request.exchange),
                paper_mode=False,
            )

            logger.info(
                "Live order submitted to Zerodha",
                extra={
                    "event_type": "BROKER_ORDER_LIVE_SUBMITTED",
                    "internal_order_id": request.internal_order_id,
                    "broker_order_id": broker_order_id,
                    "symbol": request.trading_symbol,
                    "side": request.transaction_type.value,
                    "quantity": str(request.quantity),
                },
            )
            return BrokerOrderResponse(
                internal_order_id=request.internal_order_id,
                broker_order_id=broker_order_id,
                status=BrokerOrderStatus.OPEN,
                paper_mode=False,
                placed_at=datetime.now(timezone.utc),
            )

        except BrokerTimeoutError:
            # Mark as UNCERTAIN — reconciliation will resolve (in-memory + DB)
            self._correlations[request.idempotency_key] = CorrelationStatus.UNCERTAIN.value
            await self._persist_correlation(
                idempotency_key=request.idempotency_key,
                internal_order_id=request.internal_order_id,
                status=CorrelationStatus.UNCERTAIN.value,
                trading_symbol=request.trading_symbol,
                exchange=request.exchange.value if hasattr(request.exchange, "value") else str(request.exchange),
                paper_mode=False,
                error_message="Placement timed out — UNCERTAIN, pending reconciliation",
            )
            logger.error(
                "Order placement timed out — marked UNCERTAIN for reconciliation",
                extra={
                    "event_type": "BROKER_ORDER_UNCERTAIN",
                    "internal_order_id": request.internal_order_id,
                    "symbol": request.trading_symbol,
                },
            )
            raise

        except Exception as exc:
            self._correlations[request.idempotency_key] = CorrelationStatus.FAILED.value
            await self._persist_correlation(
                idempotency_key=request.idempotency_key,
                internal_order_id=request.internal_order_id,
                status=CorrelationStatus.FAILED.value,
                trading_symbol=request.trading_symbol,
                exchange=request.exchange.value if hasattr(request.exchange, "value") else str(request.exchange),
                paper_mode=False,
                error_message=type(exc).__name__,
            )
            raise

    async def _assert_health(self) -> None:
        """Raise BrokerLiveModeError if health is not ready for live orders."""
        if not self._health.is_ready():
            raise BrokerLiveModeError(
                "Broker is not ready for live orders. "
                f"Health: {self._health.get_health().status.value}"
            )
