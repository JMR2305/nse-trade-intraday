"""Execution Recovery, Persistence & Replay Foundation.

Batch 7D — Provides deterministic crash recovery for the paper execution engine.

Modules:
    journal: ExecutionJournal — immutable append-only event journal
    snapshot: SnapshotManager — engine state snapshots
    replay_engine: ReplayEngine — deterministic event replay
    recovery_manager: RecoveryManager — recovery orchestrator
    consistency_checker: ConsistencyChecker — post-recovery validation
    persistence_adapter: OrderStateMachinePersistenceAdapter, PositionEnginePersistenceAdapter

Usage:
    from src.execution.recovery import RecoveryManager, ExecutionJournal
"""
from __future__ import annotations

from src.execution.recovery.journal import ExecutionJournal, JournalEntry, JournalEntryType
from src.execution.recovery.snapshot import SnapshotManager, EngineSnapshot
from src.execution.recovery.replay_engine import ReplayEngine
from src.execution.recovery.recovery_manager import RecoveryManager, RecoveryResult
from src.execution.recovery.consistency_checker import ConsistencyChecker, ConsistencyReport, ConsistencyViolation
from src.execution.recovery.persistence_adapter import (
    OrderStateMachinePersistenceAdapter,
    PositionEnginePersistenceAdapter,
)

__all__ = [
    "ExecutionJournal",
    "JournalEntry",
    "JournalEntryType",
    "SnapshotManager",
    "EngineSnapshot",
    "ReplayEngine",
    "RecoveryManager",
    "RecoveryResult",
    "ConsistencyChecker",
    "ConsistencyReport",
    "ConsistencyViolation",
    "OrderStateMachinePersistenceAdapter",
    "PositionEnginePersistenceAdapter",
]
