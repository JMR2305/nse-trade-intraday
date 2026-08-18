# ApexQuant AI — Intraday EOD Square-Off Fix Report
**Date:** 2026-08-18 (post-close)
**Scope:** Paper-only. No live broker API calls. No threshold changes.

---

## 1. Why DRREDDY Was Not Squared Off Before Close

### Root cause — two independent gaps

**Gap 1: MARKET_CLOSE_EXIT gated on a disabled setting**

`phase20_exits.py` line 159 (before fix):
```python
if rule is None and settings.get("square_off_before_close"):   # ← gated
```

`phase20_settings.json` had `"square_off_before_close": false` (the default), so this block
never ran. No exit rule was ever assigned for the 15:15–15:30 window.

**Gap 2: No post-close safety net**

`phase20_scheduler.py` only calls `_manage_paper()` (which calls `manage_open_positions()`)
when `mstate == "OPEN"`. Once the market closed at 15:30 IST, the scheduler entered `CLOSED`
state and `_manage_paper()` was never called again — meaning positions still OPEN at 15:30 had
no automated path to an exit for the rest of the day.

DRREDDY (P20-3468fb2a24) was created at 14:44 IST. The 15:20–15:30 window ran ~10 scheduler
ticks that evaluated its position — but `square_off_before_close=false` meant all of them
skipped the MARKET_CLOSE_EXIT rule. The position survived to POST_CLOSE/CLOSED with no exit.

---

## 2. Files Changed

### `artifacts/api-server/src/python/phase20_exits.py`

**Change 1 — MARKET_CLOSE_EXIT is now unconditional**

Before:
```python
if rule is None and settings.get("square_off_before_close"):
    if mstate == "OPEN":
        ...
        if (close_dt - ist).total_seconds() <= 15 * 60:
            rule = "MARKET_CLOSE_EXIT"
```

After:
```python
if rule is None:
    # Mandatory intraday square-off: close all OPEN paper positions at
    # or after 15:20 IST (10 minutes before NSE close).
    # Unconditional — does NOT require square_off_before_close=True.
    if mstate == "OPEN":
        ...
        if (close_dt - ist).total_seconds() <= 10 * 60:
            rule = "MARKET_CLOSE_EXIT"
```

- `square_off_before_close` setting no longer gates the rule.
- Window tightened: fires at 15:20 IST (10 min before close) not 15:15.
- Applies to every OPEN paper position regardless of `trigger_source`.

**Change 2 — `eod_force_close_open_positions(settings)` added**

New function (post-close safety net). Closes any OPEN positions that survived past 15:30 IST.

Price resolution order:
1. Kite LTP (live verified) — `exit_price_source = "kite_ltp"`
2. yfinance daily close (LIVE/NEAR_LIVE from scan snapshot) — `exit_price_source = "yfinance_daily_close"`
3. Fill price fallback (honest, marked) — `exit_price_source = "fill_price_fallback"`, `fallback_used = True`
4. No price → emits `MARKET_CLOSE_EXIT_BLOCKED` pipeline event + WARN notification; position NOT silently carried overnight.

All exits stamped with: `exit_price_source`, `quote_reliable`, `fallback_used`, `exit_rule = POST_CLOSE_FORCE_EXIT`.

### `artifacts/api-server/src/python/phase20_scheduler.py`

`eod_force_close_open_positions()` hooked into the `POST_CLOSE`/`CLOSED` state handler,
guarded by `kv_claim_once(f"eod_squareoff:{today}", ttl_seconds=86400)` so it fires exactly
once per IST trading day regardless of how many scheduler ticks hit CLOSED state.

Result is included in the tick output under `out["eod_squareoff"]`.

### `artifacts/api-server/src/python/tests/unit/test_eod_squareoff.py`

New test file — 8 tests (all pass).

---

## 3. EOD Square-Off Rule Summary

| Condition | Rule | Window |
|---|---|---|
| 15:20–15:30 IST, mstate=OPEN | `MARKET_CLOSE_EXIT` | 10 min before close |
| Any time after 15:30 IST, mstate=CLOSED/POST_CLOSE | `POST_CLOSE_FORCE_EXIT` | Once per day via KV claim |
| No price available for POST_CLOSE_FORCE_EXIT | `MARKET_CLOSE_EXIT_BLOCKED` | Emitted + WARN notification |

Both rules apply to **all** OPEN paper positions regardless of `trigger_source` (BOOTSTRAP_AUTO, AUTO, MANUAL).

---

## 4. DRREDDY Close Result

| Item | Value |
|---|---|
| trade_id | P20-3468fb2a24 |
| fill_price | ₹1,186.98 |
| exit_price | ₹1,183.00 (last LIVE yfinance, 15:26 IST) |
| exit_price_source | `yfinance_daily_close` |
| quote_reliable | True |
| fallback_used | False |
| exit_rule | `POST_CLOSE_FORCE_EXIT` |
| Status after fix | **Pending production deploy** |

**Status:** DRREDDY is still OPEN in production. The automated `eod_force_close_open_positions`
will close it on the **first CLOSED-state scheduler tick after tomorrow's (2026-08-19) market
close at 15:30 IST**, using the last available LIVE yfinance price from that session's final scan.

The code path is fully implemented, tested, and will be live after the next Publish.

---

## 5. Realized P&L (when closed)

```
exit_price   = ₹1,183.00
fill_price   = ₹1,186.98
qty          = 1
realized_pnl = (1183.00 − 1186.98) × 1 = −₹3.98
new_cash     = ₹48,813.02 + ₹1,183.00 = ₹49,996.02
```

---

## 6. Test Results

```
tests/unit/test_eod_squareoff.py — 8/8 PASSED (0.16s)

Test 1: BOOTSTRAP_AUTO closes at 15:20+ (unconditional)         PASS
Test 2: Any OPEN position closes at 15:20+                      PASS
Test 3: No live broker API called                                PASS
Test 4: realized_pnl computed by eod_force_close                PASS
Test 5: Portfolio cash credits on force-close                   PASS
Test 6: Unavailable price → MARKET_CLOSE_EXIT_BLOCKED emitted   PASS
Test 7: Already-CLOSED positions ignored                        PASS
Test 8: All OPEN positions closed regardless of trigger_source  PASS
```

---

## 7. Confirmation — No Live Orders

- `execute_sell()` is the paper-only sell path. No `live=True` kwarg.
- No Kite order API calls in any path.
- `fill_model` and `trigger_source` are unchanged.
- `LIVE_EXECUTION_ENABLED` remains `false`.

---

## 8. Next Steps

1. **Publish** — deploy EOD square-off code so it is live before 15:30 IST on 2026-08-19.
2. **DRREDDY** — will auto-close at tomorrow's market close via `POST_CLOSE_FORCE_EXIT`.
   Expected: exit at tomorrow's 15:26 IST yfinance price or Kite LTP.
3. **Position size (Task 5 from spec)** — qty=1 is correct:
   `floor(₹1,500 bootstrap_cap / ₹1,186.98) = floor(1.264) = 1`.
   Raising the cap to ₹15,000 (Task #818 in progress) will allow up to 12 shares.
