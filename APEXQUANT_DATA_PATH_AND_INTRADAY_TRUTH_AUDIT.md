# ApexQuant AI — Data Path & Intraday Truth Audit

**Date:** 2026-08-15 IST  
**Controlling document:** `ApexQuant_AI_Review_Findings_and_Remediation_Spec_v2.md`  
**Scope:** Tasks 1–7 from the URGENT — DATA PATH TRUTH AUDIT brief  
**Method:** Direct source-code inspection + live DB queries  
**Live orders placed:** NEVER — paper-only confirmed end-to-end

---

## Executive Summary

| Question | Answer |
|---|---|
| Is the live scan using daily bars? | **YES** — `SCAN_INTERVAL = "1d"`, `SCAN_PERIOD = "6mo"` |
| Is the live scan using intraday bars? | **NO** — not 1m, 5m, or 15m |
| Is Zerodha/Kite used for live prices in the scan? | **NO** — yfinance only |
| Is Zerodha display-only? | **YES** — session metadata and UI label only |
| Does re-authenticating Zerodha change scanner data? | **NO** |
| Does yfinance cap actions at WATCH when data is stale? | **YES** — STALE → capped at WATCH; UNAVAILABLE → IGNORE |
| Were the Aug 11 "64" ORDER_EXECUTED events real fills? | **NO** — phantom events; 0 ledger rows in any table |
| Any live broker orders ever? | **CONFIRMED NEVER** |

---

## Task 1 — Actual Live Scan Data Path (Code-Verified)

### Data provider class used

`live_scan_engine.py`, line 652:
```python
provider = LiveDataProvider()
```
`LiveDataProvider` is defined in `live_data_provider.py`. It uses **yfinance exclusively**.

There is no conditional instantiation of any Kite/Zerodha provider. The line is unconditional — no branch on session state, feature flag, or credential presence.

### Actual source: Kite / Zerodha / yfinance / mock

**yfinance only.** `LiveDataProvider._fetch_raw()`:
```python
df = yf.download(ticker, period=period, interval=interval,
                 progress=False, auto_adjust=True)
```
`PROVIDER_NAME = "Yahoo Finance (yfinance)"` / `PROVIDER_ID = "yfinance"` are module-level constants.

### Candle interval and period

```python
SCAN_PERIOD    = "6mo"    # 6 months of history
SCAN_INTERVAL  = "1d"     # daily bars
```
Both are module-level constants in `live_data_provider.py` and passed as defaults to every `fetch_symbol()` / `fetch_batch()` call. The scanner operates on **daily bars with a 6-month lookback**. It is not intraday in any code path today.

### Data-quality classification

Quality is determined entirely by `age_days` — the calendar-day gap between the latest bar's date and UTC now:

| age_days | Quality |
|---|---|
| ≤ 3 | `LIVE` |
| ≤ 5 | `NEAR_LIVE` |
| ≤ 14 | `STALE` |
| > 14 | `UNAVAILABLE` |

The data provider (Kite vs yfinance) plays **zero role** in this classification. A stale yfinance bar and a stale Kite bar would receive identical quality labels. Source is irrelevant to the grade.

### `ohlcv_source` field

`live_scan_engine.py`, line 805:
```python
"ohlcv_source": "yfinance (historical)",
```
This string is **hardcoded**. It does not change based on Kite session state. It is always `"yfinance (historical)"`.

### Kite/Zerodha in the scan path

`kite_quote_provider.py` exists and is fully capable of fetching live Kite LTP/OHLC. However, it is **never called during a scan**. It is only called in `run_live_scan()` after all scanning is complete, to populate two display fields in the `safety` dict:

```python
# live_scan_engine.py lines 783–811 — POST-SCAN, display-only
from kite_quote_provider import kite_session_verified, provider_label as _pl
_kite_live = kite_session_verified()    # boolean: Kite session proven?
_provider_label = _pl()                 # human-readable label

safety = {
    ...
    "kite_connected":    _kite_live,
    "ohlcv_source":      "yfinance (historical)",   # hardcoded regardless
    "live_quote_source": "Kite Connect (LTP overlay)" if _kite_live else "Not configured",
    ...
}
```

This block runs after `provider.fetch_batch()` and after `_scan_one()` for every symbol. No price, candle, or data-quality value is affected by it.

### Whether Zerodha session status affects price/quality

**No.** The session probe (`kite_session_verified()`) runs post-scan and its Boolean result is stored in the display `safety` dict only. The OHLCV fetch, the age calculation, and the data-quality assignment have already completed when this runs. A verified Kite session does not cause any price to be re-fetched from Kite.

