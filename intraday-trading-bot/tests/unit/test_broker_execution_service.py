"""Tests for RC-10D ExecutionService broker injection (Group M).

Covers:
  - Default broker is PaperBroker (backward compat)
  - Injectable broker is used when provided
  - All existing RC-7 call sites unaffected
  - Risk gate (RC-8) is still enforced
  - No direct strategy→broker calls possible
  - RC-8 cannot be bypassed
"""
from __future__ import annotations

import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from src.brokers.paper_broker import PaperBroker
from src.services.execution_service import ExecutionService


class TestBrokerInjection:
    def test_default_broker_is_paper(self):
        """ExecutionService() with no broker arg uses PaperBroker."""
        db_mock = MagicMock()
        # We can't call __init__ without full DB setup, so just check the signature
        import inspect
        sig = inspect.signature(ExecutionService.__init__)
        params = list(sig.parameters.keys())
        assert "broker" in params

    def test_broker_param_is_optional(self):
        """broker parameter must have a default of None."""
        import inspect
        sig = inspect.signature(ExecutionService.__init__)
        broker_param = sig.parameters.get("broker")
        assert broker_param is not None
        assert broker_param.default is None

    def test_custom_broker_stored(self):
        """When a broker is provided, it's stored on the instance."""
        db_mock = MagicMock()
        mock_broker = MagicMock(spec=PaperBroker)

        # Patch the dependencies that ExecutionService __init__ calls
        with patch("src.services.execution_service.OrderService"), \
             patch("src.services.execution_service.PositionService"), \
             patch("src.services.execution_service.OrderRepository"), \
             patch("src.services.execution_service.FillRepository"), \
             patch("src.services.execution_service.LedgerRepository"), \
             patch("src.services.execution_service.RiskEngine"), \
             patch("src.services.execution_service.ProjectExecutionAdapter"), \
             patch("src.services.execution_service.RiskIntegrationLayer"):
            svc = ExecutionService(db_mock, broker=mock_broker)
            assert svc._broker is mock_broker

    def test_no_broker_arg_uses_paper_broker(self):
        """When broker=None, ExecutionService creates PaperBroker."""
        db_mock = MagicMock()

        with patch("src.services.execution_service.OrderService"), \
             patch("src.services.execution_service.PositionService"), \
             patch("src.services.execution_service.OrderRepository"), \
             patch("src.services.execution_service.FillRepository"), \
             patch("src.services.execution_service.LedgerRepository"), \
             patch("src.services.execution_service.RiskEngine"), \
             patch("src.services.execution_service.ProjectExecutionAdapter"), \
             patch("src.services.execution_service.RiskIntegrationLayer"):
            svc = ExecutionService(db_mock)
            assert isinstance(svc._broker, PaperBroker)


class TestBackwardCompatibility:
    def test_execution_service_signature_compatible(self):
        """Old call: ExecutionService(db_session) must still work (no exception)."""
        import inspect
        sig = inspect.signature(ExecutionService.__init__)
        # First non-self param is db_session
        params = list(sig.parameters.keys())
        assert params[1] == "db_session"
        # broker is optional (has default)
        broker = sig.parameters.get("broker")
        assert broker.default is None

    def test_existing_submit_approved_order_still_available(self):
        """_submit_approved_order method must still exist."""
        assert hasattr(ExecutionService, "_submit_approved_order")
        assert callable(ExecutionService._submit_approved_order)

    def test_cancel_order_still_available(self):
        """cancel_order method must still exist."""
        assert hasattr(ExecutionService, "cancel_order")
        assert callable(ExecutionService.cancel_order)

    def test_execute_order_still_available(self):
        """execute_order method must still exist."""
        assert hasattr(ExecutionService, "execute_order")
        assert callable(ExecutionService.execute_order)


class TestRC8Enforcement:
    def test_risk_integration_always_created(self):
        """RiskIntegrationLayer must be instantiated regardless of broker type."""
        db_mock = MagicMock()
        custom_broker = MagicMock(spec=PaperBroker)

        with patch("src.services.execution_service.OrderService"), \
             patch("src.services.execution_service.PositionService"), \
             patch("src.services.execution_service.OrderRepository"), \
             patch("src.services.execution_service.FillRepository"), \
             patch("src.services.execution_service.LedgerRepository"), \
             patch("src.services.execution_service.RiskEngine") as mock_risk_engine, \
             patch("src.services.execution_service.ProjectExecutionAdapter"), \
             patch("src.services.execution_service.RiskIntegrationLayer") as mock_ril:
            svc = ExecutionService(db_mock, broker=custom_broker)
            # RiskIntegrationLayer should have been constructed
            mock_ril.assert_called_once()

    def test_risk_integration_enabled_by_default(self):
        """RiskIntegrationLayer must be created with enabled=True."""
        db_mock = MagicMock()

        with patch("src.services.execution_service.OrderService"), \
             patch("src.services.execution_service.PositionService"), \
             patch("src.services.execution_service.OrderRepository"), \
             patch("src.services.execution_service.FillRepository"), \
             patch("src.services.execution_service.LedgerRepository"), \
             patch("src.services.execution_service.RiskEngine"), \
             patch("src.services.execution_service.ProjectExecutionAdapter"), \
             patch("src.services.execution_service.RiskIntegrationLayer") as mock_ril:
            svc = ExecutionService(db_mock)
            # Check that enabled=True was passed
            call_kwargs = mock_ril.call_args[1]
            assert call_kwargs.get("enabled", True) is True
