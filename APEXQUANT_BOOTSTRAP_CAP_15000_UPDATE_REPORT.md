# ApexQuant AI — Bootstrap Paper Trade Cap Update Report
**Raised from ₹1,500 → ₹15,000**
_Generated: 2026-08-18_

---

## Section 1 — Files Changed

| File | Change |
|------|--------|
| `artifacts/api-server/src/python/phase20_executor.py` | `_BOOTSTRAP_MAX_ORDER_VALUE = 1_500` → `_BOOTSTRAP_MAX_ORDER_VALUE = 15_000` |
| `artifacts/api-server/src/python/phase20_executor.py` | Docstring: "Position size capped at ₹1,500" → "₹15,000" |
| `artifacts/api-server/src/python/phase20_executor.py` | Inline sizing comment: "₹1,500 ceiling" → "₹15,000 ceiling" |
| `artifacts/api-server/src/python/phase20_executor.py` | Approval event reason: "Max order value ₹1,500" → "₹15,000" |
| `artifacts/api-server/src/python/phase20_executor.py` | Notification body: "Max ₹1,500 position" → "Max ₹15,000 position" |
| `artifacts/api-server/src/python/phase20_bootstrap_status.py` | Added `bootstrap_max_order_value: int = 15_000` parameter to `build_bootstrap_status_payload`; included in return payload |
| `artifacts/api-server/src/python/main.py` | Imports `_BOOTSTRAP_MAX_ORDER_VALUE` from `phase20_executor`; passes it as `bootstrap_max_order_value` to `build_bootstrap_status_payload` |
| `artifacts/api-server/src/python/tests/unit/test_bootstrap_paper_trade.py` | `test_order_value_capped_at_1500` → `test_order_value_capped_at_15000`; price ₹5,000 → ₹16,000 |
| `artifacts/api-server/src/python/tests/unit/test_bootstrap_paper_trade.py` | `test_order_value_capped_affordable_stock` comment updated (qty≈74, notional≈₹14,822 ≤ ₹15,000) |
| `artifacts/api-server/src/python/tests/unit/test_bootstrap_paper_trade.py` | `test_refuses_when_worst_case_fill_exceeds_cap`: price ₹1,499 → ₹14,979 |
| `artifacts/api-server/src/python/tests/unit/test_bootstrap_paper_trade.py` | Added `test_drreddy_bootstrap_quantity` (mocked sizing capture, qty 10–12) |
| `artifacts/api-server/src/python/tests/unit/test_bootstrap_paper_trade.py` | Added `test_drreddy_exposure_cap_integration` (calls real `validate_pre_trade`; asserts capped_qty=10) |
| `artifacts/api-server/src/python/tests/unit/test_bootstrap_paper_trade.py` | Added `test_existing_open_bootstrap_trade_blocks_new_entry` (regression guard) |
| `artifacts/api-server/src/python/tests/unit/test_bootstrap_status_command.py` | Added `TestBootstrapMaxOrderValue` (3 tests: present, equals 15_000, overrideable via kwarg) |
| `artifacts/trading-dashboard/src/pages/AIPaperTraderPage.tsx` | Line ~1464: "Max ₹1,500 per position" → "Max ₹15,000 per position" |
| `artifacts/trading-dashboard/src/pages/AIPaperTraderPage.tsx` | Line ~2639 tooltip: "Max ₹1,500 position" → "Max ₹15,000 position" |

---

## Section 2 — Old Cap vs New Cap

| Attribute | Old Value | New Value |
|-----------|-----------|-----------|
| `_BOOTSTRAP_MAX_ORDER_VALUE` constant | ₹1,500 | ₹15,000 |
| Maximum bootstrap trade notional (before exposure cap) | ₹1,500 | ₹15,000 |
| `bootstrap_max_order_value` in status API payload | absent | ₹15,000 (single source of truth from executor constant) |
| DRREDDY (₹1,187) maximum shares from bootstrap ceiling | 1 share (₹1,187) | 12 shares (₹14,265) |

The old cap of ₹1,500 caused DRREDDY (≈₹1,187) to size to exactly 1 share, producing a trivial paper ledger entry. The new cap allows meaningful position sizing for liquid large-cap stocks.

