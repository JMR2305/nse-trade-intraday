# ApexQuant AI — Scan Count & Data Fetch Reference
**Date:** 2026-08-18 (post-session)  
**Production URL:** https://nse-trade-intraday.replit.app  

---

## PART 1 — CORRECT SCAN COUNT FOR 2026-08-18

### Summary

| Source | Count | What it measures |
|--------|-------|-----------------|
| `pipeline_events` SCAN_STARTED | **19** | Scans that acquired the lock and began |
| `pipeline_events` SCAN_COMPLETED | **18** | Scans that fully finished ← **authoritative** |
| API `/api/live-data/scan/status` → `scan_count_today` | **18** | DB-backed SCAN_COMPLETED count |
| API → `rotation` | **18** | Same as `scan_count_today` |
| Mission Control page | **19** | Counts SCAN_STARTED (includes 1 incomplete scan) |
| `scan_state` table rows | **1** | Single-snapshot store; keeps only the latest scan |

**Correct count: 18 completed scans, 19 started (1 scan started at 09:36 IST and never completed).**

---

### Full Per-Scan Breakdown (production DB, all 19 scan_ids)

| # | scan_id | Start IST | End IST | Duration | Status |
|---|---------|-----------|---------|----------|--------|
| 1 | `90485405f6c5` | 09:15:52 | 09:16:15 | 23 s | ✅ COMPLETED |
| 2 | `5b9ddd5fbb4c` | 09:21:40 | 09:21:59 | 19 s | ✅ COMPLETED |
| 3 | `e070bac6fcbc` | 09:27:39 | 09:27:56 | 17 s | ✅ COMPLETED |
| 4 | **`bf004caf48b5`** | **09:36:04** | — | — | ❌ STARTED ONLY — never completed |
| 5 | `9acc266e3395` | 09:39:40 | 09:39:58 | 18 s | ✅ COMPLETED |
| 6 | `0317f51f40fd` | 09:52:01 | 10:04:36 | 12 m 35 s | ✅ COMPLETED |
| 7 | `5ada78615b60` | 10:15:14 | 10:22:48 | 7 m 34 s | ✅ COMPLETED |
| 8 | `f3193a81f241` | 10:44:24 | 10:56:27 | 12 m 3 s | ✅ COMPLETED |
| 9 | `466001718153` | 11:19:59 | 11:39:39 | 19 m 40 s | ✅ COMPLETED |
| 10 | `a43c18c8561e` | 12:09:23 | 12:31:33 | 22 m 10 s | ✅ COMPLETED |
| 11 | `7f879e9d129c` | 13:00:21 | 13:23:02 | 22 m 41 s | ✅ COMPLETED |
| 12 | `f4c10f0c85ba` | 13:54:00 | 13:54:35 | 35 s | ✅ COMPLETED |
| 13 | `f48d95bcb3ce` | 13:59:47 | 14:00:08 | 21 s | ✅ COMPLETED |
| 14 | `2652e3a7c8d2` | 14:15:21 | 14:27:48 | 12 m 27 s | ✅ COMPLETED |
| 15 | **`114b4d2bd161`** | 14:40:01 | 14:43:53 | 3 m 52 s | ✅ COMPLETED ← DRREDDY entry scan |
| 16 | `47ded37ac449` | 14:45:16 | 14:45:37 | 21 s | ✅ COMPLETED |
| 17 | `2e23e7c1a314` | 14:51:14 | 14:51:33 | 19 s | ✅ COMPLETED |
| 18 | `34fe9b162bc0` | 15:05:53 | 15:18:52 | 13 m | ✅ COMPLETED |
| 19 | `6a55aefb0622` | 15:26:14 | 15:26:32 | 18 s | ✅ COMPLETED ← last scan of day |

All 19 scan_ids confirmed with `mode = LIVE` in `pipeline_events`.

---

### Why Mission Control Shows 19, API Shows 18

