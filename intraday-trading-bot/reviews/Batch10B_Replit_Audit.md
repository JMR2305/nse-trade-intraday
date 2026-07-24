# Batch 10B — Independent Production Audit
## RC-10B: AI Forecast Integration

**Audit date:** 2026-07-24  
**Auditor:** Replit Agent (independent)  
**Commit audited:** `0098994` + audit-fix patch  
**Tag base:** RC-10A-FINAL (`a72fc77`)  
**Reference docs:** `docs/RC10_Reference.md`, `docs/RC10_Master_Implementation_Plan.md`  
**Audit scope:** Production-readiness and freeze eligibility for RC-10B as baseline for RC-10C and RC-10D  

---

## 1. Executive Summary

RC-10B delivers a clean, well-structured set of AI forecast components (`src/ai_forecast/`) that are individually correct and fully tested in isolation. All six modules compile without error, all 62 RC-10B tests pass, and the RC-10A regression suite is unaffected (104 + 15 integration tests pass).

However, the audit identified **one critical structural gap and five code-level defects** that must be resolved before this release can be frozen. The critical gap is that the **AI forecast pipeline is not wired into the live signal routing path**. The `ForecastConfidenceGate`, `KronosAdapter`, and `FeatureGenerator` are injected into `ContextBuilder` and `SignalRouter` constructor arguments but are never called during signal routing. No live signal is ever enriched with a forecast; no forecast is ever suppressed; no benchmark entry is ever recorded from a real trading event. RC-10B as merged is a library of correct isolated components with zero operational integration.

Additionally, `ForecastBenchmark` is in-memory only — it does not persist to the database the migration creates. `VolatilityForecast.computed_at` was always an empty string. The feature schema (42 features) deviates significantly and silently from the master plan (~25 features), which is a model-inference risk if the Kronos service was trained on the planned schema.

The audit applied five targeted defect fixes (described in Section 15). The critical runtime wiring gap requires a separate implementation pass and **prevents this release from being frozen**.

---

## 2. Requirement Coverage Table

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| 10B-F01 | `KronosAdapter.forecast()` returns `None` (not raise) on unavailability | ✓ | `kronos_adapter.py:119` — all exceptions caught, `None` returned |
| 10B-F02 | `ForecastConfidenceGate.should_route()` returns `(True, None)` when adapter returns `None` | ✗ | `should_route()` does not exist; `apply()` exists but is never called in routing path |
| 10B-F03 | Signals suppressed when confidence < `StrategyConfig.parameters["min_forecast_confidence"]` | ✗ | Gate reads its own `min_confidence` field; it never reads `StrategyConfig.parameters` |
| 10B-F04 | `ForecastResult` attached to `Signal.metadata["forecast"]` before routing callback fires | ✗ | No code in any production module assigns `signal.metadata["forecast"]` at any point |
| 10B-F05 | `FeatureGenerator.generate()` returns same `FeatureVector` for identical `MultiTimeframeContext` | ✓ | `features.py:151` — deterministic; verified by test |
| 10B-F06 | `VolatilityForecaster.forecast()` produces positive `predicted_atr` and `predicted_range_pct` | ⚠ | Fields renamed: `expected_range` / `expected_range_pct` instead of `predicted_atr` / `predicted_range_pct` — positivity verified |
| 10B-F07 | `ForecastBenchmark.record_forecast()` idempotent by `(instrument_token, forecast_horizon, computed_at)` | ⚠ | **Fixed by audit** — was keyed by `instrument_token` alone, now uses composite key; still in-memory only |
| 10B-F08 | No Kronos call generates, submits, or routes an order | ✓ | `KronosAdapter` has no reference to `SignalRouter`, `RiskEngine`, or any broker path |
| 10B-F09 | `KronosAdapter` logs `model_version` in every structured entry | ✓ | `kronos_adapter.py:107-116` — `model_version` in structured `extra` dict |
| 10B-F10 | All Kronos HTTP calls respect configurable timeout (default 2000ms) | ✓ | `httpx.Timeout(self._timeout / 1000.0)` applied at client construction |
| 10B-NF01 | `KronosAdapter.forecast()` P95 < 500ms (network included) | ↪ | Cannot measure without live Kronos; timeout enforcement verified |
| 10B-NF02 | Kronos prefetch must not delay bar processing critical path | ✗ | Prefetch pattern (`asyncio.create_task`) specified in plan is not implemented |
| 10B-NF03 | `FeatureGenerator.generate()` < 1ms | ✓ | Measured: **0.015ms avg** (66× faster than requirement) |
| 10B-NF04 | `VolatilityForecaster.forecast()` < 5ms | ✓ | Measured: **0.038ms avg** (130× faster than requirement) |
| 10B-NF05 | All AI components must degrade gracefully if services fail | ✓ | Each component handles errors independently and fail-opens |
| 10B-NF06 | No live Kronos API calls in test suite | ✓ | All adapter tests use `http://localhost:99999` (unreachable); fail-open path tested |

