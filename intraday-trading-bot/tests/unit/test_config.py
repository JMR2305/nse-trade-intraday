"""Tests for configuration."""

import pytest

from src.core.config import Settings, TradingSettings


class TestConfig:
    def test_trading_settings_default(self):
        ts = TradingSettings()
        assert ts.mode == "PAPER"
        assert ts.timezone_display == "Asia/Kolkata"
        assert ts.timezone_storage == "UTC"

    def test_trading_settings_live_mode_allowed(self):
        """LIVE mode is accepted by TradingSettings; runtime gates in is_live_order_allowed() enforce safety."""
        ts = TradingSettings(mode="LIVE")
        assert ts.mode == "LIVE"

    def test_trading_settings_valid_modes(self):
        for mode in ["PAPER", "REPLAY", "SHADOW", "SIMULATION", "LIVE"]:
            ts = TradingSettings(mode=mode)
            assert ts.mode == mode

    def test_settings_is_paper_mode(self, monkeypatch):
        monkeypatch.setenv("TRADING__MODE", "PAPER")
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
        monkeypatch.setenv("JWT_SECRET_KEY", "a" * 64)
        settings = Settings()
        assert settings.is_paper_mode is True
