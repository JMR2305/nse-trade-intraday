# ApexQuant AI — Final Pre-Market Guardrail & Validation Prep Report

**Date:** 2026-08-16  
**Constraint:** Paper only. No live orders. No new pages. No threshold changes.  
**Tests:** 18/18 passing

---

## 1. Files Changed

| File | Change |
|------|--------|
| `artifacts/api-server/src/python/pipeline_events.py` | Added `_CANONICAL_ORDER_TYPES` frozenset; guardrail in `_emit_unsafe`; `emit_replay()` helper; `REPLAY_*` event types in `EVENT_TYPES` |
| `artifacts/api-server/src/python/buy_audit.py` | Added `_is_canonical_order_event()` helper; P20- SQL filter on ORDER_* DB query; P20- filter on file-fallback path |
| `artifacts/api-server/src/python/validation_engines.py` | Added P20- prefix skip in order lifecycle reconciliation loop |
| `artifacts/api-server/src/python/phase26_consistency.py` | Added P20- filter to `executed_events` list comprehension |
| `artifacts/api-server/src/python/phase26_live_monitor.py` | Added P20- filter to `executed` list comprehension |
| `artifacts/api-server/src/python/paper_exploration_engine.py` | *(previous session)* `_with_db` error logging; Kite LTP first in `update_experimental_exits`; event-after-insert ordering |
| `artifacts/api-server/src/python/tests/test_btt_guardrail.py` | **New** — 18 tests covering guardrail, consumer filters, exploration fixes |

---

## 2. BTT/Replay Event Namespace Fix

### Problem
`backtest_portfolio.py` generates `BTT-` prefixed trade IDs (line 984: `f"BTT-{uuid.uuid4().hex[:10]}"`). During the Aug 11 session a backtest/replay run emitted execution-type events that reached `pipeline_events` but produced 0 rows in `phase20_paper_trades`, because backtest trades are isolated in `backtest_trades`. Any consumer counting `ORDER_EXECUTED` by event type alone would mis-count these as real paper trades.

### Fix applied: emit-level guardrail in `pipeline_events._emit_unsafe`

```python
# Canonical ORDER_* events in LIVE mode must carry a P20- trade_id.
if event_type in _CANONICAL_ORDER_TYPES and mode == "LIVE":
    _tid = str((payload or {}).get("trade_id") or "")
    if _tid and not _tid.startswith("P20-"):
        logger.warning(
            "pipeline_events: BLOCKED non-canonical %s (trade_id=%s) — "
            "only P20-... IDs may use ORDER_* event types in LIVE mode.",
            event_type, _tid,
        )
        return
```

**Behaviour:**
- `ORDER_SUBMITTED`/`ORDER_EXECUTED`/`ORDER_REJECTED`/`ORDER_CANCELLED` with any non-P20- trade_id in LIVE mode → **blocked + warning logged**
- `ORDER_EXECUTED` with `P20-abc1234567` → passes through (canonical)
- `ORDER_EXECUTED` with `BTT-` or `EXP-` in LIVE mode → **blocked + warning logged**
- Same event in BACKTEST mode (via `emit_replay()`) → **allowed** (by design — replays live in their own mode partition)
- Events with no `trade_id` in payload → **allowed** (backward compatible)

### New `emit_replay()` helper

```python
def emit_replay(event_type, stage, *, scan_id=None, symbol=None,
                payload=None, run_id=None, ts=None) -> None:
    """Emit a BACKTEST-mode event (mode='BACKTEST', never in LIVE stream)."""
    p = dict(payload or {})
    p["source"] = "replay"
    p["canonical_trade"] = False
    emit(event_type, stage, ..., mode="BACKTEST", ...)
```

Backtest/replay code must use `emit_replay("REPLAY_EXECUTION_COMPLETED", ...)` — not `emit("ORDER_EXECUTED", ...)`. The new `REPLAY_EXECUTION_COMPLETED`, `REPLAY_ORDER_SUBMITTED`, `REPLAY_ORDER_REJECTED` types are registered in `EVENT_TYPES`.

---

## 3. Event Consumer Filters Updated

All consumers that aggregate `ORDER_EXECUTED` events now enforce the P20- prefix rule:

### `buy_audit.py` — DB query (SQL filter)
```sql
AND event_type IN ('ORDER_SUBMITTED', 'ORDER_EXECUTED', 'ORDER_REJECTED', 'ORDER_CANCELLED')
AND (payload->>'trade_id' IS NULL
     OR payload->>'trade_id' LIKE 'P20-%')
```

