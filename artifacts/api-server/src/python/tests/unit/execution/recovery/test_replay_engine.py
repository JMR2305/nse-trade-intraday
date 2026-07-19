"""Tests for ReplayEngine.

Batch 7D — Execution Recovery, Persistence & Replay Foundation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from src.execution.fills import FillEvent
from src.execution.recovery.replay_engine import ReplayEngine
from src.execution.contracts import ExecutionOrderStatus, ExecutionOrderAction


class TestReplayEngineBasics:
    """Basic replay engine construction."""

    def test_replay_engine_creation(self, state_machine, position_engine):
        engine = ReplayEngine(state_machine, position_engine)
        assert engine.replayed_event_count == 0
        assert engine.errors == []

    def test_replay_engine_reset(self, state_machine, position_engine):
        engine = ReplayEngine(state_machine, position_engine)
        engine._replayed_events = 5
        engine._errors.append("test error")
        engine.reset()
        assert engine.replayed_event_count == 0
        assert engine.errors == []


class TestReplayAuditEvents:
    """Replay of audit events through state machine."""

    @pytest.mark.asyncio
    async def test_replay_single_audit_event(self, state_machine, position_engine, sample_order):
        """Replay a validate transition."""
        engine = ReplayEngine(state_machine, position_engine)
        # First register the order
        state_machine.register(sample_order)

        from src.execution.contracts import ExecutionAuditEvent
        audit = ExecutionAuditEvent(
            event_id=uuid4(),
            order_id=sample_order.order_id,
            client_order_id=sample_order.client_order_id,
            sequence_number=0,
            previous_state=ExecutionOrderStatus.CREATED,
            new_state=ExecutionOrderStatus.VALIDATED,
            action=ExecutionOrderAction.VALIDATE,
        )

        results = await engine.replay_audit_events([audit])
        assert len(results) == 1
        assert results[0].success
        assert results[0].new_state == ExecutionOrderStatus.VALIDATED

    @pytest.mark.asyncio
    async def test_replay_audit_event_order_not_registered(self, state_machine, position_engine, sample_order):
        """Replay fails gracefully if order not registered."""
        engine = ReplayEngine(state_machine, position_engine)

        from src.execution.contracts import ExecutionAuditEvent
        audit = ExecutionAuditEvent(
            event_id=uuid4(),
            order_id=sample_order.order_id,
            client_order_id=sample_order.client_order_id,
            sequence_number=0,
            previous_state=ExecutionOrderStatus.CREATED,
            new_state=ExecutionOrderStatus.VALIDATED,
            action=ExecutionOrderAction.VALIDATE,
        )

        results = await engine.replay_audit_events([audit])
        assert len(results) == 0  # Failed, not added to results
        assert len(engine.errors) == 1

    @pytest.mark.asyncio
    async def test_replay_multiple_audit_events(self, state_machine, position_engine, sample_order):
        """Replay a sequence of transitions."""
        engine = ReplayEngine(state_machine, position_engine)
        state_machine.register(sample_order)

        from src.execution.contracts import ExecutionAuditEvent
        events = [
            ExecutionAuditEvent(
                event_id=uuid4(),
                order_id=sample_order.order_id,
                client_order_id=sample_order.client_order_id,
                sequence_number=0,
                previous_state=ExecutionOrderStatus.CREATED,
                new_state=ExecutionOrderStatus.VALIDATED,
                action=ExecutionOrderAction.VALIDATE,
            ),
            ExecutionAuditEvent(
                event_id=uuid4(),
                order_id=sample_order.order_id,
                client_order_id=sample_order.client_order_id,
                sequence_number=1,
                previous_state=ExecutionOrderStatus.VALIDATED,
                new_state=ExecutionOrderStatus.ACCEPTED,
                action=ExecutionOrderAction.ACCEPT,
            ),
        ]

        results = await engine.replay_audit_events(events)
        assert len(results) == 2
        assert results[0].new_state == ExecutionOrderStatus.VALIDATED
        assert results[1].new_state == ExecutionOrderStatus.ACCEPTED


class TestReplayFillEvents:
    """Replay of fill events through position engine."""

    @pytest.mark.asyncio
    async def test_replay_single_fill(self, state_machine, position_engine, sample_fill_event):
        """Replay a fill event."""
        engine = ReplayEngine(state_machine, position_engine)
        results = await engine.replay_fill_events([sample_fill_event])
        assert len(results) == 1
        assert results[0].trade_recorded
        assert results[0].position_impact == "OPEN"

    @pytest.mark.asyncio
    async def test_replay_duplicate_fill_is_idempotent(self, state_machine, position_engine, sample_fill_event):
        """Duplicate fills are silently ignored by PositionEngine."""
        engine = ReplayEngine(state_machine, position_engine)
        results = await engine.replay_fill_events([sample_fill_event, sample_fill_event])
        assert len(results) == 2
        assert results[0].trade_recorded
        assert not results[1].trade_recorded  # Duplicate

    @pytest.mark.asyncio
    async def test_replay_multiple_fills_same_instrument(self, state_machine, position_engine, sample_order):
        """Replay multiple fills building a position."""
        engine = ReplayEngine(state_machine, position_engine)

        fill1 = FillEvent(
            fill_id="fill-001",
            order_id=sample_order.order_id,
            client_order_id=sample_order.client_order_id,
            instrument_token=sample_order.instrument_token,
            side=sample_order.side,
            quantity=50,
            price=Decimal("150.00"),
            gross_value=Decimal("7500.00"),
            market_event_id="market-001",
            market_timestamp=datetime.now(timezone.utc),
            cumulative_filled_quantity=50,
            remaining_quantity=50,
        )
        fill2 = FillEvent(
            fill_id="fill-002",
            order_id=sample_order.order_id,
            client_order_id=sample_order.client_order_id,
            instrument_token=sample_order.instrument_token,
            side=sample_order.side,
            quantity=50,
            price=Decimal("151.00"),
            gross_value=Decimal("7550.00"),
            market_event_id="market-002",
            market_timestamp=datetime.now(timezone.utc),
            cumulative_filled_quantity=100,
            remaining_quantity=0,
        )

        results = await engine.replay_fill_events([fill1, fill2])
        assert len(results) == 2
        assert results[0].position_impact == "OPEN"
        assert results[1].position_impact == "ADD"


class TestReplayJournalEntries:
    """Replay via journal entries."""

    @pytest.mark.asyncio
    async def test_replay_journal_state_transition(self, state_machine, position_engine, sample_order):
        """Replay a STATE_TRANSITION journal entry."""
        engine = ReplayEngine(state_machine, position_engine)
        state_machine.register(sample_order)

        from src.execution.recovery.journal import ExecutionJournal
        journal = ExecutionJournal()
        entry = journal.append_state_transition(
            order_id=sample_order.order_id,
            action="validate",
            previous_state="CREATED",
            new_state="VALIDATED",
            sequence_number=0,
        )

        result = await engine.replay_journal_entries([entry])
        assert result["transitions_replayed"] == 1
        assert result["fills_replayed"] == 0

    @pytest.mark.asyncio
    async def test_replay_journal_fill(self, state_machine, position_engine, sample_order):
        """Replay a FILL_GENERATED journal entry."""
        engine = ReplayEngine(state_machine, position_engine)

        from src.execution.recovery.journal import ExecutionJournal
        journal = ExecutionJournal()
        entry = journal.append_fill_generated(
            fill_id="fill-001",
            order_id=sample_order.order_id,
            instrument_token=12345,
            side="BUY",
            quantity=50,
            price=Decimal("150.00"),
            gross_value=Decimal("7500.00"),
            market_event_id="market-001",
            cumulative_filled_quantity=50,
            remaining_quantity=50,
        )

        result = await engine.replay_journal_entries([entry])
        assert result["transitions_replayed"] == 0
        assert result["fills_replayed"] == 1
