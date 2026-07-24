"""Tests for RC-10D broker domain exceptions (Group B).

Covers:
  - All 13 exception types are subclasses of BrokerError
  - Default messages are correct
  - retryable attribute is correctly set
  - Credential values must never appear in repr/messages
  - __repr__ is safe to log
"""
from __future__ import annotations

import pytest

from src.brokers.exceptions import (
    BrokerAuthenticationError,
    BrokerConnectionError,
    BrokerDuplicateOrderError,
    BrokerError,
    BrokerKillSwitchError,
    BrokerLiveModeError,
    BrokerOrderNotFoundError,
    BrokerOrderRejectedError,
    BrokerProtocolError,
    BrokerRateLimitError,
    BrokerReconciliationError,
    BrokerSessionExpiredError,
    BrokerTimeoutError,
    BrokerUnavailableError,
    BrokerUnknownStatusError,
    BrokerValidationError,
)


# ---------------------------------------------------------------------------
# All exceptions are BrokerError subclasses
# ---------------------------------------------------------------------------

EXCEPTION_CLASSES = [
    BrokerAuthenticationError,
    BrokerSessionExpiredError,
    BrokerRateLimitError,
    BrokerTimeoutError,
    BrokerConnectionError,
    BrokerValidationError,
    BrokerOrderRejectedError,
    BrokerOrderNotFoundError,
    BrokerDuplicateOrderError,
    BrokerReconciliationError,
    BrokerUnavailableError,
    BrokerProtocolError,
    BrokerUnknownStatusError,
    BrokerKillSwitchError,
    BrokerLiveModeError,
]


@pytest.mark.parametrize("exc_class", EXCEPTION_CLASSES)
def test_all_are_broker_error_subclasses(exc_class):
    exc = exc_class()
    assert isinstance(exc, BrokerError)
    assert isinstance(exc, Exception)


@pytest.mark.parametrize("exc_class", EXCEPTION_CLASSES)
def test_all_can_be_raised_and_caught(exc_class):
    with pytest.raises(BrokerError):
        raise exc_class()


# ---------------------------------------------------------------------------
# Default messages
# ---------------------------------------------------------------------------

class TestDefaultMessages:
    def test_authentication_default_message(self):
        exc = BrokerAuthenticationError()
        assert "authentication" in str(exc).lower()

    def test_session_expired_default_message(self):
        exc = BrokerSessionExpiredError()
        assert "expired" in str(exc).lower()

    def test_rate_limit_default_message(self):
        exc = BrokerRateLimitError()
        assert "rate limit" in str(exc).lower()

    def test_timeout_default_message(self):
        exc = BrokerTimeoutError()
        assert "timeout" in str(exc).lower() or "timed" in str(exc).lower()

    def test_kill_switch_default_message(self):
        exc = BrokerKillSwitchError()
        assert "kill switch" in str(exc).lower()

    def test_live_mode_default_message(self):
        exc = BrokerLiveModeError()
        assert "live" in str(exc).lower() or "safety" in str(exc).lower()


# ---------------------------------------------------------------------------
# retryable attribute
# ---------------------------------------------------------------------------

class TestRetryable:
    def test_rate_limit_is_retryable(self):
        assert BrokerRateLimitError().retryable is True

    def test_connection_is_retryable(self):
        assert BrokerConnectionError().retryable is True

    def test_unavailable_is_retryable(self):
        assert BrokerUnavailableError().retryable is True

    def test_auth_not_retryable(self):
        assert BrokerAuthenticationError().retryable is False

    def test_session_expired_not_retryable(self):
        assert BrokerSessionExpiredError().retryable is False

    def test_order_rejected_not_retryable(self):
        assert BrokerOrderRejectedError().retryable is False

    def test_kill_switch_not_retryable(self):
        assert BrokerKillSwitchError().retryable is False

    def test_validation_not_retryable(self):
        assert BrokerValidationError().retryable is False

    def test_timeout_not_retryable_by_default(self):
        # Timeout on order placement must NOT be blindly retried
        assert BrokerTimeoutError().retryable is False


# ---------------------------------------------------------------------------
# Custom attributes
# ---------------------------------------------------------------------------

class TestCustomAttributes:
    def test_broker_error_code(self):
        exc = BrokerOrderRejectedError(broker_error_code="INSUFFICIENT_FUNDS")
        assert exc.broker_error_code == "INSUFFICIENT_FUNDS"

    def test_internal_order_id(self):
        exc = BrokerOrderRejectedError(internal_order_id="ORD-123")
        assert exc.internal_order_id == "ORD-123"

    def test_broker_order_id(self):
        exc = BrokerOrderRejectedError(broker_order_id="BRK-456")
        assert exc.broker_order_id == "BRK-456"

    def test_repr_contains_class_name(self):
        exc = BrokerAuthenticationError("test message")
        r = repr(exc)
        assert "BrokerAuthenticationError" in r

    def test_repr_safe_for_logging(self):
        """repr must not contain any credential-like strings."""
        exc = BrokerAuthenticationError(
            "Login failed",
            broker_error_code="E001",
            internal_order_id="ORD-1",
        )
        r = repr(exc)
        # Should not contain tokens, secrets, passwords
        for dangerous in ["secret", "token", "password", "key="]:
            assert dangerous not in r.lower()


# ---------------------------------------------------------------------------
# Exception chaining
# ---------------------------------------------------------------------------

class TestExceptionChaining:
    def test_can_chain_exceptions(self):
        original = ValueError("low level error")
        try:
            raise BrokerConnectionError("wrapped") from original
        except BrokerConnectionError as exc:
            assert exc.__cause__ is original

    def test_is_instance_check_works(self):
        exc = BrokerRateLimitError()
        assert isinstance(exc, BrokerError)
        assert not isinstance(exc, BrokerAuthenticationError)
