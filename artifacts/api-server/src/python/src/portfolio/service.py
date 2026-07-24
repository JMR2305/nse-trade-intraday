"""RC-10C1 Portfolio Core — PortfolioService (façade).

This module is the ONLY public entry point for external modules interacting
with the portfolio domain.  Strategy code, RC-8 risk authority, and UI code
must import from here and nowhere else within ``src.portfolio``.

Invariants
----------
* PortfolioService NEVER places, modifies, or cancels orders.
* RC-8 remains the final risk authority for all order decisions.
* RC-7 remains the execution authority.
* No Zerodha SDK types appear anywhere in this module.
* Paper trading is the default; live trading is structurally disabled.
* Dependency injection is used throughout — pass mocks for testing.

API contract
-----------
* ``initialise()``                    → PortfolioSnapshot
* ``get_state()``                     → PortfolioSnapshot
* ``get_snapshot()``                  → PortfolioSnapshot (alias)
* ``evaluate_allocation()``           → AllocationDecision
* ``calculate_position_size()``       → PositionSizeDecision
* ``evaluate_exposure()``             → ExposureSnapshot
* ``evaluate_limits()``               → LimitCheckReport
* ``apply_order_reservation()``       → PortfolioSnapshot
* ``release_order_reservation()``     → PortfolioSnapshot
* ``apply_fill()``                    → PortfolioSnapshot
* ``update_market_price()``           → None
* ``reconcile()``                     → PortfolioReconciliationReport
* ``recover()``                       → PortfolioSnapshot
* ``create_snapshot()``               → PortfolioSnapshot
* ``get_health()``                    → PortfolioHealth

Structured logging is used.  Broker credentials and raw account payloads
are never logged.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from src.portfolio.capital_allocator import CapitalAllocator, evaluate_allocation as _eval_alloc
from src.portfolio.config import DEFAULT_CONFIG, PortfolioConfig
from src.portfolio.contracts import (
    AllocationDecision,
    AllocationStatus,
    ExposureSnapshot,
    LimitCheckReport,
    PortfolioEvent,
    PortfolioEventType,
    PortfolioHealth,
    PortfolioReconciliationReport,
    PortfolioSnapshot,
    PortfolioStatus,
    PositionSide,
    PositionSizeDecision,
    PositionSizeRequest,
)
from src.portfolio.exceptions import (
    DuplicateEventError,
    NegativeQuantityError,
    PortfolioHaltedError,
    PortfolioNotReadyError,
    StalePortfolioStateError,
)
from src.portfolio.exposure import ExposureEngine
from src.portfolio.health import PortfolioHealthMonitor
from src.portfolio.ledger import PortfolioEventLedger
from src.portfolio.limits import PortfolioLimitEngine
from src.portfolio.pnl import PnLEngine
from src.portfolio.position_manager import PositionManager
from src.portfolio.position_sizer import PositionSizer, calculate_size as _calc_size
from src.portfolio.reconciliation import (
    PortfolioReconciliationEngine,
    BrokerSnapshot,
    detect_stale_state,
)
from src.portfolio.repositories.portfolio_event import PortfolioEventRepository
from src.portfolio.repositories.portfolio_snapshot import PortfolioSnapshotRepository
from src.portfolio.repositories.reconciliation import ReconciliationRepository
from src.portfolio.state_manager import PortfolioStateManager

logger = logging.getLogger(__name__)


class PortfolioService:
    """Façade for the portfolio domain.

    All external code (strategies, RC-8, UI) interacts exclusively through
    this class.  Internal portfolio sub-modules must not be imported directly
    by code outside the ``src.portfolio`` package.

    Parameters
    ----------
    config:
        Portfolio configuration.  Defaults to ``DEFAULT_CONFIG``.
    state_manager:
        Manages in-memory portfolio state.
    ledger:
        Append-only event ledger.
    position_manager:
        Position lifecycle manager (used for DI in tests).
    pnl_engine:
        P&L computation engine (used for DI in tests).
    capital_allocator:
        Capital allocation decision engine.
    position_sizer:
        Position size calculation engine.
    reconciliation_engine:
        Broker snapshot reconciliation engine.
    snapshot_repo:
        Persistence for portfolio snapshots.
    event_repo:
        Persistence for portfolio events.
    reconciliation_repo:
        Persistence for reconciliation reports.
    """

    def __init__(
        self,
        config: PortfolioConfig | None = None,
        state_manager: PortfolioStateManager | None = None,
        ledger: PortfolioEventLedger | None = None,
        position_manager: PositionManager | None = None,
        pnl_engine: PnLEngine | None = None,
        capital_allocator: CapitalAllocator | None = None,
        position_sizer: PositionSizer | None = None,
        reconciliation_engine: PortfolioReconciliationEngine | None = None,
        snapshot_repo: PortfolioSnapshotRepository | None = None,
        event_repo: PortfolioEventRepository | None = None,
        reconciliation_repo: ReconciliationRepository | None = None,
    ) -> None:
        self.config: PortfolioConfig = config or DEFAULT_CONFIG

        # Core sub-systems — create with defaults if not injected
        self._state_manager: PortfolioStateManager = (
            state_manager or PortfolioStateManager(self.config)
        )
        self._ledger: PortfolioEventLedger = ledger or PortfolioEventLedger(
            self.config.portfolio_id
        )
        # position_manager and pnl_engine accepted for DI/test
        self._position_manager: PositionManager = position_manager or PositionManager()
        self._pnl_engine: PnLEngine = pnl_engine or PnLEngine()
        self._capital_allocator: CapitalAllocator = (
            capital_allocator or CapitalAllocator(self.config)
        )
        self._position_sizer: PositionSizer = (
            position_sizer or PositionSizer(self.config)
        )
        self._exposure_engine: ExposureEngine = ExposureEngine(self.config)
        self._limits_engine: PortfolioLimitEngine = PortfolioLimitEngine(self.config)
        self._health_monitor: PortfolioHealthMonitor = PortfolioHealthMonitor(self.config)
        self._reconciliation_engine: PortfolioReconciliationEngine = (
            reconciliation_engine or PortfolioReconciliationEngine(self.config)
        )

        # Repositories (optional — omit for in-memory-only deployments)
        self._snapshot_repo: PortfolioSnapshotRepository | None = snapshot_repo
        self._event_repo: PortfolioEventRepository | None = event_repo
        self._reconciliation_repo: ReconciliationRepository | None = reconciliation_repo

        logger.info(
            "PortfolioService created",
            extra={
                "portfolio_id": self.config.portfolio_id,
                "paper_mode": self.config.paper_mode,
            },
        )

    # ──────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────

    def _snapshot_sync(self, portfolio_id: str | None = None) -> PortfolioSnapshot:
        """Return snapshot from state_manager (synchronous call)."""
        pid = portfolio_id or self.config.portfolio_id
        return self._state_manager.get_snapshot(pid)

    async def _persist_event(self, event: PortfolioEvent) -> PortfolioEvent:
        """Append to ledger and optionally persist to event_repo."""
        sequenced = await self._ledger.append(event)
        if self._event_repo is not None:
            await self._event_repo.append(sequenced)
        return sequenced

    # ──────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────────────────

    async def initialise(
        self, initial_cash: Decimal | None = None
    ) -> PortfolioSnapshot:
        """Initialise the portfolio state with *initial_cash*.

        Parameters
        ----------
        initial_cash:
            Starting cash balance.  Defaults to ``config.initial_capital``.

        Returns
        -------
        PortfolioSnapshot
            The state immediately after initialisation.
        """
        cash = initial_cash if initial_cash is not None else self.config.initial_capital
        snapshot = await self._state_manager.initialise(cash, self.config.portfolio_id)

        # Persist init event (best-effort — ignore duplicates on re-init)
        init_event = PortfolioEvent(
            idempotency_key=f"init-{self.config.portfolio_id}-{snapshot.version}",
            event_type=PortfolioEventType.PORTFOLIO_INITIALIZED,
            payload={"initial_cash": str(cash)},
        )
        try:
            await self._persist_event(init_event)
        except DuplicateEventError:
            pass

        if self._snapshot_repo is not None:
            await self._snapshot_repo.save(snapshot)

        # Record in health monitor
        self._health_monitor.record_recovery(success=True)
        self._health_monitor.record_reconciliation(
            critical_count=0, warning_count=0, completed_at=datetime.now(timezone.utc)
        )

        logger.info(
            "Portfolio initialised",
            extra={"portfolio_id": self.config.portfolio_id},
        )
        return snapshot

    # ──────────────────────────────────────────────────────────────────────
    # State access
    # ──────────────────────────────────────────────────────────────────────

    async def get_state(self) -> PortfolioSnapshot:
        """Return the current authoritative portfolio snapshot."""
        return self._snapshot_sync()

    async def get_snapshot(self) -> PortfolioSnapshot:
        """Alias for :meth:`get_state` (spec compliance)."""
        return await self.get_state()

    # ──────────────────────────────────────────────────────────────────────
    # Capital allocation
    # ──────────────────────────────────────────────────────────────────────

    async def evaluate_allocation(
        self,
        strategy_id: str,
        requested_capital: Decimal,
        instrument_token: int | None = None,
        correlation_id: str | None = None,
    ) -> AllocationDecision:
        """Evaluate a capital allocation request from a strategy.

        Returns REJECTED decision instead of raising for most guard failures
        (stale state and not-ready raise exceptions as per spec).

        Parameters
        ----------
        strategy_id:
            Requesting strategy identifier.
        requested_capital:
            Amount of capital requested in base currency.
        instrument_token:
            Target instrument (optional).
        correlation_id:
            Optional distributed tracing identifier.

        Returns
        -------
        AllocationDecision
        """
        snapshot = self._snapshot_sync()

        try:
            decision = await _eval_alloc(
                strategy_id=strategy_id,
                instrument_token=instrument_token,
                requested_capital=requested_capital,
                snapshot=snapshot,
                config=self.config,
                correlation_id=correlation_id,
            )
        except (StalePortfolioStateError, PortfolioNotReadyError):
            raise
        except NegativeQuantityError as exc:
            # Determine whether rejection is due to insufficient buying power or
            # below min_order_value.  If buying_power < requested → INSUFFICIENT;
            # otherwise genuinely below min threshold.
            net_bp = snapshot.buying_power.net
            if requested_capital > net_bp:
                reason_codes: tuple[str, ...] = ("INSUFFICIENT_BUYING_POWER",)
            else:
                reason_codes = ("BELOW_MIN_ORDER_VALUE",)
            decision = AllocationDecision(
                strategy_id=strategy_id,
                instrument_token=instrument_token,
                requested_capital=requested_capital,
                approved_capital=Decimal("0"),
                rejected_capital=requested_capital,
                status=AllocationStatus.REJECTED,
                reason_codes=reason_codes,
                portfolio_state_version=snapshot.version,
                correlation_id=correlation_id,
            )

        # Persist allocation event (non-critical — ignore errors)
        if self._event_repo is not None:
            try:
                event = PortfolioEvent(
                    idempotency_key=f"alloc-{decision.decision_id}",
                    event_type=PortfolioEventType.ORDER_RESERVED,
                    instrument_token=instrument_token,
                    strategy_id=strategy_id,
                    correlation_id=correlation_id,
                    payload={
                        "decision_id": str(decision.decision_id),
                        "status": decision.status.value,
                        "approved_capital": str(decision.approved_capital),
                    },
                )
                await self._event_repo.append(event)
            except Exception as exc:
                logger.debug("Allocation event persist failed", extra={"error": str(exc)})

        logger.info(
            "Allocation evaluated",
            extra={
                "strategy_id": strategy_id,
                "status": decision.status.value,
                "approved": str(decision.approved_capital),
            },
        )
        return decision

    # ──────────────────────────────────────────────────────────────────────
    # Position sizing
    # ──────────────────────────────────────────────────────────────────────

    async def calculate_position_size(
        self, request: PositionSizeRequest
    ) -> PositionSizeDecision:
        """Calculate an approved position size for a strategy signal.

        Raises
        ------
        StalePortfolioStateError
            If the portfolio snapshot is older than the configured threshold.
        """
        snapshot = self._snapshot_sync()
        return _calc_size(request=request, snapshot=snapshot, config=self.config)

    # ──────────────────────────────────────────────────────────────────────
    # Exposure
    # ──────────────────────────────────────────────────────────────────────

    async def evaluate_exposure(
        self,
        instrument_token: int | None = None,
        proposed_value: Decimal = Decimal("0"),
        strategy_id: str | None = None,
        sector: str | None = None,
    ) -> ExposureSnapshot:
        """Return the current portfolio exposure snapshot."""
        snapshot = self._snapshot_sync()
        return await self._exposure_engine.calculate_exposure(
            snapshot=snapshot,
            instrument_token=instrument_token,
            proposed_value=proposed_value,
            strategy_id=strategy_id,
            sector=sector,
        )

    # ──────────────────────────────────────────────────────────────────────
    # Limit checking
    # ──────────────────────────────────────────────────────────────────────

    async def evaluate_limits(
        self,
        proposed_instrument_token: int | None = None,
        proposed_value: Decimal = Decimal("0"),
        proposed_strategy_id: str | None = None,
        proposed_sector: str | None = None,
    ) -> LimitCheckReport:
        """Check all portfolio limits for a proposed action."""
        snapshot = self._snapshot_sync()
        exposure = await self._exposure_engine.calculate_exposure(
            snapshot=snapshot,
            instrument_token=proposed_instrument_token,
            proposed_value=proposed_value,
            strategy_id=proposed_strategy_id,
            sector=proposed_sector,
        )
        return await self._limits_engine.check_all_limits(
            snapshot=snapshot,
            exposure=exposure,
            proposed_instrument_token=proposed_instrument_token,
            proposed_value=proposed_value,
            proposed_strategy_id=proposed_strategy_id,
            proposed_sector=proposed_sector,
        )

    # ──────────────────────────────────────────────────────────────────────
    # Order reservation
    # ──────────────────────────────────────────────────────────────────────

    async def apply_order_reservation(
        self,
        order_id: str,
        amount: Decimal,
        instrument_token: int | None = None,
        instrument_symbol: str | None = None,
        strategy_id: str | None = None,
    ) -> PortfolioSnapshot:
        """Reserve capital for a pending order.

        Parameters
        ----------
        order_id:
            Unique reservation identifier.
        amount:
            Estimated cash to block.
        instrument_token:
            Target instrument (optional, for event metadata).
        instrument_symbol:
            Human-readable symbol (optional).
        strategy_id:
            Strategy initiating the reservation (optional).

        Returns
        -------
        PortfolioSnapshot
            Updated portfolio state.
        """
        snapshot = await self._state_manager.reserve_order_capital(order_id, amount)

        event = PortfolioEvent(
            idempotency_key=f"reserve-{order_id}",
            event_type=PortfolioEventType.ORDER_RESERVED,
            instrument_token=instrument_token,
            strategy_id=strategy_id,
            payload={
                "order_id": order_id,
                "amount": str(amount),
                "instrument_symbol": instrument_symbol or "",
            },
        )
        try:
            await self._persist_event(event)
        except DuplicateEventError:
            pass

        logger.info(
            "Order capital reserved",
            extra={"order_id": order_id, "amount": str(amount)},
        )
        return snapshot

    async def release_order_reservation(self, order_id: str) -> PortfolioSnapshot:
        """Release a previously reserved order capital.

        Returns
        -------
        PortfolioSnapshot
            Updated portfolio state.
        """
        snapshot = await self._state_manager.release_order_capital(order_id)

        event = PortfolioEvent(
            idempotency_key=f"release-{order_id}",
            event_type=PortfolioEventType.ORDER_RESERVATION_RELEASED,
            payload={"order_id": order_id},
        )
        try:
            await self._persist_event(event)
        except DuplicateEventError:
            pass

        logger.info("Order reservation released", extra={"order_id": order_id})
        return snapshot

    # ──────────────────────────────────────────────────────────────────────
    # Fill processing
    # ──────────────────────────────────────────────────────────────────────

    async def apply_fill(
        self,
        idempotency_key: str,
        instrument_token: int,
        instrument_symbol: str,
        side: PositionSide,
        quantity: int,
        price: Decimal,
        fill_id: str,
        filled_at: datetime,
        order_id: str | None = None,
        fees: Decimal = Decimal("0"),
        strategy_id: str | None = None,
        sector: str | None = None,
    ) -> PortfolioSnapshot:
        """Apply a fill event to update portfolio state.

        This is the keyword-argument API expected by the test suite.

        Parameters
        ----------
        idempotency_key:
            Unique key for deduplication.
        instrument_token:
            Numeric instrument identifier.
        instrument_symbol:
            Human-readable symbol.
        side:
            ``PositionSide.LONG`` (buy) or ``PositionSide.SHORT`` (sell).
        quantity:
            Number of units filled.
        price:
            Execution price per unit.
        fill_id:
            Broker or internal fill identifier.
        filled_at:
            Timezone-aware fill timestamp.
        order_id:
            Associated order identifier (optional).
        fees:
            Total charges for this fill.
        strategy_id:
            Strategy that initiated the order (optional).
        sector:
            Instrument sector (optional).

        Returns
        -------
        PortfolioSnapshot
            Updated portfolio state.

        Raises
        ------
        DuplicateEventError
            If *idempotency_key* was already applied.
        """
        snapshot = await self._state_manager.apply_fill(
            idempotency_key=idempotency_key,
            instrument_token=instrument_token,
            instrument_symbol=instrument_symbol,
            side=side,
            quantity=quantity,
            price=price,
            fill_id=fill_id,
            filled_at=filled_at,
            order_id=order_id,
            fees=fees,
            strategy_id=strategy_id,
            sector=sector,
        )

        side_str = "BUY" if side == PositionSide.LONG else "SELL"
        fill_event = PortfolioEvent(
            idempotency_key=idempotency_key,
            event_type=PortfolioEventType.FILL_RECEIVED,
            instrument_token=instrument_token,
            strategy_id=strategy_id,
            payload={
                "fill_id": fill_id,
                "side": side_str,
                "quantity": str(quantity),
                "price": str(price),
                "fees": str(fees),
                # instrument_symbol stored here so ledger.replay() can
                # reconstruct the full apply_fill() kwargs during recovery.
                "instrument_symbol": instrument_symbol,
                "order_id": order_id or "",
                "sector": sector or "",
            },
        )
        try:
            await self._persist_event(fill_event)
        except DuplicateEventError:
            pass

        if self._snapshot_repo is not None:
            await self._snapshot_repo.save(snapshot)

        logger.info(
            "Fill applied",
            extra={
                "fill_id": fill_id,
                "instrument_token": instrument_token,
                "side": side_str,
                "quantity": quantity,
            },
        )
        return snapshot

    async def apply_fill_dict(self, fill_event: dict[str, Any]) -> PortfolioSnapshot:
        """Apply a fill described as a broker-neutral dict.

        Convenience wrapper around :meth:`apply_fill` for callers that
        receive fill data as dicts (e.g. from broker adapters).

        Parameters
        ----------
        fill_event:
            Dict with keys: ``idempotency_key``/``fill_id``,
            ``instrument_token``, ``instrument_symbol``, ``side``,
            ``quantity``, ``price``, ``filled_at``, ``order_id``,
            ``fees``, ``strategy_id``, ``sector``.
        """
        idempotency_key = str(
            fill_event.get("idempotency_key") or fill_event.get("fill_id", "")
        )
        if not idempotency_key:
            from uuid import uuid4
            idempotency_key = f"fill-{uuid4()}"

        side_raw = str(fill_event.get("side", "BUY")).upper()
        side = PositionSide.LONG if side_raw == "BUY" else PositionSide.SHORT

        filled_at_raw = fill_event.get("filled_at")
        if filled_at_raw is None:
            filled_at: datetime = datetime.now(timezone.utc)
        elif isinstance(filled_at_raw, datetime):
            filled_at = filled_at_raw
            if filled_at.tzinfo is None:
                filled_at = filled_at.replace(tzinfo=timezone.utc)
        else:
            try:
                filled_at = datetime.fromisoformat(str(filled_at_raw))
                if filled_at.tzinfo is None:
                    filled_at = filled_at.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                filled_at = datetime.now(timezone.utc)

        return await self.apply_fill(
            idempotency_key=idempotency_key,
            instrument_token=int(fill_event["instrument_token"]),
            instrument_symbol=str(fill_event.get("instrument_symbol", "UNKNOWN")),
            side=side,
            quantity=int(fill_event["quantity"]),
            price=Decimal(str(fill_event["price"])),
            fill_id=str(fill_event.get("fill_id", idempotency_key)),
            filled_at=filled_at,
            order_id=fill_event.get("order_id") or fill_event.get("reservation_id"),
            fees=Decimal(str(fill_event.get("fees", "0"))),
            strategy_id=fill_event.get("strategy_id"),
            sector=fill_event.get("sector"),
        )

    # ──────────────────────────────────────────────────────────────────────
    # Market price updates
    # ──────────────────────────────────────────────────────────────────────

    async def update_market_price(
        self,
        instrument_token: int,
        price: Decimal,
        as_of: datetime,
    ) -> None:
        """Update the market price for an instrument."""
        await self._state_manager.update_market_price(
            instrument_token=instrument_token,
            market_price=price,
            as_of=as_of,
        )

    # ──────────────────────────────────────────────────────────────────────
    # Reconciliation
    # ──────────────────────────────────────────────────────────────────────

    async def reconcile(
        self,
        broker_snapshot: BrokerSnapshot | dict[str, Any],
        dry_run: bool = True,
    ) -> PortfolioReconciliationReport:
        """Reconcile local portfolio state against a broker snapshot.

        Parameters
        ----------
        broker_snapshot:
            Either a ``BrokerSnapshot`` typed object or a broker-neutral dict.
        dry_run:
            When ``True`` (default), analyse without mutating state.

        Returns
        -------
        PortfolioReconciliationReport
        """
        local_snapshot = self._snapshot_sync()

        # Convert BrokerSnapshot to dict if needed
        broker_dict: dict[str, Any]
        if isinstance(broker_snapshot, BrokerSnapshot):
            broker_dict = {
                "positions": [
                    {
                        "instrument_token": bp.instrument_token,
                        "quantity": bp.quantity,
                        "average_price": float(bp.average_price),
                        "realised_pnl": 0.0,
                        "product": "CNC",
                    }
                    for bp in broker_snapshot.positions
                ],
                "orders": [],
                "funds": {
                    "available_cash": float(broker_snapshot.cash),
                    "used_margin": 0.0,
                    "total": float(broker_snapshot.cash),
                },
                "trades": [],
                "as_of": broker_snapshot.as_of.isoformat(),
            }
        else:
            broker_dict = broker_snapshot  # type: ignore[assignment]

        # Delegate to the reconciliation engine
        report = await self._reconciliation_engine.reconcile(
            local_snapshot=local_snapshot,
            broker_snapshot=broker_dict,
            dry_run=dry_run,
        )

        if self._reconciliation_repo is not None:
            await self._reconciliation_repo.save(report)

        self._health_monitor.record_reconciliation(
            critical_count=report.critical_count,
            warning_count=report.warning_count,
            completed_at=report.completed_at,
        )

        # Critical discrepancies + not dry_run → halt
        if report.critical_count > 0 and not dry_run:
            self._state_manager.halt("critical_reconciliation_discrepancy")
            logger.error(
                "Portfolio halted due to critical reconciliation discrepancies",
                extra={
                    "portfolio_id": self.config.portfolio_id,
                    "critical_count": report.critical_count,
                },
            )

        # Emit reconciliation event (best-effort)
        recon_event = PortfolioEvent(
            idempotency_key=f"recon-{report.run_id}",
            event_type=PortfolioEventType.RECONCILIATION_COMPLETED,
            payload={
                "run_id": str(report.run_id),
                "critical_count": report.critical_count,
                "warning_count": report.warning_count,
                "portfolio_ready": report.portfolio_ready,
                "dry_run": dry_run,
            },
        )
        try:
            await self._persist_event(recon_event)
        except Exception as exc:
            logger.debug("Reconciliation event persist failed", extra={"error": str(exc)})

        logger.info(
            "Reconciliation complete",
            extra={
                "portfolio_id": self.config.portfolio_id,
                "critical_count": report.critical_count,
                "warning_count": report.warning_count,
                "portfolio_ready": report.portfolio_ready,
                "dry_run": dry_run,
            },
        )
        return report

    # ──────────────────────────────────────────────────────────────────────
    # Recovery
    # ──────────────────────────────────────────────────────────────────────

    async def recover(
        self,
        snapshot: PortfolioSnapshot | None = None,
        portfolio_id: str | None = None,
    ) -> PortfolioSnapshot:
        """Recover portfolio state from a persisted snapshot (or initialise fresh).

        If *snapshot* is provided, restores state from it.
        If *snapshot* is None and ``snapshot_repo`` is configured, attempts
        DB recovery.  Otherwise creates fresh state with zero cash.

        Parameters
        ----------
        snapshot:
            Optional snapshot to restore from.
        portfolio_id:
            Portfolio to recover (defaults to configured portfolio_id).

        Returns
        -------
        PortfolioSnapshot
            The recovered (or freshly initialised) portfolio state.
        """
        pid = portfolio_id or self.config.portfolio_id

        # ── Determine which snapshot to restore from ──────────────────
        restore_target: PortfolioSnapshot | None = snapshot
        if restore_target is None and self._snapshot_repo is not None:
            restore_target = await self._snapshot_repo.get_latest_valid(pid)

        if restore_target is not None:
            # Full state restore: cash + margin + positions + P&L.
            # restore_from_snapshot() is the correct entry-point; it must NOT
            # be replaced with initialise() which discards positions.
            self._state_manager.restore_from_snapshot(restore_target)

            # Replay any FILL_RECEIVED events that occurred after the snapshot
            # was taken so the in-memory state catches up to present.
            if self._event_repo is not None:
                events = await self._event_repo.get_events_after(
                    portfolio_id=pid,
                    after=restore_target.snapshotted_at,
                )
                if events:
                    replayed = await self._ledger.replay(events, self._state_manager)
                    logger.info(
                        "Recovery replayed %d events after snapshot v=%d",
                        replayed,
                        restore_target.version,
                        extra={"portfolio_id": pid},
                    )

            # Transition to READY now that state is rebuilt.
            self._state_manager._status = PortfolioStatus.READY
            self._state_manager._last_updated = datetime.now(timezone.utc)

            self._health_monitor.record_recovery(success=True)
            self._health_monitor.record_reconciliation(
                critical_count=0, warning_count=0, completed_at=datetime.now(timezone.utc)
            )
            recovered = self._state_manager.get_snapshot(pid)
            logger.info(
                "Portfolio recovered: v=%d positions=%d cash=%s",
                recovered.version,
                len(recovered.open_positions),
                str(recovered.cash.total),
                extra={"portfolio_id": pid},
            )
            return recovered

        # No snapshot available — fresh initialisation from configured capital.
        # Use config.initial_capital (not zero) so that allocations and limits
        # are immediately functional on a first-time or post-snapshot-loss start.
        fresh = await self._state_manager.initialise(self.config.initial_capital, pid)
        self._health_monitor.record_recovery(success=True)
        self._health_monitor.record_reconciliation(
            critical_count=0, warning_count=0, completed_at=datetime.now(timezone.utc)
        )
        logger.info(
            "Portfolio bootstrapped with initial_capital=%s (no prior snapshot)",
            str(self.config.initial_capital),
            extra={"portfolio_id": pid},
        )
        return fresh

    # ──────────────────────────────────────────────────────────────────────
    # Snapshot management
    # ──────────────────────────────────────────────────────────────────────

    async def create_snapshot(self) -> PortfolioSnapshot:
        """Create and persist a portfolio snapshot.

        Returns
        -------
        PortfolioSnapshot
        """
        snapshot = self._snapshot_sync()

        if self._snapshot_repo is not None:
            await self._snapshot_repo.save(snapshot)

        snap_event = PortfolioEvent(
            idempotency_key=f"snap-{snapshot.snapshot_id}",
            event_type=PortfolioEventType.SNAPSHOT_TAKEN,
            payload={
                "snapshot_id": str(snapshot.snapshot_id),
                "version": snapshot.version,
                "status": snapshot.status.value,
            },
        )
        try:
            await self._persist_event(snap_event)
        except Exception as exc:
            logger.debug("Snapshot event persist failed", extra={"error": str(exc)})

        logger.debug(
            "Snapshot created",
            extra={
                "snapshot_id": str(snapshot.snapshot_id),
                "version": snapshot.version,
            },
        )
        return snapshot

    # ──────────────────────────────────────────────────────────────────────
    # Health
    # ──────────────────────────────────────────────────────────────────────

    async def get_health(self) -> PortfolioHealth:
        """Return the current health of the portfolio service.

        Returns
        -------
        PortfolioHealth
        """
        snapshot = self._snapshot_sync()
        return await self._health_monitor.compute_health(snapshot)
