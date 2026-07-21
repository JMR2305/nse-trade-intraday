"""Strategy Engine — Batch 9A/B.

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
from strategy.coordinator import StrategyCoordinator
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
]
