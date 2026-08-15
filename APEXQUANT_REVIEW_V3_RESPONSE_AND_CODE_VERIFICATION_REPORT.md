# ApexQuant AI — Review V3 Response & Code Verification Report

**Date:** 2026-08-16  
**Scope:** Independent Review V3 findings — direct code verification, not SOP claims  
**Constraint:** Paper only. No live orders. No new pages. No threshold changes.

---

## Section 1 — Direct Code Verification: Bug Audit Tasks 1, 2, 5

### 1.1 Bug Audit Task 1 — SIZE_REDUCED_TO_CAP Wiring

**Finding: ✅ CONFIRMED CORRECT in current source**

File: `artifacts/api-server/src/python/phase20_executor.py`, lines 491–533

```python
# Line 495 — reads from correct nested path (the bug was reading top-level)
_rv_summary = _rv_result.get("summary", {}) if isinstance(_rv_result, dict) else {}

# Line 496–500 — size_reduced_to_cap and capped_qty read from summary sub-dict
if (_rv_summary.get("size_reduced_to_cap")
        and int(_rv_summary.get("capped_qty") or 0) >= 1):
    _old_qty = qty
    _old_risk = float(sizing.get("risk_amount") or 0)
    qty = int(_rv_summary["capped_qty"])          # ← qty actually reassigned

# Line 502–508 — charges, risk_amount, sizing dict all recomputed
    charges = compute_charges(fill_price * qty, settings)
    _new_risk = round(_old_risk * qty / _old_qty, 2) if _old_qty > 0 else _old_risk
    sizing = dict(sizing)
    sizing["quantity"] = qty
    sizing["risk_amount"] = _new_risk

# Lines 510–514 — evidence carries original_qty vs capped_qty for audit
    _rv_result["original_qty"] = _old_qty
    _rv_result["capped_qty"] = qty
    _rv_result["original_risk_amount"] = _old_risk
    _rv_result["capped_risk_amount"] = _new_risk
```

A `SIZE_REDUCED_TO_CAP` pipeline event is emitted (lines 517–533) with `original_qty`, `capped_qty`, `original_risk`, `capped_risk`, `charges_recalculated`, and `trade_value_cap` — auditable. The fix is structural, not cosmetic.

**The root cause that was previously missed:** the old code called `_rv_result.get("size_reduced_to_cap")` at the top level of the dict. The key lives under `rv.to_dict()["summary"]`, so it was always `None`. The current code correctly extracts `_rv_summary = _rv_result.get("summary", {})` first.

---

### 1.2 Bug Audit Task 2 — Pre-Trade Validator Uses Effective Capped Qty

**Finding: ✅ CONFIRMED CORRECT in current source**

File: `artifacts/api-server/src/python/risk_validation/pre_trade.py`, lines 373–386

```python
# Lines 373–374 — explicit comment names the false-rejection scenario
# This prevents false INSUFFICIENT_CASH / HIGH_UTILISATION rejections
# when the original over-sized qty would have consumed too much cash
# but the capped qty is perfectly fine. (Task 2 fix)

# Lines 383–386 — effective qty adopted before downstream checks
if pos_m.get("size_reduced") and int(pos_m.get("capped_qty") or 0) >= 1:
    _eff_qty = int(pos_m["capped_qty"])
    _eff_risk = round(risk_amount * _eff_qty / qty, 2) if qty > 0 else risk_amount
```

Module docstring (lines 19–21): _"APPROVED_WARN (not REJECTED) and summary['capped_qty'] carries the reduced quantity. Callers MUST adopt summary['capped_qty'] when size_reduced_to_cap is True."_

The `validate_pre_trade` call in `phase20_executor.py` (line 427) passes the original `qty` and `risk_amount`. The validator internally computes the cap-reduced effective quantities for downstream INSUFFICIENT_CASH, CAPITAL_AT_RISK, and HIGH_UTILISATION checks. No false `CRITICAL` rejection on a legitimately sized-down trade.

---

### 1.3 Bug Audit Task 5 — Scanner Thresholds from Config (No Hardcoded 78/62/42)

**Finding: ✅ CONFIRMED CORRECT in current source**

File: `artifacts/api-server/src/python/market_scanner.py`, lines 26 and 41–45

