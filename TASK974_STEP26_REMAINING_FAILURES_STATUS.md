# TASK974 Step26 — remaining focused failures

## Focused verdict

READY FOR ONE FULL VALIDATION.

All six requested groups completed sequentially in fresh interpreters: **719 passed, 0 failed, 2 explicitly DB-required skips, 0 collection errors**. This is a focused-test result, not full CI or release approval. The one authorized full workflow will be triggered only after this evidence and exact blob pins are committed.

Read and preserved the Step23, Step24 and Step25 reports. Step25's 449 passed / 39 failed / 1 skipped result is historical failed evidence and has not been rewritten.

## Environment and process control

- Existing /workspace/task972/.venv: Python 3.12.13, pytest 9.1.1, pytest_asyncio 1.4.0, yfinance 1.5.1.
- No dependency installation or lockfile change in Step26.
- Initial /proc scan found no old pytest process; no PID needed termination.
- Every local test command explicitly unset DATABASE_URL and TASK967_TEST_DATABASE_URL.
- Every group used timeout 90s, SIGINT then 10s kill grace, quiet output, short tracebacks, durations=20 and separate JUnit/JSONL evidence. None timed out.
- No local database, migration gate, whole-repository test, dashboard, TypeScript or build run.

## Proven root causes and minimal corrections

1. **Replay wording:** existing runtime explicitly distinguishes eligibility from unrecorded execution. Updated exact expected text only; ELIGIBLE and no-fabricated-order assertions remain.
2. **Trade identity:** validation_engines and phase26_consistency exclude non-canonical nonempty trade IDs. Valid execution fixtures now consistently use P20-* identities across events, ledger/replay/portfolio references. No filter changed.
3. **Collection contamination:** tests/test_invalidation_override installed empty model_versioning/predictive_intelligence modules at import and executed script assertions during collection. Removed unused empty stubs; required two external doubles are function-fixture scoped via monkeypatch. Script checks now run as a real pytest case, preserving all checks and asserting their accumulated failures are zero. Standalone entry uses the same pytest fixture path.
4. **Adaptive contract:** decision_service's Task387 contract explicitly yields WATCH for one high-confidence failed filter, AVOID for two or negative expectancy. The old “never overridden” case is replaced by two explicit boundary cases proving positive adjustment cannot turn either into BUY. No decision/risk behavior changed.
5. **Actual settings path:** get_settings reads db_available/_connect/cursor directly; obsolete _with_db mocks did not supply persisted values. Updated those DB-API doubles while retaining the real settings normalization and gate evaluation. Gate fixture now supplies required pinned-universe metadata in canonical scan meta. No provenance bypass or settings default change.
6. **OHLCV:** public refresh now uses guarded due/lease logic and a subprocess provider boundary. Scoped due clock, independent in-memory lease I/O and provider-response fixtures exercise the real guard/worker; partial result retains INFY as unfinished and releases its lease. These are unit-test doubles, not claimed native DB tests. Readiness observation proved its sole warning was “Build identity unavailable”; added explicit test build identity. Kite overlay needs quote_sources[RELIANCE]=kite_live in addition to verified session and LTP. Scan count now mocks scan_observability_counts_today_ist, not obsolete count_scans_today_ist.
7. **Durable KV:** chose authorized Option A. test_phase22_finalization skips only when DATABASE_URL is absent, matching the existing real-DB cache timing pattern. It still runs with real disposable DB configuration in CI. DurableKVError, token persistence and DB guards unchanged. This is NOT a claim that durable DB integration passed locally.
8. **Nested Phase0C:** the custom-universe test launches the Phase0C suite. Its file-fallback scan_state_store double lacked _connect, which real phase20_store imports. Added an _connect double that raises if called, proving the cutoff case cannot access DB. Existing cutoff assertion preserved.

### Import-regression evidence

New test_invalidation_import_does_not_poison_adaptive_dependencies failed before the fix at exact module-registry equality immediately after producer import (task974-step26-stub-red.log). It then verifies two scoped runs, restoration, real predictive/model APIs and the actual adaptive_adjustments consumer.

