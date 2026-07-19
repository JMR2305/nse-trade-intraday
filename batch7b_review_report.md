# Batch 7B Execution Package — Review Report

**Package:** `batch7b_execution_package`
**Reviewed against:** Batch 7A (original, unmerged)
**Date:** 2026-07-19

---

## 1. Overall Score: 7 / 10

## 2. Verdict: SAFE AFTER MINOR FIXES

All 10 test failures are test bugs, not implementation bugs.
The implementation logic is sound.
Three fixes are required before merge.

---

## 3. Test Results

```
python -m compileall src/execution   →  OK (no errors)
pytest tests/unit/execution -q       →  140 collected, 130 passed, 10 failed
```

| File | Collected | Passed | Failed |
|---|---|---|---|
| test_policies.py | 17 | 17 | 0 |
| test_contracts.py | 32 | 32 | 0 |
| test_state_machine.py | 51 | 51 | 0 |
| test_matching.py | 25 | 17 | 8 |
| test_engine.py | 15 | 13 | 2 |

**Note:** Kimi's claim of "153 tests, 130 passing" is wrong on count (actual: 140).
Root cause assessment is correct — all 10 failures are test-helper defects, not
implementation defects.

---

## 4. Every Failure — Root Cause

### test_matching.py — 8 failures (all test bugs)

| # | Test | Line | Error | Root Cause |
|---|---|---|---|---|
| 1 | test_market_buy_uses_ask | 68 | `AttributeError: module 'src' has no attribute 'ExecutionOrderStatus'` | `__import__("src.execution.contracts").ExecutionOrderStatus` returns the top-level `src` module, not the submodule. Must be a standard `from src.execution.contracts import ExecutionOrderStatus` |
| 2 | test_market_buy_fallback_to_ltp | 76 | Same | Same |
| 3 | test_market_sell_uses_bid | 84 | Same | Same |
| 4 | test_market_sell_fallback_to_ltp | 92 | Same | Same |
| 5 | test_limit_price_protection_after_slippage | 147 | `TypeError: _make_snapshot() got unexpected keyword 'tick_size'` | `_make_snapshot()` helper omits `tick_size` parameter |
| 6 | TestStopMarketOrders.test_triggered_sticky | 207 | `TypeError: _make_snapshot() got unexpected keyword 'event_id'` | `_make_snapshot()` helper omits `event_id` parameter |
| 7 | TestStopLimitOrders.test_triggered_sticky | 279 | Same | Same |
| 8 | TestPartialFills.test_multiple_partial_fills | 311 | Same | Same |

### test_engine.py — 2 failures (both test bugs)

| # | Test | Line | Error | Root Cause |
|---|---|---|---|---|
| 9 | TestIdempotency.test_deterministic_fill_id | 243 | `IndexError: list index out of range` | After `engine.reset()`, the `OrderStateMachine` still holds the order in FILLED state. `activate_order()` is a no-op; second `on_market_data` finds no executable orders. Test needs a fresh `OrderStateMachine` + `MatchingEngine` for replay |
| 10 | TestReplay.test_no_wall_clock_dependency | 378 | `TypeError: _make_snapshot() got unexpected keyword 'timestamp'` | `_make_snapshot()` helper hard-codes timestamp; `timestamp=` kwarg must be added |

---

## 5. Blockers

### B1 — Idempotency key recorded before transition outcome (carried from 7A, still unresolved)

**File:** `src/execution/state_machine.py`

`state_machine.py` is byte-identical to the 7A original. The B1 bug from the 7A review
was not fixed. The dedup key is recorded before the transition graph check; a failed
transition permanently marks the action as "seen", causing subsequent retries to raise
`IdempotencyViolation` instead of `InvalidStateTransition`.

**Fix:** Move `state._seen_transitions.add(dedup_key)` to after step 6 (post state-change).

---

### B2 — FillEvent._gross_value_matches validator is inert

**File:** `src/execution/fills.py` lines 57–63

```python
@field_validator("gross_value")
@classmethod
def _gross_value_matches(cls, v: Decimal, info) -> Decimal:
    # gross_value should equal quantity * price
    # We can't easily access sibling fields in v2 ...
    return v  # ← does nothing
```

The comment is incorrect. Pydantic v2 `model_validator(mode='after')` can access all
fields. As written, `gross_value` is never validated against `quantity * price`.
A caller can construct a `FillEvent` with `gross_value=Decimal("0")` and it is
silently accepted.

