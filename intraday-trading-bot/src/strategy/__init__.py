"""Strategy Engine — Batch 9A/B/C/D.

Protocol-based strategy framework for signal generation and order routing.
"""

from strategy.contracts import (
    Signal,
    SignalAction,
    StrategyConfig,
    StrategyContext,
    StrategyLifecycleState,
    StrategyStateSnapshot,
    StrategyPerformanceSnapshot,
    SignalRoutingResult,
    StrategyRegistrationResult,
    ConflictResolution,
)
from strategy.strategy_protocol import Strategy
from strategy.state_machine import StrategyStateMachine, TransitionResult
from strategy.runtime import StrategyRuntime
from strategy.signal_router import SignalRouter
from strategy.coordinator import StrategyCoordinator, ShutdownResult
from strategy.context_builder import ContextBuilder
from strategy.fill_tracker import StrategyFillTracker
from strategy.exceptions import (
    StrategyError,
    InvalidSignalError,
    SignalValidationError,
    StrategyConflictError,
    LifecycleTransitionError,
    StrategyNotFoundError,
    StrategyAlreadyRegisteredError,
    OrderMappingError,
    PositionLimitExceededError,
    StrategyRuntimeError,
)

# Batch 9C — session context (no circular risk)
from strategy.session_context import SessionContext
# NOTE: strategy.persistence and strategy.recovery are NOT re-exported here
# because recovery.py imports from src.strategy.persistence which creates a
# circular import through this __init__.py.  Import them directly from their
# modules when needed:
#   from strategy.persistence import StrategyPersistenceAdapter, ...
#   from strategy.recovery import StrategyRecoveryManager, ...

# Batch 9D-B — production hardening
from strategy.metrics import MetricsCollector, StrategyMetrics
from strategy.health import StrategyHealthMonitor, StrategyHealthStatus, HealthReport
from strategy.fault_isolation import FaultIsolator, FaultAction, FaultBudget, FaultIsolationStatus

__all__ = [
    # Contracts
    "Signal",
    "SignalAction",
    "StrategyConfig",
    "StrategyContext",
    "StrategyLifecycleState",
    "StrategyStateSnapshot",
    "StrategyPerformanceSnapshot",
    "SignalRoutingResult",
    "StrategyRegistrationResult",
    "ConflictResolution",
    # Protocol
    "Strategy",
    # State machine
    "StrategyStateMachine",
    "TransitionResult",
    # Runtime
    "StrategyRuntime",
    "SignalRouter",
    "StrategyCoordinator",
    "ShutdownResult",
    "ContextBuilder",
    "StrategyFillTracker",
    # Exceptions
    "StrategyError",
    "InvalidSignalError",
    "SignalValidationError",
    "StrategyConflictError",
    "LifecycleTransitionError",
    "StrategyNotFoundError",
    "StrategyAlreadyRegisteredError",
    "OrderMappingError",
    "PositionLimitExceededError",
    "StrategyRuntimeError",
    # Batch 9C — session context
    "SessionContext",
    # Batch 9D-B — production hardening
    "MetricsCollector",
    "StrategyMetrics",
    "StrategyHealthMonitor",
    "StrategyHealthStatus",
    "HealthReport",
    "FaultIsolator",
    "FaultAction",
    "FaultBudget",
    "FaultIsolationStatus",
]
