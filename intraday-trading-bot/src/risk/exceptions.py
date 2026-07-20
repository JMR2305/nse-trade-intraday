"""
Risk Engine exception hierarchy.

Typed exceptions for clear error handling and debugging.
All exceptions inherit from RiskEngineException.
"""

from __future__ import annotations


class RiskEngineException(Exception):
    """Base exception for all Risk Engine errors."""
    pass


class RiskLimitNotFoundError(RiskEngineException):
    """Raised when a referenced risk limit does not exist."""
    pass


class RiskStateCorruptionError(RiskEngineException):
    """Raised when risk state is inconsistent or corrupted."""
    pass


class RiskCheckError(RiskEngineException):
    """Raised when a risk check fails due to internal error (not a violation)."""
    pass


class KillSwitchAlreadyActiveError(RiskEngineException):
    """Raised when attempting to activate an already-active kill switch."""
    pass


class KillSwitchNotActiveError(RiskEngineException):
    """Raised when attempting to deactivate an inactive kill switch."""
    pass


class AccountNotRegisteredError(RiskEngineException):
    """Raised when an operation is attempted on an unregistered account."""
    pass