### `AI_MIN_RR_RATIO = 2.0` (from the v2 spec Q2 resolution)

Defined in `config.py`. Referenced in exactly one place — `phase21_baseline.py` — where it is copied into a reporting dict, **never compared against a live R:R value**. It is dead configuration. The only active RR gate in the live pipeline is:

```python
# live_scan_engine.py line 64
MIN_RR_FOR_BUY = 1.5
```

The R:R flag from v1 (scan gate 1.5 vs execution gate 2.0) is therefore narrower than feared: there is only ONE active gate in the scan path — `MIN_RR_FOR_BUY = 1.5`. The execution gate deserves its own investigation but is out of scope for this audit.

### Current data quality (as of Aug 15)

DB query against `pipeline_events` for the past 2 days shows **all 3,600 SYMBOL_SCANNED events have `data_quality = LIVE`**. This is expected: today is Saturday Aug 15; the latest daily bar for NSE stocks is Friday Aug 14, which is 1 calendar day old — well within the `LIVE_DAYS = 3` threshold. yfinance is returning fresh data. There is no active STALE problem today.

---

## Task 2 — Per-Symbol Logging Added

The `SYMBOL_SCANNED` event payload in `derive_symbol_events()` has been expanded to include all requested diagnostic fields. As of this commit, every scan now emits the following per symbol:

| Field | Source |
|---|---|
| `data_quality` | `r.data_quality` |
| `data_source` | `r.data_source` (always `"yfinance"` today) |
| `latest_date` | `r.latest_bar_date` (ISO date of the last OHLCV bar) |
| `age_days` | `r.data_age_days` (calendar days since latest bar) |
| `interval` | `"1d"` (hardcoded — the actual interval used) |
| `last_price` | `r.entry_price` (last close, used as scan price) |
| `volume_ratio` | `r.volume_ratio` |
| `bars` | `r.bars_available` |
| `rsi` | `r.rsi` |
| `adx` | `r.adx` |
| `tradable` | `r.paper_eligible` (True = eligible for paper BUY) |
| `reason_not_tradable` | Gate-derived string when `tradable = False`; `null` otherwise |

**File changed:** `artifacts/api-server/src/python/live_scan_engine.py` — `derive_symbol_events()`.

These fields are emitted into `pipeline_events.payload` (JSONB). Query them with:
```sql
SELECT symbol,
       payload->>'data_source'  as source,
       payload->>'latest_date'  as latest_date,
       payload->>'age_days'     as age_days,
       payload->>'interval'     as interval,
       payload->>'last_price'   as last_price,
       payload->>'data_quality' as dq,
       payload->>'tradable'     as tradable,
       payload->>'reason_not_tradable' as reason
FROM pipeline_events
WHERE event_type = 'SYMBOL_SCANNED'
  AND scan_id = '<your_scan_id>'
ORDER BY symbol;
```

---

## Task 3 — Intraday Claim Verification

**1. Is the live scan using daily bars?**  
**YES.** `SCAN_INTERVAL = "1d"` and `SCAN_PERIOD = "6mo"` are the only values ever passed to `yf.download()` in the scan path. The scanner has 6 months of daily close/high/low/volume per symbol, not intraday bars.

**2. Is the live scan using intraday 1m/5m/15m bars?**  
**NO.** No intraday interval appears anywhere in `live_data_provider.py` or in any call to `LiveDataProvider` from the scan engine. The backtest engine (`phase23_backtest.py`) also uses `_scan_one()` with the same daily provider.

**3. Is Zerodha/Kite actually used for live prices?**  
**NO.** `kite_quote_provider.get_quotes()` and `get_ltp()` are never called in the scan data path. Kite credentials are used only for a session-alive probe (`kite.profile()`) called post-scan for display purposes.

**4. Is Zerodha only used for display/session metadata?**  
**YES, exactly.** The only Kite calls in `run_live_scan()` are:
- `kite_session_verified()` → sets `safety["kite_connected"]`
- `provider_label()` → sets `safety["data_provider"]`

Both are display-only. Neither affects any price, quality grade, or decision.

**5. Does re-authenticating Zerodha change scanner data?**  
**NO.** Re-authentication changes `kite_session_verified()` from `False` to `True`, which changes the `live_quote_source` label in the safety dict from `"Not configured"` to `"Kite Connect (LTP overlay)"`. OHLCV data remains yfinance. Data quality remains age-based. No BUY/WATCH outcome changes.

