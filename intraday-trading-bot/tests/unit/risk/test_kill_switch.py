"""
Unit tests for risk/kill_switch.py.
"""

import pytest
from datetime import datetime

from src.risk.kill_switch import KillSwitch, KillSwitchEvent
from src.risk.contracts import RiskViolation, RiskSeverity


class TestKillSwitch:
    @pytest.fixture
    def ks(self):
        return KillSwitch("ACC001")

    def test_initial_state(self, ks):
        assert ks.is_active is False
        assert ks.reason is None
        assert ks.get_history() == []

    def test_activate(self, ks):
        event = ks.activate("Test reason", actor="admin", timestamp=datetime(2024, 1, 1, 12, 0, 0))
        assert ks.is_active is True
        assert ks.reason == "Test reason"
        assert isinstance(event, KillSwitchEvent)
        assert event.action == "ACTIVATED"
        assert event.actor == "admin"
        assert event.reason == "Test reason"

    def test_deactivate(self, ks):
        ks.activate("Test reason", timestamp=datetime(2024, 1, 1, 12, 0, 0))
        event = ks.deactivate("Resolved", actor="admin", timestamp=datetime(2024, 1, 1, 12, 5, 0))
        assert ks.is_active is False
        assert ks.reason is None
        assert event.action == "DEACTIVATED"

    def test_history(self, ks):
        ks.activate("First", timestamp=datetime(2024, 1, 1, 12, 0, 0))
        ks.deactivate("Resolved", timestamp=datetime(2024, 1, 1, 12, 5, 0))
        ks.activate("Second", timestamp=datetime(2024, 1, 1, 13, 0, 0))

        history = ks.get_history()
        assert len(history) == 3
        assert history[0].action == "ACTIVATED"
        assert history[1].action == "DEACTIVATED"
        assert history[2].action == "ACTIVATED"

    def test_evaluate_order_inactive(self, ks):
        result = ks.evaluate_order("BUY", "FLAT")
        assert result is None

    def test_evaluate_order_active_blocks_all(self, ks):
        ks.activate("Emergency", timestamp=datetime.utcnow())
        result = ks.evaluate_order("BUY", "FLAT")
        assert result is not None
        assert result.severity == RiskSeverity.FATAL

    def test_evaluate_order_risk_reducing_allowed(self):
        ks = KillSwitch("ACC001", allow_risk_reducing=True)
        ks.activate("Emergency", timestamp=datetime.utcnow())

        result = ks.evaluate_order("SELL", "LONG")
        assert result is None

        result = ks.evaluate_order("BUY", "FLAT")
        assert result is not None

    def test_evaluate_order_risk_reducing_short(self):
        ks = KillSwitch("ACC001", allow_risk_reducing=True)
        ks.activate("Emergency", timestamp=datetime.utcnow())

        result = ks.evaluate_order("BUY", "SHORT")
        assert result is None

        result = ks.evaluate_order("SELL", "SHORT")
        assert result is not None

    def test_reset(self, ks):
        ks.activate("Test", timestamp=datetime.utcnow())
        ks.reset()
        assert ks.is_active is False
        assert ks.reason is None
        assert ks.get_history() == []
