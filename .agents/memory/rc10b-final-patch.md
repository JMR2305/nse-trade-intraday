---
name: RC-10B Final Patch decisions
description: Canonical decisions, renames, and wiring patterns from the RC-10B AI Forecast Integration patch — required context for RC-10C/10D work.
---

## StrategyContext.forecast_snapshot (spec section 2)
`ForecastSnapshot` (frozen Pydantic, 6 spec fields: direction, confidence, forecast_horizon,
expected_volatility [None, deferred RC-10C], model_version, forecast_timestamp) is added to
`StrategyContext`. `_process_bar()` awaits the prefetch with a 300 ms shield timeout BEFORE
calling `on_bar()`; if confidence ≥ threshold, `context.model_copy(forecast_snapshot=...)` is
passed to the strategy. Any failure → `forecast_snapshot=None` → fail-open.
`_apply_forecast_gate()` takes `prefetched_result` to avoid a second network call.

**Why:** Spec section 2 requires forecast in StrategyContext before on_bar(), not just in
signal metadata after. 16 injection tests in test_strategy_context_forecast_injection.py.

## 25-feature canonical schema
`FeatureGenerator` (schema `"1.0"`) generates exactly 25 features. `FEATURE_COUNT = 25` asserted at module load.
`LegacyFeatureGenerator` (schema `"legacy-42-v1"`) retained for backward compatibility — produces 42 features.

**Why:** Audit found the 42-feature schema was never aligned to what Kronos expected; 25-feature v1.0 is the negotiated contract.

**How to apply:** Any new feature work uses `FeatureGenerator`; existing callers of 42-feature output must import `LegacyFeatureGenerator`.

## FeatureGenerator is stateful (ring buffers)
`FeatureGenerator.update_bar(token, close, volume)` must be called before `generate()` each bar. Per-instrument `close_1m`, `close_5m`, `volume_1m` ring buffers maintained internally.

**Why:** `MultiTimeframeContext` stores indicator values, not raw bar history, so the generator must own the history.

## ForecastConfidenceGate: class-based async gate
`async should_route(signal, context, min_confidence, prefetched_forecast=None) → Tuple[bool, Optional[ForecastResult]]`.
Static `apply(forecast, min_confidence)` retained as a utility (useful in tests and non-runtime callers). Fail-open: missing context, adapter errors, DB failures all return original signal.

**Why:** Old sync frozen-model approach blocked prefetch patterns and couldn't carry adapter state.

## VolatilityForecast field renames (RC-10B)
`expected_range` → `predicted_atr`, `expected_range_pct` → `predicted_range_pct`, `forecast_window` → `forecast_horizon`.
`computed_at` is now a timezone-aware `datetime`, not a string.
Old names kept as deprecated `@property` aliases.

## VolatilityForecaster API change
`update(bar: CompletedBar)` called per bar; `forecast(instrument_token)` then produces result.
Old positional `forecast(token, bars)` signature is gone.

**Why:** Forecaster should accumulate history across bars rather than receiving ad-hoc slices.

## ForecastBenchmarkRecord ORM rename
`ForecastBenchmark` (ORM) → `ForecastBenchmarkRecord`. Table name: `forecast_benchmark` (singular).
`ForecastBenchmarkRepository` is the service class (async, DB-backed). `InMemoryForecastBenchmark` for tests/dev.

**Why:** Name collision between the ORM class and the service class caused SQLAlchemy import errors.

## Double-import guard (SQLAlchemy MetaData clash)
Any code or test importing ORM models must use try/except:
```python
try:
    from src.database.models import ForecastBenchmarkRecord
except ImportError:
    from database.models import ForecastBenchmarkRecord
```
Conftest loads `src.database.models`; test code on sys.path loads `database.models`. Two module identities on one MetaData = `InvalidRequestError: Table already defined`.

**Why:** pytest conftest and test modules resolve the same file through different sys.path prefixes.

## StrategyRuntime wiring (RC-10B optional kwargs)
`StrategyRuntime` accepts `ai_forecast_gate`, `feature_generator`, `benchmark_repo` (all optional).
Prefetch via `asyncio.create_task()` before `strategy.on_bar()`; awaited with `asyncio.shield + 2s timeout`; cancelled if no signal emitted.
Signal enrichment: `signal.model_copy(update={...})` — never mutate a frozen Signal.

## State machine transition sequence
`REGISTERED → STARTING → ACTIVE` (two steps). Direct `REGISTERED → ACTIVE` is invalid and raises `LifecycleTransitionError`.

**How to apply:** Tests that need a runtime in ACTIVE state must call both transitions.

## SQLAlchemy AsyncSession result methods are synchronous
`await session.execute(stmt)` returns a synchronous result object. Call `.scalar_one_or_none()`, `.scalars().all()` without await.
`session.add(row)` is also synchronous — use `MagicMock()` (not `AsyncMock`) for it in tests.

**Why:** SQLAlchemy 2.x async result objects have sync accessor methods even though execute() is async.

## BenchmarkReport field names (RC-10B)
`sample_count` (was `total_predictions`), `directional_accuracy` (was `accuracy`). No `correct_predictions` or `by_instrument` fields.