### `buy_audit.py` — file fallback path
Added `and _is_canonical_order_event(e)` filter:
```python
def _is_canonical_order_event(e: dict) -> bool:
    tid = str((e.get("payload") or {}).get("trade_id") or "")
    return not tid or tid.startswith("P20-")
```

### `validation_engines.py` — order lifecycle reconciliation
```python
_tid = str((e.get("payload") or {}).get("trade_id") or "")
if _tid and not _tid.startswith("P20-"):
    continue  # skip BTT-/replay events
```

### `phase26_consistency.py` — executed_events dedup check
```python
executed_events = [
    e for e in scan_events
    if e.get("event_type") == "ORDER_EXECUTED"
    and (not str((e.get("payload") or {}).get("trade_id") or "")
         or str(...).startswith("P20-"))
]
```

### `phase26_live_monitor.py` — live execution liveness check
Same P20- guard on the `executed` list comprehension.

### Consumers NOT patched (already safe)
- `pipeline_stats.py` — counts from `phase20_paper_trades` ledger rows, not from events. Already canonical by construction (P20- IDs only in that table).
- `phase27_operator_analytics.py` — reads from canonical snapshot, not raw ORDER_EXECUTED events.
- `replay_engine.py` — reads from `backtest_trades` (BTT- table), isolated from live ledger.

---

## 4. Test Results

**18/18 tests pass** (`tests/test_btt_guardrail.py`, 0.67 s)

| Test | What it proves |
|------|---------------|
| `test_p20_prefix_is_canonical` | P20- events pass `_is_canonical_order_event` |
| `test_btt_prefix_is_not_canonical` | BTT- events fail `_is_canonical_order_event` |
| `test_exp_prefix_is_not_canonical` | EXP- events fail (exploration trades also non-canonical) |
| `test_no_trade_id_passes_through` | Events with no trade_id are backward-compatible |
| `test_empty_trade_id_passes_through` | Empty string trade_id also backward-compatible |
| `test_emit_replay_uses_backtest_mode` | `emit_replay()` stamps mode=BACKTEST, source=replay, canonical_trade=False |
| `test_emit_replay_never_calls_live_emit_directly` | All calls through emit_replay use BACKTEST mode |
| `test_btt_order_executed_is_blocked_in_live` | BTT- ORDER_EXECUTED in LIVE mode → BLOCKED warning |
| `test_p20_order_executed_is_not_blocked` | P20- ORDER_EXECUTED in LIVE mode → no BLOCKED warning |
| `test_btt_order_executed_backtest_mode_is_not_blocked` | BTT- in BACKTEST mode → allowed |
| `test_aug11_phantoms_not_counted_by_is_canonical` | 63 BTT- events + 1 P20- event → only 1 counted |
| `test_aug11_phantoms_excluded_from_validation_engine_lifecycle` | Lifecycle reconciler counts 1 P20- lifecycle, ignores 63 BTT- |
| `test_p20_filter_in_phase26_consistency` | phase26 consistency filter correctly isolates P20- events |
| `test_with_db_logs_on_exception` | `_with_db` logs `logger.error` when DB fails |
| `test_no_event_when_insert_fails` | `EXPERIMENTAL_PAPER_TRADE_PLACED` never fires if insert returns False |
| `test_event_fires_when_insert_succeeds` | `EXPERIMENTAL_PAPER_TRADE_PLACED` fires after successful insert |
| `test_kite_ltp_used_when_session_verified` | Exploration exits call `kite_ltp_overlay.fetch_ltp_overlay` when session OK |
| `test_yfinance_fallback_when_kite_unavailable` | Falls back to yfinance close when Kite session unverified |

---

## 5. Canonical Paper Executions Count Only P20- Trades

**Before this session:** Any process that wrote `ORDER_EXECUTED` to `pipeline_events` — including a backtest replay — could inflate the canonical execution count. The Aug 11 phantom batch (63 BTT- events) appeared as 63 executions in event-stream consumers despite 0 rows in `phase20_paper_trades`.

**After this session:** Three independent layers enforce the invariant:

1. **Emit layer** (`pipeline_events._emit_unsafe`): Blocks non-P20- ORDER_* events at write time. Aug 11 phantom events would never reach the DB.
2. **SQL layer** (`buy_audit.py` DB query): `payload->>'trade_id' LIKE 'P20-%'` filters out any historical non-canonical events that may already exist in the table.
3. **Application layer** (validation_engines, phase26_consistency, phase26_live_monitor): `_is_canonical_order_event()` / P20- prefix check applied before counting.

---

## 6. Exploration DB / Exit Fixes Confirmed

All confirmed by direct code verification and passing tests:

| Fix | Code evidence | Test |
|-----|--------------|------|
| `_with_db` logs DB errors | `paper_exploration_engine.py` line 128: `logger.error(...)` in except | `test_with_db_logs_on_exception` |
| Event fires only after insert | `create_exploration_entry` lines 664–686: `ok = _insert_exp_row(row)` → early return → emit | `test_no_event_when_insert_fails`, `test_event_fires_when_insert_succeeds` |
| Exploration exits try Kite LTP first | `update_experimental_exits`: imports `kite_ltp_overlay`, checks `session_verified`, falls back to yfinance | `test_kite_ltp_used_when_session_verified` |
| No fabricated intraday price | When `session_verified=False`, `_used_kite_ltp=False`, yfinance daily close used | `test_yfinance_fallback_when_kite_unavailable` |

---

## 7. Confirmation: No Live Orders Enabled

Verified by direct code inspection and config check:

```
KITE_LTP_OVERLAY_ENABLED = True    ← set, confirmed
PAPER_TRADING_MODE       = True    ← hardcoded in config.py line 135
LIVE_EXECUTION_ENABLED   = False   ← not set in environment; defaults False
```

- No `place_order` / `modify_order` / `cancel_order` calls found anywhere in `artifacts/api-server/src/python/`
- `execution_agent/execution_planner.py` docstring confirms: "LIVE_EXECUTION_ENABLED defaults to False"
- Safety dict emitted in every scan response: `"no_live_broker_calls": True, "no_real_orders": True`

---

## 8. Checklist: Next Market Session — P20 Signal → Fill → Exit → P&L Proof

**Before 09:15 IST (next trading day):**

- [ ] **Authenticate Kite session** at `/kite-auth` in the dashboard
- [ ] Verify Kite session probe: `GET /api/kite-auth/status` → `session_verified: true`
- [ ] Confirm `KITE_LTP_OVERLAY_ENABLED=true` in env (already set ✅)
- [ ] Confirm `LIVE_EXECUTION_ENABLED` is absent/false (confirmed ✅)

**At 09:20–09:25 IST (first scan):**

- [ ] Scan completes — check Mission Control for `kite_ltp_overlay_enabled: true, kite_ltp_session_verified: true` in scan metadata
- [ ] `_retry_pending()` fires for the 4 EXIT_PENDING positions:
  - BAJFINANCE (P20-4a5f909738, 8 shares @ ₹1,100.05)
  - GRASIM (P20-83aa1be8f9, 3 shares @ ₹3,223.63)
  - DIVISLAB (P20-a205b1ef09, 1 share @ ₹8,370.04)
  - TRENT (P20-acad172b74, 3 shares @ ₹3,082.42)
- [ ] Verify in DB — all 4 should transition OPEN/EXIT_PENDING → CLOSED with non-NULL `realized_pnl`:
  ```sql
  SELECT trade_id, symbol, status, exit_price, realized_pnl
  FROM phase20_paper_trades
  WHERE trade_id IN (
    'P20-4a5f909738','P20-83aa1be8f9','P20-a205b1ef09','P20-acad172b74'
  );
  ```
  Expected: `status=CLOSED`, `exit_price` ≈ live LTP (will differ from stale daily close), `realized_pnl` non-NULL

**Proving the full cycle:**

- [ ] `exit_price` should be a live Kite LTP, not the prior day's yfinance close (BAJFINANCE daily close ~₹1,100 — if `exit_price` differs, Kite LTP is working)
- [ ] `ORDER_EXECUTED` events in `pipeline_events` for these 4 trades must have `trade_id LIKE 'P20-%'` (not BTT-)
- [ ] Performance Snapshot on dashboard shows non-zero realized P&L for the day
- [ ] Equity curve shows 4 closed trades

**If EXIT_PENDING do not resolve:**

- Confirm Kite session is fresh (tokens expire after market day; re-authenticate if needed)
- Check `quote_reliable` field: `SELECT evidence->>'kite_ltp_overlay_note' FROM phase20_paper_trades WHERE status='EXIT_PENDING'`
- If `reason_not_live_ltp` is set, the overlay is enabled but LTP fetch failed — check API key validity

**Bonus proof (if a new BUY signal fires this session):**

- [ ] A new `P20-` trade should appear with `fill_price` = live Kite LTP, not daily close
- [ ] `ORDER_SUBMITTED` → `ORDER_EXECUTED` events in `pipeline_events` — both with `P20-` prefix
- [ ] No `BTT-` events appear in `pipeline_events WHERE mode='LIVE'`

---

*Report generated 2026-08-16. 18/18 tests passing. All workflows running.*