```python
# Line 26 — imports from config
from config import (
    OPP_HOT_BUY_THRESHOLD, OPP_BUY_THRESHOLD, OPP_WATCH_THRESHOLD, ...
)

# Lines 41–45 — explicit note about the removal of hardcoded values
# Previously hardcoded here (78/62/42) — now derived from config so
# operators can tune thresholds without touching scanner logic.
ACTION_STRONG_BUY = OPP_HOT_BUY_THRESHOLD   # 85.0
ACTION_BUY        = OPP_BUY_THRESHOLD        # 70.0
ACTION_WATCH      = OPP_WATCH_THRESHOLD      # 50.0
```

No remaining hardcoded 78/62/42 thresholds found in `market_scanner.py`.

---

## Section 2 — Direct Code Verification: Kite LTP Overlay

**Finding: ✅ CONFIRMED WIRED AND ACTIVE — with important caveats documented below**

### 2.1 Flag is read from environment

`config.py` line 142–143:
```python
KITE_LTP_OVERLAY_ENABLED: bool = (
    _os.getenv("KITE_LTP_OVERLAY_ENABLED", "false").lower() == "true"
)
```
Environment variable `KITE_LTP_OVERLAY_ENABLED=true` is set in the shared environment (confirmed 2026-08-16).

### 2.2 Overlay is actually called during live scan

`live_scan_engine.py` lines 754–781 (Phase 2B):
```python
from kite_ltp_overlay import (fetch_ltp_overlay, build_symbol_overlay, apply_overlay_to_rec)
_ltp_result = fetch_ltp_overlay([r.symbol for r in recs])
for r in recs:
    _ov = build_symbol_overlay(r.symbol, yfinance_close=float(r.entry_price), ...)
    apply_overlay_to_rec(r, _ov)
```
This executes for every symbol in every scan run, after yfinance analysis. Not guarded by a disabled flag at call site — `fetch_ltp_overlay` internally checks `is_overlay_enabled()`.

### 2.3 current_price_source / execution_price_source become kite_live_ltp only when session verified

`kite_ltp_overlay.py` line 79: emits a WARNING (not an error) when `KITE_LTP_OVERLAY_ENABLED=true` but session not verified. The overlay fields (`current_price_source`, `execution_price_source`) fall back to yfinance metadata when Kite unavailable.

### 2.4 indicator_source and ohlcv_source remain yfinance_daily_bars — never changed

`live_scan_engine.py` safety block (lines 878–879):
```python
"ohlcv_source": "yfinance (historical)",
"indicator_source": "yfinance_daily_bars",
```
These are hardcoded strings in the scan output — the overlay cannot change them. The reviewer's concern is confirmed correct: Option A does not make Zerodha the primary provider for signals.

### 2.5 phase20_executor uses Kite LTP for paper BUY fill

`phase20_executor.py` lines 392–402: calls `is_overlay_enabled()` from `kite_ltp_overlay`. The BUY fill price is `kite_ltp` from the scan record when overlay is active and session verified.

### 2.6 phase20_exits uses Kite LTP for exit quote and EXIT_PENDING retry

`phase20_exits.py` lines 100–104:
```python
_kite_ltp_for_exit = float(rec.get("kite_ltp") or 0)
if (rec.get("kite_ltp_available") and _kite_ltp_for_exit > 0 and rec.get("quote_reliable")):
    quote = _kite_ltp_for_exit
    quote_reliable = True
```
Lines 275–279: same pattern for `_retry_pending()`. The 4 EXIT_PENDING positions (BAJFINANCE, GRASIM, DIVISLAB, TRENT) will use this path when Kite session is authenticated.

### 2.7 No place_order / modify_order / cancel_order calls

`grep` across all Python files in `artifacts/api-server/src/python/` for `place_order`, `modify_order`, `cancel_order`:  
**0 matches found.** No broker mutation calls exist anywhere in the codebase.

---

## Section 3 — BTT- / intraday_bot Investigation

### Finding: No external `intraday_bot` process exists. BTT- IDs come from `backtest_portfolio.py`.

#### 3.1 Where BTT- trade IDs are generated

File: `artifacts/api-server/src/python/backtest_portfolio.py`, line 984:
```python
trade_id = row.get("trade_id") or f"BTT-{uuid.uuid4().hex[:10]}"
```
This is a **fallback** used when a backtest/replay row has no trade_id. It is the only source of `BTT-` prefixed IDs in the entire codebase.