---

## 3. Runtime Wiring Review

**This is the most critical finding of the audit.**

### What the master plan requires

The plan (Section 10, Data Flow) specifies a concrete runtime path:

```
StrategyRuntime._process_bar(bar)
  → ContextBuilder.build() → StrategyContext
  → KronosAdapter.forecast() [asyncio.create_task — prefetch]
  → strategy.on_bar(bar, ctx) → Optional[Signal]
  → if Signal:
      ForecastConfidenceGate.should_route(signal, context, min_confidence)
        → if confidence < threshold → suppress signal
        → if confidence ≥ threshold (or adapter unavailable):
            Signal.metadata["forecast"] = ForecastResult
            SignalRouter.route(signal)
            ForecastBenchmark.record_forecast(session, forecast)
```

### What is actually implemented

- `ContextBuilder.__init__` accepts `ai_forecast_adapter`, `confidence_gate`, `volatility_forecaster` — **stored as `self._ai_forecast_adapter`, etc. — never called**
- `SignalRouter.__init__` accepts `ai_forecast_adapter`, `confidence_gate` — **stored — never called**
- `SignalRouter.route_signal()` (lines 64–274): zero references to AI forecast, feature generation, or confidence gating
- `ContextBuilder.build()` / `build_context()`: zero references to AI forecast services
- `Signal.metadata["forecast"]`: not set anywhere in production code
- `ForecastBenchmark.record_forecast()`: not called from `route_signal()` or anywhere in the strategy runtime

**Conclusion:** The entire AI enrichment pipeline from bar arrival to signal metadata is a stub. Every component exists and is individually correct, but end-to-end the feature does not function.

### Impact

- RC-10B's primary functional requirements (10B-F02, 10B-F03, 10B-F04) cannot be satisfied
- The prefetch pattern (10B-NF02) is not implemented
- All 62 tests pass only because they test components in isolation, not the runtime path
- `test_context_builder_with_ai_forecast` (integration) verifies only that the constructor accepts new args and `build()` returns — not that any AI service is called

---

## 4. Feature Schema Review

### Plan specification (Section 5.2)

The master plan specifies **~25 features** drawn from:
- 1m and 5m returns (last 5 / 3 bars)
- RSI(14) normalised to [0, 1] for 1m and 5m
- MACD histogram sign and magnitude (1m, 5m)
- Bollinger band position: `(close − lower) / (upper − lower)` for 1m
- ATR/close ratio for 1m and 5m
- Regime one-hot encoding (7 values)
- Volume ratio (relative to 20-bar average, 1m)

### Actual implementation (`features.py`)

The implementation produces **42 features** in a different composition:

| Index range | Content |
|-------------|---------|
| 1–17 | 1m: SMA-10/close, SMA-20/close, SMA-50/close, EMA-9/close, EMA-21/close, RSI-14 (raw, not normalised), ATR-14/close, ADX-14, +DI, −DI, MACD-line, MACD-signal, MACD-histogram, VWAP/close, BB-upper/close, BB-lower/close, BB-width |
| 18–22 | 5m compact: SMA-10/close, SMA-20/close, RSI-14, ATR-14/close, ADX-14 |
| 23–27 | 15m compact: same 5 |
| 28–32 | 1h compact: same 5 |
| 33–34 | Regime confidence, Regime encoding (0–6) |
| 35–39 | Announcement count, earnings flag, dividend flag, bonus flag, split flag |
| 40–41 | Watchlist rank/100, composite score |
| 42 | Time-of-day (minutes since 09:15 / 375) |

### Assessment

The implementations differs from the plan in:
- **Feature count: 42 vs ~25** — 68% more features than specified
- **Composition differs**: plan requires returns (price momentum) and volume ratio; implementation omits both and adds announcement, watchlist, and multi-timeframe features not in the plan
- **RSI normalisation**: plan requires RSI normalised to [0, 1]; implementation passes raw RSI (0–100)
- **Bollinger position**: plan requires `(close − lower) / (upper − lower)`; implementation sends `bb_upper/close` and `bb_lower/close` separately, plus `bb_width`
- **MACD**: plan requires histogram sign and magnitude; implementation sends raw `macd_line`, `macd_signal`, `macd_histogram`

