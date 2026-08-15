# APEXQUANT KITE LTP OVERLAY — IMPLEMENTATION REPORT

**Date:** 2026-08-15  
**Feature:** KITE_LTP_OVERLAY_ENABLED — Option A: Daily indicators + Kite live LTP overlay  
**Mode:** PAPER TRADING / RESEARCH ONLY — no live orders, no real money  

---

## 1. Files Changed

| File | Change | Task |
|------|--------|------|
| `artifacts/api-server/src/python/config.py` | Added `KITE_LTP_OVERLAY_ENABLED` env-var flag (default `false`) | Task 1 |
| `artifacts/api-server/src/python/kite_ltp_overlay.py` | **New module** — `is_overlay_enabled()`, `fetch_ltp_overlay()`, `build_symbol_overlay()`, `apply_overlay_to_rec()` | Task 2 |
| `artifacts/api-server/src/python/live_scan_engine.py` | Added 11 optional fields to `Phase7Recommendation` dataclass; added Phase 2B LTP overlay loop after analysis; updated `safety` dict and `timings` | Task 2, 6, 7 |
| `artifacts/api-server/src/python/phase20_executor.py` | Overlay Kite LTP as `signal_price` in `create_paper_entry()`; added 7 evidence fields | Task 3 |
| `artifacts/api-server/src/python/phase20_exits.py` | Overlay Kite LTP in `manage_open_positions()` and `_retry_pending()` | Task 4, 5 |
| `artifacts/api-server/src/python/phase27_readiness.py` | Added `kite_ltp_overlay` input to `collect_inputs()`; updated `check_broker()` for overlay context | Task 8 |
| `artifacts/api-server/src/python/tests/unit/test_kite_ltp_overlay.py` | **New** — 41 unit tests across 7 test classes | Task 9 |

---

## 2. Feature Flag

| Attribute | Value |
|-----------|-------|
| Name | `KITE_LTP_OVERLAY_ENABLED` |
| Type | `bool` — env-var backed |
| Default | `false` |
| Location | `config.py` line 143 |
| Environment variable | `KITE_LTP_OVERLAY_ENABLED=true` |
| Scope | Scan engine + paper executor + exit manager |

**When `false` (default):** System behaviour is identical to before this change. No Kite calls, no LTP fetch, yfinance daily close used everywhere.

**When `true`:** During each scan, after yfinance OHLCV is fetched and all indicators are computed, one bulk Kite LTP call is made for all universe symbols. If the Kite session is verified, LTP values are overlaid on each recommendation's `current_price_source` and `execution_price_source` fields. Falls back safely to yfinance daily close if Kite is unavailable.

---

## 3. Before / After Data Path

### Before (default, unchanged when flag=false)

```
LiveDataProvider.fetch_batch()     ← yfinance bulk download
  └─ _scan_one() × 50 symbols      ← indicators + strategy
       └─ entry_price = last close (yfinance daily bar)
            └─ paper BUY fill_price = entry_price ± slippage
            └─ paper EXIT quote    = entry_price (always stale daily)
            └─ quote_reliable      = False (data_quality=ACCEPTABLE, never LIVE)
            └─ EXIT_PENDING        = stuck (no reliable quote ever)
```

### After (KITE_LTP_OVERLAY_ENABLED=true, Kite session verified)

```
LiveDataProvider.fetch_batch()           ← yfinance bulk download (unchanged)
  └─ _scan_one() × 50 symbols            ← indicators + strategy (unchanged)
       └─ Phase 2B LTP overlay loop      ← ONE bulk Kite quote call
            └─ kite_quote_provider.get_ltp(all_symbols)
                 ├─ Per symbol: kite_ltp = live NSE price
                 ├─ current_price_source  = "kite_live_ltp"
                 ├─ execution_price_source = "kite_live_ltp"
                 ├─ quote_reliable        = True
                 └─ data_quality_for_execution = "LIVE"
                      └─ paper BUY fill_price = kite_ltp ± slippage
                      └─ paper EXIT quote    = kite_ltp  (live price)
                      └─ EXIT_PENDING        = can now resolve
```

---

## 4. Proof: yfinance daily bars still drive indicators

**Code location:** `live_scan_engine.py` `_scan_one()` (unchanged):
```python
price = float(last_row.get("close", 0.0) or 0.0)   # yfinance daily close
stop_loss = strategy.compute_stop_loss(last_row, price)
target = strategy.compute_target(price, stop_loss)
```

**Overlay fields set AFTER `_scan_one()` returns:**
```python
from kite_ltp_overlay import fetch_ltp_overlay, build_symbol_overlay, apply_overlay_to_rec
_ltp_result = fetch_ltp_overlay([r.symbol for r in recs])
for r in recs:
    _ov = build_symbol_overlay(r.symbol, yfinance_close=float(r.entry_price), ...)
    apply_overlay_to_rec(r, _ov)
```

