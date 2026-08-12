# TATAMOTORS / TMPV / TMCV Symbol Mapping Fix Report

**Date:** 2026-08-12  
**Scope:** Symbol remapping after Tata Motors 2024 demerger. No strategy logic, thresholds, live defaults, or order flow changed. Paper/research only.

---

## 1. Investigation Findings

### Instrument Master Check

| Symbol | yfinance (NSE .NS) | Live Price | Status |
|--------|--------------------|------------|--------|
| `TATAMOTORS.NS` | `ERROR: 'exchangeTimezoneName'` | — | **INVALID** — demerged, exchange metadata broken |
| `TMPV.NS` | ✅ Works | **₹343.0** | Live and tradeable |
| `TMCV.NS` | ✅ Works | **₹457.05** | Live and tradeable |
| `TATAMOTORS-BE.NS` | `ERROR: 'exchangeTimezoneName'` | — | **INVALID** |

The `'exchangeTimezoneName'` error is yfinance's symptom for a symbol whose exchange metadata is no longer available — consistent with a demerger restructuring on the NSE exchange.

The price of `~₹768.62` previously shown for `TATAMOTORS` was a **stale/historical close** from before the demerger. It does not represent any currently tradeable instrument on NSE.

### NSE Successor Instruments (Post-Demerger)

| NSE Symbol | Full Name | Sector | Live Price (2026-08-12) |
|-----------|-----------|--------|------------------------|
| `TMPV` | Tata Motors Passenger Vehicles Ltd | Auto | ₹343.0 |
| `TMCV` | Tata Motors Commercial Vehicles Ltd | Auto | ₹457.05 |

Both instruments are confirmed live on NSE, accessible via yfinance (`TMPV.NS`, `TMCV.NS`), and return valid `fast_info` data.

### Where TATAMOTORS Appeared

| File | Location | Notes |
|------|----------|-------|
| `config.py` | `SECTOR_MAP["AUTO"]` | Drives `NIFTY_50` universe — source of truth for scanner, whitelist, live quotes |
| `symbol_validation.py` | `COMPANY_NAMES` | Name-search lookup |
| `preopen_provider.py` | `FIXTURE_SNAPSHOTS` (line 207) | Mock pre-open fixture: prev_close=900, ind=864 |
| `risk_validation/correlation.py` | `_load_sector_map()` | Sector-level correlation estimator |
| `trading-dashboard/src/pages/` | 5 pages: `StrategyLab`, `Optimizer`, `Validate`, `Backtest`, `AIValidationV2Page` | Hardcoded symbol picker lists |
| `trading-dashboard/src/lib/phase1-connectivity.test.ts` | Test fixture `missing_symbols` | Test data |

---

## 2. Fixes Applied

### 2A — `config.py` — Universe / NIFTY_50 (Primary fix)

`SECTOR_MAP["AUTO"]` was the canonical source for the scan universe, quote whitelist, and sector-strength computation. Replaced `TATAMOTORS` with both successor instruments.

```python
# Before:
"AUTO": ["MARUTI", "TATAMOTORS", "BAJAJ-AUTO", "EICHERMOT", "M&M", "HEROMOTOCO"]

# After:
"AUTO": ["MARUTI", "TMPV", "TMCV", "BAJAJ-AUTO", "EICHERMOT", "M&M", "HEROMOTOCO"]
```

Effect: `NIFTY_50` (derived from `SECTOR_MAP`) now contains `TMPV` and `TMCV` instead of `TATAMOTORS`. This automatically propagates to:
- `live_quote_service._ALLOWED` whitelist
- `symbol_validation.validate_symbol` universe check
- All scan pipeline universe filtering

### 2B — `symbol_validation.py` — Three changes

**i. `COMPANY_NAMES` updated:**
```python
# Removed: "TATAMOTORS": "Tata Motors"
# Added:
"TMPV": "Tata Motors Passenger Vehicles Ltd",
"TMCV": "Tata Motors Commercial Vehicles Ltd",
```

**ii. `ALIASES` updated:**
```python
"TATA MOTORS PV": "TMPV",
"TATA MOTORS CV": "TMCV",
```

**iii. `DEPRECATED_SYMBOLS` dict added** (new concept):