First post-fix run exposed NumPy's “cannot load module more than once per process”: tmp_db first imported the scientific dependency inside a per-test module-restoration scope. Moved that real dependency import alongside the adaptive file's existing module imports, so the native extension is initialized once before per-test snapshots. No global isolation-hook expansion. Also corrected the new regression's consumer name from nonexistent adaptive_engine to actual adaptive_adjustments. Second regression group: 51 passed in 7.10s. Final C1: 33 passed; final Control includes the new fresh-interpreter regression.

## Final controlled results

| Group | Passed | Failed | Skipped | Collection errors | Seconds |
|---|---:|---:|---:|---:|---:|
| Control | 230 | 0 | 0 | 0 | 54.224 |
| A | 67 | 0 | 0 | 0 | 0.597 |
| B | 122 | 0 | 2 | 0 | 8.161 |
| C1 | 33 | 0 | 0 | 0 | 0.809 |
| C2 | 82 | 0 | 0 | 0 | 5.357 |
| D | 185 | 0 | 0 | 0 | 0.803 |
| Total | 719 | 0 | 2 | 0 | 69.951 |

Skipped explicitly: test_ohlcv_cache.py::test_fetch_batch_warm_cache_timing (existing), test_phase22_final.py::test_phase22_finalization (Option A). Both require real DB; none of the remaining logic failures was skipped.

Additional focused runs: wording/IDs 134 passed; settings 82 passed; cache/DB-required/custom-universe 47 passed, 2 skipped. All logs and XML remain under repository root as task974-step26-*.

## Exact commands

Cwd: /workspace/task972/artifacts/api-server/src/python. Observation-only runner logs start/outcome/traceback without replacing test behavior.

### Control

```sh
timeout --signal=INT --kill-after=10s 90s env -u DATABASE_URL -u TASK967_TEST_DATABASE_URL ../../../../.venv/bin/python ../../../../scripts/task974_step24_runner.py ../../../../task974-step26-Control.events.jsonl test_task974_import_isolation.py risk_validation/test_risk_validation.py research_lab/test_research_lab.py test_analysis_agents.py -q --tb=short --durations=20 --junitxml=../../../../task974-step26-Control.xml > ../../../../task974-step26-Control.log 2>&1
```

### A

```sh
timeout --signal=INT --kill-after=10s 90s env -u DATABASE_URL -u TASK967_TEST_DATABASE_URL ../../../../.venv/bin/python ../../../../scripts/task974_step24_runner.py ../../../../task974-step26-A.events.jsonl strategy_optimisation/test_strategy_optimisation.py test_morning_stale_reset.py test_task482_trades.py tests/test_replay_conservation.py -q --tb=short --durations=20 --junitxml=../../../../task974-step26-A.xml > ../../../../task974-step26-A.log 2>&1
```

### B

```sh
timeout --signal=INT --kill-after=10s 90s env -u DATABASE_URL -u TASK967_TEST_DATABASE_URL ../../../../.venv/bin/python ../../../../scripts/task974_step24_runner.py ../../../../task974-step26-B.events.jsonl test_ohlcv_cache.py test_phase22_final.py test_validation_certification.py tests/unit/test_custom_universe_store.py -q --tb=short --durations=20 --junitxml=../../../../task974-step26-B.xml > ../../../../task974-step26-B.log 2>&1
```

### C1

```sh
timeout --signal=INT --kill-after=10s 90s env -u DATABASE_URL -u TASK967_TEST_DATABASE_URL ../../../../.venv/bin/python ../../../../scripts/task974_step24_runner.py ../../../../task974-step26-C1.events.jsonl tests/test_adaptive_engine.py tests/test_invalidation_override.py -q --tb=short --durations=20 --junitxml=../../../../task974-step26-C1.xml > ../../../../task974-step26-C1.log 2>&1
```

### C2

