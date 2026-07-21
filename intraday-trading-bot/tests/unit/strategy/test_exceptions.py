"""Tests for strategy/exceptions.py."""
import pytest

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
)


class TestExceptions:
    def test_strategy_error_is_exception(self):
        err = StrategyError("test")
        assert isinstance(err, Exception)
        assert str(err) == "test"

    def test_invalid_signal_error(self):
        err = InvalidSignalError("bad signal")
        assert isinstance(err, StrategyError)
        assert "bad signal" in str(err)

    def test_signal_validation_error(self):
        err = SignalValidationError("validation failed")
        assert isinstance(err, StrategyError)

    def test_strategy_conflict_error(self):
        err = StrategyConflictError("conflict")
        assert isinstance(err, StrategyError)

    def test_lifecycle_transition_error(self):
        err = LifecycleTransitionError("invalid transition")
        assert isinstance(err, StrategyError)

    def test_strategy_not_found_error(self):
        err = StrategyNotFoundError("not found")
        assert isinstance(err, StrategyError)

    def test_strategy_already_registered_error(self):
        err = StrategyAlreadyRegisteredError("already exists")
        assert isinstance(err, StrategyError)

    def test_order_mapping_error(self):
        err = OrderMappingError("mapping failed")
        assert isinstance(err, StrategyError)

    def test_position_limit_exceeded_error(self):
        err = PositionLimitExceededError("limit exceeded")
        assert isinstance(err, StrategyError)