**Risk**: If the Kronos model was trained on the plan's ~25-feature schema, the 42-feature vector will cause inference errors or silent garbage output. The `schema_version = "1.0"` label is shared between plan and implementation but describes different schemas.

**This is an undocumented schema deviation and is a release risk.** It must be either documented with model compatibility evidence, or the schema must be brought into alignment with the plan.

---

## 5. Architecture Review

### Package boundaries — ✓

```
ai_forecast/
  benchmark.py    ← depends on core.config only
  confidence_gate.py  ← depends on ai_forecast.kronos_adapter
  features.py     ← depends on core.config, market_intelligence
  kronos_adapter.py   ← depends on ai_forecast.features, core.config
  volatility.py   ← depends on market_data.contracts, market_intelligence.indicator_engine
```

Dependency direction is correct: `ai_forecast` depends on `core`, `market_intelligence`, and `market_data`. No circular imports. No hidden coupling to `strategy`, `execution`, `risk`, or `broker` layers.

### Immutability — ✓

All output types (`ForecastResult`, `FeatureVector`, `VolatilityForecast`, `BenchmarkReport`) are frozen Pydantic models. `BenchmarkEntry` is a `@dataclass` — mutable but internal-only.

### Async task lifecycle — ⚠

`KronosAdapter._get_client()` lazily initialises a single `httpx.AsyncClient`. The client is shared across concurrent calls without locking. Under concurrent use this can create a race condition where two coroutines both see `self._client is None` and both construct a client — one is dropped and its connection pool leaked. This is low-risk in the current context (gate is not wired) but must be addressed before live use.

### Fire-and-forget tasks — ↪ (not implemented)

The plan specifies `ForecastBenchmark.record_forecast()` as fire-and-forget via `asyncio.create_task()`. Not implemented; the current synchronous benchmark avoids this risk.

### Mutable shared state — ⚠

`ForecastBenchmark._entries` and `ForecastBenchmark._pending` are plain Python lists/dicts shared within a process. Under concurrent strategy runtimes, concurrent `record_forecast()` / `evaluate()` calls without locking could produce corrupted state. A `threading.Lock` or `asyncio.Lock` is required before any multi-strategy deployment.

`VolatilityForecaster._bar_buffers` has the same issue.

### Frozen RC-10A contracts — ✓

All frozen contracts from RC-10A verified intact:
- `ContextBuilder.build()` — signature unchanged (lines 1–258), new kwargs are keyword-only after `*`
- `ContextBuilder.build_context()` — unchanged
- `ContextBuilder._inject_market_intelligence()` — unchanged, `market_snapshots[token]` still typed `MultiTimeframeContext`
- `SignalRouter.route_signal()` — signature unchanged; new constructor kwargs are keyword-only
- `Signal`, `StrategyContext`, `SignalRoutingResult` — all fields present and frozen
- `ConflictResolution.has_conflict` — present
- `database/models.py` — 630 prior lines intact; RC-10B model appended after

---

## 6. Kronos Adapter Review

| Check | Result |
|-------|--------|
| Async HTTP client (httpx) | ✓ |
| Client cleanup via `close()` | ✓ — `aclose()` called, `self._client = None` |
| Per-request timeout | ✓ — `httpx.Timeout(self._timeout / 1000.0)` |
| Retry count | ✓ — `range(max_retries + 1)` |
| Back-off algorithm | **Fixed** — was linear (`0.1 * (attempt + 1)`); corrected to exponential (`0.1 * 2^attempt`) |
| No retry explosion | ✓ — bounded by `max_retries` (default 1) |
| Safe URL handling | ✓ — `base_url` trimmed of trailing `/`; only `/forecast` appended |
| HTTP status handling | ✓ — `response.raise_for_status()` |
| Malformed JSON handling | ✓ — caught by broad `except Exception` |
| Pydantic validation of response | ✓ — `ForecastResult(...)` validates on construction |
| Response size bounded | **Fixed** — now rejects payloads > 65 536 bytes |
| Decimal conversion | ✓ — `Decimal(str(data["confidence"]))` — no float precision loss |
| No account/portfolio/order data sent | ✓ — payload is `instrument_token`, `features[]`, `schema_version`, `horizon` only |
| Logs do not expose full payloads | ✓ — only `model_version`, `direction`, `confidence`, `horizon` logged |
| `model_version` in success logs | ✓ — `kronos_adapter.py:111` |
| All failures return `None` | ✓ |
| No live calls in tests | ✓ — all tests use unreachable URL |
| Protected namespace warning on `model_version` | **Fixed** — `protected_namespaces=()` added to `ForecastResult.model_config` |