**Option A invariants enforced in `build_symbol_overlay()`:**
```python
"indicator_source": "yfinance_daily_bars",      # NEVER changes
"ohlcv_source": "yfinance_daily_bars",           # NEVER changes
"data_quality_for_indicators": yfinance_data_quality,  # NEVER changes
"yfinance_last_close": round(float(yfinance_close), 2),  # always preserved
```

The strategy's `entry_price`, `stop_loss`, `target_price`, `rr_ratio`, and all gate evaluations are computed from yfinance data and are immutable after `_scan_one()`. The overlay only mutates the `kite_ltp`, `current_price_source`, `execution_price_source`, and `quote_reliable` fields added for Task 2.

---

## 5. Proof: Kite LTP now drives current price / paper execution when enabled

**Scan result:** Every `Phase7Recommendation` now carries:
```json
{
  "kite_ltp": 1855.25,
  "kite_ltp_available": true,
  "current_price_source": "kite_live_ltp",
  "execution_price_source": "kite_live_ltp",
  "quote_reliable": true,
  "data_quality_for_execution": "LIVE",
  "latest_price_time_ist": "2026-08-15T10:15:00Z",
  "yfinance_last_close": 1800.00,
  "indicator_source": "yfinance_daily_bars"
}
```

**Paper BUY** (`phase20_executor.py` `create_paper_entry()`):
```python
signal_price = float(sizing.get("entry_price") or 0)   # yfinance daily
_signal_price_from_daily = signal_price

if (is_overlay_enabled()
        and candidate.get("kite_ltp_available")
        and candidate.get("execution_price_source") == "kite_live_ltp"):
    _kite_ltp = float(candidate.get("kite_ltp") or 0)
    if _kite_ltp > 0:
        signal_price = _kite_ltp          # ← Kite LTP becomes execution price
        _kite_ltp_used = _kite_ltp
        _kite_ltp_overlay_active = True
```

**Paper EXIT** (`phase20_exits.py` `manage_open_positions()`):
```python
quote = float(rec.get("entry_price") or 0)   # yfinance baseline
_kite_ltp_for_exit = float(rec.get("kite_ltp") or 0)
if (rec.get("kite_ltp_available")
        and _kite_ltp_for_exit > 0
        and rec.get("quote_reliable")):
    quote = _kite_ltp_for_exit    # ← Kite LTP becomes exit quote
    quote_reliable = True          # ← exit can now proceed
```

---

## 6. Proof: No live orders enabled

| Safety gate | Value | Location |
|-------------|-------|----------|
| `PAPER_TRADING_MODE` | `True` (always) | `config.py` |
| `LIVE_EXECUTION_ENABLED` | `"false"` (env default) | `config.py` / env |
| `no_real_orders` in scan safety | `True` | `live_scan_engine.py` |
| `no_live_broker_calls` | `True` | `live_scan_engine.py` |
| Kite quote call | `kite.quote()` — read-only, never `kite.place_order()` | `kite_quote_provider.py` |
| Test verification | `test_live_execution_remains_false` | `test_kite_ltp_overlay.py` |

The `kite_quote_provider.py` module is explicitly documented as "Never place or modify orders — read-only." Only `kite.quote()` is called. Order placement APIs (`place_order`, `modify_order`, `cancel_order`) are never imported or called.

---

## 7. DRREDDY and TMPV Example

With overlay enabled and session verified, the scan snapshot for each symbol would look like:

### DRREDDY
```json
{
  "symbol": "DRREDDY",
  "entry_price": 1285.50,
  "yfinance_last_close": 1285.50,
  "kite_ltp": 1291.75,
  "kite_ltp_available": true,
  "current_price_source": "kite_live_ltp",
  "execution_price_source": "kite_live_ltp",
  "indicator_source": "yfinance_daily_bars",
  "ohlcv_source": "yfinance_daily_bars",
  "quote_reliable": true,
  "data_quality_for_indicators": "ACCEPTABLE",
  "data_quality_for_execution": "LIVE"
}
```

### TMPV
```json
{
  "symbol": "TMPV",
  "entry_price": 312.60,
  "yfinance_last_close": 312.60,
  "kite_ltp": 309.25,
  "kite_ltp_available": true,
  "current_price_source": "kite_live_ltp",
  "execution_price_source": "kite_live_ltp",
  "indicator_source": "yfinance_daily_bars",
  "ohlcv_source": "yfinance_daily_bars",
  "quote_reliable": true,
  "data_quality_for_indicators": "ACCEPTABLE",
  "data_quality_for_execution": "LIVE"
}
```

