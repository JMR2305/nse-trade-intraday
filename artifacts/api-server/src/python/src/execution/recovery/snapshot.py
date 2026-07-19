"""SnapshotManager — engine state snapshots for fast recovery.

Batch 7D — Execution Recovery, Persistence & Replay Foundation.

Snapshots capture the complete in-memory state of the execution engine
at a point in time.  Recovery loads the latest snapshot and replays
only journal entries after the snapshot timestamp.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from src.execution.portfolio import PortfolioSnapshot, PositionSnapshot
from src.execution.state_machine import OrderState
from src.execution.trades import ExecutionTrade


@dataclass(frozen=True)
class EngineSnapshot:
    """Immutable snapshot of the complete execution engine state.

    Attributes:
        snapshot_id: Unique identifier for this snapshot.
        timestamp: When the snapshot was taken.
        order_states: All registered orders and their runtime states.
        positions: All per-instrument position snapshots.
        portfolio: Portfolio-wide aggregate snapshot.
        trades: All recorded trades up to this point.
        cash: Current cash balance.
        cumulative_realized_pnl: Running total realized P&L.
        metadata: Optional caller metadata.
    """

    snapshot_id: UUID
    timestamp: datetime
    order_states: dict[UUID, OrderState] = field(default_factory=dict)
    positions: dict[int, PositionSnapshot] = field(default_factory=dict)
    portfolio: PortfolioSnapshot | None = None
    trades: list[ExecutionTrade] = field(default_factory=list)
    cash: Decimal = Decimal("0")
    cumulative_realized_pnl: Decimal = Decimal("0")
    metadata: dict[str, Any] | None = None


class SnapshotManager:
    """Manages creation, storage, and retrieval of engine snapshots.

    Snapshots are stored in the database via PositionSnapshotRepository
    and ExecutionOrderRepository.  The manager coordinates the multi-table
    snapshot operation within a single transaction.
    """

    def __init__(
        self,
        order_repo: Any,
        position_repo: Any,
        trade_repo: Any,
    ) -> None:
        self._order_repo = order_repo
        self._position_repo = position_repo
        self._trade_repo = trade_repo

    # ------------------------------------------------------------------
    # Create snapshot
    # ------------------------------------------------------------------

    async def create_snapshot(
        self,
        state_machine: Any,
        position_engine: Any,
        trade_ledger: Any,
        session: Any,
        metadata: dict[str, Any] | None = None,
    ) -> EngineSnapshot:
        """Capture a complete snapshot of all engine state.

        Args:
            state_machine: The OrderStateMachine instance.
            position_engine: The PositionEngine instance.
            trade_ledger: The TradeLedger instance.
            session: AsyncSession for DB persistence.
            metadata: Optional metadata to attach to the snapshot.

        Returns:
            EngineSnapshot with all current state.
        """
        from uuid import uuid4

        snapshot_id = uuid4()
        timestamp = datetime.now(timezone.utc)

        # Capture order states
        order_states: dict[UUID, OrderState] = {}
        # Note: OrderStateMachine doesn't expose internal registry directly.
        # The persistence adapter or caller must provide the active orders.
        # We use the repository's list_active as the source of truth.
        active_orders = await self._order_repo.list_active(session)
        for state in active_orders:
            order_states[state.order.order_id] = state

        # Capture positions
        positions: dict[int, PositionSnapshot] = {}
        all_pos = await self._position_repo.get_all(session)
        for pos in all_pos:
            positions[pos.instrument_token] = pos

        # Capture portfolio
        portfolio = position_engine.snapshot() if position_engine else None

        # Capture trades
        trades = list(trade_ledger.get_trades()) if trade_ledger else []

        # Cash and cumulative P&L from position engine
        cash = position_engine.get_cash() if position_engine else Decimal("0")
        cum_pnl = (
            getattr(position_engine, "_cumulative_realized_pnl", Decimal("0"))
            if position_engine
            else Decimal("0")
        )

        snapshot = EngineSnapshot(
            snapshot_id=snapshot_id,
            timestamp=timestamp,
            order_states=order_states,
            positions=positions,
            portfolio=portfolio,
            trades=trades,
            cash=cash,
            cumulative_realized_pnl=cum_pnl,
            metadata=metadata,
        )

        # Persist to DB
        await self._persist_snapshot(snapshot, session)
        return snapshot

    async def _persist_snapshot(
        self,
        snapshot: EngineSnapshot,
        session: Any,
    ) -> None:
        """Persist snapshot components to their respective tables."""
        # Persist each position snapshot
        for pos in snapshot.positions.values():
            await self._position_repo.save_snapshot(pos, session)

        # Persist order states (they are already in execution_orders table,
        # but we ensure they are up to date)
        for state in snapshot.order_states.values():
            await self._order_repo.save(state.order, state, session)

    # ------------------------------------------------------------------
    # Load snapshot
    # ------------------------------------------------------------------

    async def load_latest_snapshot(
        self,
        session: Any,
    ) -> EngineSnapshot | None:
        """Load the most recent snapshot from the database.

        Returns None if no snapshot exists.
        """
        from uuid import uuid4

        all_positions = await self._position_repo.get_all(session)
        if not all_positions:
            return None

        positions = {p.instrument_token: p for p in all_positions}
        active_orders = await self._order_repo.list_active(session)
        order_states = {s.order.order_id: s for s in active_orders}

        # Determine snapshot timestamp from most recent position
        latest_ts = max(
            (p.position_timestamp for p in all_positions),
            default=datetime.now(timezone.utc),
        )

        return EngineSnapshot(
            snapshot_id=uuid4(),
            timestamp=latest_ts,
            order_states=order_states,
            positions=positions,
            portfolio=None,  # Recomputed on recovery
            trades=[],  # Loaded separately if needed
            cash=Decimal("0"),  # Recomputed on recovery
            cumulative_realized_pnl=Decimal("0"),
        )

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def snapshot_to_dict(self, snapshot: EngineSnapshot) -> dict[str, Any]:
        """Serialize a snapshot to a plain dict (for logging/debugging)."""
        return {
            "snapshot_id": str(snapshot.snapshot_id),
            "timestamp": snapshot.timestamp.isoformat(),
            "order_count": len(snapshot.order_states),
            "position_count": len(snapshot.positions),
            "trade_count": len(snapshot.trades),
            "cash": str(snapshot.cash),
            "cumulative_realized_pnl": str(snapshot.cumulative_realized_pnl),
            "metadata": snapshot.metadata,
        }