**SSRF note:** `kronos_base_url` is fully configurable via the `AI_KRONOS_BASE_URL` environment variable. An attacker with env-var write access can redirect forecast traffic to any internal endpoint. This is an accepted risk for environment-controlled infrastructure but should be documented in the ops runbook.

---

## 7. Confidence Gate Review

| Check | Result |
|-------|--------|
| No configured threshold → pass | ✗ | Gate is never called without explicit injection, but the gate itself has a hard default of `min_confidence=0.55` — any injected gate will silently filter without strategy opt-in |
| Adapter unavailable → pass | ✗ | Gate does not call the adapter; the caller must obtain a `ForecastResult` first. If no forecast is available, the gate is simply not called — but this is the caller's responsibility |
| Confidence below threshold → suppress | ✓ — `confidence_gate.py:23` |
| Confidence at or above threshold → pass | ✓ — `confidence_gate.py:22` (strict `<`) |
| Forecast attached to signal metadata | ✗ — never done anywhere |
| `should_route()` async method | ✗ — plan specifies `async .should_route(signal, context, min_confidence) → Tuple[bool, Optional[ForecastResult]]`; implementation has synchronous `.apply(forecast) → Optional[ForecastResult]` |
| Gate reads `StrategyConfig.parameters["min_forecast_confidence"]` | ✗ — gate reads its own `min_confidence` field; not per-strategy |

**Opinionated default risk:** `enforce_direction_mandatory=True` and `min_confidence=0.55` are hard defaults. Per the plan, filtering should only occur when a strategy explicitly opts in via `parameters["min_forecast_confidence"]`. Any operator who injects a gate without overriding these defaults will silently suppress all NEUTRAL forecasts and any forecast with confidence < 0.55. This contradicts the fail-open principle.

**Dead code removed by audit:** `neutral_band: Decimal = Decimal("0.05")` was declared but never referenced — removed.

---

## 8. Volatility Review

| Check | Result |
|-------|--------|
| ATR algorithm correctness | ✓ — delegates to `market_intelligence.indicator_engine.compute_atr` |
| `expected_range` positive | ✓ — ATR > 0 multiplied by 2; STD > 0 multiplied by 2; 1% floor always positive |
| `expected_range_pct` positive | ✓ — close > 0 enforced by `_get_close()` defaulting to 1 |
| Confidence in [0, 1] | ✓ — values are 0.6, 0.5, 0.3 — all in range |
| Insufficient-data behaviour | ✓ — fixed by merge (< 14+1 bars → STD path with `min(len,period)`) |
| Empty-buffer fallback | ✓ — 1% floor, confidence 0.3 |
| 50-bar ring buffer bounded | ✓ — `volatility.py:102` truncates to last 50 |
| Deterministic results | ✓ — verified by test |
| No division by zero | ✓ — `close > 0` guarded; `Decimal.sqrt()` safe on non-negative |
| Correct Decimal arithmetic | ✓ — no float mixing |
| `computed_at` always set | **Fixed** — was `""` always; now `datetime.now(UTC).isoformat()` |

**Deviations from plan (documented):**

| Plan field | Implementation field | Note |
|------------|---------------------|------|
| `predicted_atr` | `expected_range` | Range is `2 × ATR`, not raw ATR |
| `predicted_range_pct` | `expected_range_pct` | Same value, different name |
| Confidence = ATR stability-based | Fixed discrete values (0.6/0.5/0.3) | Simpler but less informative |
| STD fallback | Not in plan | Added during merge bug-fix; documented |
| 1% price floor | Not in plan | Prevents zero-range edge case; acceptable |

---

## 9. Benchmark Review

