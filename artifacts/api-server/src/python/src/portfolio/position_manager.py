"""RC-10C1 Portfolio Core — position lifecycle manager.

PositionManager handles the full lifecycle of PortfolioPosition objects:
opening, increasing, reducing, closing, and unrealised P&L updates.

Design notes:
- All monetary arithmetic uses Decimal with ROUND_HALF_UP.
- Lot-level tracking via PortfolioLot enables FIFO realised P&L.
- Thread safety: the caller (StateManager) must hold an asyncio.Lock before
  invoking any method here. This class itself is NOT thread-safe internally.
- Methods mutate position in-place and also return the same object for
  convenience. Callers should not rely on the returned reference being
  distinct.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from .contracts import PortfolioLot, PortfolioPosition, PositionSide, PositionStatus
from .exceptions import (
    InvalidPositionTransitionError,
    NegativeQuantityError,
)

logger = logging.getLogger(__name__)

# Rounding quantiser for monetary values (paise precision)
_PAISE = Decimal("0.01")
# Rounding quantiser for price (store 4dp internally)
_PRICE_DP = Decimal("0.0001")
_ZERO = Decimal("0")


def _q(value: Decimal, places: Decimal = _PAISE) -> Decimal:
    """Round *value* to *places* using ROUND_HALF_UP."""
    return value.quantize(places, rounding=ROUND_HALF_UP)


class PositionManager:
    """Manages the lifecycle of individual PortfolioPosition objects.

    This class maintains an internal collection of open positions and
    provides methods for opening, increasing, reducing, and closing them.
    """

    def __init__(self) -> None:
        self._positions: dict[int, PortfolioPosition] = {}

    # ------------------------------------------------------------------
    # Collection management
    # ------------------------------------------------------------------

    def get_position(self, instrument_token: int) -> Optional[PortfolioPosition]:
        """Return the position for *instrument_token*, or None."""
        return self._positions.get(instrument_token)

    def all_open_positions(self) -> list[PortfolioPosition]:
        """Return all tracked positions (open, reducing, pending)."""
        return list(self._positions.values())

    def position_count(self) -> int:
        """Return the number of tracked positions."""
        return len(self._positions)

    def restore_position(self, position: PortfolioPosition) -> None:
        """Restore a position directly from a snapshot (no lot recalculation).

        Used exclusively by ``PortfolioStateManager.restore_from_snapshot()``
        during recovery.  The position object is trusted as-is from the
        persisted snapshot.

        Args:
            position: A PortfolioPosition previously serialised into a snapshot.
        """
        self._positions[position.instrument_token] = position
        logger.debug(
            "Restored position from snapshot: token=%d symbol=%s qty=%d",
            position.instrument_token,
            position.instrument_symbol,
            position.open_quantity,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def open_position(
        self,
        instrument_token: int,
        instrument_symbol: str,
        side: PositionSide,
        quantity: int,
        price: Decimal,
        fill_id: str,
        filled_at: datetime,
        fees: Decimal = Decimal("0"),
        strategy_id: Optional[str] = None,
        sector: Optional[str] = None,
    ) -> PortfolioPosition:
        """Create and return a new OPEN PortfolioPosition.

        Args:
            instrument_token: Unique instrument identifier.
            instrument_symbol: Human-readable symbol (e.g. "RELIANCE").
            side: LONG or SHORT.
            quantity: Number of units in this first fill.
            price: Executed price per unit.
            fill_id: Idempotency key for this fill.
            filled_at: Fill timestamp.
            fees: Charges associated with this fill (default 0).
            strategy_id: Originating strategy (optional).
            sector: Sector tag for exposure bucketing (optional).

        Returns:
            A freshly created PortfolioPosition with status=OPEN.

        Raises:
            InvalidPositionTransitionError: if *quantity* <= 0.
        """
        fill_qty = quantity
        fill_price = price
        if fill_qty <= 0:
            raise InvalidPositionTransitionError(
                f"open_position requires quantity > 0, got {fill_qty}"
            )

        lot = PortfolioLot(
            fill_id=fill_id,
            quantity=fill_qty,
            entry_price=_q(fill_price, _PRICE_DP),
            filled_at=filled_at,
            fees=_q(fees),
            strategy_id=strategy_id,
        )

        position = PortfolioPosition(
            instrument_token=instrument_token,
            instrument_symbol=instrument_symbol,
            side=side,
            status=PositionStatus.OPEN,
            open_quantity=fill_qty,
            closed_quantity=0,
            average_entry_price=_q(fill_price, _PRICE_DP),
            unrealised_pnl=Decimal("0"),
            realised_pnl=Decimal("0"),
            total_fees=_q(fees),
            lots=[lot],
            strategy_id=strategy_id,
            sector=sector,
            opened_at=filled_at,
            version=1,
        )

        self._positions[instrument_token] = position

        logger.info(
            "Opened position %s %s %s qty=%d @%s fees=%s",
            position.position_id,
            instrument_symbol,
            side.value,
            fill_qty,
            fill_price,
            fees,
        )
        return position

    def increase_position(
        self,
        instrument_token: int,
        quantity: int,
        price: Decimal,
        fill_id: str,
        filled_at: datetime,
        fees: Decimal = Decimal("0"),
    ) -> PortfolioPosition:
        """Add to an existing open position (averaging in).

        Args:
            instrument_token: Instrument to increase.
            quantity: Additional units being added.
            price: Executed price for the new fill.
            fill_id: Idempotency key for this fill.
            filled_at: Fill timestamp.
            fees: Charges for this fill.

        Returns:
            The mutated position (same object).

        Raises:
            InvalidPositionTransitionError: if position is not found, not OPEN
                or REDUCING, quantity <= 0, or fill_id is a duplicate.
        """
        position = self._positions.get(instrument_token)
        if position is None:
            raise InvalidPositionTransitionError(
                f"No position found for instrument_token={instrument_token}"
            )

        fill_qty = quantity
        fill_price = price

        if position.status not in (PositionStatus.OPEN, PositionStatus.REDUCING):
            raise InvalidPositionTransitionError(
                f"Cannot increase position {position.position_id} in status "
                f"{position.status.value}; must be OPEN or REDUCING"
            )
        if fill_qty <= 0:
            raise InvalidPositionTransitionError(
                f"increase_position requires quantity > 0, got {fill_qty}"
            )
        if self.is_fill_duplicate(position, fill_id):
            raise InvalidPositionTransitionError(
                f"Duplicate fill_id '{fill_id}' on position {position.position_id}"
            )

        new_avg = self._calculate_weighted_avg_price(
            position, position.open_quantity, fill_qty, fill_price
        )

        lot = PortfolioLot(
            fill_id=fill_id,
            quantity=fill_qty,
            entry_price=_q(fill_price, _PRICE_DP),
            filled_at=filled_at,
            fees=_q(fees),
            strategy_id=position.strategy_id,
        )

        position.open_quantity += fill_qty
        position.average_entry_price = new_avg
        position.total_fees = _q(position.total_fees + fees)
        position.lots = position.lots + [lot]
        position.status = PositionStatus.OPEN
        position.version += 1

        logger.info(
            "Increased position %s %s qty+%d @%s new_avg=%s",
            position.position_id,
            position.instrument_symbol,
            fill_qty,
            fill_price,
            new_avg,
        )
        return position

    def reduce_position(
        self,
        instrument_token: int,
        quantity: int,
        price: Decimal,
        fill_id: str,
        filled_at: datetime,
        fees: Decimal = Decimal("0"),
    ) -> tuple[PortfolioPosition, Decimal]:
        """Partially or fully close a position using FIFO lot matching.

        Args:
            instrument_token: Instrument to reduce.
            quantity: Number of units being closed.
            price: Exit price per unit.
            fill_id: Idempotency key for this fill.
            filled_at: Fill timestamp.
            fees: Charges attributed to this closing fill.

        Returns:
            Tuple of (updated_position, realised_pnl_this_fill).

        Raises:
            InvalidPositionTransitionError: if position not found, is CLOSED or
                PENDING, quantity > open_quantity, or fill_id is duplicate.
            NegativeQuantityError: if FIFO matching has an internal inconsistency.
        """
        position = self._positions.get(instrument_token)
        if position is None:
            raise InvalidPositionTransitionError(
                f"No position found for instrument_token={instrument_token}"
            )

        fill_qty = quantity
        fill_price = price

        if position.status == PositionStatus.CLOSED:
            raise InvalidPositionTransitionError(
                f"Cannot reduce position {position.position_id}: already CLOSED"
            )
        if position.status == PositionStatus.PENDING:
            raise InvalidPositionTransitionError(
                f"Cannot reduce position {position.position_id}: status is PENDING"
            )
        if fill_qty <= 0:
            raise InvalidPositionTransitionError(
                f"reduce_position requires quantity > 0, got {fill_qty}"
            )
        if fill_qty > position.open_quantity:
            raise InvalidPositionTransitionError(
                f"quantity {fill_qty} exceeds open_quantity "
                f"{position.open_quantity} for position {position.position_id}"
            )
        if self.is_fill_duplicate(position, fill_id):
            raise InvalidPositionTransitionError(
                f"Duplicate fill_id '{fill_id}' on position {position.position_id}"
            )

        realised = self.fifo_pnl(position.lots, fill_qty, fill_price, position.side)

        # Consume lots FIFO, splitting partial lots
        remaining_to_close = fill_qty
        new_lots: list[PortfolioLot] = []
        for lot in position.lots:
            if remaining_to_close <= 0:
                new_lots.append(lot)
                continue
            if lot.quantity <= remaining_to_close:
                # Entire lot consumed
                remaining_to_close -= lot.quantity
            else:
                # Partial lot — keep the remainder
                remaining_qty = lot.quantity - remaining_to_close
                partial_lot = PortfolioLot(
                    lot_id=lot.lot_id,
                    fill_id=lot.fill_id,
                    quantity=remaining_qty,
                    entry_price=lot.entry_price,
                    filled_at=lot.filled_at,
                    fees=lot.fees,
                    strategy_id=lot.strategy_id,
                    metadata=lot.metadata,
                )
                new_lots.append(partial_lot)
                remaining_to_close = 0

        if remaining_to_close != 0:
            raise NegativeQuantityError(
                f"FIFO matching left {remaining_to_close} units unmatched — "
                f"internal inconsistency in position {position.position_id}"
            )

        new_open_qty = position.open_quantity - fill_qty
        if new_open_qty < 0:
            raise NegativeQuantityError(
                f"open_quantity would be negative ({new_open_qty}) "
                f"for position {position.position_id}"
            )

        position.lots = new_lots
        position.open_quantity = new_open_qty
        position.closed_quantity += fill_qty
        position.realised_pnl = _q(position.realised_pnl + realised)
        position.total_fees = _q(position.total_fees + fees)
        position.version += 1

        if new_open_qty == 0:
            position.status = PositionStatus.CLOSED
            position.closed_at = filled_at
        else:
            position.status = PositionStatus.REDUCING

        logger.info(
            "Reduced position %s %s qty=%d @%s realised=%s remaining=%d status=%s",
            position.position_id,
            position.instrument_symbol,
            fill_qty,
            fill_price,
            realised,
            new_open_qty,
            position.status.value,
        )
        return position, realised

    def update_unrealised_pnl(
        self,
        instrument_token: int,
        market_price: Decimal,
        as_of: Optional[datetime] = None,
    ) -> Optional[PortfolioPosition]:
        """Recalculate unrealised P&L from current market price.

        Args:
            instrument_token: Instrument to update.
            market_price: Current market price per unit.
            as_of: Optional timestamp of the price.

        Returns:
            The mutated position or None if instrument not tracked.
        """
        position = self._positions.get(instrument_token)
        if position is None:
            return None

        if position.status == PositionStatus.CLOSED or position.open_quantity == 0:
            position.unrealised_pnl = Decimal("0")
            position.last_market_price = market_price
            position.last_price_as_of = as_of or datetime.now(timezone.utc)
            return position

        open_qty = Decimal(str(position.open_quantity))

        if position.side == PositionSide.LONG:
            raw_pnl = (market_price - position.average_entry_price) * open_qty
        else:
            raw_pnl = (position.average_entry_price - market_price) * open_qty

        position.unrealised_pnl = _q(raw_pnl)
        position.last_market_price = market_price
        position.last_price_as_of = as_of or datetime.now(timezone.utc)

        logger.debug(
            "Updated unrealised P&L for %s %s: %s",
            position.instrument_symbol,
            position.side.value,
            position.unrealised_pnl,
        )
        return position

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    def _calculate_weighted_avg_price(
        self,
        position: PortfolioPosition,
        existing_qty: int,
        new_qty: int,
        new_price: Decimal,
    ) -> Decimal:
        """Compute the weighted average entry price after adding *new_qty* at *new_price*."""
        total_qty = existing_qty + new_qty
        if total_qty == 0:
            return Decimal("0")

        existing_value = Decimal(str(existing_qty)) * position.average_entry_price
        new_value = Decimal(str(new_qty)) * new_price
        avg = (existing_value + new_value) / Decimal(str(total_qty))
        return _q(avg, _PRICE_DP)

    # Keep original name for backward compat with state_manager.py
    def calculate_weighted_avg_price(
        self,
        position: PortfolioPosition,
        existing_qty: int,
        new_qty: int,
        new_price: Decimal,
    ) -> Decimal:
        """Public alias for _calculate_weighted_avg_price."""
        return self._calculate_weighted_avg_price(position, existing_qty, new_qty, new_price)

    def is_fill_duplicate(self, position: PortfolioPosition, fill_id: str) -> bool:
        """Return True if *fill_id* already exists in any lot of *position*."""
        return any(lot.fill_id == fill_id for lot in position.lots)

    def fifo_pnl(
        self,
        lots: list[PortfolioLot],
        close_qty: int,
        close_price: Decimal,
        side: PositionSide,
    ) -> Decimal:
        """Calculate realised P&L for *close_qty* units using FIFO matching.

        Matches against the oldest lots first. Does not mutate *lots*.

        For LONG:  each unit P&L = close_price - lot.entry_price
        For SHORT: each unit P&L = lot.entry_price - close_price

        Args:
            lots: Ordered list of open lots (oldest first).
            close_qty: Number of units being closed.
            close_price: Exit price per unit.
            side: Position side (LONG or SHORT).

        Returns:
            Total gross realised P&L for *close_qty* units, rounded to paise.

        Raises:
            InvalidPositionTransitionError: if *close_qty* exceeds total lot
                quantity (internal consistency error).
        """
        total_pnl = Decimal("0")
        remaining = close_qty

        for lot in lots:
            if remaining <= 0:
                break
            matched = min(lot.quantity, remaining)
            matched_dec = Decimal(str(matched))

            if side == PositionSide.LONG:
                lot_pnl = (close_price - lot.entry_price) * matched_dec
            else:
                lot_pnl = (lot.entry_price - close_price) * matched_dec

            total_pnl += lot_pnl
            remaining -= matched

        if remaining > 0:
            raise InvalidPositionTransitionError(
                f"FIFO matching exhausted all lots but {remaining} units remain unmatched. "
                f"close_qty={close_qty}, matched={close_qty - remaining}"
            )

        return _q(total_pnl)
