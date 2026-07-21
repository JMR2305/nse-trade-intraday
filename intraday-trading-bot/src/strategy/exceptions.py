"""Typed exception hierarchy for the Strategy Engine."""


class StrategyError(Exception):
    """Base exception for all strategy-related errors."""
    pass


class InvalidSignalError(StrategyError):
    """Raised when a signal fails validation."""
    pass


class SignalValidationError(StrategyError):
    """Raised when signal-to-order mapping fails validation."""
    pass


class StrategyConflictError(StrategyError):
    """Raised when two strategies generate conflicting signals."""
    pass


class LifecycleTransitionError(StrategyError):
    """Raised when an invalid lifecycle state transition is attempted."""
    pass


class StrategyNotFoundError(StrategyError):
    """Raised when a strategy_id cannot be found."""
    pass


class StrategyAlreadyRegisteredError(StrategyError):
    """Raised when attempting to register a strategy with a duplicate ID."""
    pass


class OrderMappingError(StrategyError):
    """Raised when a signal cannot be mapped to an ExecutionOrder."""
    pass


class PositionLimitExceededError(StrategyError):
    """Raised when a signal would exceed strategy position limits."""
    pass


class StrategyRuntimeError(StrategyError):
    """Raised when the strategy runtime encounters an unrecoverable error."""
    pass
