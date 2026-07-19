"""P&L calculation engine.

Deterministic, pure functions for realized and unrealized P&L.
No side effects.  All monetary values use Decimal.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from src.execution.contracts import ExecutionOrderSide
from src.execution.portfolio import PositionDirection, PositionSnapshot


# ------------------------------------------------------------------
# Realized P&L computation
# ------------------------------------------------------------------

class PnLCalculator:
    """Deterministic P&L calculator.

    Computes realized P&L from fill events against current position state.
    """

    @staticmethod
    def compute_realized_pnl(
        current_position: PositionSnapshot,
        fill_side: ExecutionOrderSide,
        fill_quantity: int,
        fill_price: Decimal,
    ) -> tuple[Decimal, PositionSnapshot, str]:
        """Compute realized P&L and new position state from a fill.

        Returns:
            (realized_pnl, new_position, position_impact)

        position_impact is one of: OPEN, ADD, REDUCE, CLOSE, REVERSE
        """
        if fill_quantity <= 0:
            raise ValueError(f"fill_quantity must be positive, got {fill_quantity}")
        if fill_price <= 0:
            raise ValueError(f"fill_price must be positive, got {fill_price}")

        # FLAT position — always OPEN
        if current_position.is_flat:
            if fill_side == ExecutionOrderSide.BUY:
                new_pos = _build_position(
                    instrument_token=current_position.instrument_token,
                    net_quantity=fill_quantity,
                    direction=PositionDirection.LONG,
                    avg_buy_price=fill_price,
                    avg_sell_price=Decimal("0"),
                    total_buy_quantity=fill_quantity,
                    total_sell_quantity=0,
                    total_buy_value=Decimal(fill_quantity) * fill_price,
                    total_sell_value=Decimal("0"),
                    realized_pnl=Decimal("0"),
                    unrealized_pnl=Decimal("0"),
                    market_price=current_position.market_price,
                    market_timestamp=current_position.market_timestamp,
                )
                return Decimal("0"), new_pos, "OPEN"
            else:  # SELL
                new_pos = _build_position(
                    instrument_token=current_position.instrument_token,
                    net_quantity=-fill_quantity,
                    direction=PositionDirection.SHORT,
                    avg_buy_price=Decimal("0"),
                    avg_sell_price=fill_price,
                    total_buy_quantity=0,
                    total_sell_quantity=fill_quantity,
                    total_buy_value=Decimal("0"),
                    total_sell_value=Decimal(fill_quantity) * fill_price,
                    realized_pnl=Decimal("0"),
                    unrealized_pnl=Decimal("0"),
                    market_price=current_position.market_price,
                    market_timestamp=current_position.market_timestamp,
                )
                return Decimal("0"), new_pos, "OPEN"

        # LONG position
        if current_position.is_long:
            if fill_side == ExecutionOrderSide.BUY:
                # Adding to long — ADD
                new_total_buy_qty = current_position.total_buy_quantity + fill_quantity
                new_total_buy_val = current_position.total_buy_value + (Decimal(fill_quantity) * fill_price)
                new_avg_buy = new_total_buy_val / Decimal(new_total_buy_qty)
                new_net_qty = current_position.net_quantity + fill_quantity

                new_pos = _build_position(
                    instrument_token=current_position.instrument_token,
                    net_quantity=new_net_qty,
                    direction=PositionDirection.LONG,
                    avg_buy_price=new_avg_buy,
                    avg_sell_price=current_position.average_sell_price,
                    total_buy_quantity=new_total_buy_qty,
                    total_sell_quantity=current_position.total_sell_quantity,
                    total_buy_value=new_total_buy_val,
                    total_sell_value=current_position.total_sell_value,
                    realized_pnl=current_position.realized_pnl,
                    unrealized_pnl=Decimal("0"),  # recalc later
                    market_price=current_position.market_price,
                    market_timestamp=current_position.market_timestamp,
                )
                return Decimal("0"), new_pos, "ADD"

            else:  # SELL against LONG
                if fill_quantity < current_position.net_quantity:
                    # Partial exit — REDUCE
                    realized = (fill_price - current_position.average_buy_price) * Decimal(fill_quantity)
                    new_net_qty = current_position.net_quantity - fill_quantity
                    new_total_sell_qty = current_position.total_sell_quantity + fill_quantity
                    new_total_sell_val = current_position.total_sell_value + (Decimal(fill_quantity) * fill_price)

                    new_pos = _build_position(
                        instrument_token=current_position.instrument_token,
                        net_quantity=new_net_qty,
                        direction=PositionDirection.LONG,
                        avg_buy_price=current_position.average_buy_price,
                        avg_sell_price=new_total_sell_val / Decimal(new_total_sell_qty) if new_total_sell_qty > 0 else Decimal("0"),
                        total_buy_quantity=current_position.total_buy_quantity,
                        total_sell_quantity=new_total_sell_qty,
                        total_buy_value=current_position.total_buy_value,
                        total_sell_value=new_total_sell_val,
                        realized_pnl=current_position.realized_pnl + realized,
                        unrealized_pnl=Decimal("0"),
                        market_price=current_position.market_price,
                        market_timestamp=current_position.market_timestamp,
                    )
                    return realized, new_pos, "REDUCE"

                elif fill_quantity == current_position.net_quantity:
                    # Complete exit — CLOSE
                    realized = (fill_price - current_position.average_buy_price) * Decimal(fill_quantity)
                    new_total_sell_qty = current_position.total_sell_quantity + fill_quantity
                    new_total_sell_val = current_position.total_sell_value + (Decimal(fill_quantity) * fill_price)

                    new_pos = _build_position(
                        instrument_token=current_position.instrument_token,
                        net_quantity=0,
                        direction=PositionDirection.FLAT,
                        avg_buy_price=Decimal("0"),
                        avg_sell_price=new_total_sell_val / Decimal(new_total_sell_qty) if new_total_sell_qty > 0 else Decimal("0"),
                        total_buy_quantity=current_position.total_buy_quantity,
                        total_sell_quantity=new_total_sell_qty,
                        total_buy_value=current_position.total_buy_value,
                        total_sell_value=new_total_sell_val,
                        realized_pnl=current_position.realized_pnl + realized,
                        unrealized_pnl=Decimal("0"),
                        market_price=current_position.market_price,
                        market_timestamp=current_position.market_timestamp,
                    )
                    return realized, new_pos, "CLOSE"

                else:  # fill_quantity > current_position.net_quantity
                    # Reversal — close long, open short
                    close_qty = current_position.net_quantity
                    realized = (fill_price - current_position.average_buy_price) * Decimal(close_qty)
                    short_qty = fill_quantity - close_qty
                    new_total_sell_qty = current_position.total_sell_quantity + fill_quantity
                    new_total_sell_val = current_position.total_sell_value + (Decimal(fill_quantity) * fill_price)

                    new_pos = _build_position(
                        instrument_token=current_position.instrument_token,
                        net_quantity=-short_qty,
                        direction=PositionDirection.SHORT,
                        avg_buy_price=Decimal("0"),
                        avg_sell_price=new_total_sell_val / Decimal(new_total_sell_qty),
                        total_buy_quantity=current_position.total_buy_quantity,
                        total_sell_quantity=new_total_sell_qty,
                        total_buy_value=current_position.total_buy_value,
                        total_sell_value=new_total_sell_val,
                        realized_pnl=Decimal("0"),  # reversed position starts fresh
                        unrealized_pnl=Decimal("0"),
                        market_price=current_position.market_price,
                        market_timestamp=current_position.market_timestamp,
                    )
                    return realized, new_pos, "REVERSE"

        # SHORT position
        if current_position.is_short:
            if fill_side == ExecutionOrderSide.SELL:
                # Adding to short — ADD
                new_total_sell_qty = current_position.total_sell_quantity + fill_quantity
                new_total_sell_val = current_position.total_sell_value + (Decimal(fill_quantity) * fill_price)
                new_avg_sell = new_total_sell_val / Decimal(new_total_sell_qty)
                new_net_qty = current_position.net_quantity - fill_quantity

                new_pos = _build_position(
                    instrument_token=current_position.instrument_token,
                    net_quantity=new_net_qty,
                    direction=PositionDirection.SHORT,
                    avg_buy_price=current_position.average_buy_price,
                    avg_sell_price=new_avg_sell,
                    total_buy_quantity=current_position.total_buy_quantity,
                    total_sell_quantity=new_total_sell_qty,
                    total_buy_value=current_position.total_buy_value,
                    total_sell_value=new_total_sell_val,
                    realized_pnl=current_position.realized_pnl,
                    unrealized_pnl=Decimal("0"),
                    market_price=current_position.market_price,
                    market_timestamp=current_position.market_timestamp,
                )
                return Decimal("0"), new_pos, "ADD"

            else:  # BUY against SHORT
                abs_qty = abs(current_position.net_quantity)
                if fill_quantity < abs_qty:
                    # Partial exit — REDUCE
                    realized = (current_position.average_sell_price - fill_price) * Decimal(fill_quantity)
                    new_net_qty = current_position.net_quantity + fill_quantity  # negative + positive
                    new_total_buy_qty = current_position.total_buy_quantity + fill_quantity
                    new_total_buy_val = current_position.total_buy_value + (Decimal(fill_quantity) * fill_price)

                    new_pos = _build_position(
                        instrument_token=current_position.instrument_token,
                        net_quantity=new_net_qty,
                        direction=PositionDirection.SHORT,
                        avg_buy_price=new_total_buy_val / Decimal(new_total_buy_qty) if new_total_buy_qty > 0 else Decimal("0"),
                        avg_sell_price=current_position.average_sell_price,
                        total_buy_quantity=new_total_buy_qty,
                        total_sell_quantity=current_position.total_sell_quantity,
                        total_buy_value=new_total_buy_val,
                        total_sell_value=current_position.total_sell_value,
                        realized_pnl=current_position.realized_pnl + realized,
                        unrealized_pnl=Decimal("0"),
                        market_price=current_position.market_price,
                        market_timestamp=current_position.market_timestamp,
                    )
                    return realized, new_pos, "REDUCE"

                elif fill_quantity == abs_qty:
                    # Complete exit — CLOSE
                    realized = (current_position.average_sell_price - fill_price) * Decimal(fill_quantity)
                    new_total_buy_qty = current_position.total_buy_quantity + fill_quantity
                    new_total_buy_val = current_position.total_buy_value + (Decimal(fill_quantity) * fill_price)

                    new_pos = _build_position(
                        instrument_token=current_position.instrument_token,
                        net_quantity=0,
                        direction=PositionDirection.FLAT,
                        avg_buy_price=new_total_buy_val / Decimal(new_total_buy_qty) if new_total_buy_qty > 0 else Decimal("0"),
                        avg_sell_price=current_position.average_sell_price,
                        total_buy_quantity=new_total_buy_qty,
                        total_sell_quantity=current_position.total_sell_quantity,
                        total_buy_value=new_total_buy_val,
                        total_sell_value=current_position.total_sell_value,
                        realized_pnl=current_position.realized_pnl + realized,
                        unrealized_pnl=Decimal("0"),
                        market_price=current_position.market_price,
                        market_timestamp=current_position.market_timestamp,
                    )
                    return realized, new_pos, "CLOSE"

                else:  # fill_quantity > abs_qty
                    # Reversal — close short, open long
                    close_qty = abs_qty
                    realized = (current_position.average_sell_price - fill_price) * Decimal(close_qty)
                    long_qty = fill_quantity - close_qty
                    new_total_buy_qty = current_position.total_buy_quantity + fill_quantity
                    new_total_buy_val = current_position.total_buy_value + (Decimal(fill_quantity) * fill_price)

                    new_pos = _build_position(
                        instrument_token=current_position.instrument_token,
                        net_quantity=long_qty,
                        direction=PositionDirection.LONG,
                        avg_buy_price=new_total_buy_val / Decimal(new_total_buy_qty),
                        avg_sell_price=current_position.average_sell_price,
                        total_buy_quantity=new_total_buy_qty,
                        total_sell_quantity=current_position.total_sell_quantity,
                        total_buy_value=new_total_buy_val,
                        total_sell_value=current_position.total_sell_value,
                        realized_pnl=Decimal("0"),  # reversed position starts fresh
                        unrealized_pnl=Decimal("0"),
                        market_price=current_position.market_price,
                        market_timestamp=current_position.market_timestamp,
                    )
                    return realized, new_pos, "REVERSE"

        # Should never reach here
        raise RuntimeError(f"Unhandled position state: {current_position}")

    # ------------------------------------------------------------------
    # Unrealized P&L
    # ------------------------------------------------------------------
    @staticmethod
    def compute_unrealized_pnl(
        position: PositionSnapshot,
        market_price: Decimal,
    ) -> Decimal:
        """Compute unrealized P&L from position and current market price."""
        if position.is_flat:
            return Decimal("0")
        if position.is_long:
            return Decimal(position.net_quantity) * (market_price - position.average_buy_price)
        else:  # SHORT
            return Decimal(abs(position.net_quantity)) * (position.average_sell_price - market_price)


# ------------------------------------------------------------------
# Helper
# ------------------------------------------------------------------

def _build_position(
    instrument_token: int,
    net_quantity: int,
    direction: str,
    avg_buy_price: Decimal,
    avg_sell_price: Decimal,
    total_buy_quantity: int,
    total_sell_quantity: int,
    total_buy_value: Decimal,
    total_sell_value: Decimal,
    realized_pnl: Decimal,
    unrealized_pnl: Decimal,
    market_price: Decimal | None,
    market_timestamp: Any | None,
) -> PositionSnapshot:
    """Build a PositionSnapshot with proper Decimal quantization."""
    return PositionSnapshot(
        instrument_token=instrument_token,
        net_quantity=net_quantity,
        direction=direction,
        average_buy_price=avg_buy_price,
        average_sell_price=avg_sell_price,
        total_buy_quantity=total_buy_quantity,
        total_sell_quantity=total_sell_quantity,
        total_buy_value=total_buy_value,
        total_sell_value=total_sell_value,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        market_price=market_price,
        market_timestamp=market_timestamp,
    )
