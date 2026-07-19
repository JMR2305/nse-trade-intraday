"""Tests for RecoveryManager.

Batch 7D — Execution Recovery, Persistence & Replay Foundation.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.execution.recovery.recovery_manager import RecoveryManager, RecoveryResult


class TestRecoveryManagerBasics:
    """Basic construction and state."""

    def test_recovery_manager_creation(self, state_machine, position_engine, trade_ledger):
        """RecoveryManager can be constructed with all dependencies."""
        # We need mock repos for this test
        manager = RecoveryManager(
            state_machine=state_machine,
            position_engine=position_engine,
            trade_ledger=trade_ledger,
            order_repo=None,  # type: ignore[arg-type]
            audit_repo=None,  # type: ignore[arg-type]
            fill_repo=None,  # type: ignore[arg-type]
            trade_repo=None,  # type: ignore[arg-type]
            position_repo=None,  # type: ignore[arg-type]
        )
        assert not manager.is_recovered

    def test_recovery_manager_reset(self, state_machine, position_engine, trade_ledger):
        """Reset clears recovery flag."""
        manager = RecoveryManager(
            state_machine=state_machine,
            position_engine=position_engine,
            trade_ledger=trade_ledger,
            order_repo=None,  # type: ignore[arg-type]
            audit_repo=None,  # type: ignore[arg-type]
            fill_repo=None,  # type: ignore[arg-type]
            trade_repo=None,  # type: ignore[arg-type]
            position_repo=None,  # type: ignore[arg-type]
        )
        manager._recovered = True
        manager.reset()
        assert not manager.is_recovered


class TestRecoveryResult:
    """RecoveryResult dataclass."""

    def test_recovery_result_creation(self):
        result = RecoveryResult(
            success=True,
            orders_restored=5,
            positions_restored=3,
            trades_restored=10,
            journal_entries_replayed=25,
            snapshot_used=True,
            consistency_report=None,
            errors=[],
            recovery_timestamp=datetime.now(timezone.utc),
        )
        assert result.success
        assert result.orders_restored == 5
        assert result.snapshot_used

    def test_recovery_result_with_errors(self):
        result = RecoveryResult(
            success=False,
            orders_restored=0,
            positions_restored=0,
            trades_restored=0,
            journal_entries_replayed=0,
            snapshot_used=False,
            consistency_report=None,
            errors=["DB connection failed"],
            recovery_timestamp=datetime.now(timezone.utc),
        )
        assert not result.success
        assert len(result.errors) == 1
