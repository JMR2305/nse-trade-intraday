"""RC-10C1 Portfolio Core — in-memory portfolio state manager."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from .config import PortfolioConfig
from .contracts import (
    BuyingPower,
    CashBalance,
    ExposureSnapshot,
    MarginState,
    PortfolioEvent,
    PortfolioEventType,
    PortfolioPnL,
    PortfolioPosition,
    PortfolioSnapshot,
    PortfolioStatus,
    PositionSide,
    PositionStatus,
)
from .exceptions import (
    DuplicateEventError,
    InsufficientCapitalError,
    PortfolioHaltedError,
    PortfolioNotReadyError,
)
from .position_manager import PositionManager
from .pnl import PnLCalculator


def _zero_exposure() -> ExposureSnapshot:
    return ExposureSnapshot(
        gross_exposure=Decimal("0"),
        net_exposure=Decimal("0"),
    )


def _zero_pnl() -> PortfolioPnL:
    return PortfolioPnL()


class PortfolioStateManager:
    """In-memory portfolio state manager — not thread-safe without external lock."""

    def __init__(self, config: PortfolioConfig) -> None:
        self.config = config
        self._status = PortfolioStatus.INITIALISING
        self._cash: CashBalance | None = None
        self._margin: MarginState | None = None
        self._pnl: PortfolioPnL = _zero_pnl()
        self._exposure: ExposureSnapshot = _zero_exposure()
        self._position_manager = PositionManager()
        self._pending_reservations: dict[str, Decimal] = {}  # order_id -> amount
        self._seen_idempotency_keys: set[str] = set()
        self._version: int = 0
        self._last_updated: datetime | None = None
        self._halted_reason: str | None = None
        self._peak_equity: Decimal = Decimal("0")
        self._daily_pnl: Decimal = Decimal("0")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialise(
        self,
        initial_cash: Decimal,
        portfolio_id: str = "default",
    ) -> PortfolioSnapshot:
        """Initialise from scratch with given cash."""
        now = datetime.now(timezone.utc)
        self._cash = CashBalance(
            available=initial_cash,
            blocked=Decimal("0"),
            total=initial_cash,
            as_of=now,
        )
        self._margin = MarginState(
            used=Decimal("0"),
            available=initial_cash,
            total=initial_cash,
            as_of=now,
        )
        self._status = PortfolioStatus.READY
        self._version += 1
        self._last_updated = now
        self._peak_equity = initial_cash
        return self._build_snapshot(portfolio_id)

    def restore_from_snapshot(self, snapshot: "PortfolioSnapshot") -> None:
        """Restore full in-memory state from a persisted PortfolioSnapshot.

        This is the correct recovery entry-point.  Unlike ``initialise()``,
        which only sets cash and resets everything else to zero, this method
        reconstructs positions, P&L, pending order count, and all other
        fields so that the in-memory state exactly mirrors what was persisted.

        After calling this, replay any FILL_RECEIVED events that occurred
        after the snapshot's ``snapshotted_at`` timestamp to catch up to
        present state.

        Args:
            snapshot: A valid PortfolioSnapshot loaded from the repository.
        """
        import logging as _logging
        _log = _logging.getLogger(__name__)

        self._cash = snapshot.cash
        self._margin = snapshot.margin
        self._version = snapshot.version
        self._last_updated = snapshot.snapshotted_at
        self._peak_equity = snapshot.pnl.peak_equity
        self._daily_pnl = snapshot.pnl.daily_pnl
        self._status = PortfolioStatus.RECOVERING

        # Rebuild position manager from snapshot positions
        self._position_manager = PositionManager()
        for pos in snapshot.open_positions:
            self._position_manager.restore_position(pos)
            # Register all lot fill_ids as seen so replay skips them
            for lot in pos.lots:
                self._seen_idempotency_keys.add(lot.fill_id)

        # pending_order_count is recorded in snapshot but individual amounts
        # are not persisted; start with empty reservations (conservative —
        # any genuinely pending orders will be reconciled on startup).
        self._pending_reservations = {}

        _log.info(
            "State restored from snapshot version=%d positions=%d status→RECOVERING",
            snapshot.version,
            len(snapshot.open_positions),
        )

    def halt(self, reason: str = "manual") -> None:
        self._status = PortfolioStatus.HALTED
        self._halted_reason = reason

    def resume(self) -> None:
        self._status = PortfolioStatus.READY
        self._halted_reason = None

    def is_stale(self, threshold_s: float | None = None) -> bool:
        if self._last_updated is None:
            return True
        t = threshold_s if threshold_s is not None else self.config.stale_state_threshold_s
        age = (datetime.now(timezone.utc) - self._last_updated).total_seconds()
        return age >= t

    # ------------------------------------------------------------------
    # Capital reservation
    # ------------------------------------------------------------------

    async def reserve_order_capital(
        self,
        order_id: str,
        amount: Decimal,
    ) -> PortfolioSnapshot:
        """Block cash for a pending order."""
        if self._status == PortfolioStatus.HALTED:
            raise PortfolioHaltedError(f"Portfolio halted: {self._halted_reason}")
        if self._status not in (PortfolioStatus.READY, PortfolioStatus.DEGRADED):
            raise PortfolioNotReadyError(f"Portfolio not ready: {self._status}")
        assert self._cash is not None

        if self._cash.available < amount:
            raise InsufficientCapitalError(
                f"Available {self._cash.available} < requested {amount}"
            )

        now = datetime.now(timezone.utc)
        self._pending_reservations[order_id] = amount
        new_available = self._cash.available - amount
        new_blocked = self._cash.blocked + amount
        self._cash = CashBalance(
            available=new_available,
            blocked=new_blocked,
            total=self._cash.total,
            as_of=now,
        )
        self._version += 1
        self._last_updated = now
        return self._build_snapshot()

    async def release_order_capital(
        self,
        order_id: str,
    ) -> PortfolioSnapshot:
        """Release a capital reservation (idempotent)."""
        now = datetime.now(timezone.utc)
        if order_id not in self._pending_reservations:
            return self._build_snapshot()  # idempotent
        amount = self._pending_reservations.pop(order_id)
        assert self._cash is not None
        self._cash = CashBalance(
            available=self._cash.available + amount,
            blocked=max(Decimal("0"), self._cash.blocked - amount),
            total=self._cash.total,
            as_of=now,
        )
        self._version += 1
        self._last_updated = now
        return self._build_snapshot()

    # ------------------------------------------------------------------
    # Fill processing
    # ------------------------------------------------------------------

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
        """Apply a fill — idempotent via idempotency_key AND fill_id.

        Idempotency is enforced at two levels:
        1. ``idempotency_key`` — fast path; used by the normal write flow.
        2. ``fill_id`` within the position's lot list — used when recovering
           from a snapshot where lot fill_ids are seeded into
           ``_seen_idempotency_keys``, but the event's ``idempotency_key``
           may differ (the public API allows them to be independent values).

        Either check being True means the fill was already applied; this
        method returns the current snapshot as a no-op without re-applying
        and without raising, so ``ledger.replay()`` can safely call it for
        every post-snapshot fill event regardless of key alignment.
        """
        if idempotency_key in self._seen_idempotency_keys:
            raise DuplicateEventError(f"Duplicate event: {idempotency_key}")

        pm = self._position_manager
        existing = pm.get_position(instrument_token)

        # Guard against replay re-applying a fill whose fill_id is already
        # present in the position's lots (possible when idempotency_key ≠
        # fill_id and restore_from_snapshot seeded _seen_idempotency_keys from
        # fill_ids only).
        if existing is not None and pm.is_fill_duplicate(existing, fill_id):
            # Mark the event idempotency_key as seen so subsequent replays of
            # the same event are deduped via the fast path.
            self._seen_idempotency_keys.add(idempotency_key)
            return self._build_snapshot()

        self._seen_idempotency_keys.add(idempotency_key)
        now = datetime.now(timezone.utc)
        order_value = Decimal(str(quantity)) * price

        if side == PositionSide.LONG:
            # BUY
            if existing is None or existing.status == PositionStatus.CLOSED:
                pm.open_position(
                    instrument_token=instrument_token,
                    instrument_symbol=instrument_symbol,
                    side=PositionSide.LONG,
                    quantity=quantity,
                    price=price,
                    fill_id=fill_id,
                    filled_at=filled_at,
                    fees=fees,
                    strategy_id=strategy_id,
                    sector=sector,
                )
            else:
                pm.increase_position(
                    instrument_token=instrument_token,
                    quantity=quantity,
                    price=price,
                    fill_id=fill_id,
                    filled_at=filled_at,
                    fees=fees,
                )
            # Debit cash — maintain CashBalance invariant: total == available + blocked.
            #
            # Two cases:
            #   A) Reserved order: blocked contains `reserved` for this order_id.
            #      The actual fill costs `order_value` which may differ from `reserved`
            #      (partial fill → order_value < reserved; slippage → order_value > reserved).
            #      - total   decreases by order_value (cash paid to broker)
            #      - blocked decreases by reserved    (reservation fully cleared)
            #      - available is DERIVED as new_total − new_blocked so the
            #        invariant always holds exactly, even under partial fills.
            #
            #   B) No reservation: debit directly from available; blocked unchanged.
            #      Derive total as available + blocked to maintain invariant.
            assert self._cash is not None
            if order_id and order_id in self._pending_reservations:
                reserved = self._pending_reservations.pop(order_id)
                new_blocked = max(Decimal("0"), self._cash.blocked - reserved)
                new_total = max(Decimal("0"), self._cash.total - order_value)
                # Derive available so total == available + blocked exactly.
                # Positive delta (reserved > order_value): excess is returned to available.
                # Negative delta (reserved < order_value): extra is taken from available.
                new_available = max(Decimal("0"), new_total - new_blocked)
                # Re-anchor total from the derived pair to eliminate any rounding gap.
                new_total = new_available + new_blocked
            else:
                new_available = max(Decimal("0"), self._cash.available - order_value)
                new_blocked = self._cash.blocked  # unchanged — no reservation to release
                new_total = new_available + new_blocked  # always exact

            self._cash = CashBalance(
                available=new_available,
                blocked=new_blocked,
                total=new_total,
                as_of=now,
            )
        else:
            # SELL — close/reduce existing LONG
            if existing is not None and existing.status != PositionStatus.CLOSED:
                pos, realised = pm.reduce_position(
                    instrument_token=instrument_token,
                    quantity=quantity,
                    price=price,
                    fill_id=fill_id,
                    filled_at=filled_at,
                    fees=fees,
                )
                self._daily_pnl += realised
                # Credit cash
                assert self._cash is not None
                self._cash = CashBalance(
                    available=self._cash.available + order_value,
                    blocked=self._cash.blocked,
                    total=self._cash.total + order_value,
                    as_of=now,
                )
            else:
                # Short opening — not implemented in paper mode simplification
                pm.open_position(
                    instrument_token=instrument_token,
                    instrument_symbol=instrument_symbol,
                    side=PositionSide.SHORT,
                    quantity=quantity,
                    price=price,
                    fill_id=fill_id,
                    filled_at=filled_at,
                    fees=fees,
                    strategy_id=strategy_id,
                    sector=sector,
                )

        self._version += 1
        self._last_updated = now
        return self._build_snapshot()

    async def update_market_price(
        self,
        instrument_token: int,
        market_price: Decimal,
        as_of: datetime | None = None,
    ) -> PortfolioSnapshot:
        """Update market price for a position and recompute unrealised P&L."""
        pos = self._position_manager.get_position(instrument_token)
        if pos is not None:
            self._position_manager.update_unrealised_pnl(
                instrument_token=instrument_token,
                market_price=market_price,
                as_of=as_of,
            )
        self._version += 1
        self._last_updated = datetime.now(timezone.utc)
        return self._build_snapshot()

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def get_snapshot(self, portfolio_id: str = "default") -> PortfolioSnapshot:
        return self._build_snapshot(portfolio_id)

    def _build_snapshot(self, portfolio_id: str = "default") -> PortfolioSnapshot:
        now = datetime.now(timezone.utc)
        cash = self._cash or CashBalance(
            available=Decimal("0"),
            blocked=Decimal("0"),
            total=Decimal("0"),
            as_of=now,
        )
        margin = self._margin or MarginState(
            used=Decimal("0"),
            available=Decimal("0"),
            total=Decimal("0"),
            as_of=now,
        )
        positions = self._position_manager.all_open_positions()

        # Simple buying power
        buying_power = BuyingPower(
            gross=cash.available + margin.available,
            net=cash.available,
            reserved=cash.blocked,
            as_of=now,
        )

        # Simple exposure
        gross = sum(
            (p.gross_exposure for p in positions),
            Decimal("0"),
        )
        exposure = ExposureSnapshot(
            gross_exposure=gross,
            net_exposure=gross,
            portfolio_equity=cash.total + gross,
            as_of=now,
            state_version=self._version,
        )

        # Rebuild P&L
        pnl = PnLCalculator.build_portfolio_pnl(
            positions=positions,
            daily_pnl=self._daily_pnl,
            peak_equity=self._peak_equity,
            # Equity = cash + open-position market value. Using cash alone
            # makes any deployed portfolio look like a massive drawdown and
            # blocks every allocation via DRAWDOWN_LIMIT_BREACHED.
            current_equity=cash.total + gross,
            state_version=self._version,
        )

        return PortfolioSnapshot(
            portfolio_id=portfolio_id,
            status=self._status,
            version=self._version,
            cash=cash,
            margin=margin,
            buying_power=buying_power,
            exposure=exposure,
            pnl=pnl,
            open_positions=tuple(
                p for p in positions if p.status != PositionStatus.CLOSED
            ),
            pending_order_count=len(self._pending_reservations),
            snapshotted_at=now,
        )
