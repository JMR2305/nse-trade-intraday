"""RC-10D: Broker domain exceptions.

All broker-specific exceptions inherit from BrokerError.
Raw third-party exceptions (kiteconnect.NetworkException, etc.) must never
leak into the execution domain — they must be caught inside src/brokers/zerodha/
and re-raised as one of these domain exceptions.

No exception message or attribute should include:
  - API secrets
  - Access tokens
  - Request tokens
  - Full authentication payloads
"""
from __future__ import annotations

from typing import Optional


class BrokerError(Exception):
    """Base class for all broker layer errors."""

    def __init__(
        self,
        message: str,
        *,
        broker_error_code: Optional[str] = None,
        internal_order_id: Optional[str] = None,
        broker_order_id: Optional[str] = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.broker_error_code = broker_error_code
        self.internal_order_id = internal_order_id
        self.broker_order_id = broker_order_id
        self.retryable = retryable

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"message={str(self)!r}, "
            f"code={self.broker_error_code!r}, "
            f"internal_order_id={self.internal_order_id!r}"
            f")"
        )


class BrokerAuthenticationError(BrokerError):
    """Authentication failed — invalid credentials or missing token."""
    def __init__(self, message: str = "Broker authentication failed", **kwargs):
        super().__init__(message, **kwargs)


class BrokerSessionExpiredError(BrokerError):
    """Access token expired — re-authentication required."""
    def __init__(self, message: str = "Broker session expired", **kwargs):
        super().__init__(message, **kwargs)


class BrokerRateLimitError(BrokerError):
    """Rate limit exceeded — request rejected to protect the API budget."""
    def __init__(self, message: str = "Broker rate limit exceeded", **kwargs):
        kwargs.setdefault("retryable", True)
        super().__init__(message, **kwargs)


class BrokerTimeoutError(BrokerError):
    """Request timed out — broker response not received in time.

    IMPORTANT: A timeout on order placement does NOT mean the order was NOT
    received by the broker. Placement timeouts must enter reconciliation,
    not blind retry.
    """
    def __init__(self, message: str = "Broker request timed out", **kwargs):
        super().__init__(message, **kwargs)


class BrokerConnectionError(BrokerError):
    """Network or connection failure."""
    def __init__(self, message: str = "Broker connection failed", **kwargs):
        kwargs.setdefault("retryable", True)
        super().__init__(message, **kwargs)


class BrokerValidationError(BrokerError):
    """Order parameters failed broker-side validation before submission."""
    def __init__(self, message: str = "Broker order validation failed", **kwargs):
        super().__init__(message, **kwargs)


class BrokerOrderRejectedError(BrokerError):
    """Broker explicitly rejected the order (e.g. insufficient margin)."""
    def __init__(self, message: str = "Broker rejected order", **kwargs):
        super().__init__(message, **kwargs)


class BrokerOrderNotFoundError(BrokerError):
    """Order not found in broker system."""
    def __init__(self, message: str = "Broker order not found", **kwargs):
        super().__init__(message, **kwargs)


class BrokerDuplicateOrderError(BrokerError):
    """Duplicate order detected — idempotency key already used."""
    def __init__(self, message: str = "Duplicate broker order detected", **kwargs):
        super().__init__(message, **kwargs)


class BrokerReconciliationError(BrokerError):
    """Reconciliation process encountered an unresolvable discrepancy."""
    def __init__(self, message: str = "Broker reconciliation error", **kwargs):
        super().__init__(message, **kwargs)


class BrokerUnavailableError(BrokerError):
    """Broker service is unavailable or in maintenance mode."""
    def __init__(self, message: str = "Broker service unavailable", **kwargs):
        kwargs.setdefault("retryable", True)
        super().__init__(message, **kwargs)


class BrokerProtocolError(BrokerError):
    """Unexpected or malformed broker response."""
    def __init__(self, message: str = "Broker protocol error", **kwargs):
        super().__init__(message, **kwargs)


class BrokerUnknownStatusError(BrokerError):
    """Order status not in the known canonical set — persisted and alerted."""
    def __init__(self, message: str = "Unknown broker order status", **kwargs):
        super().__init__(message, **kwargs)


class BrokerKillSwitchError(BrokerError):
    """Order blocked by the platform kill switch."""
    def __init__(self, message: str = "Order blocked by kill switch", **kwargs):
        super().__init__(message, **kwargs)


class BrokerLiveModeError(BrokerError):
    """Attempted live order without satisfying all live-mode safety gates."""
    def __init__(self, message: str = "Live order requires all safety gates", **kwargs):
        super().__init__(message, **kwargs)
