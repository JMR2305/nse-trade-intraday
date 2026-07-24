"""RC-10D: REST reconciliation engine.

ReconciliationEngine compares local orders against the broker order book and
trade book.  It classifies discrepancies into 9 types and records them in
broker_reconciliation_runs and broker_reconciliation_discrepancies tables.

No destructive corrections are made without an explicit policy.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from src.brokers.contracts import (
    BrokerOrderStatus,
    BrokerOrderUpdate,
    BrokerTrade,
    ReconciliationDiscrepancy,
    ReconciliationDiscrepancyType,
    ReconciliationReport,
)
from src.brokers.exceptions import BrokerReconciliationError
from src.brokers.zerodha.config import ZerodhaBrokerConfig
from src.brokers.zerodha.health import BrokerHealthTracker
from src.core.logging import logger


class ReconciliationEngine:
    """Reconciles local orders against broker state.

    Triggers
    --------
      - Startup
      - After WebSocket reconnect
      - After uncertain order submission
      - After failed cancellation/modification
      - Periodic schedule during market hours

    Discrepancy types (9 total):
      LOCAL_ONLY, BROKER_ONLY, STATE_MISMATCH, FILL_MISMATCH,
      QUANTITY_MISMATCH, PRICE_MISMATCH, MISSING_EXCHANGE_ORDER_ID,
      DUPLICATE_ORDER, UNRESOLVED_BROKER_EVENT
    """

    def __init__(
        self,
        config: ZerodhaBrokerConfig,
        health_tracker: BrokerHealthTracker,
        order_gateway,
        db_session=None,
    ) -> None:
        self._config = config
        self._health = health_tracker
        self._order_gateway = order_gateway
        self._last_run: Optional[datetime] = None
        self._run_count: int = 0
        self._lock = asyncio.Lock()
        # Stored DB session — set via constructor or set_db_session().
        # Used for loading local orders and persisting run/discrepancy rows
        # when caller does not pass db_session explicitly (e.g. adapter trigger).
        self._db_session = db_session

    def set_db_session(self, db_session) -> None:
        """Wire a SQLAlchemy async session into the reconciliation engine.

        Called by ZerodhaAdapter.set_db_session() after injection.
        """
        self._db_session = db_session

    async def run(
        self,
        *,
        trigger: str = "manual",
        local_orders: Optional[List[Dict[str, Any]]] = None,
        db_session=None,
    ) -> ReconciliationReport:
        """Run a full reconciliation cycle.

        Parameters
        ----------
        trigger:
            Reason for this run (startup / post_reconnect / uncertain_submission /
            periodic / eod / manual).
        local_orders:
            List of local order dicts from the DB.  If None, fetched from db_session.
        db_session:
            SQLAlchemy async session for reading local state and writing results.

        Returns
        -------
        ReconciliationReport
        """
        # Prefer caller-supplied session; fall back to stored session
        effective_session = db_session or self._db_session
        async with self._lock:
            return await self._run_locked(
                trigger=trigger,
                local_orders=local_orders,
                db_session=effective_session,
            )

    # ── Private helpers ────────────────────────────────────────────────────

    async def _run_locked(
        self,
        *,
        trigger: str,
        local_orders: Optional[List[Dict[str, Any]]],
        db_session,
    ) -> ReconciliationReport:
        started_at = datetime.now(timezone.utc)
        run_id = str(uuid4())
        self._run_count += 1

        logger.info(
            f"Reconciliation started (run #{self._run_count}, trigger={trigger!r})",
            extra={
                "event_type": "RECONCILIATION_START",
                "run_id": run_id,
                "trigger": trigger,
                "paper_mode": self._config.paper_trading,
            },
        )

        # In paper mode, report clean with no checks
        if self._config.paper_trading:
            report = ReconciliationReport(
                run_id=run_id,
                trigger=trigger,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                discrepancies=[],
                orders_checked=0,
                clean=True,
                paper_mode=True,
            )
            self._last_run = datetime.now(timezone.utc)
            await self._health.set_reconciliation_status("CLEAN")
            return report

        discrepancies: List[ReconciliationDiscrepancy] = []

        try:
            # Fetch broker order book
            broker_orders = await self._order_gateway.get_order_book()
            broker_trades = await self._order_gateway.get_trades()

            broker_by_id: Dict[str, BrokerOrderUpdate] = {
                o.broker_order_id: o for o in broker_orders
            }
            trade_by_order: Dict[str, List[BrokerTrade]] = {}
            for t in broker_trades:
                trade_by_order.setdefault(t.broker_order_id, []).append(t)

            # Load local orders from DB when not supplied explicitly
            if local_orders is not None:
                local_order_list = local_orders
            elif db_session is not None:
                local_order_list = await self._load_local_orders_from_db(db_session)
            else:
                local_order_list = []
            local_by_broker_id: Dict[str, Dict] = {
                o["broker_order_id"]: o
                for o in local_order_list
                if o.get("broker_order_id")
            }

            orders_checked = len(local_order_list)

            # ── Check 1: LOCAL_ONLY ────────────────────────────────────────
            for local in local_order_list:
                broker_oid = local.get("broker_order_id")
                if broker_oid and broker_oid not in broker_by_id:
                    if local.get("status") not in ("COMPLETE", "CANCELLED", "REJECTED"):
                        discrepancies.append(ReconciliationDiscrepancy(
                            discrepancy_type=ReconciliationDiscrepancyType.LOCAL_ONLY,
                            internal_order_id=str(local.get("id", "")),
                            broker_order_id=broker_oid,
                            trading_symbol=local.get("symbol", ""),
                            description="Local order not found in broker order book",
                            requires_manual_review=True,
                        ))

            # ── Check 2: BROKER_ONLY ──────────────────────────────────────
            for broker_oid, broker_order in broker_by_id.items():
                if broker_oid not in local_by_broker_id:
                    if broker_order.status not in (
                        BrokerOrderStatus.COMPLETE,
                        BrokerOrderStatus.CANCELLED,
                        BrokerOrderStatus.REJECTED,
                    ):
                        discrepancies.append(ReconciliationDiscrepancy(
                            discrepancy_type=ReconciliationDiscrepancyType.BROKER_ONLY,
                            broker_order_id=broker_oid,
                            trading_symbol=broker_order.trading_symbol,
                            description="Broker order has no local counterpart",
                            broker_value=broker_order.status.value,
                            requires_manual_review=True,
                        ))

            # ── Checks 3-9: STATUS, FILL, QUANTITY, PRICE, EXCHANGE_ID, DUP, EVENT
            for local in local_order_list:
                broker_oid = local.get("broker_order_id")
                if not broker_oid or broker_oid not in broker_by_id:
                    continue

                broker_order = broker_by_id[broker_oid]

                # STATE_MISMATCH (simplified — local terminal vs broker open)
                local_terminal = local.get("status") in ("COMPLETE", "CANCELLED", "REJECTED")
                broker_terminal = broker_order.status in (
                    BrokerOrderStatus.COMPLETE,
                    BrokerOrderStatus.CANCELLED,
                    BrokerOrderStatus.REJECTED,
                )
                if local_terminal != broker_terminal:
                    discrepancies.append(ReconciliationDiscrepancy(
                        discrepancy_type=ReconciliationDiscrepancyType.STATE_MISMATCH,
                        internal_order_id=str(local.get("id", "")),
                        broker_order_id=broker_oid,
                        trading_symbol=local.get("symbol", ""),
                        description="Local and broker terminal states differ",
                        local_value=local.get("status"),
                        broker_value=broker_order.status.value,
                        requires_manual_review=True,
                    ))

                # MISSING_EXCHANGE_ORDER_ID
                if not broker_order.exchange_order_id and broker_order.status in (
                    BrokerOrderStatus.COMPLETE,
                    BrokerOrderStatus.PARTIALLY_FILLED,
                ):
                    discrepancies.append(ReconciliationDiscrepancy(
                        discrepancy_type=ReconciliationDiscrepancyType.MISSING_EXCHANGE_ORDER_ID,
                        internal_order_id=str(local.get("id", "")),
                        broker_order_id=broker_oid,
                        description="Filled order missing exchange_order_id",
                    ))

                # FILL_MISMATCH (check fill count vs broker filled_quantity)
                broker_trades_for_order = trade_by_order.get(broker_oid, [])
                if broker_order.status == BrokerOrderStatus.COMPLETE:
                    if broker_order.filled_quantity > 0 and not broker_trades_for_order:
                        discrepancies.append(ReconciliationDiscrepancy(
                            discrepancy_type=ReconciliationDiscrepancyType.FILL_MISMATCH,
                            internal_order_id=str(local.get("id", "")),
                            broker_order_id=broker_oid,
                            description="Order COMPLETE but no trade records found",
                            requires_manual_review=True,
                        ))

                # QUANTITY_MISMATCH (local intended quantity vs broker filled)
                local_qty = local.get("quantity")
                if (
                    local_qty is not None
                    and broker_order.status == BrokerOrderStatus.COMPLETE
                    and broker_order.filled_quantity > Decimal("0")
                ):
                    try:
                        if abs(Decimal(str(local_qty)) - broker_order.filled_quantity) > Decimal("0.001"):
                            discrepancies.append(ReconciliationDiscrepancy(
                                discrepancy_type=ReconciliationDiscrepancyType.QUANTITY_MISMATCH,
                                internal_order_id=str(local.get("id", "")),
                                broker_order_id=broker_oid,
                                trading_symbol=local.get("symbol", ""),
                                description="Local intended quantity differs from broker filled quantity",
                                local_value=str(local_qty),
                                broker_value=str(broker_order.filled_quantity),
                                requires_manual_review=True,
                            ))
                    except Exception:
                        pass

                # PRICE_MISMATCH (local limit price vs actual trade average — tolerance 1%)
                local_price = local.get("price")
                if (
                    local_price is not None
                    and broker_trades_for_order
                    and broker_order.status == BrokerOrderStatus.COMPLETE
                ):
                    try:
                        local_p = Decimal(str(local_price))
                        if local_p > Decimal("0"):
                            trade_avg = sum(
                                t.price * t.quantity for t in broker_trades_for_order
                            ) / sum(t.quantity for t in broker_trades_for_order)
                            pct_diff = abs(trade_avg - local_p) / local_p
                            if pct_diff > Decimal("0.01"):  # >1% deviation
                                discrepancies.append(ReconciliationDiscrepancy(
                                    discrepancy_type=ReconciliationDiscrepancyType.PRICE_MISMATCH,
                                    internal_order_id=str(local.get("id", "")),
                                    broker_order_id=broker_oid,
                                    trading_symbol=local.get("symbol", ""),
                                    description="Fill price deviates >1% from local expected price",
                                    local_value=str(local_p),
                                    broker_value=str(trade_avg.quantize(Decimal("0.01"))),
                                    requires_manual_review=True,
                                ))
                    except Exception:
                        pass

            # ── Check 8: DUPLICATE_ORDER ──────────────────────────────────
            # Multiple local orders pointing to the same broker_order_id
            from collections import Counter
            broker_id_counts = Counter(
                o["broker_order_id"]
                for o in local_order_list
                if o.get("broker_order_id")
            )
            for dup_broker_oid, cnt in broker_id_counts.items():
                if cnt > 1:
                    discrepancies.append(ReconciliationDiscrepancy(
                        discrepancy_type=ReconciliationDiscrepancyType.DUPLICATE_ORDER,
                        broker_order_id=dup_broker_oid,
                        description=f"broker_order_id {dup_broker_oid!r} mapped to {cnt} local orders",
                        broker_value=str(cnt),
                        requires_manual_review=True,
                    ))

            # ── Check 9: UNRESOLVED_BROKER_EVENT ─────────────────────────
            # Broker orders whose status is UNKNOWN (unrecognised status string)
            for broker_oid, broker_order in broker_by_id.items():
                if broker_order.status == BrokerOrderStatus.UNKNOWN:
                    discrepancies.append(ReconciliationDiscrepancy(
                        discrepancy_type=ReconciliationDiscrepancyType.UNRESOLVED_BROKER_EVENT,
                        broker_order_id=broker_oid,
                        trading_symbol=broker_order.trading_symbol,
                        description="Broker order has an unrecognised status (mapped to UNKNOWN)",
                        broker_value=str(broker_order.status.value),
                        requires_manual_review=False,
                    ))

            # ── Finalise report ────────────────────────────────────────────
            clean = len(discrepancies) == 0
            report = ReconciliationReport(
                run_id=run_id,
                trigger=trigger,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                discrepancies=discrepancies,
                orders_checked=orders_checked,
                clean=clean,
                paper_mode=False,
            )

            status_str = "CLEAN" if clean else f"DISCREPANCIES:{len(discrepancies)}"
            await self._health.set_reconciliation_status(status_str)
            self._last_run = datetime.now(timezone.utc)

            if discrepancies:
                logger.warning(
                    f"Reconciliation found {len(discrepancies)} discrepancies",
                    extra={
                        "event_type": "RECONCILIATION_DISCREPANCIES",
                        "run_id": run_id,
                        "count": len(discrepancies),
                        "trigger": trigger,
                    },
                )
            else:
                logger.info(
                    "Reconciliation: clean",
                    extra={"event_type": "RECONCILIATION_CLEAN", "run_id": run_id},
                )

            # Write to DB if session available
            if db_session is not None:
                await self._persist_report(report, db_session)

            return report

        except Exception as exc:
            logger.error(
                f"Reconciliation failed: {type(exc).__name__}",
                extra={"event_type": "RECONCILIATION_ERROR", "run_id": run_id},
            )
            await self._health.set_reconciliation_status("ERROR")
            raise BrokerReconciliationError(
                f"Reconciliation failed: {type(exc).__name__}"
            ) from exc

    async def _load_local_orders_from_db(self, db_session) -> List[Dict[str, Any]]:
        """Fetch today's non-terminal orders from the local DB.

        Returns a list of dicts with at minimum: id, broker_order_id,
        symbol, status, quantity, price.  Returns [] on any error so a
        failed DB read never blocks reconciliation from running.
        """
        try:
            from sqlalchemy import text
            result = await db_session.execute(text("""
                SELECT
                    id,
                    order_id       AS broker_order_id,
                    symbol,
                    status,
                    quantity,
                    price,
                    created_at
                FROM orders
                WHERE DATE(created_at AT TIME ZONE 'UTC') = CURRENT_DATE
                ORDER BY id
            """))
            rows = result.mappings().fetchall()
            return [dict(row) for row in rows]
        except Exception as exc:
            logger.warning(
                f"Failed to load local orders from DB: {type(exc).__name__}",
                extra={"event_type": "RECONCILIATION_DB_LOAD_FAILED"},
            )
            return []

    async def _persist_report(self, report: ReconciliationReport, db_session) -> None:
        """Persist reconciliation run and discrepancies to DB."""
        try:
            from sqlalchemy import text

            await db_session.execute(text("""
                INSERT INTO broker_reconciliation_runs
                    (run_id, trigger, started_at, completed_at, orders_checked,
                     clean, discrepancy_count, paper_mode)
                VALUES
                    (:run_id, :trigger, :started_at, :completed_at, :orders_checked,
                     :clean, :count, :paper_mode)
                ON CONFLICT (run_id) DO NOTHING
            """), {
                "run_id": report.run_id,
                "trigger": report.trigger,
                "started_at": report.started_at,
                "completed_at": report.completed_at,
                "orders_checked": report.orders_checked,
                "clean": report.clean,
                "count": len(report.discrepancies),
                "paper_mode": report.paper_mode,
            })

            for d in report.discrepancies:
                await db_session.execute(text("""
                    INSERT INTO broker_reconciliation_discrepancies
                        (run_id, discrepancy_type, internal_order_id,
                         broker_order_id, trading_symbol, description,
                         local_value, broker_value, requires_manual_review)
                    VALUES
                        (:run_id, :dtype, :iid, :bid, :symbol,
                         :desc, :lval, :bval, :review)
                """), {
                    "run_id": report.run_id,
                    "dtype": d.discrepancy_type.value,
                    "iid": d.internal_order_id,
                    "bid": d.broker_order_id,
                    "symbol": d.trading_symbol,
                    "desc": d.description,
                    "lval": d.local_value,
                    "bval": d.broker_value,
                    "review": d.requires_manual_review,
                })

            await db_session.commit()
        except Exception as exc:
            logger.warning(
                f"Failed to persist reconciliation report: {type(exc).__name__}"
            )
