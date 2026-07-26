---
name: Phase 3 completion
description: Phase 3A–3G implementation — blocker fixes, dashboards, logging, validation; test isolation and validator pitfalls.
---

## Phase 3G validator patterns

- `phase3g_validate.py` must pass `extra_env={"PORT": "3199", "BASE_PATH": "/trading-dashboard"}` for the Vitest command; vite.config.ts throws if either is absent.
- Python test exit-code detection: trust `returncode == 0`. The `"FAIL" in out.upper()` pattern hits "0 failed" as a false positive — use `re.search(r"(\d+)\s+fail", out.lower())` and check captured count > 0.
- @ts-ignore grep needs `timeout=45` (not 10s); exclude `node_modules` from file list.
- Secret scan uses `-E` flag with `|` (not shell-escaped `\|`); always exclude `intraday-trading-bot/` and known broker API client files.

## test_phase20 date sensitivity

- Default `_trade()` fill_ts must stay within `max_holding_days` (default=10). If the fill_ts is exactly N days ago and the cutoff is `>= N`, TIME_EXIT fires for every test using the default trade. Keep default fill_ts to "yesterday" relative to any known test date.
- **Why:** Test written with a fixed date that was recent at time of writing; date advances, TIME_EXIT triggers in tests that don't intend it.
- **How to apply:** When fixing time-based test failures, update the default `_trade()` fill_ts to 1–2 days before the current session date.

## test_phase11 portfolio DB isolation

- `paper_trader.execute_buy()` reads from Postgres via `portfolio_store.load_state()`. Tests that `write_state()` to a JSON file do NOT affect what execute_buy sees. Use `unittest.mock.patch.object(pt._store, "load_state", return_value=clean_state)` and `patch.object(pt._store, "save_state", lambda s: None)` around execute_buy calls.
- `portfolio_store` has `load_state` and `save_state` but NOT `add_trade` — don't patch a non-existent attribute.
- **Why:** paper_trader migrated from file-based state to Postgres; old test helper pre-dates the migration.

## phase3f logging API

- `StructuredLogger.info(event_type: str, **extra)` — `event_type` is the first positional parameter. Never also pass `event_type=` as a kwarg or you get "multiple values" TypeError.
- Correct: `_log.info("order_submitted", symbol=sym, quantity=qty)`
- Wrong: `_log.info("order_submitted", event_type="order_submitted", symbol=sym)`

## Phase 19C freshness coverage

- Every page registered in `freshness-coverage.test.ts` must render `<DataFreshnessBar ... />` or contain the literal string "No live dataset used on this page". Add `import DataFreshnessBar from "@/components/DataFreshnessBar"` and `<DataFreshnessBar variant="scan" />` to any new page that uses live API data.
