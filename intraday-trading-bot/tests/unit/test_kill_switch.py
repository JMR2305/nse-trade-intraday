"""Tests for kill switch."""

import pytest

from src.core.kill_switch import KillSwitchManager, KillSwitchLevel, KillSwitchState


class TestKillSwitch:
    def test_initial_state(self):
        manager = KillSwitchManager()
        assert manager.state.level == KillSwitchLevel.NORMAL
        assert manager.state.can_place_orders() is True

    def test_escalate_pause(self):
        manager = KillSwitchManager()
        manager.escalate(KillSwitchLevel.PAUSE, "Test pause")
        assert manager.state.level == KillSwitchLevel.PAUSE
        assert manager.state.can_place_orders() is False
        assert manager.state.can_modify_orders() is True

    def test_escalate_cancel_pending(self):
        manager = KillSwitchManager()
        manager.escalate(KillSwitchLevel.CANCEL_PENDING, "Test cancel")
        assert manager.state.level == KillSwitchLevel.CANCEL_PENDING
        assert manager.state.should_cancel_pending() is True
        assert manager.state.should_flatten() is False

    def test_escalate_flatten_all(self):
        manager = KillSwitchManager()
        manager.escalate(KillSwitchLevel.FLATTEN_ALL, "Test flatten")
        assert manager.state.level == KillSwitchLevel.FLATTEN_ALL
        assert manager.state.should_flatten() is True
        assert manager.state.can_place_orders() is False

    def test_no_de_escalation(self):
        manager = KillSwitchManager()
        manager.escalate(KillSwitchLevel.FLATTEN_ALL, "Test")
        manager.escalate(KillSwitchLevel.PAUSE, "Should be ignored")
        assert manager.state.level == KillSwitchLevel.FLATTEN_ALL

    def test_reset(self):
        manager = KillSwitchManager()
        manager.escalate(KillSwitchLevel.PAUSE, "Test")
        manager.reset("Manual reset")
        assert manager.state.level == KillSwitchLevel.NORMAL
        assert manager.state.can_place_orders() is True

    def test_history(self):
        manager = KillSwitchManager()
        manager.escalate(KillSwitchLevel.PAUSE, "Test")
        manager.reset("Reset")
        history = manager.get_history()
        assert len(history) == 1
        assert history[0]["level"] == "PAUSE"

    def test_check_risk_limits(self):
        manager = KillSwitchManager()
        manager.check_risk_limits(0, 0)
        assert manager.state.level == KillSwitchLevel.NORMAL
        from src.core.config import settings
        limit = settings.risk.daily_loss_limit_inr
        manager.check_risk_limits(-limit * 0.5, 0)
        assert manager.state.level == KillSwitchLevel.PAUSE
