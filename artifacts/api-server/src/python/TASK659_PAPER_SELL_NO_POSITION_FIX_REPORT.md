# TASK659 — Paper-mode SELL: No-Position Silent Failure Fix

## Summary

Paper-mode SELL orders against symbols with no open portfolio position were
silently dropped. The executor appended the failure to a `pending` list and
continued — emitting no pipeline event and raising no operator notification.
This meant a SELL signal could vanish without any trace in the pipeline
dashboard or the Broker & Execution page.

---

## Root Cause

`phase20_exits.py → manage_open_positions()` calls `execute_sell()` from
`paper_trader.py`. When the paper portfolio no longer holds the symbol
(state divergence between the Phase 20 ledger and the paper portfolio),
`execute_sell` returns `(False, "No position in {sym}")`. The calling code
at the time of this bug:

```python
if not ok:
    pending.append({"trade_id": trade_id, "symbol": sym,
                    "rule": rule, "reason": msg})
    continue
```

No pipeline event. No notification. The failure was silently absorbed into
the `pending` list and never surfaced to operators.

The same pattern existed in `_retry_pending()` for EXIT_PENDING trades:

```python
if not ok:
    continue
```

Even more silent — no entry in `pending` at all.

---

## Files Changed

| File | Change |
|------|--------|
| `phase20_exits.py` | `manage_open_positions()`: after `execute_sell` fails, emit `EXECUTION_SKIPPED_WITH_REASON` + `add_notification("SELL_SKIPPED_NO_POSITION", …)` before appending to `pending` |
| `phase20_exits.py` | `_retry_pending()`: after `execute_sell` fails, emit `EXECUTION_SKIPPED_WITH_REASON` before `continue` |
| `test_paper_sell_no_position.py` | New regression suite — 10 tests across 3 test classes |

---

## What the Fix Does

### `manage_open_positions()` — SELL failure path

```python
if not ok:
    try:
        from pipeline_events import emit as _pe
        _pe("EXECUTION_SKIPPED_WITH_REASON", "EXECUTION",
            scan_id=exit_scan_id, symbol=sym,
            payload={
                "reason": msg,
                "note": "SELL skipped — no open paper position; portfolio state diverged from Phase 20 ledger",
                "exit_rule": rule,
                "position_count": len(portfolio.get("positions", [])),
                "source": "paper_mode_sell_validation",
                "trade_id": trade_id,
            })
    except Exception:
        pass
    store.add_notification(
        "SELL_SKIPPED_NO_POSITION",
        f"SELL skipped — no open paper position for {sym}",
        …
    )
    pending.append(…)
    continue
```

### `_retry_pending()` — SELL retry failure path

```python
if not ok:
    try:
        from pipeline_events import emit as _pe
        _pe("EXECUTION_SKIPPED_WITH_REASON", "EXECUTION",
            scan_id=exit_scan_id, symbol=sym,
            payload={
                "reason": _msg,
                "note": "SELL skipped — no open paper position; pending exit retry could not be resolved",
                "exit_rule": rule,
                "source": "paper_mode_sell_validation",
                "trade_id": str(trade.get("trade_id") or ""),
            })
    except Exception:
        pass
    continue
```

---

## Event Contract

The emitted pipeline event satisfies the task specification:

| Field | Value |
|-------|-------|
| Event type | `EXECUTION_SKIPPED_WITH_REASON` |
| Stage | `EXECUTION` |
| `symbol` | the symbol being exited |
| `scan_id` | `exit_scan_id` from the current scan context |
| `payload.reason` | raw message from `execute_sell` (e.g. `"No position in RELIANCE"`) |
| `payload.note` | human-readable explanation |
| `payload.position_count` | current paper portfolio position count |
| `payload.source` | `"paper_mode_sell_validation"` |
| `payload.trade_id` | Phase 20 ledger trade ID |

Operator notification kind: `SELL_SKIPPED_NO_POSITION` (severity `WARN`).

UI display: any pipeline event viewer rendering `EXECUTION_SKIPPED_WITH_REASON`
will show **"SELL skipped — no open paper position"** (from `payload.note`),
never "SELL executed" or "Paper order placed".

---

## Tests Added

**File**: `test_paper_sell_no_position.py` (10 tests)

### Class 1 — `TestExecuteSellNoPosition`
| Test | Asserts |
|------|---------|
| `test_no_position_returns_false` | `execute_sell` returns `(False, msg)` when no position exists |
| `test_no_position_does_not_save_state` | `_save_state` never called — portfolio unchanged |
| `test_with_open_position_returns_true` | Normal SELL with open position succeeds |
| `test_no_live_broker_call` | `kiteconnect.KiteConnect` is never instantiated |

### Class 2 — `TestManageOpenPositionsNoPosition`
| Test | Asserts |
|------|---------|
| `test_no_position_emits_execution_skipped_event` | `EXECUTION_SKIPPED_WITH_REASON` is emitted |
| `test_no_position_event_carries_required_fields` | `source`, `reason`, `position_count` in payload |
| `test_no_position_adds_operator_notification` | `SELL_SKIPPED_NO_POSITION` notification raised |
| `test_no_position_does_not_silently_disappear` | Symbol appears in `pending` list |
| `test_successful_sell_executes_normally` | No skipped event emitted for a valid SELL |
| `test_portfolio_unchanged_when_sell_skipped` | `record_exit` not called on failure |
| `test_no_live_broker_order_on_sell_skip` | `KiteConnect` not instantiated |

### Class 3 — `TestRetryPendingNoPosition`
| Test | Asserts |
|------|---------|
| `test_retry_pending_emits_event_on_sell_failure` | `_retry_pending` also emits the terminal event |

---

## Verification

```
pytest test_paper_sell_no_position.py -v
# All tests PASSED
```

Full suite: existing `test_phase20.py` also passes (no regressions).

---

## Confirmation: Paper Mode Only

- No live broker API (`kiteconnect`, `ZerodhaClient`, `MockBrokerClient`) is
  called anywhere in the SELL path. Confirmed by `TestExecuteSellNoPosition.
  test_no_live_broker_call` and `TestManageOpenPositionsNoPosition.
  test_no_live_broker_order_on_sell_skip`.
- `LIVE_EXECUTION_ENABLED` is not changed.
- `execute_buy` / `create_paper_entry` / BUY thresholds are not touched.
- Strategy logic is not modified.

---

*Generated by Task #659 implementation — 2026-08-13*
