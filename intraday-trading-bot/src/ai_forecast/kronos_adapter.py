"""RC-10B KronosAdapter — async HTTP client for the Kronos inference API.

Design:
  - Fail-open: returns None on any error, never raises.
  - Single shared httpx.AsyncClient per adapter instance.
  - asyncio.Lock guards lazy client initialisation (concurrency-safe).
  - Response size capped at 65 536 bytes before JSON parsing.
  - Exponential back-off between retries.
  - No account, portfolio, order, or personal data is sent.
  - SSRF risk: kronos_base_url is operator-controlled via env AI_KRONOS_BASE_URL;
    document in ops runbook and restrict network egress accordingly.
"""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Optional

import httpx
from pydantic import BaseModel, ConfigDict, field_validator

from ai_forecast.features import FeatureVector
from core.config import settings

logger = logging.getLogger(__name__)

_RESPONSE_SIZE_LIMIT = 65_536  # bytes


class ForecastResult(BaseModel, frozen=True):
    """Immutable, validated response from Kronos."""

    model_config = ConfigDict(frozen=True, protected_namespaces=())

    instrument_token: str
    forecast_horizon: str
    direction: str
    confidence: Decimal
    price_target: Optional[Decimal] = None
    forecast_error: Optional[str] = None
    model_version: str
    computed_at: str

    @field_validator("direction")
    @classmethod
    def _validate_direction(cls, v: str) -> str:
        allowed = {"UP", "DOWN", "NEUTRAL"}
        if v not in allowed:
            raise ValueError(f"direction must be one of {allowed}, got {v!r}")
        return v

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, v: Decimal) -> Decimal:
        if v < Decimal("0") or v > Decimal("1"):
            raise ValueError(f"confidence must be in [0, 1], got {v}")
        return v


class KronosAdapter:
    """Async HTTP client for Kronos inference API.

    Fail-open: returns None on any error; never raises from forecast().

    Concurrency: a single httpx.AsyncClient is shared and lazily initialised
    under an asyncio.Lock so that concurrent coroutines never construct
    duplicate clients.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout_ms: Optional[int] = None,
        max_retries: Optional[int] = None,
    ) -> None:
        self._base_url = (base_url or settings.ai_forecast.kronos_base_url).rstrip("/")
        self._timeout = timeout_ms if timeout_ms is not None else settings.ai_forecast.kronos_timeout_ms
        self._max_retries = (
            max_retries if max_retries is not None
            else settings.ai_forecast.kronos_max_retries
        )
        self._client: Optional[httpx.AsyncClient] = None
        self._client_lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazily create the shared AsyncClient.  Guarded by asyncio.Lock."""
        if self._client is None:
            async with self._client_lock:
                # Double-check inside the lock (another coroutine may have
                # created the client while we waited for the lock).
                if self._client is None:
                    self._client = httpx.AsyncClient(
                        timeout=httpx.Timeout(self._timeout / 1000.0),
                        limits=httpx.Limits(
                            max_connections=10, max_keepalive_connections=5
                        ),
                    )
        return self._client

    async def close(self) -> None:
        """Close and discard the shared HTTP client."""
        async with self._client_lock:
            if self._client is not None:
                await self._client.aclose()
                self._client = None

    async def forecast(
        self,
        instrument_token: str,
        features: FeatureVector,
        horizon: str = "15m",
    ) -> Optional[ForecastResult]:
        """Request a forecast from Kronos.  Returns None on any error (fail-open)."""
        url = f"{self._base_url}/forecast"
        payload = {
            "instrument_token": instrument_token,
            "features": [str(f) for f in features.features],
            "schema_version": features.schema_version,
            "horizon": horizon,
        }

        last_error: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            try:
                client = await self._get_client()
                response = await client.post(url, json=payload)
                response.raise_for_status()

                # Reject oversized responses before JSON parsing
                raw = response.text
                if len(raw.encode()) > _RESPONSE_SIZE_LIMIT:
                    raise ValueError(
                        f"Kronos response too large: {len(raw.encode())} bytes "
                        f"(limit {_RESPONSE_SIZE_LIMIT})"
                    )

                data = response.json()
                result = ForecastResult(
                    instrument_token=data["instrument_token"],
                    forecast_horizon=data.get("forecast_horizon", horizon),
                    direction=data["direction"],
                    confidence=Decimal(str(data["confidence"])),
                    price_target=(
                        Decimal(str(data["price_target"]))
                        if data.get("price_target") is not None
                        else None
                    ),
                    model_version=data.get("model_version", "unknown"),
                    computed_at=data.get("computed_at", ""),
                )
                logger.info(
                    "Kronos forecast received",
                    extra={
                        "instrument_token": instrument_token,
                        "model_version": result.model_version,
                        "direction": result.direction,
                        "confidence": str(result.confidence),
                        "horizon": horizon,
                        "schema_version": features.schema_version,
                    },
                )
                return result

            except Exception as e:
                last_error = e
                if attempt < self._max_retries:
                    # Exponential back-off: 0.1s, 0.2s, 0.4s, …
                    await asyncio.sleep(0.1 * (2 ** attempt))

        logger.warning(
            "Kronos forecast failed after %d attempt(s): %s",
            self._max_retries + 1,
            str(last_error),
            extra={
                "instrument_token": instrument_token,
                "horizon": horizon,
            },
        )
        return None