**Fix:** Replace with a `model_validator(mode='after')` that asserts
`self.gross_value == Decimal(self.quantity) * self.price`.

---

## 6. Warnings

### W1 — import hashlib inside function body
**File:** `src/execution/fills.py` line 104
`import hashlib` is inside `FillEventBuilder.build()`. Move to top-level.

### W2 — fill_id type mismatch with Batch 7A FillRecord
`FillEvent.fill_id` is `str` (hex string); `FillRecord.fill_id` is `UUID`.
Deliberate but divergent. Future adapter code must be aware.

### W3 — MarketSnapshot.event_id defaults to empty string
In `_evaluate_order`, dedup key is `(order_id, snapshot.event_id or str(snapshot.timestamp))`.
Two distinct events with the same millisecond timestamp and `event_id=""` would be
incorrectly deduplicated. Callers must always set `event_id`.

### W4 — Engine accesses self._state_machine._orders directly
`_executable_orders_for_instrument()` iterates the private `_orders` dict. Safe under
asyncio's cooperative scheduler (no await inside loop) but breaks encapsulation and
is fragile against future state-machine refactoring.

### W5 — FixedTicksSlippagePolicy skips explicit tick rounding
`BasisPointsSlippagePolicy` rounds to tick; `FixedTicksSlippagePolicy` does not.
Correct only when input price is tick-aligned; fragile otherwise.

### W6 — No engine-level test for STOP_LIMIT "trigger then wait then fill"
STOP_LIMIT may trigger without immediately filling (tested in `test_matching.py`),
but there is no engine-level test proving the order remains alive and fills on the
next eligible event.

---

## 7. Differences Found in Repeated Batch 7A Files

| File | Status |
|---|---|
| `src/execution/contracts.py` | **Identical** to 7A original |
| `src/execution/exceptions.py` | **Identical** to 7A original |
| `src/execution/state_machine.py` | **Identical** to 7A original — **B1 not fixed** |
| `src/execution/__init__.py` | **Additive only** — all 7A exports preserved; 7B exports appended. No removals, no signature changes. Safe to replace |
| `tests/unit/execution/conftest.py` | **Identical** to 7A original |
| `tests/unit/execution/test_contracts.py` | **Identical** to 7A original |
| `tests/unit/execution/test_state_machine.py` | **Identical** to 7A original |

---

## 8. Market-Data Compatibility Findings

**An adapter layer is required.** `MarketSnapshot` is not wire-compatible with Batch 6 `Tick`.

| Field | Batch 6 Tick | 7B MarketSnapshot | Status |
|---|---|---|---|
| Instrument ID | `instrument_token: int` | `instrument_token: int` | ✅ Match |
| Exchange time | `exchange_timestamp` | `timestamp` | ⚠️ Name differs |
| Last price | `last_price` | `last_traded_price` | ⚠️ Name differs |
| Bid side qty | `buy_quantity` | `bid_quantity` | ⚠️ Name + semantics differ |
| Ask side qty | `sell_quantity` | `ask_quantity` | ⚠️ Name + semantics differ |
| Bid/Ask price | Inside `market_depth[0]` | `bid_price` / `ask_price` (flat fields) | ⚠️ Structure differs |
| Event identifier | *(none)* | `event_id: str` | ⚠️ Missing in Tick |
| Tick size | *(none)* | `tick_size: Decimal = 0.05` | ⚠️ Hardcoded default |

`MarketSnapshot` acknowledges this ("Adapted from Batch 6 Tick/Quote contracts").
The `__init__.py` states adapters come in a future batch. This is architecturally
clean — **not a blocker** — but Batch 7B cannot be wired to live market data
until the adapter batch lands.

---

## 9. Concurrency & Idempotency Findings

### Concurrency — Sound
- Per-order `asyncio.Lock` in the state machine serialises all mutation.
- `asyncio.gather` in `on_market_data` evaluates different orders concurrently;
  same-order transitions are serialised by the lock.
- No `await` between dedup-key check and insert → no TOCTOU race in asyncio.
- Dict iteration in `_executable_orders_for_instrument` is safe (no yields inside loop).

### Idempotency — Partly Sound, One Gap
- Dedup is per `(order_id, market_event_id)` — correct; one order processing an event
  does not block other orders from using the same event.
