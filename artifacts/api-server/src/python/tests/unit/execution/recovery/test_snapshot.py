"""Tests for SnapshotManager and EngineSnapshot.

Batch 7D — Execution Recovery, Persistence & Replay Foundation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from src.execution.recovery.snapshot import SnapshotManager, EngineSnapshot
from src.execution.portfolio import PositionSnapshot


class TestEngineSnapshot:
    """EngineSnapshot dataclass behavior."""

    def test_snapshot_creation(self):
        snapshot = EngineSnapshot(
            snapshot_id=uuid4(),
            timestamp=datetime.now(timezone.utc),
        )
        assert snapshot.snapshot_id is not None
        assert snapshot.order_states == {}
        assert snapshot.positions == {}
        assert snapshot.trades == []
        assert snapshot.cash == Decimal("0")

    def test_snapshot_is_frozen(self):
        snapshot = EngineSnapshot(
            snapshot_id=uuid4(),
            timestamp=datetime.now(timezone.utc),
        )
        # Frozen dataclass — cannot modify
        with pytest.raises(AttributeError):
            snapshot.cash = Decimal("1000")

    def test_snapshot_with_positions(self, sample_position_snapshot):
        snapshot = EngineSnapshot(
            snapshot_id=uuid4(),
            timestamp=datetime.now(timezone.utc),
            positions={12345: sample_position_snapshot},
        )
        assert 12345 in snapshot.positions
        assert snapshot.positions[12345].net_quantity == 100


class TestSnapshotManager:
    """SnapshotManager behavior with mock repositories."""

    def test_snapshot_to_dict(self):
        """Test serialization helper."""
        snapshot = EngineSnapshot(
            snapshot_id=uuid4(),
            timestamp=datetime.now(timezone.utc),
            order_states={},
            positions={},
            trades=[],
            cash=Decimal("100000"),
            cumulative_realized_pnl=Decimal("500"),
        )
        # SnapshotManager requires repos, so we test the dict method directly
        # by creating a minimal manager with None repos (for this test only)
        manager = SnapshotManager(
            order_repo=None,  # type: ignore[arg-type]
            position_repo=None,  # type: ignore[arg-type]
            trade_repo=None,  # type: ignore[arg-type]
        )
        d = manager.snapshot_to_dict(snapshot)
        assert d["order_count"] == 0
        assert d["position_count"] == 0
        assert d["trade_count"] == 0
        assert d["cash"] == "100000"
        assert d["cumulative_realized_pnl"] == "500"
