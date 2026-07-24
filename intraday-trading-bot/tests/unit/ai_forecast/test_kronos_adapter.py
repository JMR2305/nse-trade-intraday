"""Tests for RC-10B KronosAdapter — including concurrency safety."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_forecast.kronos_adapter import ForecastResult, KronosAdapter
from ai_forecast.features import FeatureVector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_feature_vector(token: str = "INFY") -> FeatureVector:
    return FeatureVector(
        instrument_token=token,
        features=tuple(Decimal("0.1") for _ in range(25)),
        schema_version="1.0",
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def make_success_response(token: str = "INFY") -> dict:
    return {
        "instrument_token": token,
        "forecast_horizon": "15m",
        "direction": "UP",
        "confidence": 0.78,
        "price_target": 1550.0,
        "model_version": "v2.1",
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# ForecastResult validation
# ---------------------------------------------------------------------------

class TestForecastResult:
    def test_valid_direction_up(self) -> None:
        r = ForecastResult(
            instrument_token="INFY",
            forecast_horizon="15m",
            direction="UP",
            confidence=Decimal("0.75"),
            model_version="v1",
            computed_at=datetime.now(timezone.utc).isoformat(),
        )
        assert r.direction == "UP"
        assert r.confidence == Decimal("0.75")

    def test_valid_direction_down(self) -> None:
        r = ForecastResult(
            instrument_token="INFY",
            forecast_horizon="15m",
            direction="DOWN",
            confidence=Decimal("0.60"),
            model_version="v1",
            computed_at=datetime.now(timezone.utc).isoformat(),
        )
        assert r.direction == "DOWN"

    def test_valid_direction_neutral(self) -> None:
        r = ForecastResult(
            instrument_token="INFY",
            forecast_horizon="15m",
            direction="NEUTRAL",
            confidence=Decimal("0.55"),
            model_version="v1",
            computed_at=datetime.now(timezone.utc).isoformat(),
        )
        assert r.direction == "NEUTRAL"

    def test_invalid_direction_raises(self) -> None:
        with pytest.raises(ValueError, match="direction must be one of"):
            ForecastResult(
                instrument_token="INFY",
                forecast_horizon="15m",
                direction="SIDEWAYS",
                confidence=Decimal("0.75"),
                model_version="v1",
                computed_at=datetime.now(timezone.utc).isoformat(),
            )

    def test_confidence_above_one_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence must be in"):
            ForecastResult(
                instrument_token="INFY",
                forecast_horizon="15m",
                direction="UP",
                confidence=Decimal("1.1"),
                model_version="v1",
                computed_at=datetime.now(timezone.utc).isoformat(),
            )

    def test_confidence_below_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence must be in"):
            ForecastResult(
                instrument_token="INFY",
                forecast_horizon="15m",
                direction="UP",
                confidence=Decimal("-0.1"),
                model_version="v1",
                computed_at=datetime.now(timezone.utc).isoformat(),
            )

    def test_optional_price_target(self) -> None:
        r = ForecastResult(
            instrument_token="INFY",
            forecast_horizon="15m",
            direction="UP",
            confidence=Decimal("0.75"),
            model_version="v1",
            computed_at=datetime.now(timezone.utc).isoformat(),
        )
        assert r.price_target is None

    def test_is_frozen(self) -> None:
        r = ForecastResult(
            instrument_token="INFY",
            forecast_horizon="15m",
            direction="UP",
            confidence=Decimal("0.75"),
            model_version="v1",
            computed_at=datetime.now(timezone.utc).isoformat(),
        )
        with pytest.raises(Exception):
            r.direction = "DOWN"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# KronosAdapter — response size guard
# ---------------------------------------------------------------------------

class TestKronosAdapterResponseSizeGuard:
    @pytest.mark.asyncio
    async def test_oversized_response_returns_none(self) -> None:
        """Responses > 65 536 bytes must be rejected (fail-open)."""
        adapter = KronosAdapter(
            base_url="http://kronos.test",
            timeout_ms=1000,
            max_retries=0,
        )
        oversized_text = "x" * 70_000
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.text = oversized_text
        mock_response.json.return_value = {}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        adapter._client = mock_client

        fv = make_feature_vector()
        result = await adapter.forecast("INFY", fv)
        assert result is None


# ---------------------------------------------------------------------------
# KronosAdapter — exponential back-off
# ---------------------------------------------------------------------------

class TestKronosAdapterBackoff:
    @pytest.mark.asyncio
    async def test_exponential_backoff(self) -> None:
        """Back-off delays: attempt 0→sleep(0.1), attempt 1→sleep(0.2)."""
        adapter = KronosAdapter(
            base_url="http://kronos.test",
            timeout_ms=100,
            max_retries=2,
        )
        mock_client = AsyncMock()
        mock_client.post.side_effect = RuntimeError("connection refused")
        adapter._client = mock_client

        sleep_calls = []
        with patch("asyncio.sleep", new=AsyncMock(side_effect=lambda t: sleep_calls.append(t))):
            fv = make_feature_vector()
            result = await adapter.forecast("INFY", fv)

        assert result is None
        # 2 retries → sleeps at 0.1, 0.2
        assert sleep_calls == [0.1, 0.2]


# ---------------------------------------------------------------------------
# KronosAdapter — concurrency (one AsyncClient created under concurrent init)
# ---------------------------------------------------------------------------

class TestKronosAdapterConcurrency:
    @pytest.mark.asyncio
    async def test_single_client_under_concurrent_init(self) -> None:
        """Concurrent _get_client() calls must produce exactly ONE AsyncClient.

        Verifies asyncio.Lock prevents double-initialisation.
        """
        import httpx

        adapter = KronosAdapter(
            base_url="http://kronos.test",
            timeout_ms=100,
            max_retries=0,
        )

        clients_created = []

        async def mock_get_client():
            # Simulate real _get_client with our tracking list
            if adapter._client is None:
                async with adapter._client_lock:
                    if adapter._client is None:
                        new_client = AsyncMock(spec=httpx.AsyncClient)
                        clients_created.append(new_client)
                        adapter._client = new_client
            return adapter._client

        # Concurrently call _get_client 50 times
        results = await asyncio.gather(*[mock_get_client() for _ in range(50)])

        # All calls must return the same client object
        assert len(set(id(c) for c in results)) == 1
        # Exactly one client was created
        assert len(clients_created) == 1

    @pytest.mark.asyncio
    async def test_close_resets_client(self) -> None:
        adapter = KronosAdapter(
            base_url="http://kronos.test",
            timeout_ms=100,
            max_retries=0,
        )
        mock_client = AsyncMock()
        adapter._client = mock_client
        await adapter.close()
        assert adapter._client is None
        mock_client.aclose.assert_called_once()