- Dedup key in `_evaluate_order` is added **before** the state machine transition.
  If the transition fails and is caught (e.g. `OverfillError` → returns `None`),
  the key is still recorded, permanently suppressing a legitimate retry.
  Same structural pattern as B1 in the state machine. Low probability in normal
  flow but a real correctness gap.

---

## 10. Code Quality Scan Results

| Check | Result |
|---|---|
| `pass` in production logic | ✅ None |
| TODO / FIXME | ✅ None |
| NotImplementedError | ✅ None |
| Random execution behaviour | ✅ None |
| `datetime.now()` without timezone | ✅ None — all use `timezone.utc` |
| Float-based price calculations | ✅ None — all Decimal |
| `asyncio.sleep()` in matching logic | ✅ None |
| Direct order mutation (bypassing state machine) | ✅ None |
| Live broker calls | ✅ None |
| Zerodha order API usage | ✅ None |
| `import hashlib` inside function body | ⚠️ W1 — `fills.py` line 104 |
| Inert validator | ⚠️ B2 — `fills.py` `_gross_value_matches` |

---

## 11. Files Requiring Changes

| File | Change Required |
|---|---|
| `src/execution/state_machine.py` | Fix B1: commit dedup key after successful transition only |
| `src/execution/fills.py` | Fix B2: replace inert validator; move `import hashlib` to top |
| `tests/unit/execution/test_matching.py` | Fix 8 failures: replace `__import__` with proper imports; add `event_id` and `tick_size` to `_make_snapshot()` helper |
| `tests/unit/execution/test_engine.py` | Fix 2 failures: add `timestamp` to `_make_snapshot()` helper; fix `test_deterministic_fill_id` to use a fresh machine for replay |

---

## 12. Minimum Recommended Fixes

1. **`state_machine.py`** — Move `state._seen_transitions.add(dedup_key)` to after
   step 6 (post state-change). Same B1 fix specified in the 7A review.

2. **`fills.py`** — Replace the `_gross_value_matches` stub:
   ```python
   @model_validator(mode="after")
   def _validate_gross_value(self) -> "FillEvent":
       expected = Decimal(self.quantity) * self.price
       if self.gross_value != expected:
           raise ValueError(
               f"gross_value {self.gross_value} != quantity*price {expected}"
           )
       return self
   ```
   Also move `import hashlib` to top of file.

3. **`test_matching.py`** — Add `event_id` and `tick_size` kwargs to `_make_snapshot()`:
   ```python
   def _make_snapshot(
       ltp=..., bid=..., ask=..., bid_qty=..., ask_qty=...,
       event_id: str = "evt-001",
       tick_size: Decimal = Decimal("0.05"),
   ) -> MarketSnapshot:
   ```
   Replace all `__import__("src.execution.contracts").ExecutionOrderStatus`
   with `from src.execution.contracts import ExecutionOrderStatus` at the top
   of each test class or at module level.

4. **`test_engine.py`** — Add `timestamp` kwarg to `_make_snapshot()`. Fix
   `test_deterministic_fill_id` to construct a fresh `OrderStateMachine` and
   `MatchingEngine` for the replay run rather than calling `engine.reset()` on
   the already-filled engine.

---

## 13. Safe Merge Plan

| Action | Files |
|---|---|
| **ADD** (new files, safe) | `src/execution/fills.py` |
| **ADD** (new files, safe) | `src/execution/matching.py` |
| **ADD** (new files, safe) | `src/execution/engine.py` |
| **ADD** (new files, safe) | `src/execution/policies.py` |
| **ADD** (new tests, after fixes) | `tests/unit/execution/test_policies.py` |
| **ADD** (new tests, after fixes) | `tests/unit/execution/test_matching.py` |
| **ADD** (new tests, after fixes) | `tests/unit/execution/test_engine.py` |
| **REPLACE** (additive only, safe) | `src/execution/__init__.py` — all 7A exports intact |
| **PRESERVE** (identical to 7A) | `src/execution/contracts.py` |
| **PRESERVE** (identical to 7A) | `src/execution/exceptions.py` |
| **REPLACE only after B1 fix** | `src/execution/state_machine.py` |
| **PRESERVE** (identical to 7A) | `tests/unit/execution/conftest.py` |
| **PRESERVE** (identical to 7A) | `tests/unit/execution/test_contracts.py` |
| **PRESERVE** (identical to 7A) | `tests/unit/execution/test_state_machine.py` |

---

*End of Report*