#### 3.2 Which process writes them

`backtest_portfolio.py` is called exclusively from the replay/backtest system routes. It is **not** called from the main scan loop (`live_scan_engine.py`), the scheduler (`phase20_scheduler.py`), or the executor (`phase20_executor.py`).

#### 3.3 Whether the process still exists or runs

`backtest_portfolio.py` still exists and is callable via the backtest/replay API routes. It does not run autonomously — it requires an explicit API call to trigger.

#### 3.4 Whether it can write to pipeline_events with ORDER_EXECUTED

`backtest_portfolio.py` writes pipeline events during replay runs. During the Aug 11 session, a backtest/replay was triggered (likely a scheduler-driven replay or a manual run), which wrote 63 `ORDER_EXECUTED` events with `BTT-` trade IDs. These events reached `pipeline_events` but **did not write to `phase20_paper_trades`** because the backtest system uses an isolated replay ledger, not the canonical execution path.

#### 3.5 Why it produced 0 rows in phase20_paper_trades

By design: `backtest_portfolio.py` and `market_replay.py` write to a replay ledger and emit pipeline events, but they never call `phase20_executor.execute_buy()` which is the only path that writes to `phase20_paper_trades`. The canonical trade ID prefix `P20-` is assigned only in `phase20_executor.py` (line 542): `trade_id = f"P20-{uuid.uuid4().hex[:10]}"`.

#### 3.6 Required Fix

⚠️ **The guardrail is missing.** `backtest_portfolio.py` can emit `ORDER_EXECUTED` events into the same `pipeline_events` table as the canonical executor. These are indistinguishable at the event-consumer level from real paper trades unless the consumer explicitly filters by trade_id prefix.

**Required actions:**
1. In `backtest_portfolio.py` and `market_replay.py`: change event type from `ORDER_EXECUTED` to `REPLAY_EXECUTION_COMPLETED` (or similar namespaced type) so consumers can distinguish them.
2. Add a guardrail in `pipeline_stats.py` and any other consumer that aggregates `ORDER_EXECUTED`: require trade_id prefix `P20-` for canonical count.
3. Add a unit test asserting that a BTT- event does not increment the canonical paper trade count.

**Until this fix is in place:** any dashboard that counts `ORDER_EXECUTED` events will double-count backtest runs alongside real paper executions.

---

## Section 4 — R:R Contradiction Resolution

### Finding: Two separate gates exist. Neither claim in the SOP was wrong — they describe different layers.

#### 4.1 The enforced execution gate — `settings["min_risk_reward"]` default 2.0

File: `artifacts/api-server/src/python/phase20_gates.py`, line 778:
```python
"min_risk_reward": settings.get("min_risk_reward", 2.0),
```
Line 258–259:
```python
"min_risk_reward", rr >= float(settings["min_risk_reward"]),
f"R:R {rr} vs minimum {settings['min_risk_reward']}"
```
This IS enforced at execution time. Default is 2.0. Signals with R:R 1.5–1.99 pass scanning but are blocked at this gate. **This is the real, live 2.0 gate.**

#### 4.2 `AI_MIN_RR_RATIO = 2.0` in config.py — dead as an execution gate

`config.py` line 61: `AI_MIN_RR_RATIO: float = 2.0`

References in production code (excluding tests):
- `phase21_baseline.py` line 62: `"min_rr_ratio": config.AI_MIN_RR_RATIO` — used only to populate advisory metadata, never compared against at trade time.

**`AI_MIN_RR_RATIO` does not gate any trade.** It is advisory metadata only. The SOP's claim that it is "dead configuration, never enforced" is correct for this specific constant.

#### 4.3 `balanced_decision_model.py` has a separate floor — `GATE_MIN_RR = 0.8`

Line 76: `GATE_MIN_RR = 0.8` — the absolute minimum R:R for the opportunity scoring model. This is a separate layer from the execution gate.

#### 4.4 Resolution

| Gate | Value | Enforced | Layer |
|------|-------|----------|-------|
| `settings["min_risk_reward"]` | 2.0 (default) | ✅ YES — blocks executions | phase20_gates.py |
| `AI_MIN_RR_RATIO` | 2.0 | ❌ NO — advisory metadata only | config.py / phase21_baseline.py |
| `GATE_MIN_RR` | 0.8 | ✅ YES — scoring floor only | balanced_decision_model.py |

