"""Unit tests for RC-10B AIForecastConfig."""
from __future__ import annotations

from decimal import Decimal

import pytest

from ai_forecast.config import AIForecastConfig
from ai_forecast.features import FEATURE_SCHEMA_VERSION


class TestAIForecastConfigDefaults:
    def test_disabled_by_default(self) -> None:
        """Safe default: AI disabled preserves pre-RC-10B behaviour."""
        cfg = AIForecastConfig()
        assert cfg.enabled is False

    def test_default_fallback_behaviour(self) -> None:
        cfg = AIForecastConfig()
        assert cfg.fallback_behaviour == "fail_open"

    def test_default_schema_version(self) -> None:
        cfg = AIForecastConfig()
        assert cfg.feature_schema_version == FEATURE_SCHEMA_VERSION

    def test_default_threshold(self) -> None:
        cfg = AIForecastConfig()
        assert cfg.default_confidence_threshold == Decimal("0.60")

    def test_default_horizon(self) -> None:
        cfg = AIForecastConfig()
        assert cfg.default_horizon == "15m"

    def test_immutable(self) -> None:
        cfg = AIForecastConfig()
        with pytest.raises(Exception):
            cfg.enabled = True  # type: ignore[misc]


class TestAIForecastConfigValidation:
    def test_invalid_fallback_raises(self) -> None:
        with pytest.raises(ValueError, match="fallback_behaviour"):
            AIForecastConfig(fallback_behaviour="crash")

    def test_timeout_too_low_raises(self) -> None:
        with pytest.raises(ValueError, match="timeout_ms"):
            AIForecastConfig(timeout_ms=50)

    def test_timeout_too_high_raises(self) -> None:
        with pytest.raises(ValueError, match="timeout_ms"):
            AIForecastConfig(timeout_ms=999_999)

    def test_negative_retries_raises(self) -> None:
        with pytest.raises(ValueError, match="max_retries"):
            AIForecastConfig(max_retries=-1)

    def test_too_many_retries_raises(self) -> None:
        with pytest.raises(ValueError, match="max_retries"):
            AIForecastConfig(max_retries=11)

    def test_response_bytes_too_small_raises(self) -> None:
        with pytest.raises(ValueError, match="max_response_bytes"):
            AIForecastConfig(max_response_bytes=512)

    def test_threshold_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="default_confidence_threshold"):
            AIForecastConfig(default_confidence_threshold=Decimal("1.5"))

    def test_valid_suppress_fallback(self) -> None:
        cfg = AIForecastConfig(fallback_behaviour="suppress")
        assert cfg.fallback_behaviour == "suppress"

    def test_valid_enabled_config(self) -> None:
        cfg = AIForecastConfig(
            enabled=True,
            kronos_base_url="http://kronos:8080",
            timeout_ms=2000,
            max_retries=3,
        )
        assert cfg.enabled is True
        assert cfg.timeout_ms == 2000


class TestAIForecastConfigLogSafety:
    def test_log_safe_url_strips_credentials(self) -> None:
        cfg = AIForecastConfig(kronos_base_url="http://user:secret@kronos:8080/v1")
        safe = cfg.log_safe_url()
        assert "secret" not in safe
        assert "user" not in safe

    def test_repr_does_not_expose_url(self) -> None:
        cfg = AIForecastConfig(kronos_base_url="http://user:secret@kronos:8080/v1")
        r = repr(cfg)
        assert "secret" not in r

    def test_log_safe_url_plain(self) -> None:
        cfg = AIForecastConfig(kronos_base_url="http://kronos:8080")
        safe = cfg.log_safe_url()
        assert "kronos" in safe


class TestAIForecastDisabledMode:
    """Verify that AI-disabled mode is the correct safe default.

    When enabled=False, the runtime must behave identically to the
    pre-RC-10B baseline: no forecast enrichment, no gate calls,
    no benchmark writes.  This is enforced by the runtime checking
    ai_forecast_gate is None (which happens when AIForecastConfig.enabled=False).
    """

    def test_disabled_config_sentinel(self) -> None:
        """The enabled flag is the canonical switch read by the runtime factory."""
        disabled = AIForecastConfig()
        assert disabled.enabled is False

    def test_enabled_config(self) -> None:
        enabled = AIForecastConfig(enabled=True)
        assert enabled.enabled is True

    def test_ai_disabled_runtime_has_no_gate(self) -> None:
        """When no gate is injected (disabled mode), runtime has no _ai_forecast_gate."""
        from unittest.mock import AsyncMock, MagicMock
        from strategy.contracts import StrategyConfig
        from strategy.runtime import StrategyRuntime

        config = StrategyConfig(
            strategy_id="no-ai",
            strategy_type="baseline",
            name="No AI",
            instrument_tokens=["INFY"],
        )
        runtime = StrategyRuntime(
            config=config,
            strategy=MagicMock(),
            context_builder=AsyncMock(),
            market_data_service=AsyncMock(),
            fill_event_bus=MagicMock(),
            signal_callback=lambda s: None,
            # No gate injected → disabled mode
            ai_forecast_gate=None,
            feature_generator=None,
            benchmark_repo=None,
        )
        assert runtime._ai_forecast_gate is None
        assert runtime._feature_generator is None