- **API counts SCAN_COMPLETED events** via `count_scans_today_ist()` in `scan_state_store.py`
- **Mission Control shows the `rotation` field** which equals `scan_count_today` from the same API (18), but during the session it was live-updating and showed 19 when the incomplete scan (#4 at 09:36) was counted before it was clear it had failed
- **The 1-gap:** scan `bf004caf48b5` started at 09:36:04 IST — only a SCAN_STARTED event, no SCAN_COMPLETED. Likely killed by a lock timeout or server restart. The next scan started at 09:39:40 IST.

---

### Why 18–19, Not 75 (the SOP was wrong)

The SOP stated "~75 scans per full session" based on the calculation: 375 min ÷ 5-min cadence = 75 ticks. **This was the scheduler tick count, not actual completed scans.**

**The key fact:** individual scans take 7–22 minutes each. While a scan is running, its lock is held. All subsequent 5-minute scheduler ticks fire but find the lock held and skip. Only after the slow scan finishes can a new one begin.

| Scan speed | Examples | Cause |
|------------|---------|-------|
| 17–23 seconds (fast) | Scans 1–3, 5, 12–13, 16–17, 19 | yfinance data cached / minimal symbols changed |
| 3–13 minutes (medium) | Scans 6, 7, 8, 14, 15, 18 | Partial yfinance cache misses |
| 19–22 minutes (slow) | Scans 9, 10, 11 | Full yfinance bulk download for 50 NSE symbols |

The **"77 scans"** figure in `APEXQUANT_FINAL_PUBLISH_AND_BOOTSTRAP_TRADE_STATUS.md` was the scheduler's internal tick counter (every 5-minute clock pulse that fired, including skipped/locked ticks). The production DB has never had 77 SCAN_COMPLETED events in a single day.

**Confirmed by yesterday (2026-08-17):** 23 completed, 25 started — same pattern.

### Correct Expected Scan Range Per Session

| Session | Expected | Actual |
|---------|---------|--------|
| Full day 09:15–15:30 IST | **18–25 completed** | 18 (today), 23 (yesterday) |
| Scheduler ticks that fire | ~75–80 | 75–80 (but most skip due to lock) |

The SOP figure of "~75 per session" referred to scheduler ticks, not completed scans. The correct range is **18–25 completed scans per full session**.

---

## PART 2 — DATA FETCH ARCHITECTURE: yfinance vs Zerodha Kite

### The Short Answer

ApexQuant uses **both** sources, for entirely different jobs:

| Job | Source | Why |
|-----|--------|-----|
| Historical OHLCV bars (all candles) | **yfinance** | Bulk daily history, free, no rate limits |
| Technical indicators (MACD, RSI, Bollinger, ATR, Volume) | **yfinance daily bars** | Requires 20–200 days of history — hardcoded, never changes |
| Current live price (`current_price`, `execution_price`) | **Zerodha Kite LTP** | Real-time intraday quote for accurate entry/exit |
| Trade fill price | **Kite LTP** (slippage-adjusted) | Paper trade sized at the live market price |

This is declared explicitly in `kite_ltp_overlay.py`:

```python
indicator_source       = "yfinance_daily_bars"   # NEVER changes
ohlcv_source           = "yfinance_daily_bars"   # NEVER changes
current_price_source   = "kite_live_ltp"         # when Kite session is live
execution_price_source = "kite_live_ltp"         # when Kite session is live
```

---

### Why Not Use Kite for Everything?

**Kite's `quote()` API gives the current day's LTP and today's OHLC only — it does not provide historical daily bars.** To calculate MACD (26-day EMA), RSI (14-day), and Bollinger Bands (20-day) you need months of daily candles. Kite's Historical Data API can provide that, but:

| Constraint | Detail |
|------------|--------|
| Rate limits | Kite historical API throttles; 50 symbols × N candle calls = 50+ requests → hits limits mid-scan |
| Subscription | Kite historical data requires a higher-tier paid plan; not available on the base Kite Connect plan |
| Bulk fetch | yfinance `yf.download(50 tickers, period="6mo")` fetches all 50 symbols in a single request |

**yfinance is used because it is the only practical way to get months of daily OHLCV for all 50 NIFTY 50 symbols reliably and for free, in one bulk call.**

---

### Scan Flow — Step by Step

```
PHASE 1 — yfinance bulk download (the slow part: 7–22 minutes)
  yf.download(50 NIFTY symbols, period=6mo)
  → OHLCV daily bars for all 50 symbols

PHASE 2 — Indicator calculation (seconds)
  For each symbol:
    → MACD, RSI, Bollinger Bands, ATR, Volume ratio
    → All from yfinance bars — Kite not involved

PHASE 3 — AI signal engine (seconds)
  → confidence score, opportunity score
  → strategy selection (macd_cross, rsi_reversal, ...)
  → regime classification (Trending / Ranging / High-Vol)
  → BUY / WATCH / IGNORE decision

PHASE 4 — Kite LTP overlay (< 1 second)
  kite.quote([50 NSE symbols])             ← ONE bulk Kite API call
  → Replaces current_price + execution_price with live LTP
  → Indicators remain from yfinance — UNCHANGED

PHASE 5 — Risk gate + bootstrap executor (seconds)
  → Position sizing uses Kite LTP (accurate entry price)
  → Paper trade row created with Kite LTP as fill base
```

---

### What Happens When Kite Session Expires

When `kite_session_verified = false`:

- Phase 4 is skipped entirely
- `current_price_source` stays `yfinance_daily_bars` (yesterday's close)
- `quote_reliable = false` on every record
- **Bootstrap entries are blocked** — bootstrap requires `quote_reliable = true`
- Normal BUY entries are also blocked (entry gate requires a reliable price)
- Indicators and signal decisions are unaffected (still run on yfinance bars)

This is why re-verifying the Kite session at 09:00 IST every morning is mandatory — without it the system can scan and generate signals but cannot create any paper trades.

---

### Why Scans Are Slow (7–22 minutes)

The bottleneck is **yfinance**, not Kite:

- `yf.download()` for 50 `.NS` suffix symbols sends requests to Yahoo Finance's servers for Indian NSE stocks
- Yahoo Finance's NSE feed is slow — bulk pulls for 50 symbols with 6 months of history regularly take 7–22 minutes
- Kite's LTP call (Phase 4) takes < 1 second for all 50 symbols
- This is why only 18–25 actual scans complete per full session despite a 5-minute target cadence

---

*Source: `live_scan_engine.py` (Phase 1–3, Phase 2B), `kite_ltp_overlay.py`, `scan_state_store.py`*  
*All DB counts from production `pipeline_events` table, 2026-08-18.*  
*PAPER TRADING ONLY — no real orders.*