---

## Section 3 — Effective Cap After Risk Rules

For a portfolio with `INITIAL_CAPITAL = ₹50,000` and `per_stock_exposure_cap_pct = 25 %`:

| Risk Rule | Value |
|-----------|-------|
| Bootstrap ceiling (`_BOOTSTRAP_MAX_ORDER_VALUE`) | ₹15,000 |
| Per-stock exposure cap (25 % × ₹50,000) | ₹12,500 |
| **Effective sizing cap (min of both)** | **₹12,500** |

The bootstrap executor computes quantity from the ₹15,000 ceiling. The per-stock exposure cap (₹12,500) is enforced downstream inside `create_paper_entry` via `validate_pre_trade._check_position_size`. When the bootstrap-computed qty (12) exceeds the 25% cap, `validate_pre_trade` returns `APPROVED_WARN` with `summary["size_reduced_to_cap"]=True` and `summary["capped_qty"]=10`, and `create_paper_entry` adopts the reduced quantity (lines 600–642 of `phase20_executor.py`).

---

## Section 4 — DRREDDY Quantity Simulation

**Inputs:**

| Parameter | Value |
|-----------|-------|
| Symbol | DRREDDY |
| Kite LTP (signal price) | ₹1,186.98 |
| Slippage | 0.15 % |
| Fill price (worst-case) | ₹1,186.98 × 1.0015 = **₹1,188.76** |
| Bootstrap ceiling | ₹15,000 |
| Portfolio capital (`INITIAL_CAPITAL`) | ₹50,000 |
| Per-stock exposure cap | 25 % |
| Stop-loss | ₹1,150.00 |
| Target price | ₹1,250.00 |

**Sizing calculation (bootstrap executor):**

| Step | Calculation | Result |
|------|-------------|--------|
| Worst-case fill | ₹1,186.98 × 1.0015 | ₹1,188.76 |
| Raw bootstrap qty | ⌊15,000 ÷ 1,188.76⌋ | **12 shares** |
| Bootstrap notional | 12 × ₹1,188.76 | ₹14,265.12 ≤ ₹15,000 ✓ |

**Exposure cap (validate_pre_trade):**

| Step | Calculation | Result |
|------|-------------|--------|
| Exposure cap amount | 25 % × ₹50,000 | ₹12,500 |
| Exposure-capped qty | ⌊12,500 ÷ 1,188.76⌋ | **10 shares** |
| Exposure-capped notional | 10 × ₹1,188.76 | ₹11,887.60 ≤ ₹12,500 ✓ |

**Risk and R:R at fill price (10 shares, after exposure cap):**

| Metric | Calculation | Result |
|--------|-------------|--------|
| Risk per share | ₹1,188.76 − ₹1,150.00 | ₹38.76 |
| Reward per share | ₹1,250.00 − ₹1,188.76 | ₹61.24 |
| R:R ratio (at fill price) | 61.24 ÷ 38.76 | **1.58** ≥ 1.5 minimum ✓ |
| Total risk (10 shares) | ₹38.76 × 10 | ₹387.60 |
| Risk % of capital | ₹387.60 ÷ ₹50,000 | **0.78 %** ≤ 2.0 % limit ✓ |
| Final notional | 10 × ₹1,188.76 | **₹11,887.60** |
| Cash consumed | ₹11,887.60 + charges | ≈ ₹11,903.88 |
| Remaining cash | ₹50,000 − ₹11,903.88 | ≈ ₹38,096 (76 % of portfolio) ✓ |

Final quantity after all risk rules: **10 shares** (₹11,887.60), compared to **1 share** (₹1,187) under the old ₹1,500 cap.

---

## Section 5 — Confirmation: Existing DRREDDY Trade Not Modified

The existing open DRREDDY paper trade **`P20-3468fb2a24`** was **not mutated** by this change.