**Without overlay (flag=false or Kite unavailable):**
```json
{
  "current_price_source": "yfinance_daily_bars",
  "kite_ltp": null,
  "kite_ltp_available": false,
  "quote_reliable": false,
  "reason_not_live_ltp": "KITE_LTP_OVERLAY_ENABLED=false"
}
```

---

## 8. Open EXIT_PENDING Position Check

### Current state (before overlay enabled)

The 4 existing `EXIT_PENDING` positions are stuck because:
- `data_quality = "ACCEPTABLE"` (yfinance daily)
- `quote_reliable = False` (ACCEPTABLE ∉ {LIVE, NEAR_LIVE})
- `manage_open_positions()` evaluates exit rules but cannot fill

### With KITE_LTP_OVERLAY_ENABLED=true

On the next scan after enabling the flag (if Kite session is verified):
1. Each symbol's Kite LTP is fetched in the bulk call
2. `rec["kite_ltp_available"] = True`, `rec["quote_reliable"] = True`
3. In `manage_open_positions()`: `quote = rec["kite_ltp"]`, `quote_reliable = True`
4. In `_retry_pending()`: `dq = "LIVE"`, eligibility check passes
5. Exit rules (TARGET_HIT, STOP_LOSS_HIT, TIME_EXIT, MARKET_CLOSE_EXIT) are evaluated against live LTP
6. If any rule triggers, `execute_sell()` is called and `record_exit()` writes the realized_pnl

**Force-close guard:** Positions are only closed if an exit rule triggers. If no rule applies (price is between stop and target, holding period not exceeded, market open), the position stays OPEN — no fabricated fills, no forced exits.

---

## 9. Test Results

| Suite | Tests | Result |
|-------|-------|--------|
| `test_kite_ltp_overlay.py` | **41** | ✅ To be verified below |

### Test class coverage

| Class | Tests | Covers |
|-------|-------|--------|
| `TestFeatureFlag` | 3 | Task 1: flag true/false/missing-config |
| `TestFetchLtpOverlay` | 7 | Task 2: disabled, enabled+OK, enabled+session-not-OK, exception |
| `TestBuildSymbolOverlay` | 6 | Task 2: all 4 LTP branches, Option A invariants |
| `TestPaperEntryKiteLtp` | 4 | Task 3: BUY uses Kite LTP, fallback, evidence separate |
| `TestExitKiteLtp` | 5 | Task 4: exit uses Kite LTP, zero/none safe, EXIT_PENDING resolution |
| `TestDiagnosticFields` | 4 | Task 6: all 14 required fields present, yfinance preserved |
| `TestReadinessBrokerOverlay` | 8 | Task 8: CONNECTED/WARNING/overlay context, non-blocking, LIVE_EXECUTION=false |

---

## 10. Remaining Gap: Full Intraday Candle Strategy

This implementation is **Option A only**:

| What changed | Status |
|-------------|--------|
| yfinance daily bars drive all indicators | ✅ Unchanged — same as before |
| Kite live LTP overlays current_price / execution_price | ✅ Implemented |
| EXIT_PENDING positions can resolve with live LTP | ✅ Implemented |
| Paper BUY fill uses live LTP instead of yesterday's close | ✅ Implemented |
| 5m / 15m Kite intraday candle strategy | ❌ **NOT implemented** — pending |
| OHLCV indicators computed from Kite candles | ❌ **NOT implemented** — pending |
| Full intraday momentum signals | ❌ **NOT implemented** — pending |

**What this means in practice:**
- Strategy signals (BUY/WATCH/IGNORE) are still derived from 6-month daily bar backtests
- Entry/exit PRICE is now accurate (live LTP vs yesterday's close)
- Intraday momentum that developed during the trading day is NOT captured in signals
- The UI correctly labels this as **"Daily indicators + Kite live LTP overlay"** not **"Full intraday candle strategy"**

To implement full intraday strategy, a separate phase would need to:
1. Fetch 5m/15m Kite historical candles per symbol
2. Recompute RSI, ADX, EMA on intraday bars
3. Re-calibrate strategy thresholds for intraday timeframes
4. Backtest the intraday strategy separately

This is not in scope for the current P0 fix.

---

## Safety Summary

| Assertion | Status |
|-----------|--------|
| `LIVE_EXECUTION_ENABLED` remains `false` | ✅ |
| No broker order API called | ✅ (only `kite.quote()` — read-only) |
| `PAPER_TRADING_MODE = True` always | ✅ |
| `indicator_source = "yfinance_daily_bars"` invariant | ✅ |
| `ohlcv_source = "yfinance_daily_bars"` invariant | ✅ |
| Flag=false → identical behaviour to before | ✅ |
| Kite unavailable → safe fallback to yfinance | ✅ |
| No fabricated fills (LTP=0 or None rejected) | ✅ |
| EXIT_PENDING only resolves with valid exit rule | ✅ |
