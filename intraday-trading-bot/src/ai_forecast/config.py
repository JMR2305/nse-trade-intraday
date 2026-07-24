"""RC-10B AI Forecast Configuration.

All settings have safe defaults that preserve pre-RC-10B behaviour.
When enabled=False, the AI forecast pipeline is bypassed entirely and
the runtime behaves identically to the RC-9 baseline.

Usage::

    from ai_forecast.config import AIForecastConfig

    cfg = AIForecastConfig(
        enabled=True,
        kronos_base_url="http://kronos:8080",
        timeout_ms=3000,
    )

Secrets (auth tokens in the URL) are never logged — the config
validator strips credentials from log-safe representations.

Invalid configuration that would make production inference impossible
(e.g. timeout=0, max_retries<0) is rejected at construction time so
failures surface at startup, not mid-trade.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_forecast.features import FEATURE_SCHEMA_VERSION


class AIForecastConfig(BaseModel):
    """Validated, immutable configuration for the RC-10B AI forecast pipeline.

    All fields have safe defaults so callers may construct a minimal config
    without touching unrelated settings::

        # AI disabled → identical to pre-RC-10B behaviour
        cfg = AIForecastConfig()

        # Production
        cfg = AIForecastConfig(enabled=True, kronos_base_url="http://...", ...)

    Attributes:
        enabled:                    Master switch. False → no forecast enrichment.
        kronos_base_url:            Kronos inference service base URL.
                                    May embed auth tokens — never logged.
        timeout_ms:                 Per-request timeout in milliseconds [100, 60000].
        max_retries:                Retry attempts with exponential back-off [0, 10].
        max_response_bytes:         Response-size guard (bytes). Larger responses
                                    are rejected to prevent OOM attacks.
        default_confidence_threshold: Minimum confidence to route a signal when
                                    the strategy does not configure its own threshold.
        default_horizon:            Default forecast horizon label (e.g. "15m").
        feature_schema_version:     Expected schema version. Mismatch is logged.
        expected_model_version:     When set, forecasts from a different model
                                    version are flagged (not rejected).
        benchmark_persistence_enabled: Persist forecasts/outcomes to DB.
        fallback_behaviour:         "fail_open" (always route signal when AI
                                    unavailable) or "suppress" (drop signal on
                                    AI unavailability).  Production default is
                                    "fail_open" to preserve RC-8/RC-7 flow.
    """

    model_config = ConfigDict(frozen=True, protected_namespaces=())

    # ---------- master switch ----------
    enabled: bool = False

    # ---------- Kronos client ----------
    kronos_base_url: str = "http://localhost:8080"
    timeout_ms: int = 3000
    max_retries: int = 2
    max_response_bytes: int = 65536

    # ---------- gate ----------
    default_confidence_threshold: Decimal = Decimal("0.60")
    default_horizon: str = "15m"

    # ---------- schema compatibility ----------
    feature_schema_version: str = Field(default=FEATURE_SCHEMA_VERSION)
    expected_model_version: Optional[str] = None

    # ---------- benchmark ----------
    benchmark_persistence_enabled: bool = True

    # ---------- fallback ----------
    fallback_behaviour: str = "fail_open"

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    @field_validator("fallback_behaviour")
    @classmethod
    def _validate_fallback(cls, v: str) -> str:
        allowed = {"fail_open", "suppress"}
        if v not in allowed:
            raise ValueError(
                f"fallback_behaviour must be one of {sorted(allowed)}, got {v!r}"
            )
        return v

    @field_validator("timeout_ms")
    @classmethod
    def _validate_timeout(cls, v: int) -> int:
        if not (100 <= v <= 60_000):
            raise ValueError(
                f"timeout_ms must be in [100, 60000], got {v}"
            )
        return v

    @field_validator("max_retries")
    @classmethod
    def _validate_retries(cls, v: int) -> int:
        if not (0 <= v <= 10):
            raise ValueError(
                f"max_retries must be in [0, 10], got {v}"
            )
        return v

    @field_validator("max_response_bytes")
    @classmethod
    def _validate_response_size(cls, v: int) -> int:
        if v < 1024:
            raise ValueError(
                f"max_response_bytes must be ≥ 1024, got {v}"
            )
        return v

    @field_validator("default_confidence_threshold")
    @classmethod
    def _validate_threshold(cls, v: Decimal) -> Decimal:
        if not (Decimal("0") <= v <= Decimal("1")):
            raise ValueError(
                f"default_confidence_threshold must be in [0, 1], got {v}"
            )
        return v

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def log_safe_url(self) -> str:
        """Return a credential-stripped version of kronos_base_url for logging."""
        try:
            from urllib.parse import urlparse, urlunparse
            parsed = urlparse(self.kronos_base_url)
            safe = parsed._replace(netloc=parsed.hostname or "")
            return urlunparse(safe)
        except Exception:
            return "<url-parse-error>"

    def __repr__(self) -> str:
        # Never include the raw URL in repr; use the log-safe variant
        return (
            f"AIForecastConfig(enabled={self.enabled}, "
            f"url={self.log_safe_url()!r}, "
            f"timeout_ms={self.timeout_ms}, "
            f"max_retries={self.max_retries}, "
            f"threshold={self.default_confidence_threshold})"
        )