| Check | Result |
|-------|--------|
| Database-backed persistence | ✗ — **Critical gap** — `ForecastBenchmark` is entirely in-memory; `ForecastBenchmark` ORM model exists and migration creates the table, but the service class never writes to it |
| Idempotency key: `(instrument_token, forecast_horizon, computed_at)` | ⚠ **Fixed** — was keyed by `instrument_token` alone; now uses composite key in both `record_forecast()` and `evaluate()` |
| `record_forecast()` | ✓ — stores pending entry |
| `record_outcome()` | ✗ — **Missing** — plan requires `record_outcome(session, instrument_token, horizon, actual_return, reference_timestamp)`; implementation has `evaluate()` with different signature; no `actual_return` field |
| Matching the correct forecast row | ⚠ **Partially fixed** — composite key matching improved; DB-row matching impossible without persistence |
| `actual_return` persistence | ✗ — not stored; only `actual_direction` (string) and `correct` (bool) |
| Directional accuracy | ✓ — computed correctly |
| Calibration error (MAE) | ✗ — not implemented; plan requires calibration error between predicted confidence and binary outcome |
| Sample count | ✓ — `total_predictions` |
| Instrument filtering in report | ✗ — `generate_report()` aggregates all entries; no `instrument_token` filter |
| last_n ordering and limit | ✗ — no `last_n` parameter |
| DB failure fail-safe | ✗ — no DB interaction; N/A |
| `SessionContext` conventions | ✗ — no DB interaction |

**API contract mismatch (plan vs implementation):**

| Plan | Implementation |
|------|----------------|
| `async record_forecast(session, ForecastResult)` | `record_forecast(token, direction, confidence, timestamp, horizon="15m")` — sync, no session |
| `async record_outcome(session, token, horizon, actual_return, reference_ts)` | `evaluate(token, actual_direction, timestamp, horizon, forecast_ts)` — sync, no session, no `actual_return` |
| `async get_accuracy_report(session, token?, last_n=100)` | `generate_report(period="daily")` — sync, no session, no filtering |

---

## 10. Database and Migration Review

| Check | Result |
|-------|--------|
| Revision chain 0004 → 0005 | ✓ — `down_revision = "0004"` |
| Table name consistency (ORM ↔ migration) | ✓ — both use `forecast_benchmarks` |
| Table name consistency (plan ↔ implementation) | ✗ — plan specifies `forecast_benchmark` (singular); implementation uses `forecast_benchmarks` (plural). ORM and migration are consistent with each other; the deviation is from the plan only |
| ORM ↔ migration column consistency | ✓ — all 11 columns match |
| Unique constraint on `benchmark_id` | ✓ — migration `unique=True`; ORM `unique=True` |
| Indexes | ✓ — 3 indexes: instrument, timestamp, correct |
| NUMERIC precision | ✓ — `NUMERIC(10, 4)` for confidence |
| Timezone-aware timestamps | ✓ — `DateTime(timezone=True)` on all timestamp columns |
| Upgrade correctness | ✓ — creates table and all indexes |
| Downgrade correctness | ✓ — drops all indexes then table in reverse order |
| No damage to existing models | ✓ — appended after `Announcement`; all prior lines intact |
| No manual commits | ✓ — uses `op.create_table()` / `op.create_index()` / `op.drop_*` |

**Plan schema deviation:**

The migration table schema differs from the plan in column set:

| Plan column | Migration column | Delta |
|-------------|-----------------|-------|
| `instrument_token` | `instrument_token` | ✓ |
| `forecast_horizon` | — | **Missing in migration** |
| `direction` | `forecast_direction` | Renamed |
| `confidence` | `confidence` | ✓ |
| `model_version` | `model_version` | ✓ |
| `computed_at` | — | **Missing — replaced by `forecast_timestamp`** |
| `actual_direction` | `actual_direction` | ✓ |
| `actual_return` | — | **Missing** |
| `outcome_recorded_at` | `actual_timestamp` | Renamed |
| `created_at` | `created_at` | ✓ |
| — | `benchmark_id` | New — surrogate unique key |
| — | `correct` | New — precomputed boolean |
| Composite UNIQUE `(instrument_token, forecast_horizon, computed_at)` | Only `benchmark_id` unique | **Idempotency index missing** |

---

## 11. Performance and Concurrency Review

| Check | Measured / Verified | Result |
|-------|---------------------|--------|
| `FeatureGenerator.generate()` < 1ms | 0.015ms avg (1 000 iterations) | ✓ |
| `VolatilityForecaster.forecast()` < 5ms | 0.038ms avg (1 000 iterations) | ✓ |
| Forecast call timeout enforced | `httpx.Timeout` at construction | ✓ |
| No blocking I/O in asyncio event loop | All Kronos calls via `httpx.AsyncClient` | ✓ |
| No unbounded task creation | No `create_task()` calls anywhere | ✓ |
| No unbounded buffers | Ring buffer capped at 50 bars per token | ✓ |
| No leaked httpx clients | `close()` method exists and zeroes `self._client` | ✓ |
| Race condition in httpx client init | ✗ — `_get_client()` not guarded by lock | ⚠ |
| Race condition in benchmark state | ✗ — `_entries`, `_pending` unguarded | ⚠ |
| Race condition in volatility buffers | ✗ — `_bar_buffers` unguarded | ⚠ |
| Prefetch `create_task()` lifecycle | ↪ — Not implemented | N/A |