```sh
timeout --signal=INT --kill-after=10s 90s env -u DATABASE_URL -u TASK967_TEST_DATABASE_URL ../../../../.venv/bin/python ../../../../scripts/task974_step24_runner.py ../../../../task974-step26-C2.events.jsonl tests/test_research_loader_v43.py tests/test_v43_entry_gates.py -q --tb=short --durations=20 --junitxml=../../../../task974-step26-C2.xml > ../../../../task974-step26-C2.log 2>&1
```

### D

```sh
timeout --signal=INT --kill-after=10s 90s env -u DATABASE_URL -u TASK967_TEST_DATABASE_URL ../../../../.venv/bin/python ../../../../scripts/task974_step24_runner.py ../../../../task974-step26-D.events.jsonl tests/unit/portfolio/test_exposure.py tests/unit/portfolio/test_freeze_patch_coverage.py tests/unit/portfolio/test_reconciliation.py tests/unit/test_paper_exploration.py tests/unit/test_phase26_live_monitor.py -q --tb=short --durations=20 --junitxml=../../../../task974-step26-D.xml > ../../../../task974-step26-D.log 2>&1
```

## Exact Step25 failures reconciled

JUnit identifiers below are preserved from Step25. All now pass, except the explicitly DB-required Phase22 case handled by Option A. The adaptive hard-risk case is replaced by the two documented policy-boundary cases above.

- `test_morning_stale_reset.TestReplayEngineExecutionLabel::test_paper_eligible_no_order_id_is_eligible`
- `test_ohlcv_cache::test_postmarket_job_appends_candle`
- `test_ohlcv_cache::test_premarket_readiness_ready`
- `test_ohlcv_cache::test_kite_ltp_overrides_price`
- `test_ohlcv_cache::test_missing_symbol_makes_refresh_partial`
- `test_ohlcv_cache::test_scan_count_api_has_correct_fields`
- `test_phase22_final::test_phase22_finalization`
- `test_validation_certification.TestPipelineValidation::test_conserved_pipeline_pass`
- `test_validation_certification.TestPipelineValidation::test_rejected_order_is_valid_terminal_outcome`
- `tests.unit.test_custom_universe_store.TestPhase0CSafetySuiteUnaffected::test_phase0c_safety_suite_passes`
- `tests.test_adaptive_engine::test_no_proposals_below_sample_minimum`
- `tests.test_adaptive_engine::test_proposals_created_with_sufficient_sample`
- `tests.test_adaptive_engine::test_positive_adjustment_cannot_create_buy`
- `tests.test_adaptive_engine::test_negative_adjustment_can_demote_buy`
- `tests.test_adaptive_engine::test_hard_risk_filter_never_overridden`
- `tests.test_research_loader_v43.TestV43MalformedPersistedSettings::test_fractional_conc_coerced_to_zero`
- `tests.test_research_loader_v43.TestV43MalformedPersistedSettings::test_non_numeric_conc_coerced_to_zero`
- `tests.test_research_loader_v43.TestV43MalformedPersistedSettings::test_out_of_range_conc_coerced_to_zero`
- `tests.test_v43_entry_gates.TestMaxConcurrentPositions::test_gate_absent_when_disabled`
- `tests.test_v43_entry_gates.TestMaxConcurrentPositions::test_reason_includes_counts`
- `tests.test_v43_entry_gates.TestMinLiquidity::test_fallback_to_avg_daily_volume`
- `tests.test_v43_entry_gates.TestMinLiquidity::test_fallback_to_volume`
- `tests.test_v43_entry_gates.TestMinLiquidity::test_gate_fails_when_volume_below_threshold`
- `tests.test_v43_entry_gates.TestMinLiquidity::test_gate_passes_when_exactly_at_threshold`
- `tests.test_v43_entry_gates.TestMinLiquidity::test_gate_passes_when_volume_above_threshold`
- `tests.test_v43_entry_gates.TestMinLiquidity::test_reason_shows_k_units`
- `tests.test_v43_entry_gates.TestMaxVolatility::test_derives_atr_pct_from_atr_abs`
- `tests.test_v43_entry_gates.TestMaxVolatility::test_derives_atr_pct_from_atr_abs_fail`
- `tests.test_v43_entry_gates.TestMaxVolatility::test_derives_from_atr_field_alias`
- `tests.test_v43_entry_gates.TestMaxVolatility::test_gate_fails_when_atr_above_max`
- `tests.test_v43_entry_gates.TestMaxVolatility::test_gate_passes_exactly_at_threshold`
- `tests.test_v43_entry_gates.TestMaxVolatility::test_gate_passes_when_atr_below_max`
- `tests.test_v43_entry_gates.TestMaxVolatility::test_reads_atr_percent_field`
- `tests.test_v43_entry_gates.TestMaxVolatility::test_reason_shows_pct_values`
- `tests.test_v43_entry_gates.TestGateResultReflectedInEligibility::test_max_concurrent_fail_marks_ineligible`
- `tests.test_v43_entry_gates.TestGateResultReflectedInEligibility::test_max_volatility_fail_marks_ineligible`
- `tests.test_v43_entry_gates.TestGateResultReflectedInEligibility::test_min_liquidity_fail_marks_ineligible`
- `tests.unit.test_phase26_live_monitor.TestConsistency::test_closing_prior_scan_trade_does_not_break_parity`
- `tests.unit.test_phase26_live_monitor.TestConsistency::test_two_legit_same_symbol_trades_are_not_duplicates`