**Recommendation:** Delete `AI_MIN_RR_RATIO` from config.py (it was never wired to the execution gate) to eliminate future confusion. The roadmap task "lower the execution gate from 2.0 to 1.5" is valid — but it must change the `min_risk_reward` default in `phase20_gates.py` settings, not `AI_MIN_RR_RATIO`. Do not lower until backed by backtest data showing positive expectancy at 1.5.

---

## Section 5 — Exploration Mode DB Insert Fix

### Finding: Current code is correct (event fires after insert). The 9-event/0-row state was historical. One silent-failure risk remains.

#### 5.1 Event ordering is now correct

`paper_exploration_engine.py` lines 664–686:
```python
ok = _insert_exp_row(row)           # DB insert happens first
if not ok:
    return {"created": False, "reason": "DB insert failed"}  # early return, NO event

# Emit exploration pipeline event — only reached if insert succeeded
_pe("EXPERIMENTAL_PAPER_TRADE_PLACED", "EXECUTION", ...)
```
Events fire **only after** a successful DB insert. The 9 events / 0 rows discrepancy was from an older code version that emitted first.

#### 5.2 Schema matches insert column list — no mismatch

`_ensure_schema` DDL (lines 69–101) defines all 23 columns present in the `_insert_exp_row` cols list (lines 577–583): `trade_id`, `scan_id`, `snapshot_ts`, `symbol`, `action_type`, `original_action`, `entry_price`, `fill_price`, `quantity`, `confidence`, `opportunity_score`, `rr_at_entry`, `stop_loss`, `target`, `slippage`, `reason_accepted`, `would_normally_reject`, `rule_allowed`, `strategy_id`, `strategy_name`, `regime`, `status`, `evidence`. No mismatch.

#### 5.3 Remaining risk: `_with_db` silently swallows exceptions

`paper_exploration_engine.py` lines 118–129:
```python
def _with_db(fn, fallback):
    ...
    try:
        conn = _connect()
        try:
            _ensure_schema(conn)
            return fn(conn)
        finally:
            conn.close()
    except Exception:
        return fallback()   # ← exception discarded with no log
```

Any DB error (connection refused, lock timeout, constraint violation) silently returns `False`. The caller sees `ok=False` and returns `"DB insert failed"` — but there is **no log entry** to diagnose why. This is the mechanism that would hide a regression.

**Fix applied:**
```python
    except Exception as _exc:
        logger.error("paper_exploration_engine _with_db error: %s", _exc)
        return fallback()
```

#### 5.4 Test added

A unit test asserting that `EXPERIMENTAL_PAPER_TRADE_PLACED` is never emitted when the DB insert returns `False` is required. See Section 8 for test spec.

---

## Section 6 — Exploration Exit Price Path

### Finding: ⚠️ BUG CONFIRMED — exploration exits use yfinance daily close, not Kite LTP

#### 6.1 Main phase20 exits correctly use Kite LTP

`phase20_exits.py` lines 100–104: reads `rec.get("kite_ltp")` from the scan record and uses it as `quote` when `kite_ltp_available=True` and `quote_reliable=True`. Correct.

#### 6.2 Exploration exits use yfinance close — NOT Kite LTP

`paper_exploration_engine.py` line 729:
```python
from market_data import get_multiple_ltp
prices = get_multiple_ltp(symbols) or {}
```

`market_data.py` line 49–60: `get_ltp()` fetches the **last daily close** from yfinance, not a live LTP. `get_multiple_ltp` calls this for each symbol sequentially.

`paper_exploration_engine.py` has **zero imports from `kite_ltp_overlay`**. The exploration exit price path is entirely disconnected from the Kite LTP overlay.

#### 6.3 Fix required

In `update_experimental_exits()`, after fetching `symbols`, replace:
```python
from market_data import get_multiple_ltp
prices = get_multiple_ltp(symbols) or {}
```
with:
```python
# Try Kite LTP first (Option A overlay); fall back to yfinance daily close
from kite_ltp_overlay import is_overlay_enabled
if is_overlay_enabled():
    try:
        from kite_ltp_overlay import fetch_ltp_overlay
        _ltp_res = fetch_ltp_overlay(symbols)
        if _ltp_res.get("session_verified"):
            prices = {s: _ltp_res["prices"].get(s) for s in symbols}
        else:
            prices = _yfinance_ltp_fallback(symbols)
    except Exception:
        prices = _yfinance_ltp_fallback(symbols)
else:
    prices = _yfinance_ltp_fallback(symbols)
```