All three concurrency gaps are low-risk in the current deployment context because the gate is not wired, but must be resolved before multi-strategy live operation.

---

## 12. Security Review

| Check | Result |
|-------|--------|
| Kronos URL from settings only | ✓ — `settings.ai_forecast.kronos_base_url` |
| No hardcoded secrets | ✓ |
| Response size bounded | **Fixed** — now rejects responses > 65 536 bytes |
| Request payload validated | ✓ — only safe fields sent |
| Response payload validated | ✓ — Pydantic validates on construction |
| HTTP timeout enforced | ✓ |
| Safe logging | ✓ — only metadata logged, not raw payloads |
| SSRF exposure documented | ⚠ — configurable URL is an SSRF vector; should appear in ops runbook |
| No confidential data sent | ✓ — only feature vector (market data derived), no account/order/portfolio data |
| Malformed response cannot crash routing | ✓ — all adapter exceptions caught and return `None` |

---

## 13. Test Results

### RC-10B test suite (post-fix)

| File | Tests | Result |
|------|-------|--------|
| `tests/unit/ai_forecast/test_kronos_adapter.py` | 10 | ✅ All pass |
| `tests/unit/ai_forecast/test_features.py` | 13 | ✅ All pass |
| `tests/unit/ai_forecast/test_confidence_gate.py` | 9 | ✅ All pass |
| `tests/unit/ai_forecast/test_volatility.py` | 11 | ✅ All pass |
| `tests/unit/ai_forecast/test_benchmark.py` | 13 | ✅ All pass |
| `tests/integration/test_ai_forecast.py` | 6 | ✅ All pass |
| **RC-10B total** | **62** | **✅ 62 / 62** |

### RC-10A regression

| Suite | Tests | Result |
|-------|-------|--------|
| `tests/unit/market_intelligence/` | 104 | ✅ All pass |
| `tests/integration/test_context_builder_*.py` | 15 | ✅ All pass |

### Full unit suite

| Suite | Tests | Result |
|-------|-------|--------|
| All `tests/unit/` | 605 | ✅ 604 pass, 1 pre-existing failure |
| `test_kill_switch::test_history` | — | ⚠ Pre-existing; tracked since RC-8B |

**Test gap (not a test failure):** No test verifies runtime wiring — that the gate is actually invoked during `route_signal()`, or that `Signal.metadata["forecast"]` is set. The integration tests call `ContextBuilder.build()` with AI args and check the returned context, but do not exercise the signal routing path with forecast enrichment. This gap will persist until the runtime wiring is implemented.

**Integration test count vs plan:** Plan requires minimum 25 integration tests. Implementation has 6.

### Test classification

| Category | Tests |
|----------|-------|
| A — RC-10B introduced failures | 0 |
| B — Pre-existing failures | 1 (`test_kill_switch::test_history`) |
| C — Environment/fixture failures | 22 (pre-existing DB fixture issues in `test_orders`, `test_positions`, `test_sessions`) |

---

## 14. Issues Found

### Critical

| # | Issue | File | Severity |
|---|-------|------|----------|
| C-1 | **AI forecast pipeline not wired into runtime** — `ForecastConfidenceGate`, `KronosAdapter`, `FeatureGenerator` stored in constructors but never called; no signal enrichment occurs; 10B-F02, F03, F04 unmet | `signal_router.py`, `context_builder.py` | Critical |
| C-2 | **`ForecastBenchmark` is in-memory only** — ORM model and migration table exist but `ForecastBenchmark` service never writes to DB; all benchmark data lost on restart | `benchmark.py` | Critical |

### High

| # | Issue | File | Severity |
|---|-------|------|----------|
| H-1 | **Feature schema drift: 42 features vs ~25 in plan** — composition, count, and normalisation all differ; `schema_version="1.0"` used for both schemas; breaks Kronos model if trained on plan's schema | `features.py` | High |
| H-2 | **`ForecastConfidenceGate` API mismatch** — plan requires `async should_route(signal, context, min_confidence)→Tuple[bool, Optional[ForecastResult]]`; implementation is synchronous `apply(forecast)→Optional[ForecastResult]`; per-strategy opt-in logic absent | `confidence_gate.py` | High |
| H-3 | **`ForecastBenchmark` missing `record_outcome()`, `get_accuracy_report()` with session** — calibration error not computed; `actual_return` not stored; `last_n` and instrument filtering absent | `benchmark.py` | High |
| H-4 | **Migration table schema diverges from plan** — missing `forecast_horizon`, `actual_return`, `outcome_recorded_at`; idempotency composite index absent; surrogate `benchmark_id` replaces planned natural key | `migrations/versions/0005_rc10b_forecast_benchmarks.py` | High |

