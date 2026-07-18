"""Core exceptions for the trading platform."""


class TradingPlatformError(Exception):
    """Base exception for all trading platform errors."""
    pass


class ConfigurationError(TradingPlatformError):
    """Raised when configuration is invalid or missing."""
    pass


class AuthenticationError(TradingPlatformError):
    """Raised when authentication fails."""
    pass


class AuthorizationError(TradingPlatformError):
    """Raised when user is not authorized for an action."""
    pass


class IdempotencyError(TradingPlatformError):
    """Raised when idempotency check fails."""
    pass


class KillSwitchError(TradingPlatformError):
    """Raised when kill switch blocks an operation."""
    pass


class RiskLimitError(TradingPlatformError):
    """Raised when a risk limit is exceeded."""
    pass


class OrderValidationError(TradingPlatformError):
    """Raised when order validation fails."""
    pass


class SessionError(TradingPlatformError):
    """Raised when session operations fail."""
    pass


class BrokerError(TradingPlatformError):
    """Raised when broker operations fail."""
    pass


class LiveModeBlockedError(TradingPlatformError):
    """Raised when live trading is attempted. Structurally unavailable."""
    pass
