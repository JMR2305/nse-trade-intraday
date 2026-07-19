"""Position, portfolio, and P&L engine.

Consumes FillEvents from Batch 7B and maintains:
  - per-instrument positions
  - cash ledger
  - trade history
  - realized and unrealized P&L
  - portfolio snapshots

Concurrency:
  - per-instrument asyncio.Lock for position mutation
  - cash ledger protected by same lock (single instrument at a time)
  - multiple instruments processed concurrently

Idempotency:
  - duplicate fill_id silently ignored
  - deterministic replay: same fill stream → same state

Known limitation — reversal accounting:
  Reversals (e.g. LONG → SHORT or SHORT → LONG in a single fill) are
  handled by the PnLCalculator but the current architecture does not
  separately track realized P&L for the closed portion vs. the new
  reversed portion in a single atomic trade.  The realized_pnl on the
  trade reflects the closed portion only; the new reversed position
  starts with zero realized_pnl.  This is a documented limitation —
  reversals are rare in the current NSE CNC product model and will be
  addressed in a future batch if required.
"""
from __future__ import annotations

import asyncio
import weakref
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.execution.contracts import ExecutionOrderSide
from src.execution.fills import FillEvent
from src.execution.pnl import PnLCalculator
from src.execution.portfolio import (
    CashLedger,
    PortfolioSnapshot,
    PositionDirection,
    PositionSnapshot,
)
from src.execution.trades import ExecutionTrade, TradeLedger


# ------------------------------------------------------------------
# EngineResult
# ------------------------------------------------------------------

@dataclass(frozen=True)
class PositionEngineResult:
    """Result of processing a single FillEvent."""
    fill_id: str
    instrument_token: int
    position_impact: str  # OPEN, ADD, REDUCE, CLOSE, REVERSE
    realized_pnl: Decimal
    new_position: PositionSnapshot
    trade_recorded: bool


# ------------------------------------------------------------------
# PositionEngine
# ------------------------------------------------------------------