### Medium

| # | Issue | File | Severity |
|---|-------|------|----------|
| M-1 | **`VolatilityForecast.computed_at` always `""`** — every forecast has an empty timestamp | `volatility.py` | Medium — **Fixed** |
| M-2 | **Retry back-off described as exponential but was linear** (`0.1*(attempt+1)`) | `kronos_adapter.py` | Medium — **Fixed** |
| M-3 | **Response size unbounded** — no limit on Kronos response; oversized payloads could exhaust memory | `kronos_adapter.py` | Medium — **Fixed** |
| M-4 | **`ForecastBenchmark.record_forecast()` single-key overwrite** — keyed by `instrument_token` alone; second forecast for same token overwrites first | `benchmark.py` | Medium — **Fixed** |
| M-5 | **Gate default `min_confidence=0.55` + `enforce_direction_mandatory=True` active without strategy opt-in** — violates fail-open principle | `confidence_gate.py` | Medium |
| M-6 | **`httpx.AsyncClient` lazy init has race condition** — two concurrent coroutines can both see `self._client is None` | `kronos_adapter.py` | Medium |
| M-7 | **`ForecastBenchmark._entries` / `_pending` unguarded** — concurrent `record_forecast()` / `evaluate()` calls will corrupt state | `benchmark.py` | Medium |
| M-8 | **`VolatilityForecaster._bar_buffers` unguarded** — concurrent `update()` calls will corrupt state | `volatility.py` | Medium |

### Low / Observations

| # | Issue | File | Severity |
|---|-------|------|----------|
| L-1 | **`ForecastResult.model_version` Pydantic protected_namespaces warning** | `kronos_adapter.py` | Low — **Fixed** |
| L-2 | **`neutral_band` field declared but never used in `ForecastConfidenceGate`** — dead code | `confidence_gate.py` | Low — **Fixed** |
| L-3 | **`VolatilityForecast.predicted_atr` renamed to `expected_range`** — differs from plan field name | `volatility.py` | Low |
| L-4 | **`ForecastResult.computed_at` typed as `str` instead of `datetime`** | `kronos_adapter.py` | Low |
| L-5 | **`datetime.utcnow()` deprecated** — used in `context_builder.py:185`, `contracts.py:124`; pre-existing | Multiple | Low |
| L-6 | **Integration test count: 6 vs 25 minimum required by plan** | `tests/integration/` | Low |
| L-7 | **SSRF from configurable Kronos URL not documented in ops runbook** | — | Low |
| L-8 | **`AiForecastMetadata` has no validators on `direction` or `confidence`** — unlike `ForecastResult` which validates both | `contracts.py` | Low |
| L-9 | **Table name `forecast_benchmarks` (plural) vs plan's `forecast_benchmark` (singular)** — ORM and migration agree; deviates from plan only | `models.py`, `0005_*.py` | Low |

---

## 15. Issues Fixed by This Audit

The following defects were corrected during the audit. All 62 RC-10B tests continue to pass after each fix.

| # | Fix | Files Changed |
|---|-----|--------------|
| F-1 | **`VolatilityForecast.computed_at`** — changed from hardcoded `""` to `datetime.now(timezone.utc).isoformat()` | `volatility.py` |
| F-2 | **Exponential back-off** — `0.1 * (attempt + 1)` (linear) corrected to `0.1 * (2 ** attempt)` (exponential) | `kronos_adapter.py` |
| F-3 | **Response size guard** — added 65 536-byte limit before `response.json()` | `kronos_adapter.py` |
| F-4 | **`ForecastResult` Pydantic warning** — added `protected_namespaces=()` to `ForecastResult.model_config` | `kronos_adapter.py` |
| F-5 | **Dead code removal** — removed `neutral_band: Decimal = Decimal("0.05")` from `ForecastConfidenceGate` | `confidence_gate.py` |
| F-6 | **Benchmark composite key** — `record_forecast()` now keys pending entries as `f"{token}:{horizon}:{timestamp}"`; `evaluate()` matches by same composite key with instrument+horizon prefix fallback | `benchmark.py` |