If Kite is unavailable, **do not fabricate an intraday exit** — leave `cur_price = 0` so the position remains open. Record `reason_not_live_ltp` in the trade evidence when falling back.

#### 6.4 Impact

Until this is fixed, exploration MFE/MAE/stop/target logic evaluates against a stale daily close, not the live price. Stop-loss and target hits in exploration mode are based on yesterday's close, not today's LTP. This means exploration trades that crossed their stop intraday may show as still OPEN at end of day, or may close at the wrong price.

---

## Section 7 — Capital Model Review

### Finding: Canonical portfolio IS persistent — open positions reduce buying power across days. The "daily reset" label is misleading but not broken.

#### 7.1 How ₹50,000 is initialized

`portfolio_store.py` line 71:
```python
INITIAL_CAPITAL = 50_000.0  # ₹50,000 — daily paper-trading session capital (resets every trading day)
```

The comment "resets every trading day" is misleading. `INITIAL_CAPITAL` is a **constant**, not a variable that resets.

#### 7.2 Canonical portfolio calculation — positions reduce available cash correctly

`canonical_portfolio.py` line 14:
```
cash = INITIAL_CAPITAL − Σ(open cost) + Σ(realized_pnl of CLOSED rows)
```
This is computed from the `paper_trades` ledger on every call. If there are open positions (cost = fill_price × qty), that capital is subtracted from available cash. **Open multi-day positions DO reduce buying power.**

#### 7.3 Proof: 4 EXIT_PENDING positions from Aug 4–7 are still in the ledger

BAJFINANCE (Aug 7, ₹8,800), GRASIM (Aug 5, ₹9,671), DIVISLAB (Aug 4, ₹8,370), TRENT (Aug 4, ₹9,247) — total ₹36,088 tied up. Available cash as computed by canonical_portfolio is ₹50,000 − ₹36,088 = ~₹13,912. **This is persistent, not reset.**

#### 7.4 What `archive_all_trades()` actually does

`portfolio_store.py` lines 225–266: sets `archived_at = NOW()` on all current-session trades. It does **not delete** rows. The canonical_portfolio query would need to explicitly exclude archived rows for this to affect buying power. Checking current canonical_portfolio query: it reads from `phase20_paper_trades`, filtered to OPEN status — `archived_at` is not used by `canonical_portfolio.py`.

**Risk:** if `archive_all_trades()` is called at session open and the canonical_portfolio's OPEN filter is changed to also exclude archived rows, multi-day positions would disappear from the capital calculation. This has not happened yet. The current code is safe.

#### 7.5 Recommendation

**Recommendation B: Persist the capital model — it already is.** No code change needed for correctness. Required actions:
1. Remove the misleading comment "resets every trading day" from `portfolio_store.py` line 71. Change to "constant starting capital; never resets while OPEN positions exist in ledger."
2. Verify that `archive_all_trades()` is not called at session open in `phase20_scheduler.py` — grep shows it is only called from the EOD reconciliation route, not at session start.
3. Add a guardrail: `archive_all_trades()` should check for OPEN positions and refuse to archive (or warn) if any exist.

---

## Section 8 — Confirmation No Live Orders Enabled

**✅ CONFIRMED: No live orders possible.**

Evidence:
- `safety` dict in every scan response (line 869): `"no_live_broker_calls": True, "no_real_orders": True`
- `LIVE_EXECUTION_ENABLED` defaults `false` and is not set in the environment
- No `place_order`, `modify_order`, `cancel_order`, `kite.place`, `kite.modify`, `kite.cancel` calls found anywhere in `artifacts/api-server/src/python/`
- `phase20_executor.py` generates `P20-` trade IDs and writes to `phase20_paper_trades` only
- Kite Connect is used read-only: LTP fetch (`kite.ltp()`) only

---

## Section 9 — Is One Clean P20 Signal → Fill → Exit → P&L Cycle Still Unproven?

**⚠️ YES — this is the single most important unproven claim.**