```python
DEPRECATED_SYMBOLS: Dict[str, Dict[str, str]] = {
    "TATAMOTORS": {
        "reason": "TATAMOTORS was demerged in 2024...",
        "replacement": "TMPV",
        "also_see": "TMCV",
        "deprecated_since": "2024",
        "action": "DATA_UNAVAILABLE — no BUY allowed",
    },
}
```

**iv. `validate_symbol` — deprecated check added** (fires before the generic "outside universe" check):

```python
if sym in DEPRECATED_SYMBOLS:
    return {
        "valid": False,
        "reason": "...",  # specific demerger explanation
        "deprecated": True,
        "replacement": "TMPV",
        "also_see": "TMCV",
        "action": "DATA_UNAVAILABLE — no BUY allowed",
    }
```

Operators attempting to add `TATAMOTORS` to the watchlist, scan universe, or paper portfolio now receive: `"'TATAMOTORS' is deprecated — TATAMOTORS was demerged... Use 'TMPV' (and 'TMCV') instead."` — not a cryptic "outside universe" rejection.

### 2C — `live_quote_service.py` — Demerged-symbol guard

Added `_DEMERGED` dict and an early-exit path in `get_quotes()` for demerged symbols. This fires **before any yfinance call** — no network request is made, no stale price is returned.

```python
_DEMERGED: dict[str, str] = {
    "TATAMOTORS": "TATAMOTORS was demerged in 2024 into TMPV (~₹343) and TMCV (~₹457)...",
}

# In get_quotes():
if sym in _DEMERGED:
    quotes[sym] = {
        "ltp": None,
        "quality": "UNAVAILABLE",
        "tradable": False,           # ← new field: signals non-tradable to UI
        "demerger_note": _DEMERGED[sym],
        "error": "DATA UNAVAILABLE — TATAMOTORS is demerged. No BUY allowed.",
        ...
    }
    continue
```

The `tradable: False` flag is consumed by the updated `LiveDataHealth.tsx` (see §2F).

### 2D — `preopen_provider.py` — Fixture updated

```python
# Before:
{"symbol": "TATAMOTORS", "prev_close": 900.0, "ind_price": 864.0, ...}

# After:
{"symbol": "TMPV", "prev_close": 340.0, "ind_price": 343.0, ...}
```

### 2E — `risk_validation/correlation.py` — Sector map updated

```python
# Before:
"MARUTI": "Auto", "TATAMOTORS": "Auto", "HEROMOTOCO": "Auto"

# After:
"MARUTI": "Auto", "TMPV": "Auto", "TMCV": "Auto", "HEROMOTOCO": "Auto"
```

### 2F — `LiveDataHealth.tsx` — Non-tradable label (Task 7 UI)

Quote display updated to clearly label demerged/STALE symbols as non-tradable:

```tsx
{q?.tradable === false
  ? "DATA UNAVAILABLE — no BUY allowed · yfinance"   // red text
  : q?.ltp != null
  ? `₹${q.ltp} (${...}) · ${q.quality}${staleWarning} · ${q.source}`
  : `Unavailable · ${q?.quality}`}
```

Demerged symbols render in **red** with `DATA UNAVAILABLE — no BUY allowed`. STALE quotes append `⚠ NON-TRADABLE`. Both show the quote source provider name.

### 2G — 5 Dashboard pages — Symbol picker lists

All pages that hardcoded `"TATAMOTORS"` in their expandable symbol arrays now use `"TMPV", "TMCV"`:

| Page | Change |
|------|--------|
| `StrategyLab.tsx` | `TATAMOTORS` → `TMPV`, `TMCV` |
| `Optimizer.tsx` | `TATAMOTORS` → `TMPV`, `TMCV` |
| `Validate.tsx` | `TATAMOTORS` → `TMPV`, `TMCV` |
| `Backtest.tsx` | `TATAMOTORS` → `TMPV`, `TMCV` |
| `AIValidationV2Page.tsx` | `TATAMOTORS` → `TMPV`, `TMCV` |

### 2H — `phase1-connectivity.test.ts` — Test fixture

```typescript
// Before:
missing_symbols: ["LTIM", "TATAMOTORS"]
// After:
missing_symbols: ["LTIM", "TMPV"]
```

---

## 3. Verification Results

All checks passed (exit 0):

