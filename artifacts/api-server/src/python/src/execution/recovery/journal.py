"""ExecutionJournal — immutable, append-only journal for recovery.

Batch 7D — Execution Recovery, Persistence & Replay Foundation.

The journal captures every significant event in the execution pipeline
as an immutable entry.  Entries are sequenced and replayable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum, auto
from typing import Any
from uuid import UUID


class JournalEntryType(Enum):
    """Types of journal entries."""

    ORDER_SUBMITTED = auto()
    STATE_TRANSITION = auto()
    FILL_GENERATED = auto()
    POSITION_UPDATED = auto()
    PORTFOLIO_UPDATED = auto()
    SNAPSHOT_CREATED = auto()
    RECOVERY_COMPLETED = auto()


@dataclass(frozen=True)
class JournalEntry:
    """Immutable journal entry.

    Attributes:
        entry_id: Unique identifier (UUID).
        entry_type: Classification of the entry.
        order_id: Associated order UUID (if applicable).
        instrument_token: NSE instrument token (if applicable).
        sequence_number: Monotonic sequence for ordering (global or per-order).
        timestamp: When the entry was created.
        payload: Typed payload dict (specific to entry_type).
    """

    entry_id: UUID
    entry_type: JournalEntryType
    order_id: UUID | None
    instrument_token: int | None
    sequence_number: int
    timestamp: datetime
    payload: dict[str, Any]


class ExecutionJournal:
    """Append-only, in-memory journal with optional DB persistence.

    The journal is the source of truth for recovery.  All entries are
    immutable and monotonically sequenced.
    """

    def __init__(self) -> None:
        self._entries: list[JournalEntry] = []
        self._global_sequence: int = 0
        self._order_sequences: dict[UUID, int] = {}
        self._entry_ids: set[UUID] = set()

    # ------------------------------------------------------------------
    # Append
    # ------------------------------------------------------------------

    def append(
        self,
        entry_type: JournalEntryType,
        order_id: UUID | None = None,
        instrument_token: int | None = None,
        payload: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
        entry_id: UUID | None = None,
    ) -> JournalEntry:
        """Append a new journal entry.  Idempotent by entry_id."""
        from uuid import uuid4 as _uuid4
        eid = entry_id if entry_id is not None else _uuid4()
        if eid in self._entry_ids:
            # Find and return existing
            for entry in self._entries:
                if entry.entry_id == eid:
                    return entry

        ts = timestamp or datetime.now(timezone.utc)
        payload = payload or {}

        # Per-order sequence if applicable, else global
        if order_id is not None:
            seq = self._order_sequences.get(order_id, -1) + 1
            self._order_sequences[order_id] = seq
        else:
            self._global_sequence += 1
            seq = self._global_sequence

        entry = JournalEntry(
            entry_id=eid,
            entry_type=entry_type,
            order_id=order_id,
            instrument_token=instrument_token,
            sequence_number=seq,
            timestamp=ts,
            payload=payload,
        )
        self._entries.append(entry)
        self._entry_ids.add(eid)
        return entry

    def append_order_submitted(
        self,
        order_id: UUID,
        client_order_id: str,
        instrument_token: int,
        side: str,
        order_type: str,
        quantity: int,
        limit_price: Decimal | None = None,
        trigger_price: Decimal | None = None,
        timestamp: datetime | None = None,
    ) -> JournalEntry:
        """Convenience: ORDER_SUBMITTED entry."""
        return self.append(
            entry_type=JournalEntryType.ORDER_SUBMITTED,
            order_id=order_id,
            instrument_token=instrument_token,
            payload={
                "client_order_id": client_order_id,
                "side": side,
                "order_type": order_type,
                "quantity": quantity,
                "limit_price": str(limit_price) if limit_price else None,
                "trigger_price": str(trigger_price) if trigger_price else None,
            },
            timestamp=timestamp,
        )

    def append_state_transition(
        self,
        order_id: UUID,
        action: str,
        previous_state: str,
        new_state: str,
        sequence_number: int,
        reason: str | None = None,
        actor: str = "system",
        timestamp: datetime | None = None,
    ) -> JournalEntry:
        """Convenience: STATE_TRANSITION entry."""
        return self.append(
            entry_type=JournalEntryType.STATE_TRANSITION,
            order_id=order_id,
            payload={
                "action": action,
                "previous_state": previous_state,
                "new_state": new_state,
                "sequence_number": sequence_number,
                "reason": reason,
                "actor": actor,
            },
            timestamp=timestamp,
        )

    def append_fill_generated(
        self,
        fill_id: str,
        order_id: UUID,
        instrument_token: int,
        side: str,
        quantity: int,
        price: Decimal,
        gross_value: Decimal,
        market_event_id: str,
        cumulative_filled_quantity: int,
        remaining_quantity: int,
        timestamp: datetime | None = None,
    ) -> JournalEntry:
        """Convenience: FILL_GENERATED entry."""
        return self.append(
            entry_type=JournalEntryType.FILL_GENERATED,
            order_id=order_id,
            instrument_token=instrument_token,
            payload={
                "fill_id": fill_id,
                "side": side,
                "quantity": quantity,
                "price": str(price),
                "gross_value": str(gross_value),
                "market_event_id": market_event_id,
                "cumulative_filled_quantity": cumulative_filled_quantity,
                "remaining_quantity": remaining_quantity,
            },
            timestamp=timestamp,
        )

    def append_position_updated(
        self,
        order_id: UUID,
        instrument_token: int,
        fill_id: str,
        position_impact: str,
        realized_pnl: Decimal,
        net_quantity: int,
        timestamp: datetime | None = None,
    ) -> JournalEntry:
        """Convenience: POSITION_UPDATED entry."""
        return self.append(
            entry_type=JournalEntryType.POSITION_UPDATED,
            order_id=order_id,
            instrument_token=instrument_token,
            payload={
                "fill_id": fill_id,
                "position_impact": position_impact,
                "realized_pnl": str(realized_pnl),
                "net_quantity": net_quantity,
            },
            timestamp=timestamp,
        )

    def append_portfolio_updated(
        self,
        cash: Decimal,
        equity: Decimal,
        realized_pnl: Decimal,
        unrealized_pnl: Decimal,
        trade_count: int,
        timestamp: datetime | None = None,
    ) -> JournalEntry:
        """Convenience: PORTFOLIO_UPDATED entry."""
        return self.append(
            entry_type=JournalEntryType.PORTFOLIO_UPDATED,
            payload={
                "cash": str(cash),
                "equity": str(equity),
                "realized_pnl": str(realized_pnl),
                "unrealized_pnl": str(unrealized_pnl),
                "trade_count": trade_count,
            },
            timestamp=timestamp,
        )

    def append_snapshot_created(
        self,
        snapshot_type: str,
        instrument_count: int,
        order_count: int,
        timestamp: datetime | None = None,
    ) -> JournalEntry:
        """Convenience: SNAPSHOT_CREATED entry."""
        return self.append(
            entry_type=JournalEntryType.SNAPSHOT_CREATED,
            payload={
                "snapshot_type": snapshot_type,
                "instrument_count": instrument_count,
                "order_count": order_count,
            },
            timestamp=timestamp,
        )

    def append_recovery_completed(
        self,
        orders_restored: int,
        positions_restored: int,
        trades_restored: int,
        journal_entries_replayed: int,
        timestamp: datetime | None = None,
    ) -> JournalEntry:
        """Convenience: RECOVERY_COMPLETED entry."""
        return self.append(
            entry_type=JournalEntryType.RECOVERY_COMPLETED,
            payload={
                "orders_restored": orders_restored,
                "positions_restored": positions_restored,
                "trades_restored": trades_restored,
                "journal_entries_replayed": journal_entries_replayed,
            },
            timestamp=timestamp,
        )

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    @property
    def entries(self) -> tuple[JournalEntry, ...]:
        """Immutable view of all entries."""
        return tuple(self._entries)

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    def get_entries_for_order(
        self,
        order_id: UUID,
    ) -> list[JournalEntry]:
        """Return all entries for a specific order."""
        return [e for e in self._entries if e.order_id == order_id]

    def get_entries_after(
        self,
        timestamp: datetime,
    ) -> list[JournalEntry]:
        """Return all entries after a given timestamp."""
        return [e for e in self._entries if e.timestamp > timestamp]

    def get_entries_by_type(
        self,
        entry_type: JournalEntryType,
    ) -> list[JournalEntry]:
        """Return all entries of a specific type."""
        return [e for e in self._entries if e.entry_type == entry_type]

    # ------------------------------------------------------------------
    # Reset (for testing / replay)
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear all entries.  Used in replay tests."""
        self._entries.clear()
        self._global_sequence = 0
        self._order_sequences.clear()
        self._entry_ids.clear()
