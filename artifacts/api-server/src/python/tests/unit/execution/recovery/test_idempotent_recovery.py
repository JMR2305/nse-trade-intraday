"""Tests for idempotent recovery behavior.

Batch 7D — Execution Recovery, Persistence & Replay Foundation.

Validates that recovery safely handles duplicates:
- Duplicate orders
- Duplicate fills
- Duplicate journal entries
- Duplicate snapshots
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from src.execution.contracts import (
    ExecutionOrderStatus,
    ExecutionOrderAction,
    ExecutionOrderSide,
)
from src.execution.fills import FillEvent
from src.execution.trades import ExecutionTrade
from src.execution.recovery.replay_engine import ReplayEngine
from src.execution.recovery.journal import ExecutionJournal, JournalEntryType


class TestIdempotentFillReplay:
    """Duplicate fill events during replay."""

    @pytest.mark.asyncio
    async def test_duplicate_fill_silently_ignored(self, state_machine, position_engine, sample_fill_event):
        """Replaying the same fill twice should not double-count."""
        engine = ReplayEngine(state_machine, position_engine)

        # First replay
        results1 = await engine.replay_fill_events([sample_fill_event])
        assert results1[0].trade_recorded
        pos1 = position_engine.get_position(sample_fill_event.instrument_token)
        assert pos1.net_quantity == 50

        # Second replay (same fill)
        results2 = await engine.replay_fill_events([sample_fill_event])
        assert not results2[0].trade_recorded  # Duplicate
        pos2 = position_engine.get_position(sample_fill_event.instrument_token)
        assert pos2.net_quantity == 50  # Unchanged

    @pytest.mark.asyncio
    async def test_multiple_duplicate_fills(self, state_machine, position_engine, sample_order):
        """Multiple duplicate fills in a batch."""
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

        # Replay same fill 3 times
        results = await engine.replay_fill_events([fill1, fill1, fill1])
        assert results[0].trade_recorded
        assert not results[1].trade_recorded
        assert not results[2].trade_recorded

        pos = position_engine.get_position(sample_order.instrument_token)
        assert pos.net_quantity == 50


class TestIdempotentAuditEventReplay:
    """Duplicate audit events during replay."""

    @pytest.mark.asyncio
    async def test_duplicate_audit_event_handled(self, state_machine, position_engine, sample_order):
        """Replaying the same audit event should be idempotent."""
        engine = ReplayEngine(state_machine, position_engine)
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

        # First replay
        results1 = await engine.replay_audit_events([audit])
        assert results1[0].success

        # Second replay (same event) — state machine handles idempotency
        results2 = await engine.replay_audit_events([audit])
        # May fail or succeed depending on state machine idempotency
        # The key is: state remains VALIDATED, no corruption
        state = state_machine.get_state(sample_order.order_id)
        assert state.status == ExecutionOrderStatus.VALIDATED


class TestIdempotentJournalEntries:
    """Duplicate journal entries."""

    def test_duplicate_journal_entry_id(self):
        """Journal should deduplicate by entry_id."""
        journal = ExecutionJournal()
        entry_id = uuid4()

        e1 = journal.append(
            JournalEntryType.ORDER_SUBMITTED,
            entry_id=entry_id,
        )
        e2 = journal.append(
            JournalEntryType.ORDER_SUBMITTED,
            entry_id=entry_id,
        )

        assert e1 is e2  # Same object returned
        assert journal.entry_count == 1


class TestIdempotentTradeRecording:
    """Duplicate trade recording."""

    def test_duplicate_trade_in_ledger(self, trade_ledger):
        """TradeLedger silently ignores duplicate fill_ids."""
        from src.execution.contracts import ExecutionOrderSide
        trade = ExecutionTrade(
            trade_id="T-001",
            fill_id="fill-001",
            order_id=uuid4(),
            client_order_id="test-001",
            instrument_token=12345,
            side=ExecutionOrderSide.BUY,
            quantity=100,
            price=Decimal("150.00"),
            gross_value=Decimal("15000.00"),
            position_impact="OPEN",
            market_timestamp=datetime.now(timezone.utc),
        )

        r1 = trade_ledger.record(trade)
        r2 = trade_ledger.record(trade)

        assert r1 is True
        assert r2 is False
        assert trade_ledger.trade_count == 1