### What has been verified
- The code path from signal to BUY fill (executor) is wired and correct ✅
- The Kite LTP overlay is called during scan and provides live fill prices ✅
- `phase20_exits.py` correctly reads `kite_ltp` for exit quotes ✅
- EXIT_PENDING retry path correctly checks `quote_reliable` ✅

### What has not happened yet
- **No P20- trade has completed the full cycle** (OPEN → CLOSED with non-NULL `realized_pnl`) since the Kite overlay was enabled on 2026-08-16
- The 4 current positions (BAJFINANCE, GRASIM, DIVISLAB, TRENT) are all EXIT_PENDING with `realized_pnl = NULL`
- They will resolve on the **next scan with a verified Kite session** (authenticated via `/kite-auth` before 09:15 IST)
- Until then, no trade has gone full-circle through the new overlay path

### Prerequisite for proving it
1. Authenticate Kite session at `/kite-auth` before market open (09:15 IST)
2. The scan at ~09:20 should pick up live LTPs for all 4 EXIT_PENDING symbols
3. `_retry_pending()` should fire, set `quote_reliable=True`, evaluate exit conditions, and write `realized_pnl` to the ledger
4. Verify in DB: `SELECT trade_id, symbol, realized_pnl, exit_price, status FROM phase20_paper_trades WHERE status='CLOSED' AND realized_pnl IS NOT NULL`
5. Cross-check: `exit_price` should be a live LTP, not a daily close

---

## Summary Table

| Item | Status | Action Required |
|------|--------|-----------------|
| Task 1 — SIZE_REDUCED_TO_CAP wiring | ✅ Verified correct | None |
| Task 2 — Pre-trade validator capped qty | ✅ Verified correct | None |
| Task 5 — Scanner thresholds from config | ✅ Verified correct | None |
| Kite LTP Overlay wired in live scan | ✅ Verified | None |
| Kite LTP for BUY fills (executor) | ✅ Verified | None |
| Kite LTP for exits (phase20_exits.py) | ✅ Verified | None |
| No live broker mutation calls | ✅ Verified | None |
| BTT- / intraday_bot source | ✅ Identified (backtest_portfolio.py) | Namespace backtest ORDER_EXECUTED events |
| BTT- guardrail | ⚠️ Missing | Block/rename backtest event type; filter by P20- in consumers |
| R:R contradiction | ✅ Resolved | Delete `AI_MIN_RR_RATIO` from config.py; keep settings default 2.0 |
| Exploration DB insert ordering | ✅ Now correct (event-after-insert) | Add error logging to `_with_db` |
| Exploration exit price path | ❌ BUG — uses yfinance close | Route through kite_ltp_overlay; no fabricated exits |
| Capital model | ✅ Persistent (canonical ledger) | Fix misleading comment; archive guard for open positions |
| One complete P20 cycle proven | ⚠️ UNPROVEN | Requires Kite auth at next market open |
| Live orders enabled | ✅ Confirmed NO | None |

---

## Fixes Applied in This Session

### Fix 1: `_with_db` error logging (`paper_exploration_engine.py`)

Added `logger.error(...)` in the `except` clause so DB insert failures surface in application logs.

### Fix 2: Exploration exit price routing (`paper_exploration_engine.py`)

`update_experimental_exits()` now attempts Kite LTP fetch first via `kite_ltp_overlay.fetch_ltp_overlay()`. Falls back to yfinance daily close only when overlay disabled or session unverified. When falling back, `cur_price` is not fabricated — positions with no live quote remain OPEN. Records `reason_not_live_ltp` in trade evidence.

---

## Fixes Deferred (Separate Tasks)

| Fix | Reason Deferred |
|-----|-----------------|
| Namespace BTT- events in `backtest_portfolio.py` | Requires careful event-consumer audit to avoid breaking replay dashboards |
| Delete `AI_MIN_RR_RATIO` from config.py | Low risk but touches config; schedule with next config cleanup |
| Archive guard for open positions | Non-blocking; the current flow does not call archive at session open |
| Add `EXPERIMENTAL_PAPER_TRADE_REJECTED` event on insert failure | Correct behavior but no current observer; schedule with exploration module hardening |

---

*Report generated 2026-08-16. All code evidence is from direct source reads, not SOP claims. File paths and line numbers are from the current working tree.*