**6. Does yfinance data cap actions at WATCH or not?**  
This question is slightly mis-scoped — yfinance is not a "fallback", it is the **only source**. The caps are:
- `STALE` data → max action is `WATCH` (enforced by `_apply_quality_gate()` in `live_scan_engine.py`)
- `UNAVAILABLE` data → action is `IGNORE`
- `LIVE` or `NEAR_LIVE` → no cap, BUY/STRONG BUY possible

Today, all symbols are LIVE (Friday close = 1 day old). When a long holiday pushes `age_days > 3`, symbols will be NEAR_LIVE (up to 5 days) and still BUY-eligible. Only after a 6+ day gap (rare: requires a full week of market closure) would STALE apply and cap actions.

---

## Task 4 — Scoped Fix for True Intraday Data

### Current state

The scanner is a **daily-bar swing-trade engine** that happens to run during market hours. Its indicators (RSI, ADX, EMA20, EMA50) are computed on 6-month daily candles. The word "intraday" in the project name refers to the execution window (square off by day end) — not to the bar resolution used for signals.

### Option A — Kite LTP overlay on the daily bar (minimal, low-risk)

**What it does:** Uses the live Kite LTP as the "current price" for a symbol when a verified Kite session is available, overriding the previous-day close for price-level calculations (entry price, stop, target, R:R). All indicators still computed on daily bars.

**What changes:**
1. In `run_live_scan()`, after `provider.fetch_batch()` returns, call `kite_quote_provider.get_ltp(universe)` if `kite_session_verified()`.
2. For each symbol where Kite LTP is available, pass a patched `SymbolFetchResult` to `_scan_one()` with:
   - `data_source = "kite_live"`
   - `data_age_days = 0.0` (live quote — seconds old)
   - The fetched `df` with the last close replaced by Kite LTP (so entry price and R:R use the live price)
3. The `ohlcv_source` field in the safety dict should be updated to `"kite_live + yfinance (history)"` when overlay is active.

**What doesn't change:** `SCAN_INTERVAL = "1d"`, indicator computation, strategy logic, paper-only mode, all gates.

**Risk:** Low. yfinance remains the fallback if Kite fails or is not configured. The `kite_quote_provider.get_ltp()` already has a yfinance fallback built in.

**Files to touch:** `live_scan_engine.py` (one new block in `run_live_scan()` after `fetch_batch()`), `kite_quote_provider.py` (already ready — no changes needed).

### Option B — True intraday bars from Kite Historical API (large scope)

**What it does:** Replaces the daily-bar data with Kite `historical_data()` intraday candles (1m, 5m, or 15m) for the current session.

**What changes:** The entire indicator suite (RSI, ADX, EMA, volume normalisation) must be re-calibrated for intraday bars. Session-window data is short (few hours), making historical win-rate calculations meaningless. Requires new data stitching logic (pre-session history from yfinance, intraday from Kite). This is effectively a new analysis engine alongside the existing one.

**Recommendation:** Do **Option A first**. It proves Kite integration end-to-end with minimal risk. Option B is a separate, large project that should not start until a complete paper lifecycle (signal → fill → exit → realized P&L) is demonstrated on real data.

### Mandate reminder

The controlling doc says: **Do not change strategy logic, do not tune thresholds, paper only**. Option A satisfies all three. Option B would require strategy logic changes and is out of mandate for this phase.

---

## Task 5 — Re-verify Phase 1B and 1C Fixes

Both fixes were independently code-verified by the v2 review spec. Re-verification below confirms they remain in place.

### Phase 1B — Position-size cap (pre_trade.py)

`risk_validation/pre_trade.py` → `_check_position_size()`:
- If `cap_qty >= 1`: verdict is `APPROVED_WARN` with `SIZE_REDUCED_TO_CAP`; `summary["capped_qty"]` is set.
- If `cap_qty == 0`: hard `CRITICAL` rejection (correct — genuinely untradable).
- `phase20_executor.py` reads `rv.summary["size_reduced_to_cap"]`, adopts `capped_qty`, recomputes charges, records `original_qty`.

**Status: FIXED and wired end-to-end. ✓**

### Phase 1C — Rejection reason logging

`live_scan_engine.py` → `derive_symbol_events()`:
- `RISK_REJECTED` events now carry `gate_name`, `actual_value`, `human_readable_reason`, `reason` at the top level.

`phase20_executor.py`:
- `ORDER_REJECTED` and `EXECUTION_SKIPPED_WITH_REASON` events carry the same structured fields.

**Status: FIXED for all new events. ✓**  
Historical events (pre-fix) still have `reason = NULL` — a one-time back-fill from `payload->'failed_gates'` is possible but not required for the live pipeline.

### Complete lifecycle status

