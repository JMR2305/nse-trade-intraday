"""PersistenceAdapter — wraps engine methods with DB persistence.

Batch 7D — Execution Recovery, Persistence & Replay Foundation.

These adapters sit between the in-memory engines and the database.
They call the engine method first, then persist the result to the DB
within the same session/commit.  If persistence fails, the engine
state is already updated — this is acceptable for a paper trading
system where the in-memory state is the source of truth during runtime.

On recovery, the DB is replayed to reconstruct in-memory state.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from src.execution.contracts import ExecutionOrder, ExecutionAuditEvent
from src.execution.fills import FillEvent
from src.execution.position_engine import PositionEngine, PositionEngineResult
from src.execution.state_machine import OrderStateMachine, TransitionResult
from src.execution.trades import TradeLedger
from src.execution.recovery.journal import ExecutionJournal, JournalEntryType


class OrderStateMachinePersistenceAdapter:
    """Wraps OrderStateMachine transitions with DB persistence.

    Every successful transition is persisted as an audit event.
    The order state is also updated in the execution_orders table.
    """

    def __init__(
        self,
        state_machine: OrderStateMachine,
        order_repo: Any,
        audit_repo: Any,
        journal: ExecutionJournal | None = None,
    ) -> None:
        self._state_machine = state_machine
        self._order_repo = order_repo
        self._audit_repo = audit_repo
        self._journal = journal or ExecutionJournal()

    # ------------------------------------------------------------------
    # Wrapped transitions
    # ------------------------------------------------------------------

    async def submit(
        self,
        order: ExecutionOrder,
        actor: str = "system",
        session: Any = None,
    ) -> TransitionResult:
        """Submit an order and persist."""
        result = await self._state_machine.submit(order, actor=actor)
        if result.success and session is not None:
            await self._persist_transition(result, session)
            self._journal.append_order_submitted(
                order_id=order.order_id,
                client_order_id=order.client_order_id,
                instrument_token=order.instrument_token,
                side=order.side.value,
                order_type=order.order_type.value,
                quantity=order.quantity,
                limit_price=order.limit_price,
                trigger_price=order.trigger_price,
            )
        return result

    async def validate(
        self,
        order_id: UUID,
        actor: str = "system",
        session: Any = None,
    ) -> TransitionResult:
        result = await self._state_machine.validate(order_id, actor=actor)
        if result.success and session is not None:
            await self._persist_transition(result, session)
        return result

    async def accept(
        self,
        order_id: UUID,
        actor: str = "system",
        session: Any = None,
    ) -> TransitionResult:
        result = await self._state_machine.accept(order_id, actor=actor)
        if result.success and session is not None:
            await self._persist_transition(result, session)
        return result

    async def reject(
        self,
        order_id: UUID,
        reason: str,
        actor: str = "system",
        session: Any = None,
    ) -> TransitionResult:
        result = await self._state_machine.reject(order_id, reason=reason, actor=actor)
        if result.success and session is not None:
            await self._persist_transition(result, session)
        return result

    async def open_order(
        self,
        order_id: UUID,
        actor: str = "system",
        session: Any = None,
    ) -> TransitionResult:
        result = await self._state_machine.open_order(order_id, actor=actor)
        if result.success and session is not None:
            await self._persist_transition(result, session)
        return result

    async def partially_fill(
        self,
        order_id: UUID,
        quantity: int,
        price: Any,
        actor: str = "system",
        metadata: dict | None = None,
        session: Any = None,
    ) -> TransitionResult:
        result = await self._state_machine.partially_fill(
            order_id, quantity, price, actor=actor, metadata=metadata
        )
        if result.success and session is not None:
            await self._persist_transition(result, session)
        return result

    async def fill(
        self,
        order_id: UUID,
        quantity: int,
        price: Any,
        actor: str = "system",
        metadata: dict | None = None,
        session: Any = None,
    ) -> TransitionResult:
        result = await self._state_machine.fill(
            order_id, quantity, price, actor=actor, metadata=metadata
        )
        if result.success and session is not None:
            await self._persist_transition(result, session)
        return result

    async def request_cancel(
        self,
        order_id: UUID,
        actor: str = "system",
        session: Any = None,
    ) -> TransitionResult:
        result = await self._state_machine.request_cancel(order_id, actor=actor)
        if result.success and session is not None:
            await self._persist_transition(result, session)
        return result

    async def cancel(
        self,
        order_id: UUID,
        actor: str = "system",
        session: Any = None,
    ) -> TransitionResult:
        result = await self._state_machine.cancel(order_id, actor=actor)
        if result.success and session is not None:
            await self._persist_transition(result, session)
        return result

    async def expire(
        self,
        order_id: UUID,
        actor: str = "system",
        session: Any = None,
    ) -> TransitionResult:
        result = await self._state_machine.expire(order_id, actor=actor)
        if result.success and session is not None:
            await self._persist_transition(result, session)
        return result

    async def fail(
        self,
        order_id: UUID,
        reason: str,
        actor: str = "system",
        session: Any = None,
    ) -> TransitionResult:
        result = await self._state_machine.fail(order_id, reason=reason, actor=actor)
        if result.success and session is not None:
            await self._persist_transition(result, session)
        return result

    # ------------------------------------------------------------------
    # Persistence helper
    # ------------------------------------------------------------------

    async def _persist_transition(
        self,
        result: TransitionResult,
        session: Any,
    ) -> None:
        """Persist transition result to DB."""
        if result.audit_event is not None:
            await self._audit_repo.save(result.audit_event, session)

        if result.order is not None:
            await self._order_repo.save(result.order.order, result.order, session)

        # Journal entry for state transition
        self._journal.append_state_transition(
            order_id=result.order.order.order_id if result.order else result.audit_event.order_id,
            action=result.audit_event.action.value if result.audit_event else "unknown",
            previous_state=result.previous_state.value,
            new_state=result.new_state.value,
            sequence_number=result.audit_event.sequence_number if result.audit_event else 0,
            reason=result.audit_event.reason if result.audit_event else None,
            actor=result.audit_event.actor if result.audit_event else "system",
        )


class PositionEnginePersistenceAdapter:
    """Wraps PositionEngine.on_fill() with DB persistence.

    Every fill is persisted as a FillEvent, Trade, and PositionSnapshot.
    """

    def __init__(
        self,
        position_engine: PositionEngine,
        fill_repo: Any,
        trade_repo: Any,
        position_repo: Any,
        journal: ExecutionJournal | None = None,
    ) -> None:
        self._position_engine = position_engine
        self._fill_repo = fill_repo
        self._trade_repo = trade_repo
        self._position_repo = position_repo
        self._journal = journal or ExecutionJournal()

    async def on_fill(
        self,
        fill: FillEvent,
        session: Any,
    ) -> PositionEngineResult:
        """Process a fill and persist all derived state."""
        result = await self._position_engine.on_fill(fill)

        if session is not None:
            # Persist fill event
            await self._fill_repo.save(fill, session)

            # Persist trade if recorded
            if result.trade_recorded:
                # Reconstruct trade from result
                from src.execution.trades import ExecutionTrade
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
                    position_impact=result.position_impact,
                    realized_pnl=result.realized_pnl,
                    cumulative_realized_pnl=result.new_position.realized_pnl,
                    market_timestamp=fill.market_timestamp,
                )
                await self._trade_repo.save(trade, session)

            # Persist updated position snapshot
            updated_pos = self._position_engine.get_position(fill.instrument_token)
            if updated_pos is not None:
                await self._position_repo.save_snapshot(updated_pos, session)

        # Journal entries
        self._journal.append_fill_generated(
            fill_id=fill.fill_id,
            order_id=fill.order_id,
            instrument_token=fill.instrument_token,
            side=fill.side.value,
            quantity=fill.quantity,
            price=fill.price,
            gross_value=fill.gross_value,
            market_event_id=fill.market_event_id,
            cumulative_filled_quantity=fill.cumulative_filled_quantity,
            remaining_quantity=fill.remaining_quantity,
        )

        if result.trade_recorded:
            self._journal.append_position_updated(
                order_id=fill.order_id,
                instrument_token=fill.instrument_token,
                fill_id=fill.fill_id,
                position_impact=result.position_impact,
                realized_pnl=result.realized_pnl,
                net_quantity=result.new_position.net_quantity,
            )

        return result
