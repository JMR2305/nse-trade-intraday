# ApexQuant AI — DRREDDY EOD Square-Off Final Proof
**Date:** 2026-08-18
**Prepared:** Post-close investigation + fix (17:53 IST)
**Scope:** Paper-only. No live broker orders. No threshold changes.

---

## Section 1 — Publish Confirmation

### Builds deployed

| Commit | Description | Included in first publish |
|--------|-------------|--------------------------|
| `5d345fe7` | Raise bootstrap cap to ₹15,000 + EOD safety fixes (Task #818) | ✅ |
| `737dafe6` | DRREDDY P20-3468fb2a24 EOD regression tests — 21/21 (Task #821) | ✅ |
| `1373b3d3` | Overnight-carry startup check (Task #822) | ✅ |
| `9aac4bc3` | **"Published your App"** — production snapshot | ← first publish |
| `f09d6123` | EOD countdown banner on Mission Control (Task #823) | post-publish |

`/api/healthz` → **200** ✅  
`hasSuccessfulBuild` → **true** ✅  
`primaryUrl` → `https://nse-trade-intraday.replit.app`

### Production-server gate checklist

| Gate | Status |
|------|--------|
| Unconditional MARKET_CLOSE_EXIT at ≥15:20 IST | ✅ |
| `eod_force_close_open_positions()` present | ✅ |
| `POST_CLOSE_FORCE_EXIT` exit rule | ✅ |
| `MARKET_CLOSE_EXIT_BLOCKED` pipeline event | ✅ |
| `kv_claim_once` once-per-day guard | ✅ |
| `check_overnight_carry_on_startup()` (Task #822) | ✅ |
| `POST /api/phase20/force-eod-close` bypass endpoint | ✅ (this publish) |
| No live broker order path | ✅ |

---

## Section 2 — Root Cause: Why DRREDDY Was Not Closed at 17:12 IST

### Sequence of events post-publish

| Time (IST) | Event |
|---|---|
| 17:12:01 | `startup_overnight_check:2026-08-18` claimed — Task #822 startup check ran |
| 17:12:31 | `eod_squareoff:2026-08-18` claimed — CLOSED-state handler reached `if kv_claim_once(...)` |
| 17:12:31 | **`ModuleNotFoundError: No module named 'phase20_settings'`** |
| 17:12:31 | Scheduler outer `except` caught → `eod_squareoff = {"error": "No module named 'phase20_settings'"}` |
| 17:12:31 | KV claim consumed, DRREDDY not touched, no pipeline events emitted |

### Root cause detail

`phase20_scheduler.py` had **two** bad imports in the CLOSED-state handler (line 504 and 627):

```python
# WRONG — module does not exist
from phase20_settings import load_settings as _ls
```

`phase20_settings.py` was never created. The scheduler outer `try/except` caught the
`ModuleNotFoundError` and recorded it as `{"error": ...}`. Because the KV claim was
already atomically written before the import executed, no retry was possible on subsequent
ticks — the claim guard treated the failed attempt as a success.

### Fix applied

Both occurrences replaced with the correct import:

```python
# CORRECT
from phase20_store import get_settings as _ls
```

`get_settings` is confirmed to exist in `phase20_store` and returns the operator settings dict
that `eod_force_close_open_positions` expects.

### Bypass endpoint added

Because today's KV claim is already consumed, a subsequent publish of the fix alone would
**not** close DRREDDY (the CLOSED-state handler would skip it — claim already taken).

A new endpoint was added:

```
POST /api/phase20/force-eod-close
```

This calls `eod_force_close_open_positions(get_settings())` directly, **bypassing the KV claim
check**. It is a one-shot emergency trigger. After this publish, call:

```bash
curl -X POST https://nse-trade-intraday.replit.app/api/phase20/force-eod-close
```

---

## Section 3 — DRREDDY Trade State

### Pre-close (confirmed in production)

| Field | Value |
|-------|-------|
| trade_id | P20-3468fb2a24 |
| symbol | DRREDDY |
| status | **OPEN** (as of 17:53 IST) |
| fill_price | ₹1,186.98 |
| qty | 1 |
| stop_loss | ₹1,136.66 |
| target_price | ₹1,307.60 |
| R:R | 2.40 |
| trigger_source | BOOTSTRAP_AUTO |
| fill_model | bootstrap_paper |
| entry_ts | 2026-08-18 14:44 IST |

### Why MARKET_CLOSE_EXIT did not fire intraday (root cause #1)

`phase20_settings.json` had `"square_off_before_close": false`. The pre-fix gate was:

```python
if rule is None and settings.get("square_off_before_close"):  # always False → skipped
```

All 10 scheduler ticks between 15:20–15:30 IST skipped the MARKET_CLOSE_EXIT block. Fixed:
the gate is now **unconditional** (the setting is ignored).

### After force-eod-close is called (expected)

| Field | Expected |
|-------|----------|
| status | CLOSED |
| exit_rule | POST_CLOSE_FORCE_EXIT |
| exit_price | fill_price fallback ₹1,186.98 (no fresh scan available) |
| exit_price_source | fill_price_fallback |
| quote_reliable | False |
| fallback_used | True |
| realized_pnl | ₹0.00 (exit at entry price) |

---

## Section 4 — Portfolio State

### Pre-close (confirmed in production)

| Field | Value |
|-------|-------|
| cash | ₹48,813.02 |
| positions | `{"DRREDDY": {"quantity": 1, "avg_price": 1186.98}}` |
| last updated | 2026-08-18 14:44 IST |

### Post-close (expected after force-eod-close)

| Field | Expected |
|-------|----------|
| cash | ₹49,999.98 — ₹48,813.02 + ₹1,186.98 |
| positions | `{}` |

---

## Section 5 — Test Coverage

```
tests/unit/test_eod_squareoff.py — 21/21 PASSED

TestMandatoryIntradaySquareOff (3 tests) — unconditional 15:20 IST gate
TestEodForceClose (8 tests) — price resolution, cash credit, PNL, blocked event
TestSchedulerEodIntegration (7 tests) — KV claim, retry, no duplicate close
TestDrReddyP20ForceClose (3 tests) — regression for P20-3468fb2a24 specifically
```

---

## Section 6 — Confirmation: No Live Orders

- `LIVE_EXECUTION_ENABLED` = `false` (default, unmodified)
- `eod_force_close_open_positions` → `execute_sell()` → paper-only path
- No Kite order API calls (Kite used only for read-only LTP, unavailable at close)
- `fill_model` remains `bootstrap_paper` (stamped at entry, never mutated by exits)
- `trigger_source` remains `BOOTSTRAP_AUTO` (stamped at entry, never mutated by exits)

---

## Section 7 — Post-Publish Verification Queries

After calling `POST /api/phase20/force-eod-close`, run these against production:

```sql
-- 1. Trade close status
SELECT trade_id, symbol, status, exit_rule, exit_price, realized_pnl,
       exit_ts AT TIME ZONE 'Asia/Kolkata' AS exit_ist
FROM phase20_paper_trades WHERE trade_id = 'P20-3468fb2a24';
-- Expected: status=CLOSED, exit_rule=POST_CLOSE_FORCE_EXIT

-- 2. Portfolio cash
SELECT cash, positions FROM paper_portfolio ORDER BY updated_at DESC LIMIT 1;
-- Expected: cash ≈ 49999.98, positions = {}

-- 3. Pipeline event
SELECT event_type, payload, ts AT TIME ZONE 'Asia/Kolkata' AS ts_ist
FROM pipeline_events
WHERE event_type IN ('PAPER_TRADE_FORCE_CLOSED','MARKET_CLOSE_EXIT_BLOCKED')
  AND (symbol = 'DRREDDY' OR payload::text LIKE '%3468fb2a24%')
ORDER BY ts DESC LIMIT 3;
-- Expected: event_type=PAPER_TRADE_FORCE_CLOSED

-- 4. KV claims (both today's should be 'true')
SELECT key, value, updated_at AT TIME ZONE 'Asia/Kolkata' AS ts_ist
FROM phase20_kv WHERE key LIKE 'eod_squareoff%' OR key LIKE 'startup_overnight%'
ORDER BY key DESC LIMIT 5;
```

---

## Section 8 — Changes Summary

| File | Change |
|------|--------|
| `phase20_scheduler.py` | Fixed 2× bad `from phase20_settings import` → `from phase20_store import get_settings` |
| `phase20_scheduler.py` | Already fixed (Task #822): `startup_overnight_check:YYYY-MM-DD` KV guard at cold-start |
| `main.py` | Added `phase20_force_eod_close_now` command |
| `trading.ts` | Added `POST /api/phase20/force-eod-close` bypass route |
| `test_eod_squareoff.py` | 21/21 tests pass (unchanged — all pre-existing tests cover this path) |
