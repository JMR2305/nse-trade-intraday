# APEXQUANT SOURCE CODE BUG AUDIT AND FIX REPORT

**Date:** 2026-08-15 IST  
**Platform:** Paper only — no live orders placed or enabled at any point  
**Controlling document:** `APEXQUANT_AI_SOP_v3.html`  
**Status:** All five tasks investigated; three code bugs fixed; two items are documented findings requiring operator decision

---

## Executive Summary

| # | Task | Finding | Action |
|---|---|---|---|
| 1 | SIZE_REDUCED_TO_CAP wiring | **BUG — confirmed in code** | **Fixed** |
| 2 | Pre-trade validator false rejection | **BUG — confirmed in code** | **Fixed** |
| 3 | Data path (yfinance/daily) | Confirmed from source | Implementation plan provided |
| 4 | Exploration mode daily-close price | **BUG — confirmed in code** | Documented; no safe intraday fix yet |
| 5 | Threshold mismatch (SOP vs code) | **BUG — confirmed in code** | **Fixed** |

---

## Task 1 — SIZE_REDUCED_TO_CAP Wiring Bug

### Finding

**File:** `phase20_executor.py`, lines 459–469 (pre-fix)

`create_paper_entry()` calls `rv = validate_pre_trade(...)` then `_rv_result = rv.to_dict()`.

`rv.to_dict()` returns:

```python
{
    "verdict": "APPROVED_WARN",
    "approved": True,
    "symbol": "DRREDDY",
    ...
    "summary": {
        "size_reduced_to_cap": True,   # ← lives HERE
        "capped_qty": 15,               # ← lives HERE
        ...
    }
}
```

The old code read:

```python
_rv_result.get("size_reduced_to_cap")   # → always None (key is one level deeper)
_rv_result.get("capped_qty")            # → always None
```

Because these keys are nested inside `["summary"]`, not at the top level, the condition was **never True**. The executor always used the original oversized quantity. For DRREDDY (₹6,500/share), TMPV, BAJAJ-AUTO, GRASIM, and BAJAJFINSV the validator correctly computed a capped quantity of 1–15 shares, but the executor silently ignored the cap and placed the oversized order anyway — or if `execute_buy` failed due to cash constraints, the trade was blocked entirely.

### Fix Applied

**File:** `phase20_executor.py`

```python
# BEFORE (bug):
if (_rv_result.get("size_reduced_to_cap")
        and int(_rv_result.get("capped_qty") or 0) >= 1):
    qty = int(_rv_result["capped_qty"])

# AFTER (fix):
_rv_summary = _rv_result.get("summary", {}) if isinstance(_rv_result, dict) else {}
if (_rv_summary.get("size_reduced_to_cap")
        and int(_rv_summary.get("capped_qty") or 0) >= 1):
    qty = int(_rv_summary["capped_qty"])
    # Also recompute risk_amount proportionally:
    _new_risk = round(_old_risk * qty / _old_qty, 2)
    sizing["quantity"] = qty
    sizing["risk_amount"] = _new_risk
    # Emit SIZE_REDUCED_TO_CAP pipeline event (fully auditable)
```

Additional changes in this fix:
- `sizing["risk_amount"]` updated to reflect reduced quantity (was not updated previously)
- `_rv_result` enriched with `original_qty`, `capped_qty`, `original_risk_amount`, `capped_risk_amount` for evidence audit
- `SIZE_REDUCED_TO_CAP` pipeline event emitted with full payload (original qty, capped qty, price, risk before/after, trade value before/after, recalculated charges)

### Verification

Tests in `tests/unit/test_size_reduced_to_cap.py`:
- `TestRvToDictStructure` — proves `size_reduced_to_cap` lives in `["summary"]` not at top level
- `TestPreTradeValidatorCapResize` — DRREDDY ₹6,500 × 30 → verdict APPROVED_WARN, summary shows cap_qty=15
- `TestExecutorCapWiring` — end-to-end through `create_paper_entry()` — trade uses qty≤15, event emitted

---

## Task 2 — Pre-Trade Validator False Rejection After Capping

### Finding

**File:** `risk_validation/pre_trade.py`, `validate_pre_trade()`

The validator ran all six checks **sequentially with the original quantity** even when `_check_position_size` had already detected SIZE_REDUCED_TO_CAP. As a result:

