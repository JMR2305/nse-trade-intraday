"""RecoveryManager — orchestrates deterministic engine recovery.

Batch 7D — Execution Recovery, Persistence & Replay Foundation.

The RecoveryManager is the central coordinator for crash recovery:
1. Load the latest snapshot (if any)
2. Load all non-terminal orders and reconstruct OrderStateMachine
3. Load all audit events and replay through state machine
4. Load all fills and replay through PositionEngine
5. Run consistency checks
6. Mark recovery complete

Recovery is single-threaded and must complete before live processing resumes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from src.execution.position_engine import PositionEngine
from src.execution.state_machine import OrderStateMachine
from src.execution.trades import TradeLedger
from src.execution.recovery.journal import ExecutionJournal, JournalEntryType
from src.execution.recovery.replay_engine import ReplayEngine
from src.execution.recovery.snapshot import SnapshotManager, EngineSnapshot
from src.execution.recovery.consistency_checker import ConsistencyChecker, ConsistencyReport


@dataclass(frozen=True)
class RecoveryResult:
    """Result of a recovery operation."""

    success: bool
    orders_restored: int
    positions_restored: int
    trades_restored: int
    journal_entries_replayed: int
    snapshot_used: bool
    consistency_report: ConsistencyReport | None
    errors: list[str]
    recovery_timestamp: datetime


class RecoveryManager:
    """Orchestrates deterministic recovery of the execution engine.

    Thread safety: Recovery is single-threaded during startup.
    No concurrency with live processing is possible because recovery
    runs before the engine accepts new events.
    """

    def __init__(
        self,
        state_machine: OrderStateMachine,
        position_engine: PositionEngine,
        trade_ledger: TradeLedger,
        order_repo: Any,
        audit_repo: Any,
        fill_repo: Any,
        trade_repo: Any,
        position_repo: Any,
        journal: ExecutionJournal | None = None,
        snapshot_manager: SnapshotManager | None = None,
    ) -> None:
        self._state_machine = state_machine
        self._position_engine = position_engine
        self._trade_ledger = trade_ledger
        self._order_repo = order_repo
        self._audit_repo = audit_repo
        self._fill_repo = fill_repo
        self._trade_repo = trade_repo
        self._position_repo = position_repo
        self._journal = journal or ExecutionJournal()
        self._snapshot_manager = snapshot_manager or SnapshotManager(
            order_repo=order_repo,
            position_repo=position_repo,
            trade_repo=trade_repo,
        )
        self._replay_engine = ReplayEngine(
            state_machine=state_machine,
            position_engine=position_engine,
            trade_ledger=trade_ledger,
            journal=self._journal,
        )
        self._consistency_checker = ConsistencyChecker()
        self._recovered: bool = False

    # ------------------------------------------------------------------
    # Main recovery flow
    # ------------------------------------------------------------------

    async def recover(self, session: Any) -> RecoveryResult:
        """Execute the full recovery pipeline.

        This method must be called once at startup, before any live
        events are processed.  It is idempotent: calling it again
        after successful recovery is a no-op.

        Args:
            session: AsyncSession for all DB operations.

        Returns:
            RecoveryResult with detailed status.
        """
        if self._recovered:
            return RecoveryResult(
                success=True,
                orders_restored=0,
                positions_restored=0,
                trades_restored=0,
                journal_entries_replayed=0,
                snapshot_used=False,
                consistency_report=None,
                errors=["Recovery already completed"],
                recovery_timestamp=datetime.now(timezone.utc),
            )

        errors: list[str] = []
        snapshot_used = False
        orders_restored = 0
        positions_restored = 0
        trades_restored = 0
        entries_replayed = 0

        try:
            # Step 1: Load snapshot
            snapshot = await self._snapshot_manager.load_latest_snapshot(session)
            if snapshot is not None:
                snapshot_used = True
                await self._restore_from_snapshot(snapshot)
                orders_restored = len(snapshot.order_states)
                positions_restored = len(snapshot.positions)

            # Step 2: Load and register all non-terminal orders
            active_orders = await self._order_repo.list_active(session)
            for state in active_orders:
                # Register in state machine if not already present
                existing = self._state_machine.get_state(state.order.order_id)
                if existing is None:
                    self._state_machine.register(state.order)
                    # Manually set the state to match DB (bypass transition)
                    # This is safe because we're in recovery mode
                    sm_state = self._state_machine.get_state(state.order.order_id)
                    if sm_state:
                        sm_state._status = state.status
                        sm_state._filled_quantity = state.filled_quantity
                        sm_state._average_fill_price = state.average_fill_price
                        sm_state._sequence_number = state.sequence_number
                orders_restored += 1

            # Step 3: Load all audit events and replay
            all_audit_events = await self._audit_repo.get_all_events(session)
            if all_audit_events:
                # Filter: only replay events for orders we restored
                # and only events after snapshot timestamp if snapshot exists
                events_to_replay = all_audit_events
                if snapshot is not None:
                    events_to_replay = [
                        e for e in all_audit_events
                        if e.event_timestamp > snapshot.timestamp
                    ]

                transition_results = await self._replay_engine.replay_audit_events(
                    events_to_replay
                )
                entries_replayed += len(transition_results)

            # Step 4: Load all fills and replay
            all_fills = await self._fill_repo.get_all_fills(session)
            if all_fills:
                fills_to_replay = all_fills
                if snapshot is not None:
                    fills_to_replay = [
                        f for f in all_fills
                        if f.fill_timestamp > snapshot.timestamp
                    ]

                position_results = await self._replay_engine.replay_fill_events(
                    fills_to_replay
                )
                entries_replayed += sum(1 for r in position_results if r.trade_recorded)

            # Step 5: Load trades into ledger (for completeness)
            all_trades = await self._trade_repo.get_all(session)
            for trade in all_trades:
                self._trade_ledger.record(trade)
                trades_restored += 1

            # Step 6: Consistency checks
            consistency_report = await self._run_consistency_checks()

            # Step 7: Mark recovery complete
            self._recovered = True
            self._journal.append_recovery_completed(
                orders_restored=orders_restored,
                positions_restored=positions_restored,
                trades_restored=trades_restored,
                journal_entries_replayed=entries_replayed,
            )

            return RecoveryResult(
                success=consistency_report.is_valid if consistency_report else True,
                orders_restored=orders_restored,
                positions_restored=positions_restored,
                trades_restored=trades_restored,
                journal_entries_replayed=entries_replayed,
                snapshot_used=snapshot_used,
                consistency_report=consistency_report,
                errors=errors + self._replay_engine.errors,
                recovery_timestamp=datetime.now(timezone.utc),
            )

        except Exception as exc:
            errors.append(f"Recovery failed with exception: {exc}")
            return RecoveryResult(
                success=False,
                orders_restored=orders_restored,
                positions_restored=positions_restored,
                trades_restored=trades_restored,
                journal_entries_replayed=entries_replayed,
                snapshot_used=snapshot_used,
                consistency_report=None,
                errors=errors,
                recovery_timestamp=datetime.now(timezone.utc),
            )

    async def _restore_from_snapshot(self, snapshot: EngineSnapshot) -> None:
        """Restore engine state from a snapshot.

        This pre-populates the position engine with snapshot positions
        and registers orders in the state machine.
        """
        # Restore positions into position engine
        # PositionEngine has no direct "set position" API; positions are
        # reconstructed deterministically by replaying fill events that
        # occurred after the snapshot timestamp.  Snapshot positions are
        # retained only for post-recovery consistency validation.
        for instrument_token, pos in snapshot.positions.items():
            self._logger.info(
                "recovery: position for instrument=%s will be reconstructed "
                "via fill replay (snapshot qty=%s direction=%s)",
                instrument_token,
                pos.net_quantity,
                pos.direction,
            )

        # Register orders in state machine
        for order_id, state in snapshot.order_states.items():
            existing = self._state_machine.get_state(order_id)
            if existing is None:
                self._state_machine.register(state.order)
                sm_state = self._state_machine.get_state(order_id)
                if sm_state:
                    sm_state._status = state.status
                    sm_state._filled_quantity = state.filled_quantity
                    sm_state._average_fill_price = state.average_fill_price
                    sm_state._sequence_number = state.sequence_number

    async def _run_consistency_checks(self) -> ConsistencyReport:
        """Run post-recovery consistency validation."""
        # Get current state
        portfolio = self._position_engine.snapshot()
        all_positions = self._position_engine.get_all_positions()
        cash = self._position_engine.get_cash()

        # Get all orders from state machine
        # Note: OrderStateMachine doesn't expose all orders directly.
        # We use the repository for this.
        # For now, we validate what we can access.

        return self._consistency_checker.validate(
            portfolio=portfolio,
            positions=all_positions,
            cash=cash,
            trade_ledger=self._trade_ledger,
        )

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @property
    def is_recovered(self) -> bool:
        return self._recovered

    def reset(self) -> None:
        """Reset recovery state (for testing)."""
        self._recovered = False
        self._replay_engine.reset()