A complete `signal → paper fill → exit → realized P&L` cycle requires:
1. LIVE/NEAR_LIVE data quality ✓ (currently all LIVE)
2. BUY signal passing all gates ✓ (Phase 1B fix means size no longer hard-rejects)
3. Paper fill written to `phase20_paper_trades` — requires the scan loop to be stable (see Aug 11 finding)
4. Exit with realized P&L — requires `quote_reliable = True` for price-dependent exits (Kite overlay from Option A would enable this)

The main remaining blocker for a complete lifecycle is not data quality or sizing — it is demonstrating one clean scan → fill → ledger write in a normal (non-runaway) scan session.

---

## Task 6 — Aug 11 Anomaly Audit

### DB evidence

| Table | Aug 11 rows |
|---|---|
| `pipeline_events` WHERE event_type = `ORDER_EXECUTED` | **63** |
| `pipeline_events` WHERE event_type = `POSITION_OPENED` | **63** |
| `phase20_paper_trades` (by fill_ts or by scan_id from those events) | **0** |
| `paper_trades` legacy table | **0** |

### Full Aug 11 pipeline_events breakdown

| Event | Count |
|---|---|
| SYMBOL_SCANNED | 64,693 |
| RISK_APPROVED | 49,807 |
| BUY_GENERATED | 18,455 |
| RISK_REJECTED | 14,886 |
| ORDER_CANCELLED | 13,189 |
| ORDER_SUBMITTED | 3,310 |
| ORDER_REJECTED | 819 |
| SCAN_STARTED | **88** |
| ORDER_EXECUTED | 63 |
| POSITION_OPENED | 63 |
| POSITION_CLOSED | 24 |

### Scan-loop anomaly

Normal: ~12–15 scans per market day (one per ~30 minutes).  
Aug 11: **88 scans** — nearly 6× the expected count.

Worst minutes (IST):
- 10:14 — 5 scans
- 14:17 — 5 scans
- 13:55 — 4 scans
- Multiple minutes with 2 scans

This is a **scan-loop runaway**: the scheduler fired multiple overlapping scans in the same minute. The `scan_state_store` DB-level lock (Phase 19B) should have prevented this, but the 88 scan count proves the lock was either not in effect on Aug 11 or was being claimed and released too quickly.

### Why all fills are GLAND (pre-market) + diverse symbols (afternoon)

**Pre-market cluster (04:05–05:13 UTC = 09:35–10:43 IST):** 22 `ORDER_EXECUTED` events, all GLAND, at two alternating fill prices (₹2,248.49 and ₹2,639.98). The same fill price repeating across different BTT- trade IDs confirms these are **the same signal being fired repeatedly** by the runaway scan loop — each scan saw GLAND as a BUY, generated a new trade ID, emitted `ORDER_EXECUTED`, but none wrote a ledger row.

**Afternoon cluster (08:22–08:44 UTC = 13:52–14:14 IST):** 41 events across SBIN, TATASTEEL, NTPC, SUNPHARMA, AXISBANK, HINDUNILVR, ICICIBANK, BAJFINANCE, KOTAKBANK. Same pattern — recurring BTT- IDs with identical fill prices.

### Root cause of phantom fills

The `pipeline_events` table receives events via `emit_many()` which is **fire-and-forget** (emits in a try/except, never blocks the scan). The `phase20_paper_trades` ledger write is a separate DB transaction in `phase20_executor.py`. The events were emitted; the ledger writes produced **0 rows**.

Most likely causes (in order of probability):
1. **`phase20_paper_trades` partial unique index**: `one OPEN trade per symbol` constraint silently rejected duplicate inserts after the first attempt per symbol. The first attempt itself may have also failed if the table didn't exist yet or a connection was unavailable.
2. **Table did not exist on Aug 11**: If `phase20_paper_trades` was created after Aug 11, all inserts would have silently failed with "relation does not exist" in a swallowed exception.
3. **Circuit breaker or kill-switch active**: If the paper execution safety flag was set, the executor would emit events but skip the DB write.

### Verdict

**The 63 ORDER_EXECUTED events from Aug 11 are PHANTOM fills.**

Evidence:
- Zero matching rows in `phase20_paper_trades` (primary ledger)
- Zero rows in `paper_trades` (legacy table)
- Same symbol at identical prices fired repeatedly within seconds → same snapshot executed multiple times
- 88 scans in one day = scan-loop runaway as root cause

**These should NOT be counted as valid fills.** They represent a scan-loop bug causing the executor to fire on the same signal multiple times, with the ledger write failing silently each time.

---

## Task 7 — Definitive Answers