- `_check_post_trade_utilisation(symbol, fill_price, qty=30, ...)` was called with the original `qty=30`
- If 30 × ₹6,500 = ₹1,95,000 exceeded `cash_available`, an `INSUFFICIENT_CASH` **CRITICAL** was raised
- This CRITICAL promoted the verdict from APPROVED_WARN to **REJECTED**
- The trade was blocked even though 15 shares × ₹6,500 = ₹97,500 would fit perfectly

Similarly, `_check_capital_at_risk` and `_check_daily_risk` used the original (larger) `risk_amount`, potentially triggering false capital-at-risk violations.

### Fix Applied

**File:** `risk_validation/pre_trade.py`

`_check_position_size` now runs first. If it returns `size_reduced=True` and `cap_qty >= 1`, subsequent checks use the effective (capped) values:

```python
pos_m = metrics["position_size"]
if pos_m.get("size_reduced") and int(pos_m.get("capped_qty") or 0) >= 1:
    _eff_qty  = int(pos_m["capped_qty"])
    _eff_risk = round(risk_amount * _eff_qty / qty, 2)
else:
    _eff_qty  = qty
    _eff_risk = risk_amount

# All downstream checks now use _eff_qty / _eff_risk:
metrics["capital_at_risk"]  = _check_capital_at_risk(symbol, _eff_risk, ...)
metrics["post_utilisation"] = _check_post_trade_utilisation(symbol, fill_price, _eff_qty, ...)
metrics["daily_risk"]       = _check_daily_risk(symbol, _eff_risk, ...)
```

This means:
- DRREDDY with 15 capped shares: utilisation check uses ₹97,500 (correct), not ₹1,95,000 (wrong)
- No false INSUFFICIENT_CASH CRITICAL
- Only genuine failures (e.g. stock genuinely too expensive even at 1 share) produce REJECTED

---

## Task 3 — Data Path Confirmation

### Findings (confirmed from source code — no code changes)

| Claim | Status | Evidence |
|---|---|---|
| Scanner uses `LiveDataProvider` | ✓ Confirmed | `live_scan_engine.py:652` — `LiveDataProvider()` instantiated unconditionally |
| `LiveDataProvider` uses yfinance only | ✓ Confirmed | `live_data_provider.py` — `yf.download()` is the only OHLCV call |
| Scanner interval is `1d` (daily bars) | ✓ Confirmed | `live_data_provider.py:SCAN_INTERVAL = "1d"`, `SCAN_PERIOD = "6mo"` |
| Kite is NOT used in the scan path | ✓ Confirmed | `kite_quote_provider.py` is fully implemented but called only post-scan for two display metadata fields (`kite_connected`, `live_quote_source`); `ohlcv_source` is hardcoded `"yfinance (historical)"` |

**Consequence:** All price signals (entry, stop, target, R:R) are derived from yesterday's closing price. The system is a **daily EOD signal engine**, not an intraday system. This is not a bug in itself — it is the current design — but it must be stated accurately in all operator communications.

### Implementation Plan (for operator decision — no threshold tuning, paper only)

#### Option A — Kite LTP Overlay (Recommended, ~15 lines)

**What it does:** After `provider.fetch_batch()` in `run_live_scan()`, if `kite_session_verified()` returns True, fetch current LTP via `kite_quote_provider.get_ltp(sym)` for each symbol and overwrite `last_price` in the scan item. Sets `data_age_days=0.0`, `data_quality=LIVE`, `data_source="kite_live"`.

**What it does NOT do:** Does not change OHLCV bars used for indicator/strategy computation. Entry, stop, target still derive from daily bars. LTP overlay only affects the displayed "current price" and the `data_quality` field shown to operators.

**When to use:** Operator wants `quote_reliable=True` at exits and wants to see real NSE price during the trading session. Does not require any strategy changes. Kite session must be authenticated.

**Risk:** None to paper trades. Can be feature-flagged with `KITE_LTP_OVERLAY_ENABLED=true`.

#### Option B — True Kite Intraday Candles 5m/15m (~4–6 days work)

**What it does:** Replaces `LiveDataProvider` with `KiteIntradayCandleProvider`. Fetches 5m or 15m bars from Kite for today's session. Indicator engine, strategy engine, and scan engine recomputed on intraday bars.

**Implications:**
- All 6-month backtest calibration (trained on 1d bars) becomes invalid — strategies need re-validation on 5m/15m data
- WARMUP_BARS, SCAN_PERIOD all need adjustment
- Much larger data volume per scan (78 bars per 5m session vs 1 bar per day)
- Requires active Zerodha session during market hours; scan produces no data outside session

