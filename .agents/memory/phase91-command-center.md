---
name: Phase 9.1 Unified Command Centre
description: Architecture decisions, snapshot interfaces, and timing notes for the Phase 9.1 Command Centre.
---

## Rule
Command Centre is STRICTLY READ-ONLY / ADVISORY-ONLY. All data comes from upstream `get_*_snapshot()` calls — zero new calculations.

## Feature flag
`COMMAND_CENTER_ENABLED=true` (set as shared env var).

## Response timing
`/api/command-center/summary` takes ~6s because `_load_market_overview()` → `get_overview()` does yfinance multi-TF lookups (same as Phase 7.1 overview). This is expected — no fix needed unless the user complains about speed.

## Platform score formula
`obs×0.20 + ops×0.20 + dq×0.20 + sec×0.15 + perf×0.15 + deploy×0.10`
All inputs are existing snapshot scores — verified by tests.

## Stable downstream interface
`from command_center.shared_services import get_command_center_snapshot` → flat dict with `platform_score`, `platform_grade`, `platform_status`.

## Nav position
"Command Centre" is the FIRST item in the Operations nav group (above Executive Dashboard).

## Tests
81/81 pass. All responses validated for `advisory_only: true` and `read_only: true` by AST-level test.

**Why:** Advisory-only enforcement is tested at the AST level (no DELETE/INSERT/DROP in source) to catch accidental mutations even if new code is added to shared_services.py later.
