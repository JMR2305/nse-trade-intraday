---
name: Phase 27E/27F test conventions
description: How to run and write tests for the Operator Analytics (27E) and System Readiness (27F) pages.
---

# Phase 27E/27F test conventions

## Running frontend tests
Must supply both env vars or vitest fails to load vite.config.ts:
```
PORT=9999 BASE_PATH=/trading-dashboard/ pnpm --filter trading-dashboard exec vitest run <file>
```
Or use the package.json script: `pnpm --filter trading-dashboard test` (already sets both).

**Why:** vite.config.ts requires PORT and BASE_PATH at startup; they are not optional.

## Python check_* functions are pure
`phase27_readiness.py` check_* functions (check_market_data, check_broker, check_safety, etc.) take a pre-built `inputs` dict — they do no I/O themselves. Tests should inject via `_minimal_inputs(**overrides)` helper rather than patching modules.

Exception: `build_report()` with no args calls `collect_inputs()` which does real I/O — always pass `inputs=` explicitly in tests.

`get_history()` needs `phase20_store.kv_get` patched.

**Why:** Pure design makes tests fast (68 tests in 0.13s) and isolation-safe.

## 27E aggregator functions are also pure
`_aggregate_rejections`, `_decision_distribution`, `_risk_interventions`, `_funnel`, `_stage_timing` all take plain lists/dicts — no patching needed. Only `operator_analytics_report()` entry point needs `_replay`, `_sessions`, `_scan_events`, `_snapshot_rows` patched.

## Test counts (2026-08-15)
- `test_phase27e_operator_analytics.py`: 53 tests
- `test_phase27f_system_readiness.py`: 68 tests
- `OperatorAnalytics.test.tsx`: 15 tests
- `SystemReadiness.test.tsx`: 15 tests
