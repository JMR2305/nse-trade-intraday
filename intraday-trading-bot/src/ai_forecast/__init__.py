"""AI Forecast package — RC-10B public API.

Canonical 25-feature schema v1.0; DB-backed benchmark; async confidence gate.
"""
from __future__ import annotations

from ai_forecast.benchmark import (
    BenchmarkReport,
    BucketSummary,
    ForecastBenchmarkRepository,
    InMemoryForecastBenchmark,
)
from ai_forecast.config import AIForecastConfig
from ai_forecast.confidence_gate import ForecastConfidenceGate, GateDecision
from ai_forecast.features import (
    FEATURE_COUNT,
    FEATURE_NAMES,
    FEATURE_SCHEMA_VERSION,
    LEGACY_SCHEMA_VERSION,
    FeatureGenerator,
    FeatureVector,
    LegacyFeatureGenerator,
)
from ai_forecast.kronos_adapter import ForecastResult, KronosAdapter
from ai_forecast.volatility import VolatilityForecast, VolatilityForecaster

__all__ = [
    # Kronos adapter
    "ForecastResult",
    "KronosAdapter",
    # Feature schema
    "FeatureVector",
    "FeatureGenerator",
    "LegacyFeatureGenerator",
    "FEATURE_SCHEMA_VERSION",
    "LEGACY_SCHEMA_VERSION",
    "FEATURE_NAMES",
    "FEATURE_COUNT",
    # Gate
    "ForecastConfidenceGate",
    "GateDecision",
    # Volatility
    "VolatilityForecast",
    "VolatilityForecaster",
    # Benchmark
    "BenchmarkReport",
    "BucketSummary",
    "ForecastBenchmarkRepository",
    "InMemoryForecastBenchmark",
    # Configuration
    "AIForecastConfig",
]