- `_BOOTSTRAP_MAX_ORDER_VALUE` is used only during **new trade sizing** inside `run_bootstrap_auto_entry`.
- Existing rows in `phase20_paper_trades` are never touched by the bootstrap executor — it only reads the count of CLOSED trades and whether any BOOTSTRAP_AUTO trade is OPEN.
- The `_bootstrap_open` guard (executor lines ~966–975) returns `ran=False` when any bootstrap trade is OPEN — so while `P20-3468fb2a24` remains open, no new bootstrap trade fires regardless of cap.
- No `UPDATE` or `DELETE` SQL is executed in this code path.
- **Schema migration: not required.** The constant lives entirely in Python application code.

---

## Section 6 — Test Results Summary

### Updated tests (old ₹1,500 boundary → new ₹15,000 boundary)

| Test | Change |
|------|--------|
| `TestBootstrapPermitsWatchCandidates::test_order_value_capped_at_15000` | Renamed; price ₹5,000 → ₹16,000 (must exceed new cap) |
| `TestBootstrapPermitsWatchCandidates::test_order_value_capped_affordable_stock` | Comment updated: qty≈74 shares, notional≈₹14,822 ≤ ₹15,000 |
| `TestBootstrapRefusesFailedGates::test_refuses_when_worst_case_fill_exceeds_cap` | Price ₹1,499 → ₹14,979 (worst-fill ≈₹15,001 > ₹15,000 — blocked for 1 share) |

### New tests

| Test | Purpose |
|------|---------|
| `TestBootstrapPermitsWatchCandidates::test_drreddy_bootstrap_quantity` | Mocked capture: DRREDDY at ₹1,186.98 sizes to qty 10–12, notional ≤ ₹15,000, trigger_source="BOOTSTRAP_AUTO" |
| `TestBootstrapPermitsWatchCandidates::test_drreddy_exposure_cap_integration` | **Integration-level**: calls real `validate_pre_trade` with qty=12, fill≈₹1,188.76; asserts APPROVED_WARN, size_reduced_to_cap=True, capped_qty=10 (exposure cap ₹12,500 applied correctly) |
| `TestBootstrapPermitsWatchCandidates::test_existing_open_bootstrap_trade_blocks_new_entry` | Regression: OPEN bootstrap trade → ran=False, create_paper_entry not called |
| `TestBootstrapMaxOrderValue::test_max_order_value_present_in_payload` | Status API payload includes `bootstrap_max_order_value` field |
| `TestBootstrapMaxOrderValue::test_max_order_value_is_15000` | Status API `bootstrap_max_order_value` equals executor constant (15,000) |
| `TestBootstrapMaxOrderValue::test_max_order_value_overrideable_via_kwarg` | Caller (main.py) can inject the executor constant via kwarg |

**Total: 93 tests passed, 0 failed.**

The `_BOOTSTRAP_MAX_ORDER_VALUE` constant is imported directly by the test module, so any future cap change automatically updates the assertion threshold in `test_order_value_capped_affordable_stock` and `TestBootstrapMaxOrderValue::test_max_order_value_is_15000`.

---

## Section 7 — LIVE_EXECUTION_ENABLED Unchanged; No Broker Order API Called

- `LIVE_EXECUTION_ENABLED` remains `False` (default). **Not changed.**
- The bootstrap executor calls `paper_trader.execute_buy` via `create_paper_entry` only — this is the paper-only execution path.
- No Kite broker order API (`kiteconnect.KiteConnect.place_order`) is invoked.
- `run_bootstrap_auto_entry` docstring states: _"NEVER calls live broker order APIs (paper_trader.execute_buy only)"_.
- The pre-existing `test_no_live_broker_api_called` test continues to assert this invariant.

---

## Section 8 — Publish Recommendation

A **republish is advisable** so the running API server picks up the updated constant and status payload.

- The running API server process caches Python modules at startup. A workflow restart or full republish is required for:
  - `_BOOTSTRAP_MAX_ORDER_VALUE = 15_000` to take effect in the bootstrap executor.
  - The status API to return `"bootstrap_max_order_value": 15000` in its payload.
- **No schema migration required** — all changes are in Python application code.
- No environment variable changes needed.
- After republish, the next `run_bootstrap_auto_entry` call will size new bootstrap trades using the ₹15,000 ceiling (effective cap ₹12,500 after 25% exposure gate). The existing open DRREDDY trade `P20-3468fb2a24` is unaffected.