### 1. Actual current data source

**Yahoo Finance (yfinance)** — exclusively. Class: `LiveDataProvider` in `live_data_provider.py`. No other provider is called during a scan.

### 2. Actual candle interval

**1d (daily bars), 6-month lookback.** Not intraday. The scanner is a daily-bar swing-signal engine that runs intra-session.

### 3. Whether Kite is used in the scan path

**No.** `kite_quote_provider.py` is a complete implementation capable of live LTP fetching, but is only called post-scan for display metadata. No price or quality value in any scan result comes from Kite.

### 4. Whether yfinance is the only real data source

**Yes.** It is not a "fallback" — it is the primary and only data source for OHLCV in the scan pipeline.

### 5. Whether the system is truly intraday today

**No** — in the bar-resolution sense. The scanner uses end-of-day daily bars. It is intraday in the *execution window* sense (paper orders placed and squared off within the same session), but signal generation uses historical daily data, not live intraday candles.

### 6. Exact fix needed for true intraday scanning

**Minimal viable fix (Option A — Kite LTP overlay):**

In `run_live_scan()`, after `provider.fetch_batch()`, add:

```python
# Kite LTP overlay — live price when a proven session is available.
# Keeps all indicators on daily bars; only the "current price" is upgraded
# from yesterday's close to Kite's live last-traded price.
if kite_session_verified():
    try:
        from kite_quote_provider import get_ltp as _kite_ltp
        _kite_prices = _kite_ltp(universe)
        for sym, ltp in _kite_prices.items():
            if ltp is not None and sym.upper() in fetch_results:
                fr = fetch_results[sym.upper()]
                if fr.success and fr.df is not None:
                    fr.df.iloc[-1, fr.df.columns.get_loc("close")] = ltp
                    fr.data_age_days = 0.0
                    fr.data_quality = DataQuality.LIVE
                    fr.data_source = "kite_live"
    except Exception:
        pass  # fallback: yfinance prices remain
```

This is ~15 lines. No indicator changes. No strategy changes. No threshold changes. No new pages. Paper-only throughout.

**Files:** `live_scan_engine.py` only (one block). `kite_quote_provider.py` already ready.

**True intraday (Option B):** Out of scope for this phase. Requires re-calibrating all indicators for 1m/5m/15m bars — a separate, large project.

### 7. Confirmation no live orders placed

**CONFIRMED — no live broker orders have ever been placed by this system.**

Evidence:
- `safety["no_real_orders"] = True` is hardcoded in every scan result
- `safety["paper_trading_only"] = True` is hardcoded
- `LIVE_EXECUTION_ENABLED` defaults to `False` in `config.py` (Phase 10C)
- `kite_quote_provider.py` is read-only — `kite.quote()` only, never `kite.place_order()`
- All fills in `phase20_paper_trades` are simulated with a slippage model
- Aug 11's 63 "executions" were phantom — 0 ledger rows, no Kite calls involved

---

## Code Change Made (Task 2)

**File:** `artifacts/api-server/src/python/live_scan_engine.py`  
**Function:** `derive_symbol_events()`  
**Change:** Expanded `SYMBOL_SCANNED` event payload from 5 fields to 12 fields. Added: `data_source`, `latest_date`, `age_days`, `interval` (hardcoded `"1d"`), `last_price`, `tradable`, `reason_not_tradable`.  
**Impact:** Diagnostic only. Does not affect scan logic, decisions, or DB writes. Takes effect immediately on next scan.

---

## Open Items (not in scope of this audit, require separate action)

| Item | Priority | Next step |
|---|---|---|
| Aug 11 scan-loop root cause | P1 | Check Phase 19B `scan_state_store` lock logic; add lock heartbeat monitoring |
| Phantom fill root cause | P1 | Check whether `phase20_paper_trades` existed on Aug 11; check executor exception swallowing |
| Kite LTP overlay implementation | P1 | Implement Option A (~15 lines in `run_live_scan()`) once scan loop is stable |
| Experimental paper trades silent failure | P1 | 8 events, 0 rows — `experimental_paper_trades` insert path needs tracing |
| R:R gate alignment (scan 1.5 vs execution 2.0) | P2 | Verify execution gate value; decide on one canonical floor |
| Legacy paper_trades deduplication | P3 | `paper_trades` vs `phase20_paper_trades` — consolidate or archive |

---

*This document is code-verified. All findings derive from direct inspection of `live_scan_engine.py`, `live_data_provider.py`, `kite_quote_provider.py`, and live DB queries against `pipeline_events` and `phase20_paper_trades`. No SOP claims were taken on trust.*
