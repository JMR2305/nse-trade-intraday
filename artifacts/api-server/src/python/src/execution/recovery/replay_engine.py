"""ReplayEngine — deterministic replay of execution events.

Batch 7D — Execution Recovery, Persistence & Replay Foundation.

Given a sequence of audit events and fill events, the ReplayEngine
reconstructs identical in-memory state.  Replay is deterministic:
same input stream always produces the same output state.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from src.execution.contracts import (
    ExecutionOrder,
    ExecutionOrderAction,
    ExecutionOrderStatus,
    ExecutionAuditEvent,
    FillRecord,
)
from src.execution.fills import FillEvent, FillEventBuilder
from src.execution.portfolio import PositionSnapshot, PortfolioSnapshot
from src.execution.position_engine import PositionEngine, PositionEngineResult
from src.execution.state_machine import OrderStateMachine, TransitionResult
from src.execution.trades import ExecutionTrade, TradeLedger
from src.execution.recovery.journal import ExecutionJournal, JournalEntryType


class ReplayEngine:
    """Deterministic replay engine for execution state recovery.

    Replays audit events through OrderStateMachine and fill events
    through PositionEngine to reconstruct identical runtime state.

    Usage:
        replay = ReplayEngine(state_machine, position_engine)
        await replay.replay_audit_events(audit_events)
        await replay.replay_fill_events(fill_events)
    """

    def __init__(
        self,
        state_machine: OrderStateMachine,
        position_engine: PositionEngine,
        trade_ledger: TradeLedger | None = None,
        journal: ExecutionJournal | None = None,
    ) -> None:
        self._state_machine = state_machine
        self._position_engine = position_engine
        self._trade_ledger = trade_ledger or TradeLedger()
        self._journal = journal or ExecutionJournal()
        self._fill_builder = FillEventBuilder()
        self._replayed_events: int = 0
        self._errors: list[str] = []

    # ------------------------------------------------------------------
    # Core replay
    # ------------------------------------------------------------------

    async def replay_audit_events(
        self,
        events: list[ExecutionAuditEvent],
    ) -> list[TransitionResult]:
        """Replay a sequence of audit events through the state machine.

        Events must be ordered by (order_id, sequence_number).
        Duplicate events are silently skipped.

        Returns:
            List of TransitionResult for each successfully replayed event.
        """
        results: list[TransitionResult] = []

        for event in events:
            try:
                result = await self._replay_single_audit_event(event)
                if result.success:
                    results.append(result)
                    self._replayed_events += 1
                else:
                    self._errors.append(
                        f"Audit replay failed for order {event.order_id}: "
                        f"{event.action.value} → {result.reason}"
                    )
            except Exception as exc:
                self._errors.append(
                    f"Audit replay exception for order {event.order_id}: {exc}"
                )

        return results

    async def replay_fill_events(
        self,
        fills: list[FillEvent],
    ) -> list[PositionEngineResult]:
        """Replay a sequence of fill events through the position engine.

        Fills must be ordered by fill_timestamp.
        Duplicate fills are silently skipped (idempotent).

        Returns:
            List of PositionEngineResult for each successfully replayed fill.
        """
        results: list[PositionEngineResult] = []

        for fill in fills:
            try:
                result = await self._position_engine.on_fill(fill)
                results.append(result)
                if result.trade_recorded:
                    self._replayed_events += 1
            except Exception as exc:
                self._errors.append(
                    f"Fill replay exception for fill {fill.fill_id}: {exc}"
                )

        return results

    async def replay_journal_entries(
        self,
        entries: list[Any],
    ) -> dict[str, Any]:
        """Replay journal entries (high-level orchestration).

        This is a convenience method that dispatches to the appropriate
        replay method based on entry type.
        """
        audit_events: list[ExecutionAuditEvent] = []
        fill_events: list[FillEvent] = []

        for entry in entries:
            if entry.entry_type == JournalEntryType.STATE_TRANSITION:
                audit = self._journal_entry_to_audit_event(entry)
                if audit:
                    audit_events.append(audit)
            elif entry.entry_type == JournalEntryType.FILL_GENERATED:
                fill_evt = self._journal_entry_to_fill_event(entry)
                if fill_evt:
                    fill_events.append(fill_evt)

        transition_results = await self.replay_audit_events(audit_events)
        position_results = await self.replay_fill_events(fill_events)

        return {
            "transitions_replayed": len(transition_results),
            "fills_replayed": len(position_results),
            "errors": self._errors,
        }

    # ------------------------------------------------------------------
    # Single event replay
    # ------------------------------------------------------------------

    async def _replay_single_audit_event(
        self,
        event: ExecutionAuditEvent,
    ) -> TransitionResult:
        """Replay one audit event through the state machine.

        If the order is not yet registered, we first register it
        (for ORDER_SUBMITTED events).
        """
        # Check if order exists in state machine
        existing_state = self._state_machine.get_state(event.order_id)

        if existing_state is None:
            # Order not registered yet — we need to reconstruct it
            # In a real scenario, the order definition would be loaded
            # from ExecutionOrderRepository.  For replay, we assume
            # the caller has pre-registered orders or we skip.
            # This is handled by RecoveryManager which loads orders first.
            return TransitionResult(
                success=False,
                previous_state=ExecutionOrderStatus.CREATED,
                new_state=ExecutionOrderStatus.CREATED,
                audit_event=None,
                order=None,
                reason=f"Order {event.order_id} not registered for replay",
            )

        # Map action to transition method
        action_map = {
            ExecutionOrderAction.SUBMIT: self._state_machine.submit,
            ExecutionOrderAction.VALIDATE: self._state_machine.validate,
            ExecutionOrderAction.ACCEPT: self._state_machine.accept,
            ExecutionOrderAction.REJECT: self._state_machine.reject,
            ExecutionOrderAction.OPEN: self._state_machine.open_order,
            ExecutionOrderAction.PARTIALLY_FILL: self._state_machine.partially_fill,
            ExecutionOrderAction.FILL: self._state_machine.fill,
            ExecutionOrderAction.REQUEST_CANCEL: self._state_machine.request_cancel,
            ExecutionOrderAction.CANCEL: self._state_machine.cancel,
            ExecutionOrderAction.EXPIRE: self._state_machine.expire,
            ExecutionOrderAction.FAIL: self._state_machine.fail,
        }

        method = action_map.get(event.action)
        if method is None:
            return TransitionResult(
                success=False,
                previous_state=existing_state.status,
                new_state=existing_state.status,
                audit_event=None,
                order=existing_state,
                reason=f"Unknown action: {event.action.value}",
            )

        # Build kwargs based on action type
        kwargs: dict[str, Any] = {
            "order_id": event.order_id,
            "actor": event.actor,
        }

        if event.action in (ExecutionOrderAction.PARTIALLY_FILL, ExecutionOrderAction.FILL):
            if event.fill_record:
                kwargs["quantity"] = event.fill_record.quantity
                kwargs["price"] = event.fill_record.price
                kwargs["metadata"] = event.fill_record.metadata

        if event.action == ExecutionOrderAction.REJECT:
            kwargs["reason"] = event.reason or "replayed rejection"

        if event.action == ExecutionOrderAction.FAIL:
            kwargs["reason"] = event.reason or "replayed failure"

        return await method(**kwargs)

    # ------------------------------------------------------------------
    # Journal conversion helpers
    # ------------------------------------------------------------------

    def _journal_entry_to_audit_event(
        self,
        entry: Any,
    ) -> ExecutionAuditEvent | None:
        """Convert a STATE_TRANSITION journal entry to ExecutionAuditEvent."""
        from src.execution.contracts import ExecutionOrderStatus, ExecutionOrderAction

        p = entry.payload
        try:
            return ExecutionAuditEvent(
                event_id=entry.entry_id,
                order_id=entry.order_id,
                client_order_id=p.get("client_order_id", ""),
                sequence_number=p.get("sequence_number", 0),
                previous_state=ExecutionOrderStatus(p["previous_state"]),
                new_state=ExecutionOrderStatus(p["new_state"]),
                action=ExecutionOrderAction(p["action"]),
                reason=p.get("reason"),
                event_timestamp=entry.timestamp,
                actor=p.get("actor", "system"),
                metadata=p.get("metadata"),
            )
        except (KeyError, ValueError) as exc:
            self._errors.append(f"Failed to convert journal entry {entry.entry_id}: {exc}")
            return None

    def _journal_entry_to_fill_event(
        self,
        entry: Any,
    ) -> FillEvent | None:
        """Convert a FILL_GENERATED journal entry to FillEvent."""
        from src.execution.contracts import ExecutionOrderSide

        p = entry.payload
        try:
            return FillEvent(
                fill_id=p["fill_id"],
                order_id=entry.order_id,
                client_order_id=p.get("client_order_id", ""),
                instrument_token=entry.instrument_token or 0,
                side=ExecutionOrderSide(p["side"]),
                quantity=p["quantity"],
                price=Decimal(p["price"]),
                gross_value=Decimal(p["gross_value"]),
                market_event_id=p["market_event_id"],
                market_timestamp=entry.timestamp,
                cumulative_filled_quantity=p.get("cumulative_filled_quantity", 0),
                remaining_quantity=p.get("remaining_quantity", 0),
                metadata=p.get("metadata"),
            )
        except (KeyError, ValueError, TypeError) as exc:
            self._errors.append(f"Failed to convert fill journal entry {entry.entry_id}: {exc}")
            return None

    # ------------------------------------------------------------------
    # State access
    # ------------------------------------------------------------------

    @property
    def replayed_event_count(self) -> int:
        return self._replayed_events

    @property
    def errors(self) -> list[str]:
        return list(self._errors)

    def reset(self) -> None:
        """Reset replay state for testing."""
        self._replayed_events = 0
        self._errors.clear()
        self._fill_builder.reset()