---

## 16. Remaining Observations (Not Fixed — Require Design Decision or Future Phase)

1. **Runtime wiring (C-1):** Requires implementing `ForecastConfidenceGate.should_route()` (async, reads `StrategyConfig.parameters["min_forecast_confidence"]`), wiring it into `SignalRouter.route_signal()`, implementing signal metadata attachment, and the `asyncio.create_task()` prefetch pattern in `StrategyRuntime`. This is a substantial implementation task.

2. **Benchmark DB persistence (C-2):** The `ForecastBenchmark` service class must be converted to use `AsyncSession` for persistence, matching the plan's API. The ORM model and migration are in place — the service is the missing piece.

3. **Feature schema alignment (H-1):** The 42-feature schema must either be documented as the authoritative schema (with Kronos model compatibility confirmed), or brought into alignment with the plan's ~25-feature schema. `FEATURE_SCHEMA_VERSION` must reflect whichever is canonical. A mismatch here will cause silent model inference errors.

4. **`ForecastConfidenceGate.should_route()` (H-2):** Gate must become async, accept `signal` and `context`, call the adapter internally, and read `min_confidence` from `StrategyConfig.parameters` — not from a constructor default. The current `apply()` method can remain as a utility.

5. **Benchmark missing methods (H-3):** `record_outcome()` and calibration error computation must be implemented before forecast accuracy monitoring is meaningful.

6. **Concurrency guards (M-6, M-7, M-8):** `asyncio.Lock` needed in `KronosAdapter._get_client()`, `ForecastBenchmark.record_forecast()` / `evaluate()`, and `VolatilityForecaster.update()`.

---

## 17. Merge / Freeze Recommendation

RC-10B **must not be frozen** in its current state. The core deliverable — AI-enriched signal routing — does not function at runtime. The gate is never called, no signal is ever enriched with a forecast, and the benchmark never records a live event. All 62 tests pass exclusively because they test components in isolation.

The components themselves are well-designed and individually correct. The infrastructure (migration, ORM model, config, package structure) is in good shape. This makes RC-10B a solid foundation, but the wiring pass is mandatory before freeze.

**Recommended path to freeze:**

1. Implement `ForecastConfidenceGate.should_route()` as async per plan specification
2. Wire gate into `SignalRouter.route_signal()` reading `StrategyConfig.parameters["min_forecast_confidence"]`
3. Implement signal metadata attachment (`signal.model_copy(update={"metadata": {..., "forecast": result}})`)
4. Implement `asyncio.create_task()` prefetch in `StrategyRuntime`
5. Convert `ForecastBenchmark` to DB-backed (async sessions)
6. Resolve feature schema discrepancy with model team confirmation
7. Add 19+ integration tests covering the full wired path
8. Add concurrency guards
9. Rerun full suite; confirm 0 new failures

---

## 18. Overall Score

| Dimension | Score | Notes |
|-----------|-------|-------|
| Component correctness | 8 / 10 | Each module is individually well-implemented |
| Runtime integration | 0 / 10 | Core feature is not wired — hard zero |
| Frozen contract protection | 10 / 10 | RC-10A contracts perfectly preserved |
| Test quality | 6 / 10 | 62 tests all correct and isolated; no wiring tests; only 6 of 25 required integration tests |
| Schema / API compliance | 4 / 10 | Feature schema drifted; gate API wrong; benchmark API wrong; table name drifted |
| Security | 8 / 10 | Good; SSRF undocumented; response size fixed |
| Performance | 10 / 10 | Both compute functions exceed target by > 60× |
| Code quality | 7 / 10 | Six bugs fixed; concurrency risks remain |

**Overall: 5.4 / 10**

---

## Final Verdict

❌ **NOT READY FOR FREEZE**

RC-10B delivers high-quality isolated components with zero runtime integration. The AI forecast pipeline from bar arrival to signal metadata enrichment is unimplemented. `ForecastBenchmark` does not persist to the database. The feature schema (42 features) is undocumented and deviates materially from the model plan (~25 features), creating a model-inference risk.

RC-10B **may not be tagged RC-10B-FINAL** and **may not be used as the baseline for RC-10C or RC-10D** until the runtime wiring pass and benchmark persistence pass are complete and independently verified.

RC-10C (Portfolio Management) has no direct dependency on the AI forecast runtime path and **may proceed in parallel** on a branch from the current RC-10A-FINAL tag, merging RC-10B when it is ready.