## Exact changed files

Compared with remote review HEAD e26b4165e27777359106d304cc9b57a16287f6bb, the minimal accumulated test-fix commit includes:

- `artifacts/api-server/src/python/conftest.py`
- `artifacts/api-server/src/python/research_lab/test_research_lab.py`
- `artifacts/api-server/src/python/strategy_optimisation/test_strategy_optimisation.py`
- `artifacts/api-server/src/python/test_morning_stale_reset.py`
- `artifacts/api-server/src/python/test_ohlcv_cache.py`
- `artifacts/api-server/src/python/test_phase22_final.py`
- `artifacts/api-server/src/python/test_task974_import_isolation.py`
- `artifacts/api-server/src/python/test_validation_certification.py`
- `artifacts/api-server/src/python/tests/test_adaptive_engine.py`
- `artifacts/api-server/src/python/tests/test_invalidation_override.py`
- `artifacts/api-server/src/python/tests/test_replay_conservation.py`
- `artifacts/api-server/src/python/tests/test_research_loader_v43.py`
- `artifacts/api-server/src/python/tests/test_v43_entry_gates.py`
- `artifacts/api-server/src/python/tests/unit/test_paper_exploration.py`
- `artifacts/api-server/src/python/tests/unit/test_phase0c_safety_fixes.py`
- `artifacts/api-server/src/python/tests/unit/test_phase26_live_monitor.py`
- scripts/task969_ci_report.py: exact before/after test blob pins and this report's explicit path only.
- .github/workflows/task969-postgres16-validation.yml: downstream expensive gates additionally require Python gates to pass; upload this report.
- TASK974_STEP26_REMAINING_FAILURES_STATUS.md: this new evidence.

The conftest parent-package restoration and research os fix are preserved earlier Step22/23 changes; lifecycle/capital/exploration fixtures are the already-verified Step25 fixes. Step26 did not rewrite them. Existing runtime JSON changes, caches, unrelated local edits and historical evidence are excluded from the commit.

## Safety and release boundary

No Step26 production code change. No trading/risk/database/universe/provenance safety check weakened. No universe configuration, migration/schema, queue behavior or production data changes. No merge or deployment.

All focused historical failures are closed for the explicit DB-less test contract; durable integration awaits the one native CI run. Full-workflow PASS is not claimed here. Identity exceptions remain complete test-blob pins, not arbitrary application-file allowances. Git diff whitespace check passes.

## Single full validation

Pending exact commit/run identity. No automatic retry loop authorized.
