"""RC-10D: Zerodha broker configuration.

ZerodhaBrokerConfig is a frozen Pydantic model that:
  - Reads from environment variables (ZERODHA_* prefix)
  - Validates completeness for live mode
  - Never exposes credentials in repr/logs
  - Defaults to paper_trading=True (live requires explicit opt-in)

Environment variables used:
  ZERODHA_API_KEY           — Zerodha API key  (Replit secret)
  ZERODHA_API_SECRET        — Zerodha API secret  (Replit secret)
  ZERODHA_ACCESS_TOKEN      — Set after OAuth exchange; rotated daily
  ZERODHA_USER_ID           — Zerodha client ID
  ZERODHA_PAPER_TRADING     — "true"/"false" (default: "true")
  ZERODHA_ENABLED           — "true"/"false" (default: "false")
  ZERODHA_ENVIRONMENT       — "production"/"sandbox" (default: "production")
  ZERODHA_TIMEOUT_SECONDS
  ZERODHA_MAX_RETRIES
  ZERODHA_LIVE_TRADING_ENABLED — must also be "true" to allow live orders
"""
from __future__ import annotations

import os
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RateLimitConfig(BaseModel):
    """Per-endpoint rate limit configuration (requests per second)."""

    model_config = ConfigDict(frozen=True)

    order_api_rps: int = 10
    quote_api_rps: int = 1
    account_api_rps: int = 2
    historical_api_rps: int = 3
    websocket_subscriptions_max: int = 3000


class ZerodhaBrokerConfig(BaseModel):
    """Immutable Zerodha broker configuration. Credentials are never logged."""

    model_config = ConfigDict(frozen=True)

    # ── credentials (never logged) ────────────────────────────────────────
    api_key: str = ""
    api_secret: str = ""
    access_token: Optional[str] = None
    user_id: Optional[str] = None
    request_token: Optional[str] = None

    # ── connectivity ──────────────────────────────────────────────────────
    redirect_url: str = "http://localhost:8000/broker/callback"
    environment: str = "production"
    timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
    maximum_retries: int = Field(default=3, ge=0, le=10)
    retry_backoff_seconds: float = Field(default=1.0, ge=0.1, le=30.0)

    # ── rate limits ───────────────────────────────────────────────────────
    rate_limits: RateLimitConfig = Field(default_factory=RateLimitConfig)

    # ── WebSocket ─────────────────────────────────────────────────────────
    websocket_reconnect_max_attempts: int = Field(default=10, ge=1, le=50)
    websocket_reconnect_backoff_seconds: float = Field(default=2.0, ge=0.5, le=60.0)

    # ── safety switches ───────────────────────────────────────────────────
    paper_trading: bool = True
    enabled: bool = False
    # Separate explicit flag required in addition to paper_trading=False
    live_trading_enabled: bool = False

    # ── validators ────────────────────────────────────────────────────────

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        allowed = {"production", "sandbox"}
        if v not in allowed:
            raise ValueError(f"environment must be one of {allowed}, got {v!r}")
        return v

    @model_validator(mode="after")
    def validate_live_mode_completeness(self) -> "ZerodhaBrokerConfig":
        """Live mode requires api_key and api_secret. Paper mode is always safe."""
        if not self.paper_trading:
            if not self.api_key:
                raise ValueError("api_key required when paper_trading=False")
            if not self.api_secret:
                raise ValueError("api_secret required when paper_trading=False")
        return self

    # ── safe representations (never expose credentials) ───────────────────

    def log_safe(self) -> dict:
        """Return a dict safe for structured logging — no credentials."""
        return {
            "environment": self.environment,
            "paper_trading": self.paper_trading,
            "enabled": self.enabled,
            "live_trading_enabled": self.live_trading_enabled,
            "has_api_key": bool(self.api_key),
            "has_api_secret": bool(self.api_secret),
            "has_access_token": bool(self.access_token),
            "has_user_id": bool(self.user_id),
            "timeout_seconds": self.timeout_seconds,
            "maximum_retries": self.maximum_retries,
        }

    def __repr__(self) -> str:
        return (
            f"ZerodhaBrokerConfig("
            f"env={self.environment!r}, "
            f"paper={self.paper_trading}, "
            f"enabled={self.enabled}, "
            f"has_key={bool(self.api_key)}, "
            f"has_token={bool(self.access_token)})"
        )

    def __str__(self) -> str:
        return repr(self)

    def is_live_order_allowed(self) -> bool:
        """Return True only when ALL live-mode conditions are satisfied."""
        return (
            self.enabled
            and not self.paper_trading
            and self.live_trading_enabled
            and bool(self.api_key)
            and bool(self.access_token)
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def load_config_from_env() -> ZerodhaBrokerConfig:
    """Load ZerodhaBrokerConfig from environment variables.

    ZERODHA_API_KEY and ZERODHA_API_SECRET are loaded from Replit secrets.
    """
    def _bool(key: str, default: bool = True) -> bool:
        raw = os.environ.get(key, str(default)).lower()
        return raw in ("1", "true", "yes")

    def _float(key: str, default: float) -> float:
        try:
            return float(os.environ.get(key, str(default)))
        except ValueError:
            return default

    def _int(key: str, default: int) -> int:
        try:
            return int(os.environ.get(key, str(default)))
        except ValueError:
            return default

    return ZerodhaBrokerConfig(
        api_key=os.environ.get("ZERODHA_API_KEY", ""),
        api_secret=os.environ.get("ZERODHA_API_SECRET", ""),
        access_token=os.environ.get("ZERODHA_ACCESS_TOKEN"),
        user_id=os.environ.get("ZERODHA_USER_ID"),
        request_token=os.environ.get("ZERODHA_REQUEST_TOKEN"),
        redirect_url=os.environ.get(
            "ZERODHA_REDIRECT_URL", "http://localhost:8000/broker/callback"
        ),
        environment=os.environ.get("ZERODHA_ENVIRONMENT", "production"),
        timeout_seconds=_float("ZERODHA_TIMEOUT_SECONDS", 10.0),
        maximum_retries=_int("ZERODHA_MAX_RETRIES", 3),
        retry_backoff_seconds=_float("ZERODHA_RETRY_BACKOFF_SECONDS", 1.0),
        paper_trading=_bool("ZERODHA_PAPER_TRADING", True),
        enabled=_bool("ZERODHA_ENABLED", False),
        live_trading_enabled=_bool("ZERODHA_LIVE_TRADING_ENABLED", False),
    )