**Risk:** Significant. Strategies are backtested on daily data. Running them on 5m bars without re-validation would produce unreliable signals. Do not implement without a full strategy re-validation run.

#### Option C — yfinance Intraday (5m/15m) Fallback for Research Only

**What it does:** Fetch `period="1d"`, `interval="5m"` from yfinance as a research overlay. Does NOT replace the daily strategy evaluation. Provides a rough intraday context tab in the dashboard.

**Limitations:** yfinance 5m data has a 60-day history cap. Quality is inconsistent (missing bars during illiquid periods). Not suitable for signal generation. Acceptable for operator situational awareness only.

**Recommendation:** Do not present to operators as "live intraday data" — it is not. Label clearly as "Indicative intraday reference — not used for signal generation."

**Decision required from operator before any implementation begins.**

---

## Task 4 — Exploration Mode Daily-Close Price Bug

### Finding

**File:** `paper_exploration_engine.py`, `update_experimental_exits()`, lines 729–730

```python
from market_data import get_multiple_ltp
prices = get_multiple_ltp(symbols) or {}
```

`market_data.get_multiple_ltp()` calls `get_ltp()` which calls:

```python
fetch_ohlcv(symbol, period="5d", interval="1d")
# → returns yesterday's closing price
```

This means **MFE (Max Favorable Excursion), MAE (Max Adverse Excursion), and exit-trigger checks** in exploration mode all use yesterday's daily close, not any intraday price. Consequence:

- An experimental BUY at 10:30 AM will not have its stop-loss or target checked until the next daily close is available (at approximately 15:30 IST or later, once the bar closes and yfinance refreshes it)
- Intraday stop-loss hits are missed entirely until EOD
- MFE/MAE values are meaningful only on a per-day granularity

### Status: Documented — No Safe Fix Applied

No intraday price source is currently wired into the system (confirmed in Task 3). Replacing `get_ltp()` with a Kite intraday price requires Option A or Option B from Task 3 to be implemented first.

**What this means for operators:**
- Exploration mode is learning from daily EOD outcomes, not intraday exits
- Stops will not trigger intraday
- This is not causing financial loss (paper only, no real money) but it makes the MFE/MAE statistics unreliable for intraday strategy learning
- Until a live price source is wired, **exploration mode should be understood as a daily-bar simulation, not an intraday learning engine**

**Fix path:** Implement Task 3 Option A (Kite LTP overlay) first, then add a `get_ltp_from_kite_if_available(sym)` wrapper in `paper_exploration_engine.py` that checks `kite_session_verified()` before falling back to `market_data.get_ltp()`.

---

## Task 5 — Threshold Mismatch (Single Source of Truth)

### Finding

Three separate definitions of the same opportunity-score action thresholds existed:

| Location | STRONG BUY | BUY | WATCH |
|---|---|---|---|
| `config.py` (`OPP_HOT_BUY_THRESHOLD / OPP_BUY_THRESHOLD / OPP_WATCH_THRESHOLD`) | 85.0 | 70.0 | 50.0 |
| `market_scanner.py` (`ACTION_STRONG_BUY / ACTION_BUY / ACTION_WATCH`, hardcoded) | 78.0 | 62.0 | 42.0 |
| SOP v3.0 | 85.0 | 70.0 | 50.0 |

The scanner was using 62 as the BUY threshold while the SOP and config both said 70. A stock scoring 65 would appear as BUY in the scanner output but should have been WATCH according to both the SOP and the configuration.

### Fix Applied

**File:** `market_scanner.py`

```python
# BEFORE (hardcoded, mismatched):
ACTION_STRONG_BUY = 78.0
ACTION_BUY        = 62.0
ACTION_WATCH      = 42.0

# AFTER (single source of truth from config.py):
from config import OPP_HOT_BUY_THRESHOLD, OPP_BUY_THRESHOLD, OPP_WATCH_THRESHOLD

ACTION_STRONG_BUY = OPP_HOT_BUY_THRESHOLD   # 85.0
ACTION_BUY        = OPP_BUY_THRESHOLD        # 70.0
ACTION_WATCH      = OPP_WATCH_THRESHOLD      # 50.0
```

`ACTION_STRONG_BUY`, `ACTION_BUY`, and `ACTION_WATCH` remain exported from `market_scanner.py` (as they are re-imported by `live_scan_engine.py`), so no downstream import changes are needed. The values now derive from `config.py`.