```
SECTOR_MAP AUTO: ['MARUTI', 'TMPV', 'TMCV', 'BAJAJ-AUTO', 'EICHERMOT', 'M&M', 'HEROMOTOCO']
TATAMOTORS in NIFTY_50: False ✅
TMPV in NIFTY_50: True ✅
TMCV in NIFTY_50: True ✅

DEPRECATED_SYMBOLS: TATAMOTORS → replacement=TMPV, also_see=TMCV ✅

COMPANY_NAMES: TATAMOTORS=(not present), TMPV=Tata Motors Passenger Vehicles Ltd ✅

validate_symbol(TATAMOTORS): valid=False, deprecated=True, replacement=TMPV ✅
validate_symbol(TMPV): valid=True ✅
validate_symbol(TMCV): valid=True ✅

TATAMOTORS in _DEMERGED: True ✅
TATAMOTORS in _ALLOWED: False ✅
TATAMOTORS quote: ltp=None, quality=UNAVAILABLE, tradable=False ✅

TMPV.NS live price: ₹343.0 ✅  (NSE-consistent)
TMCV.NS live price: ₹457.05 ✅  (NSE-consistent)
```

---

## 4. BUY Signal Safety (existing engine — no changes needed)

The live scan engine (`live_scan_engine.py`) already has a data-quality gate that was active before this fix:

```python
UNAVAIL_GUARD_ACTION = "IGNORE"

def _apply_quality_gate(action, quality):
    if quality == DataQuality.UNAVAILABLE:
        return UNAVAIL_GUARD_ACTION, "Data UNAVAILABLE — capped to IGNORE"
    if quality == DataQuality.STALE:
        if action in ("BUY", "STRONG BUY"):
            return STALE_GUARD_ACTION, "Data STALE — BUY/STRONG BUY blocked"
    return action, ...
```

**With these fixes:**
- `TATAMOTORS` is not in `NIFTY_50` → excluded from all scan universes
- `TATAMOTORS` is in `_DEMERGED` → returns `UNAVAILABLE` / `tradable=False` immediately if queried directly
- `TATAMOTORS` fails `validate_symbol` with `deprecated=True` → cannot be added to watchlist or portfolio
- **Old `TATAMOTORS` cannot produce any BUY or STRONG BUY signal** through any code path

---

## 5. What Was NOT Changed

- Strategy logic, signal thresholds, quality weights — untouched
- Live trading mode defaults (`PAPER_TRADING_MODE = True` — unchanged)
- Zerodha/broker execution flow — untouched
- `DEFAULT_WATCHLIST` and `watchlist.json` — TATAMOTORS was never in either ✅
- Phase 20 paper ledger, paper trades — no TATAMOTORS positions exist ✅
- Kite instrument cache (`kite_instruments_cache.json`) — minimal (4 instruments); TATAMOTORS was not in it

---

## 6. Files Changed

| File | Change |
|------|--------|
| `artifacts/api-server/src/python/config.py` | Replace `TATAMOTORS` with `TMPV`, `TMCV` in `SECTOR_MAP["AUTO"]` |
| `artifacts/api-server/src/python/symbol_validation.py` | `COMPANY_NAMES` update; add `DEPRECATED_SYMBOLS`; deprecated check in `validate_symbol` |
| `artifacts/api-server/src/python/live_quote_service.py` | Add `_DEMERGED` guard; `tradable: False` on demerged quotes |
| `artifacts/api-server/src/python/preopen_provider.py` | Fix fixture: TATAMOTORS → TMPV |
| `artifacts/api-server/src/python/risk_validation/correlation.py` | Fix sector map: TATAMOTORS → TMPV + TMCV |
| `artifacts/trading-dashboard/src/pages/LiveDataHealth.tsx` | Non-tradable badge; source label; STALE warning |
| `artifacts/trading-dashboard/src/pages/StrategyLab.tsx` | TATAMOTORS → TMPV, TMCV |
| `artifacts/trading-dashboard/src/pages/Optimizer.tsx` | TATAMOTORS → TMPV, TMCV |
| `artifacts/trading-dashboard/src/pages/Validate.tsx` | TATAMOTORS → TMPV, TMCV |
| `artifacts/trading-dashboard/src/pages/Backtest.tsx` | TATAMOTORS → TMPV, TMCV |
| `artifacts/trading-dashboard/src/pages/AIValidationV2Page.tsx` | TATAMOTORS → TMPV, TMCV |
| `artifacts/trading-dashboard/src/lib/phase1-connectivity.test.ts` | Fix test fixture |