class PositionEngine:
    """Deterministic position, portfolio, and P&L engine.

    Thread-safe for concurrent fills on different instruments.
    Single-instrument fills are serialized per instrument.
    """

    def __init__(self, initial_cash: Decimal = Decimal("1000000")) -> None:
        self._positions: dict[int, PositionSnapshot] = {}
        self._cash = CashLedger()
        self._cash.credit(initial_cash)  # initial paper capital
        self._initial_cash = initial_cash
        self._trades = TradeLedger()
        # Per-instrument locks
        self._locks: weakref.WeakValueDictionary[int, asyncio.Lock] = weakref.WeakValueDictionary()
        # Global dedup: seen fill_ids across all instruments
        self._seen_fill_ids: set[str] = set()
        # Cumulative realized P&L (persists after position close)
        self._cumulative_realized_pnl: Decimal = Decimal("0")

    # ------------------------------------------------------------------
    # Lock management
    # ------------------------------------------------------------------
    def _get_lock(self, instrument_token: int) -> asyncio.Lock:
        lock = self._locks.get(instrument_token)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[instrument_token] = lock
        return lock

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def on_fill(self, fill: FillEvent) -> PositionEngineResult:
        """Process a FillEvent.  Idempotent and atomic.

        Returns PositionEngineResult with position impact and realized P&L.
        """
        lock = self._get_lock(fill.instrument_token)
        async with lock:
            return self._on_fill_locked(fill)

    def _on_fill_locked(self, fill: FillEvent) -> PositionEngineResult:
        """Internal fill processing — must hold per-instrument lock."""
        # Idempotency check
        if fill.fill_id in self._seen_fill_ids:
            # Return current position state without mutation
            current_pos = self._positions.get(
                fill.instrument_token,
                self._empty_position(fill.instrument_token),
            )
            return PositionEngineResult(
                fill_id=fill.fill_id,
                instrument_token=fill.instrument_token,
                position_impact="DUPLICATE",
                realized_pnl=Decimal("0"),
                new_position=current_pos,
                trade_recorded=False,
            )
        self._seen_fill_ids.add(fill.fill_id)

        # Get or create empty position
        current_pos = self._positions.get(
            fill.instrument_token,
            self._empty_position(fill.instrument_token),
        )

        # Compute P&L and new position
        realized_pnl, new_pos, impact = PnLCalculator.compute_realized_pnl(
            current_position=current_pos,
            fill_side=fill.side,
            fill_quantity=fill.quantity,
            fill_price=fill.price,
        )

        # Update cash ledger
        if fill.side == ExecutionOrderSide.BUY:
            self._cash.debit(fill.gross_value)
        else:  # SELL
            self._cash.credit(fill.gross_value)

        # Accumulate realized P&L — only on CLOSE or REVERSE.
        # For OPEN / ADD / REDUCE the running total lives in pos.realized_pnl;
        # snapshot() adds both to avoid double-counting.
        if new_pos.is_flat or impact == "REVERSE":
            self._cumulative_realized_pnl += current_pos.realized_pnl + realized_pnl

        # Store updated position
        if new_pos.is_flat:
            # Remove flat positions to keep memory clean
            self._positions.pop(fill.instrument_token, None)
        else:
            self._positions[fill.instrument_token] = new_pos

        # Record trade
        trade = ExecutionTrade(
            trade_id=f"T-{fill.fill_id}",
            fill_id=fill.fill_id,
            order_id=fill.order_id,
            client_order_id=fill.client_order_id,
            instrument_token=fill.instrument_token,
            side=fill.side,
            quantity=fill.quantity,
            price=fill.price,
            gross_value=fill.gross_value,
            position_impact=impact,
            realized_pnl=realized_pnl,
            cumulative_realized_pnl=(
                self._cumulative_realized_pnl + new_pos.realized_pnl
                if not new_pos.is_flat
                else self._cumulative_realized_pnl
            ),
            market_timestamp=fill.market_timestamp,
            metadata=fill.metadata,
        )
        trade_recorded = self._trades.record(trade)

        return PositionEngineResult(
            fill_id=fill.fill_id,
            instrument_token=fill.instrument_token,
            position_impact=impact,
            realized_pnl=realized_pnl,
            new_position=new_pos,
            trade_recorded=trade_recorded,
        )

    # ------------------------------------------------------------------
    # Market price update (for unrealized P&L)
    # ------------------------------------------------------------------
    async def update_market_price(
        self,
        instrument_token: int,
        market_price: Decimal,
        market_timestamp: datetime,
    ) -> PositionSnapshot | None:
        """Update market price for an instrument and recompute unrealized P&L.

        Returns the updated position snapshot, or None if no position.
        """
        lock = self._get_lock(instrument_token)
        async with lock:
            pos = self._positions.get(instrument_token)
            if pos is None:
                return None

            unrealized = PnLCalculator.compute_unrealized_pnl(pos, market_price)
            new_pos = PositionSnapshot(
                instrument_token=pos.instrument_token,
                net_quantity=pos.net_quantity,
                direction=pos.direction,
                average_buy_price=pos.average_buy_price,
                average_sell_price=pos.average_sell_price,
                total_buy_quantity=pos.total_buy_quantity,
                total_sell_quantity=pos.total_sell_quantity,
                total_buy_value=pos.total_buy_value,
                total_sell_value=pos.total_sell_value,
                realized_pnl=pos.realized_pnl,
                unrealized_pnl=unrealized,
                market_price=market_price,
                market_timestamp=market_timestamp,
            )
            self._positions[instrument_token] = new_pos
            return new_pos

    # ------------------------------------------------------------------
    # Portfolio snapshot
    # ------------------------------------------------------------------
    def snapshot(self) -> PortfolioSnapshot:
        """Create an immutable portfolio snapshot.

        Not async — returns a point-in-time view.  Caller should ensure
        no fills are in-flight for consistent snapshot.
        """
        positions = tuple(self._positions.values())
        market_value = sum(
            (pos.market_value for pos in positions),
            Decimal("0"),
        )
        # Cumulative realized P&L includes both:
        #   - self._cumulative_realized_pnl (from closed positions)
        #   - pos.realized_pnl (from currently open positions)
        realized_pnl = self._cumulative_realized_pnl + sum(
            (pos.realized_pnl for pos in positions),
            Decimal("0"),
        )
        unrealized_pnl = sum(
            (pos.unrealized_pnl for pos in positions),
            Decimal("0"),
        )
        margin_used = sum(
            (pos.exposure for pos in positions),
            Decimal("0"),
        )
        equity = self._cash.balance + market_value

        return PortfolioSnapshot(
            cash=self._cash.balance,
            equity=equity,
            positions=positions,
            market_value=market_value,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            total_pnl=realized_pnl + unrealized_pnl,
            buying_power=self._cash.balance,  # paper: simplified
            margin_used=margin_used,
            trade_count=self._trades.trade_count,
            turnover=self._trades.total_turnover,
        )

    # ------------------------------------------------------------------
    # Read-only accessors
    # ------------------------------------------------------------------
    def get_position(self, instrument_token: int) -> PositionSnapshot | None:
        return self._positions.get(instrument_token)

    def get_all_positions(self) -> dict[int, PositionSnapshot]:
        return dict(self._positions)

    def get_cash(self) -> Decimal:
        return self._cash.balance

    def get_trade_ledger(self) -> TradeLedger:
        return self._trades

    # ------------------------------------------------------------------
    # Reset (for deterministic replay tests)
    # ------------------------------------------------------------------
    def reset(self) -> None:
        self._positions.clear()
        self._cash.reset()
        self._cash.credit(self._initial_cash)
        self._trades.reset()
        self._seen_fill_ids.clear()
        self._locks.clear()
        self._cumulative_realized_pnl = Decimal("0")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _empty_position(instrument_token: int) -> PositionSnapshot:
        return PositionSnapshot(
            instrument_token=instrument_token,
            net_quantity=0,
            direction=PositionDirection.FLAT,
            average_buy_price=Decimal("0"),
            average_sell_price=Decimal("0"),
            total_buy_quantity=0,
            total_sell_quantity=0,
            total_buy_value=Decimal("0"),
            total_sell_value=Decimal("0"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            market_price=None,
            market_timestamp=None,
        )
