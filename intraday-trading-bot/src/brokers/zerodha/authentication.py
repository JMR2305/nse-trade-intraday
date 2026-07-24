"""RC-10D: Zerodha session manager.

ZerodhaSessionManager handles OAuth2 authentication with Zerodha Kite.

Rules:
  - NEVER automates the interactive OAuth browser step
  - NEVER logs api_secret, access_token, or request_token
  - Sessions are stored in the broker_sessions DB table (token value NOT stored in DB)
  - System stays in observe-only (paper) mode when session is invalid
  - The daily access token rotation is the operator's responsibility

Flow
----
1. Operator opens login_url in a browser → Zerodha redirects with request_token
2. Operator sets ZERODHA_REQUEST_TOKEN env var (or calls set_request_token())
3. exchange_request_token() exchanges it for an access_token
4. Access token is stored in ZERODHA_ACCESS_TOKEN env var (NOT in this code)
5. validate_session() probes Zerodha to confirm the session is alive
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Optional

from src.brokers.contracts import BrokerSession
from src.brokers.exceptions import (
    BrokerAuthenticationError,
    BrokerSessionExpiredError,
)
from src.brokers.zerodha.config import ZerodhaBrokerConfig
from src.core.logging import logger


class ZerodhaSessionManager:
    """Manages Zerodha KiteConnect session lifecycle.

    Parameters
    ----------
    config:
        ZerodhaBrokerConfig instance (credentials redacted in logs).
    """

    def __init__(self, config: ZerodhaBrokerConfig) -> None:
        self._config = config
        self._session: Optional[BrokerSession] = None
        self._kite = None  # kiteconnect.KiteConnect instance (lazy)

    # ── Public API ─────────────────────────────────────────────────────────

    def get_login_url(self) -> str:
        """Return the Zerodha OAuth2 login URL.

        The operator must open this URL in a browser.  After the user logs in,
        Zerodha redirects to redirect_url with ?request_token=<token>.

        Raises
        ------
        BrokerAuthenticationError
            If ZERODHA_API_KEY is not configured.
        """
        if not self._config.api_key:
            raise BrokerAuthenticationError(
                "ZERODHA_API_KEY is not configured. Cannot generate login URL."
            )
        kite = self._get_kite()
        url = kite.login_url()
        logger.info(
            "Zerodha login URL generated",
            extra={"event_type": "BROKER_AUTH_LOGIN_URL", **self._config.log_safe()},
        )
        return url

    def exchange_request_token(self, request_token: Optional[str] = None) -> BrokerSession:
        """Exchange a request token for an access token.

        Parameters
        ----------
        request_token:
            The token received in the OAuth2 callback.  If None, reads from
            ZERODHA_REQUEST_TOKEN environment variable.

        Returns
        -------
        BrokerSession with is_valid=True on success.

        Raises
        ------
        BrokerAuthenticationError
            If the request_token is missing or the exchange fails.
        """
        token = request_token or os.environ.get("ZERODHA_REQUEST_TOKEN", "")
        if not token:
            raise BrokerAuthenticationError(
                "No request_token provided and ZERODHA_REQUEST_TOKEN not set. "
                "Complete the OAuth2 flow in a browser first."
            )

        if not self._config.api_key:
            raise BrokerAuthenticationError(
                "ZERODHA_API_KEY is not configured. Cannot exchange request token."
            )

        if not self._config.api_secret:
            raise BrokerAuthenticationError(
                "ZERODHA_API_SECRET is not configured. Cannot exchange request token."
            )

        try:
            kite = self._get_kite()
            data = kite.generate_session(token, api_secret=self._config.api_secret)
            access_token = data.get("access_token", "")
            user_id = data.get("user_id", "")
            if not access_token:
                raise BrokerAuthenticationError(
                    "Token exchange succeeded but access_token is empty"
                )

            # Set on the kite instance (in memory only — never persisted here)
            kite.set_access_token(access_token)

            self._session = BrokerSession(
                user_id=user_id,
                broker_name="zerodha",
                created_at=datetime.now(timezone.utc),
                expires_at=self._token_expiry(),
                is_valid=True,
                paper_mode=self._config.paper_trading,
            )

            logger.info(
                "Zerodha session established",
                extra={
                    "event_type": "BROKER_AUTH_SUCCESS",
                    "user_id": user_id,
                    **self._config.log_safe(),
                },
            )
            return self._session

        except BrokerAuthenticationError:
            raise
        except Exception as exc:
            # Never include the request token or any credential in the message
            raise BrokerAuthenticationError(
                f"Token exchange failed: {type(exc).__name__}"
            ) from exc

    def restore_session(self) -> BrokerSession:
        """Restore a session from the ZERODHA_ACCESS_TOKEN environment variable.

        The operator is responsible for setting ZERODHA_ACCESS_TOKEN after the
        daily OAuth2 flow.

        Returns
        -------
        BrokerSession

        Raises
        ------
        BrokerSessionExpiredError
            If ZERODHA_ACCESS_TOKEN is not set.
        """
        access_token = os.environ.get("ZERODHA_ACCESS_TOKEN", "")
        if not access_token:
            raise BrokerSessionExpiredError(
                "ZERODHA_ACCESS_TOKEN is not set. Complete the OAuth2 flow."
            )

        try:
            kite = self._get_kite()
            kite.set_access_token(access_token)

            user_id = os.environ.get("ZERODHA_USER_ID", "")
            self._session = BrokerSession(
                user_id=user_id or None,
                broker_name="zerodha",
                created_at=datetime.now(timezone.utc),
                expires_at=self._token_expiry(),
                is_valid=True,
                paper_mode=self._config.paper_trading,
            )

            logger.info(
                "Zerodha session restored from env",
                extra={
                    "event_type": "BROKER_SESSION_RESTORED",
                    "has_token": True,
                    **self._config.log_safe(),
                },
            )
            return self._session

        except BrokerSessionExpiredError:
            raise
        except Exception as exc:
            raise BrokerSessionExpiredError(
                f"Session restoration failed: {type(exc).__name__}"
            ) from exc

    def validate_session(self) -> bool:
        """Probe Zerodha to verify the current session is alive.

        Returns
        -------
        bool
            True if the session is valid, False otherwise.
        """
        if not self._kite:
            return False

        try:
            # Probe with a lightweight API call
            profile = self._kite.profile()
            is_valid = bool(profile and profile.get("user_id"))
            if self._session is not None:
                self._session = BrokerSession(
                    session_id=self._session.session_id,
                    user_id=self._session.user_id,
                    broker_name=self._session.broker_name,
                    created_at=self._session.created_at,
                    expires_at=self._session.expires_at,
                    is_valid=is_valid,
                    paper_mode=self._session.paper_mode,
                )
            logger.debug(
                "Zerodha session validation",
                extra={"event_type": "BROKER_SESSION_VALIDATE", "is_valid": is_valid},
            )
            return is_valid
        except Exception as exc:
            logger.warning(
                f"Zerodha session validation failed: {type(exc).__name__}",
                extra={"event_type": "BROKER_SESSION_INVALID"},
            )
            return False

    def invalidate(self) -> None:
        """Explicitly invalidate the current session."""
        if self._session:
            self._session = BrokerSession(
                session_id=self._session.session_id,
                user_id=self._session.user_id,
                broker_name=self._session.broker_name,
                created_at=self._session.created_at,
                expires_at=self._session.expires_at,
                is_valid=False,
                paper_mode=self._session.paper_mode,
            )
        logger.info(
            "Zerodha session invalidated",
            extra={"event_type": "BROKER_SESSION_INVALIDATED"},
        )

    @property
    def current_session(self) -> Optional[BrokerSession]:
        """Return the current session (may be None or invalid)."""
        return self._session

    @property
    def is_valid(self) -> bool:
        """True if a valid session is currently held."""
        return self._session is not None and self._session.is_valid

    def get_kite(self):
        """Return the underlying KiteConnect instance (for gateway use).

        Returns None if api_key is not configured.
        """
        return self._get_kite() if self._config.api_key else None

    # ── Private helpers ────────────────────────────────────────────────────

    def _get_kite(self):
        """Lazy-initialise KiteConnect instance."""
        if self._kite is None:
            try:
                from kiteconnect import KiteConnect
                self._kite = KiteConnect(api_key=self._config.api_key)
            except ImportError:
                raise BrokerAuthenticationError(
                    "kiteconnect package is not installed. "
                    "Install it with: pip install kiteconnect"
                )
        return self._kite

    @staticmethod
    def _token_expiry() -> datetime:
        """Zerodha access tokens expire at midnight IST (06:00 UTC next day)."""
        now = datetime.now(timezone.utc)
        expiry_candidate = now.replace(hour=6, minute=0, second=0, microsecond=0)
        if now >= expiry_candidate:
            expiry_candidate += timedelta(days=1)
        return expiry_candidate
