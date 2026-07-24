"""Tests for RC-10D Zerodha configuration (Group D).

Covers:
  - Paper mode is the default
  - live_order_allowed only when all 5 conditions satisfied
  - log_safe() never exposes credentials
  - repr never exposes credentials
  - Validator rejects live mode without credentials
  - load_config_from_env reads environment variables
"""
from __future__ import annotations

import os
import pytest

from src.brokers.zerodha.config import ZerodhaBrokerConfig, load_config_from_env


class TestZerodhaBrokerConfig:

    def _paper(self, **kw) -> ZerodhaBrokerConfig:
        defaults = dict(paper_trading=True, enabled=False)
        defaults.update(kw)
        return ZerodhaBrokerConfig(**defaults)

    def _live(self, **kw) -> ZerodhaBrokerConfig:
        defaults = dict(
            api_key="test_key",
            api_secret="test_secret",
            access_token="test_token",
            paper_trading=False,
            enabled=True,
            live_trading_enabled=True,
        )
        defaults.update(kw)
        return ZerodhaBrokerConfig(**defaults)

    # ── defaults ────────────────────────────────────────────────────────────

    def test_paper_trading_default_true(self):
        config = ZerodhaBrokerConfig()
        assert config.paper_trading is True

    def test_enabled_default_false(self):
        config = ZerodhaBrokerConfig()
        assert config.enabled is False

    def test_live_trading_enabled_default_false(self):
        config = ZerodhaBrokerConfig()
        assert config.live_trading_enabled is False

    def test_environment_default(self):
        config = ZerodhaBrokerConfig()
        assert config.environment == "production"

    def test_timeout_default(self):
        config = ZerodhaBrokerConfig()
        assert config.timeout_seconds == 10.0

    # ── live mode gating ────────────────────────────────────────────────────

    def test_is_live_order_allowed_paper_mode(self):
        config = self._paper()
        assert config.is_live_order_allowed() is False

    def test_is_live_order_allowed_all_conditions(self):
        config = self._live()
        assert config.is_live_order_allowed() is True

    def test_is_live_order_allowed_missing_enabled(self):
        config = self._live(enabled=False)
        assert config.is_live_order_allowed() is False

    def test_is_live_order_allowed_missing_live_flag(self):
        config = self._live(live_trading_enabled=False)
        assert config.is_live_order_allowed() is False

    def test_is_live_order_allowed_missing_token(self):
        config = self._live(access_token=None)
        assert config.is_live_order_allowed() is False

    def test_is_live_order_allowed_paper_true_still_blocked(self):
        config = self._live(paper_trading=True)
        assert config.is_live_order_allowed() is False

    # ── credential safety ───────────────────────────────────────────────────

    def test_log_safe_no_api_key(self):
        config = self._live()
        safe = config.log_safe()
        assert "api_key" not in safe
        assert "api_secret" not in safe
        assert "access_token" not in safe

    def test_log_safe_has_flag_fields(self):
        config = self._live()
        safe = config.log_safe()
        assert safe["has_api_key"] is True
        assert safe["has_api_secret"] is True
        assert safe["has_access_token"] is True

    def test_log_safe_paper_mode(self):
        config = self._paper()
        safe = config.log_safe()
        assert safe["paper_trading"] is True

    def test_repr_no_credentials(self):
        config = self._live()
        r = repr(config)
        assert "test_key" not in r
        assert "test_secret" not in r
        assert "test_token" not in r

    def test_str_no_credentials(self):
        config = self._live()
        s = str(config)
        assert "test_key" not in s
        assert "test_secret" not in s

    # ── validators ──────────────────────────────────────────────────────────

    def test_invalid_environment_rejected(self):
        with pytest.raises(Exception):
            ZerodhaBrokerConfig(environment="staging")

    def test_live_mode_without_key_rejected(self):
        with pytest.raises(Exception):
            ZerodhaBrokerConfig(
                api_key="",
                api_secret="secret",
                paper_trading=False,
            )

    def test_live_mode_without_secret_rejected(self):
        with pytest.raises(Exception):
            ZerodhaBrokerConfig(
                api_key="key",
                api_secret="",
                paper_trading=False,
            )

    def test_paper_mode_without_credentials_ok(self):
        config = ZerodhaBrokerConfig(
            api_key="",
            api_secret="",
            paper_trading=True,
        )
        assert config.paper_trading is True

    # ── load_config_from_env ────────────────────────────────────────────────

    def test_load_config_defaults_paper(self, monkeypatch):
        monkeypatch.delenv("ZERODHA_PAPER_TRADING", raising=False)
        monkeypatch.delenv("ZERODHA_ENABLED", raising=False)
        config = load_config_from_env()
        assert config.paper_trading is True
        assert config.enabled is False

    def test_load_config_reads_env_vars(self, monkeypatch):
        monkeypatch.setenv("ZERODHA_USER_ID", "XY9999")
        monkeypatch.setenv("ZERODHA_PAPER_TRADING", "true")
        config = load_config_from_env()
        assert config.user_id == "XY9999"
        assert config.paper_trading is True

    def test_load_config_paper_always_safe(self, monkeypatch):
        """Setting live_trading_enabled without key/secret stays paper."""
        monkeypatch.setenv("ZERODHA_LIVE_TRADING_ENABLED", "true")
        monkeypatch.setenv("ZERODHA_PAPER_TRADING", "true")
        config = load_config_from_env()
        assert config.is_live_order_allowed() is False


class TestRateLimitConfig:
    def test_defaults(self):
        config = ZerodhaBrokerConfig()
        assert config.rate_limits.order_api_rps == 10
        assert config.rate_limits.quote_api_rps == 1
        assert config.rate_limits.account_api_rps == 2
