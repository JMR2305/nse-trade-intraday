"""Tests for configuration."""

import pytest
from pydantic import ValidationError

from src.core.config import Settings, TradingSettings


class TestConfig:
    def test_trading_settings_default(self):
        ts = TradingSettings()
        assert ts.mode == "PAPER"
        assert ts.timezone_display == "Asia/Kolkata"
        assert ts.timezone_storage == "UTC"

    def test_trading_settings_enforce_paper(self):
        with pytest.raises(ValidationError, match="LIVE mode is structurally unavailable"):
            TradingSettings(mode="LIVE")

    def test_trading_settings_valid_modes(self):
        for mode in ["PAPER", "REPLAY", "SHADOW", "SIMULATION"]:
            ts = TradingSettings(mode=mode)
            assert ts.mode == mode

    def test_settings_is_paper_mode(self, monkeypatch):
        monkeypatch.setenv("TRADING__MODE", "PAPER")
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
        monkeypatch.setenv("JWT_SECRET_KEY", "a" * 64)
        settings = Settings()
        assert settings.is_paper_mode is True
