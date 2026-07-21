"""
Risk Engine exception hierarchy.

All exceptions inherit from RiskEngineError for easy catch-all handling.
"""

from __future__ import annotations

from typing import Optional, List
from .contracts import RiskViolation


class RiskEngineError(Exception):
    """Base exception for all Risk Engine errors."""


class RiskCheckFailed(RiskEngineError):
    """Raised when a risk check rejects an order (one or more fatal violations)."""

    def __init__(self, message: str, violations: Optional[List[RiskViolation]] = None):
        super().__init__(message)
        self.violations: List[RiskViolation] = violations or []

    def __str__(self) -> str:
        base = self.args[0]
        if self.violations:
            reasons = "; ".join(v.message for v in self.violations)
            return f"{base}: {reasons}"
        return base


class KillSwitchActive(RiskEngineError):
    """Raised when the kill switch is active and an order is submitted."""

    def __init__(self, reason: Optional[str] = None):
        self.reason = reason
        message = f"Kill switch is active: {reason}" if reason else "Kill switch is active"
        super().__init__(message)


class EmergencyHaltActive(RiskEngineError):
    """Raised when emergency halt is active and an order is submitted."""

    def __init__(self, reason: Optional[str] = None):
        self.reason = reason
        message = (
            f"Emergency halt is active: {reason}" if reason else "Emergency halt is active"
        )
        super().__init__(message)


class CircuitBreakerTriggered(RiskEngineError):
    """Raised when the circuit breaker has triggered."""


class DailyLossLimitBreached(RiskEngineError):
    """Raised when the daily loss limit has been breached."""


class ThrottleLimitBreached(RiskEngineError):
    """Raised when the message throttle limit has been breached."""


class RiskStateError(RiskEngineError):
    """Raised when there is an error with the risk state."""


class RiskStateCorrupted(RiskStateError):
    """Raised when the risk state is found to be corrupted or unreadable."""


class RiskStateNotFound(RiskStateError):
    """Raised when risk state cannot be found for an account."""


class RiskConfigurationError(RiskEngineError):
    """Raised when risk engine configuration is invalid."""


class FillDeliveryError(RiskEngineError):
    """Raised when fill event delivery to the fill event bus fails."""

    def __init__(self, fill_id: str, reason: str):
        self.fill_id = fill_id
        self.reason = reason
        super().__init__(f"Fill delivery failed for fill {fill_id}: {reason}")


class IntegrationLayerError(RiskEngineError):
    """Raised when the Risk Integration Layer encounters a non-recoverable error."""
