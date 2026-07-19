"""Tests for ExecutionJournal.

Batch 7D — Execution Recovery, Persistence & Replay Foundation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from src.execution.recovery.journal import ExecutionJournal, JournalEntry, JournalEntryType


class TestExecutionJournalBasics:
    """Basic journal operations."""

    def test_empty_journal_has_zero_entries(self):
        journal = ExecutionJournal()
        assert journal.entry_count == 0
        assert len(journal.entries) == 0

    def test_append_increments_entry_count(self):
        journal = ExecutionJournal()
        journal.append(JournalEntryType.ORDER_SUBMITTED)
        assert journal.entry_count == 1

    def test_append_returns_journal_entry(self):
        journal = ExecutionJournal()
        entry = journal.append(JournalEntryType.ORDER_SUBMITTED)
        assert isinstance(entry, JournalEntry)
        assert entry.entry_type == JournalEntryType.ORDER_SUBMITTED

    def test_entries_are_immutable(self):
        journal = ExecutionJournal()
        journal.append(JournalEntryType.ORDER_SUBMITTED)
        entries = journal.entries
        # tuple is immutable
        with pytest.raises(TypeError):
            entries[0] = entries[0]  # type: ignore[index]


class TestJournalEntryTypes:
    """Journal entry type coverage."""

    def test_all_entry_types_exist(self):
        types = list(JournalEntryType)
        assert len(types) == 7
        assert JournalEntryType.ORDER_SUBMITTED in types
        assert JournalEntryType.STATE_TRANSITION in types
        assert JournalEntryType.FILL_GENERATED in types
        assert JournalEntryType.POSITION_UPDATED in types
        assert JournalEntryType.PORTFOLIO_UPDATED in types
        assert JournalEntryType.SNAPSHOT_CREATED in types
        assert JournalEntryType.RECOVERY_COMPLETED in types


class TestJournalConvenienceMethods:
    """Convenience append methods."""

    def test_append_order_submitted(self):
        journal = ExecutionJournal()
        order_id = uuid4()
        entry = journal.append_order_submitted(
            order_id=order_id,
            client_order_id="test-001",
            instrument_token=12345,
            side="BUY",
            order_type="LIMIT",
            quantity=100,
            limit_price=Decimal("150.00"),
        )
        assert entry.entry_type == JournalEntryType.ORDER_SUBMITTED
        assert entry.order_id == order_id
        assert entry.payload["client_order_id"] == "test-001"
        assert entry.payload["quantity"] == 100

    def test_append_state_transition(self):
        journal = ExecutionJournal()
        order_id = uuid4()
        entry = journal.append_state_transition(
            order_id=order_id,
            action="validate",
            previous_state="CREATED",
            new_state="VALIDATED",
            sequence_number=1,
        )
        assert entry.entry_type == JournalEntryType.STATE_TRANSITION
        assert entry.payload["action"] == "validate"
        assert entry.payload["sequence_number"] == 1

    def test_append_fill_generated(self):
        journal = ExecutionJournal()
        order_id = uuid4()
        entry = journal.append_fill_generated(
            fill_id="fill-001",
            order_id=order_id,
            instrument_token=12345,
            side="BUY",
            quantity=50,
            price=Decimal("150.00"),
            gross_value=Decimal("7500.00"),
            market_event_id="market-001",
            cumulative_filled_quantity=50,
            remaining_quantity=50,
        )
        assert entry.entry_type == JournalEntryType.FILL_GENERATED
        assert entry.payload["fill_id"] == "fill-001"

    def test_append_position_updated(self):
        journal = ExecutionJournal()
        order_id = uuid4()
        entry = journal.append_position_updated(
            order_id=order_id,
            instrument_token=12345,
            fill_id="fill-001",
            position_impact="OPEN",
            realized_pnl=Decimal("0"),
            net_quantity=50,
        )
        assert entry.entry_type == JournalEntryType.POSITION_UPDATED
        assert entry.payload["position_impact"] == "OPEN"

    def test_append_portfolio_updated(self):
        journal = ExecutionJournal()
        entry = journal.append_portfolio_updated(
            cash=Decimal("900000"),
            equity=Decimal("950000"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("5000"),
            trade_count=1,
        )
        assert entry.entry_type == JournalEntryType.PORTFOLIO_UPDATED
        assert entry.payload["cash"] == "900000"

    def test_append_snapshot_created(self):
        journal = ExecutionJournal()
        entry = journal.append_snapshot_created(
            snapshot_type="full",
            instrument_count=5,
            order_count=10,
        )
        assert entry.entry_type == JournalEntryType.SNAPSHOT_CREATED
        assert entry.payload["snapshot_type"] == "full"

    def test_append_recovery_completed(self):
        journal = ExecutionJournal()
        entry = journal.append_recovery_completed(
            orders_restored=5,
            positions_restored=3,
            trades_restored=10,
            journal_entries_replayed=25,
        )
        assert entry.entry_type == JournalEntryType.RECOVERY_COMPLETED
        assert entry.payload["orders_restored"] == 5


class TestJournalSequencing:
    """Sequence number behavior."""

    def test_global_sequence_increments_without_order_id(self):
        journal = ExecutionJournal()
        e1 = journal.append(JournalEntryType.PORTFOLIO_UPDATED)
        e2 = journal.append(JournalEntryType.PORTFOLIO_UPDATED)
        assert e1.sequence_number == 1
        assert e2.sequence_number == 2

    def test_per_order_sequence_increments(self):
        journal = ExecutionJournal()
        order_id = uuid4()
        e1 = journal.append(JournalEntryType.STATE_TRANSITION, order_id=order_id)
        e2 = journal.append(JournalEntryType.STATE_TRANSITION, order_id=order_id)
        assert e1.sequence_number == 0
        assert e2.sequence_number == 1

    def test_different_orders_have_independent_sequences(self):
        journal = ExecutionJournal()
        oid1 = uuid4()
        oid2 = uuid4()
        e1 = journal.append(JournalEntryType.STATE_TRANSITION, order_id=oid1)
        e2 = journal.append(JournalEntryType.STATE_TRANSITION, order_id=oid2)
        e3 = journal.append(JournalEntryType.STATE_TRANSITION, order_id=oid1)
        assert e1.sequence_number == 0
        assert e2.sequence_number == 0
        assert e3.sequence_number == 1


class TestJournalQueries:
    """Query methods."""

    def test_get_entries_for_order(self):
        journal = ExecutionJournal()
        oid1 = uuid4()
        oid2 = uuid4()
        journal.append(JournalEntryType.STATE_TRANSITION, order_id=oid1)
        journal.append(JournalEntryType.STATE_TRANSITION, order_id=oid2)
        journal.append(JournalEntryType.FILL_GENERATED, order_id=oid1)

        entries = journal.get_entries_for_order(oid1)
        assert len(entries) == 2

    def test_get_entries_by_type(self):
        journal = ExecutionJournal()
        journal.append(JournalEntryType.ORDER_SUBMITTED)
        journal.append(JournalEntryType.STATE_TRANSITION)
        journal.append(JournalEntryType.ORDER_SUBMITTED)

        entries = journal.get_entries_by_type(JournalEntryType.ORDER_SUBMITTED)
        assert len(entries) == 2

    def test_get_entries_after_timestamp(self):
        journal = ExecutionJournal()
        before = datetime.now(timezone.utc)
        journal.append(JournalEntryType.ORDER_SUBMITTED)
        after = datetime.now(timezone.utc)
        journal.append(JournalEntryType.STATE_TRANSITION)

        entries = journal.get_entries_after(before)
        assert len(entries) == 2

        entries = journal.get_entries_after(after)
        assert len(entries) == 1


class TestJournalReset:
    """Reset behavior."""

    def test_reset_clears_all_entries(self):
        journal = ExecutionJournal()
        journal.append(JournalEntryType.ORDER_SUBMITTED)
        journal.append(JournalEntryType.STATE_TRANSITION)
        assert journal.entry_count == 2

        journal.reset()
        assert journal.entry_count == 0
        assert len(journal.entries) == 0

    def test_reset_clears_sequences(self):
        journal = ExecutionJournal()
        order_id = uuid4()
        journal.append(JournalEntryType.STATE_TRANSITION, order_id=order_id)
        journal.reset()
        entry = journal.append(JournalEntryType.STATE_TRANSITION, order_id=order_id)
        assert entry.sequence_number == 0  # restarted