**Operational effect:** Stocks that scored 62–69 previously appeared as BUY. They now appear as WATCH. This is a correction to match the stated SOP thresholds, not a strategy change. The underlying strategy evaluation and signal logic are unchanged.

**Single source of truth going forward:** Edit only `config.py` to change action thresholds. `market_scanner.py` and all downstream modules that import from it will automatically reflect the change.

---

## Confirmation: No Live Orders Placed

Verified across all five tasks:
- All changes are in paper-mode execution paths only (`phase20_executor.py`, `risk_validation/pre_trade.py`, `market_scanner.py`)
- No broker API calls added, modified, or enabled
- `LIVE_EXECUTION_ENABLED` remains `False` (default) — confirmed from `phase20_gates.py`
- `PAPER_TRADING_MODE = True` in `config.py` — unchanged
- No Zerodha order endpoints called in any modified code path
- Exploration mode changes are report-only (no code changes to `paper_exploration_engine.py`)

---

## DRREDDY / TMPV Resize Verification

**Scenario:** DRREDDY @ ₹6,500, portfolio ₹5,00,000, cap 20%

| Step | Value |
|---|---|
| Portfolio total | ₹5,00,000 |
| Cap amount (20%) | ₹1,00,000 |
| cap_qty = floor(₹1,00,000 / ₹6,500) | **15 shares** |
| Original sizing might request | 30 shares (₹1,95,000 = 39%) |
| Validator verdict (pre-fix) | APPROVED_WARN (SIZE_REDUCED_TO_CAP in summary) |
| Executor action (pre-fix, BUG) | Read top-level `_rv_result.get("size_reduced_to_cap")` → None → used 30 shares |
| Executor action (post-fix) | Read `_rv_summary["size_reduced_to_cap"]` → True → uses 15 shares |
| Risk amount (pre-fix) | Based on 30 shares (never recomputed) |
| Risk amount (post-fix) | Proportionally scaled: `risk_orig × 15 / 30` |
| Pipeline event (pre-fix) | None |
| Pipeline event (post-fix) | `SIZE_REDUCED_TO_CAP` with full payload |

**TMPV scenario:** TMPV @ ₹343, portfolio ₹5,00,000, cap 20% → cap_amount = ₹1,00,000 → cap_qty = 291. Original sizing at 1% capital rule → qty = floor(₹500 / ₹343) = 1 (risk-based, no cap issue). TMPV is low enough that the cap is unlikely to trigger at normal position sizes.

---

## Files Changed

| File | Task | Change |
|---|---|---|
| `artifacts/api-server/src/python/phase20_executor.py` | Task 1 | Read `size_reduced_to_cap`/`capped_qty` from `rv.to_dict()["summary"]`; recompute risk_amount; update sizing; emit `SIZE_REDUCED_TO_CAP` event |
| `artifacts/api-server/src/python/risk_validation/pre_trade.py` | Task 2 | Run position_size check first; use effective (capped) qty/risk for all downstream checks |
| `artifacts/api-server/src/python/market_scanner.py` | Task 5 | Import `OPP_HOT_BUY_THRESHOLD`, `OPP_BUY_THRESHOLD`, `OPP_WATCH_THRESHOLD` from `config.py`; remove hardcoded 78/62/42 |
| `artifacts/api-server/src/python/tests/unit/test_size_reduced_to_cap.py` | Task 1 | New test file: 12 tests covering validator, executor wiring, DRREDDY scenario, event emission |

---

## Outstanding Items (Require Operator Decision)

| Priority | Item | File | Decision needed |
|---|---|---|---|
| P0 | Kite LTP overlay | `live_scan_engine.py` | Implement Option A, B, or C (or accept yfinance-only) |
| P0 | Exploration mode exit prices | `paper_exploration_engine.py` | Accept daily-close limitation, or implement after Task 3 Option A |
| P1 | Scan-loop watchdog | `live_scan_engine.py` | Aug 11 showed 5 scans/min despite DB lock; add alert if >2 scans/min |
| P2 | R:R threshold gap | `live_scan_engine.py` / config | Scan gate = 1.5; execution gate = 2.0; signals 1.5–1.99 pass scan but blocked at execution — choose 1.5 everywhere or 2.0 everywhere |
| P3 | NULL reason backfill | `pipeline_events` DB | 15,447 RISK_REJECTED rows with `reason=NULL` — one idempotent SQL migration from `payload->'failed_gates'` |
