"""Tests for RC-10D authentication / session manager (Group F).

Covers:
  - get_login_url returns a URL
  - exchange_request_token raises without token
  - exchange_request_token raises without api_key
  - restore_session raises when ZERODHA_ACCESS_TOKEN not set
  - restore_session succeeds when token is present
  - validate_session returns False without kite instance
  - invalidate() marks session invalid
  - Credentials never appear in exception messages
  - is_valid reflects session state
"""
from __future__ import annotations

import os
import pytest
from unittest.mock import MagicMock, patch

from src.brokers.exceptions import (
    BrokerAuthenticationError,
    BrokerSessionExpiredError,
)
from src.brokers.zerodha.authentication import ZerodhaSessionManager
from src.brokers.zerodha.config import ZerodhaBrokerConfig


@pytest.fixture
def paper_config():
    return ZerodhaBrokerConfig(paper_trading=True)


@pytest.fixture
def live_config():
    return ZerodhaBrokerConfig(
        api_key="test_api_key",
        api_secret="test_api_secret",
        paper_trading=False,
        enabled=True,
        live_trading_enabled=True,
    )


class TestGetLoginUrl:
    def test_no_api_key_raises(self, paper_config):
        """Without api_key, KiteConnect cannot be initialised."""
        manager = ZerodhaSessionManager(paper_config)
        # api_key is empty — should fail or return None kite
        with pytest.raises(BrokerAuthenticationError):
            manager.get_login_url()

    def test_with_api_key_returns_url(self, live_config):
        """With a valid api_key, login_url should return a URL string."""
        manager = ZerodhaSessionManager(live_config)
        mock_kite = MagicMock()
        mock_kite.login_url.return_value = "https://kite.zerodha.com/connect/login?v=3&api_key=test"
        manager._kite = mock_kite

        url = manager.get_login_url()
        assert "kite.zerodha.com" in url or "zerodha" in url.lower()


class TestExchangeRequestToken:
    def test_no_token_raises(self, live_config, monkeypatch):
        monkeypatch.delenv("ZERODHA_REQUEST_TOKEN", raising=False)
        manager = ZerodhaSessionManager(live_config)
        with pytest.raises(BrokerAuthenticationError) as exc_info:
            manager.exchange_request_token()
        # Error message must not contain the api_secret
        assert "test_api_secret" not in str(exc_info.value)

    def test_no_api_key_raises(self, paper_config):
        manager = ZerodhaSessionManager(paper_config)
        with pytest.raises(BrokerAuthenticationError) as exc_info:
            manager.exchange_request_token("some_token")
        assert "api_key" in str(exc_info.value).lower() or "api" in str(exc_info.value).lower()

    def test_no_api_secret_raises(self):
        """ZerodhaBrokerConfig itself raises when api_secret is empty in live mode."""
        from pydantic import ValidationError
        with pytest.raises((ValidationError, Exception)):
            ZerodhaBrokerConfig(
                api_key="test_key",
                api_secret="",
                paper_trading=False,
            )

    def test_success_returns_session(self, live_config):
        manager = ZerodhaSessionManager(live_config)
        mock_kite = MagicMock()
        mock_kite.generate_session.return_value = {
            "access_token": "access_tok_123",
            "user_id": "XY1234",
        }
        manager._kite = mock_kite

        session = manager.exchange_request_token("req_tok_abc")
        assert session.is_valid is True
        assert session.user_id == "XY1234"
        assert session.paper_mode is False

    def test_success_credentials_not_in_session_repr(self, live_config):
        manager = ZerodhaSessionManager(live_config)
        mock_kite = MagicMock()
        mock_kite.generate_session.return_value = {
            "access_token": "SECRET_ACCESS_TOKEN",
            "user_id": "ZZ5555",
        }
        manager._kite = mock_kite

        session = manager.exchange_request_token("req_tok")
        r = repr(session)
        assert "SECRET_ACCESS_TOKEN" not in r
        assert "test_api_secret" not in r

    def test_kiteconnect_error_wrapped(self, live_config):
        manager = ZerodhaSessionManager(live_config)
        mock_kite = MagicMock()
        mock_kite.generate_session.side_effect = Exception("Connection error")
        manager._kite = mock_kite

        with pytest.raises(BrokerAuthenticationError) as exc_info:
            manager.exchange_request_token("token")
        assert "test_api_secret" not in str(exc_info.value)


class TestRestoreSession:
    def test_no_token_raises(self, live_config, monkeypatch):
        monkeypatch.delenv("ZERODHA_ACCESS_TOKEN", raising=False)
        manager = ZerodhaSessionManager(live_config)
        with pytest.raises(BrokerSessionExpiredError):
            manager.restore_session()

    def test_with_token_returns_session(self, live_config, monkeypatch):
        monkeypatch.setenv("ZERODHA_ACCESS_TOKEN", "valid_token_abc")
        monkeypatch.setenv("ZERODHA_USER_ID", "AB1234")
        manager = ZerodhaSessionManager(live_config)
        mock_kite = MagicMock()
        manager._kite = mock_kite

        session = manager.restore_session()
        assert session.is_valid is True
        assert session.user_id == "AB1234"

    def test_restored_session_safe_repr(self, live_config, monkeypatch):
        monkeypatch.setenv("ZERODHA_ACCESS_TOKEN", "SECRET_TOKEN_123")
        manager = ZerodhaSessionManager(live_config)
        mock_kite = MagicMock()
        manager._kite = mock_kite

        session = manager.restore_session()
        r = repr(session)
        assert "SECRET_TOKEN_123" not in r


class TestValidateSession:
    def test_no_kite_returns_false(self, live_config):
        manager = ZerodhaSessionManager(live_config)
        # No _kite instance
        assert manager.validate_session() is False

    def test_valid_profile_returns_true(self, live_config):
        manager = ZerodhaSessionManager(live_config)
        mock_kite = MagicMock()
        mock_kite.profile.return_value = {"user_id": "AB1234", "user_name": "Test"}
        manager._kite = mock_kite
        manager._session = MagicMock(
            session_id="sid",
            user_id="AB1234",
            broker_name="zerodha",
            created_at=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
            expires_at=None,
            is_valid=True,
            paper_mode=False,
        )

        result = manager.validate_session()
        assert result is True

    def test_api_error_returns_false(self, live_config):
        manager = ZerodhaSessionManager(live_config)
        mock_kite = MagicMock()
        mock_kite.profile.side_effect = Exception("Unauthorized")
        manager._kite = mock_kite

        result = manager.validate_session()
        assert result is False


class TestInvalidate:
    def test_invalidate_sets_invalid(self, live_config, monkeypatch):
        monkeypatch.setenv("ZERODHA_ACCESS_TOKEN", "tok")
        manager = ZerodhaSessionManager(live_config)
        mock_kite = MagicMock()
        manager._kite = mock_kite
        manager.restore_session()

        manager.invalidate()
        assert manager.is_valid is False

    def test_invalidate_without_session_no_crash(self, live_config):
        manager = ZerodhaSessionManager(live_config)
        manager.invalidate()  # Should not crash
        assert manager.is_valid is False
