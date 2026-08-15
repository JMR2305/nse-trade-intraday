# APEXQUANT AI — Next Session Kite LTP Validation Report

**Controlling document:** APEXQUANT_AI_SOP_v4.0.html  
**Prepared:** 2026-08-16 IST (Sunday — pre-market preparation)  
**Report type:** Pre-flight static verification + market-hours placeholder  
**Market status:** CLOSED — market-hours sections (Tasks 3–6) populated with current DB baseline; fill in during next trading session

---

## Summary Table

| Check | Status | Notes |
|-------|--------|-------|
| `KITE_LTP_OVERLAY_ENABLED=true` set | ✅ DONE | Set in shared env 2026-08-16 |
| `LIVE_EXECUTION_ENABLED` disabled | ✅ CONFIRMED | Hardcoded paper-only in executor |
| `PAPER_TRADING_MODE=True` | ✅ CONFIRMED | Hardcoded in config.py |
| `place_order` absent in all 5 overlay files | ✅ CONFIRMED | AST grep — zero matches |
| `modify_order` absent in all 5 overlay files | ✅ CONFIRMED | AST grep — zero matches |
| `cancel_order` absent in all 5 overlay files | ✅ CONFIRMED | AST grep — zero matches |
| Overlay module imports correctly | ✅ CONFIRMED | All 4 functions available |
| Overlay test suite | ✅ 37/37 passing | Post-flag-enable re-run 2026-08-16 |
| Test regression from env change | ✅ FIXED | `test_missing_config_returns_false` — import sentinel |
| Zerodha session verified | ⏳ PENDING | Requires Kite Connect login before 09:15 IST |
| First-scan symbol proof | ⏳ PENDING | Fill from first market scan |
| EXIT_PENDING resolution | ⏳ PENDING | Will run on first scan after session login |
| New paper BUY execution | ⏳ PENDING | Depends on live signal + Kite session |
| Live orders placed | ✅ NEVER | Zero — confirmed structurally and by test |

---

## Task 1 — Enable Kite LTP Overlay ✅ COMPLETE

### Flag Status
| Variable | Value | Source | Verified |
|----------|-------|--------|---------|
| `KITE_LTP_OVERLAY_ENABLED` | `true` | Replit shared env | ✅ set 2026-08-16 |

### Config Layer Confirmation
```
config.py:142  KITE_LTP_OVERLAY_ENABLED: bool = (
config.py:143      _os.getenv("KITE_LTP_OVERLAY_ENABLED", "false").lower() == "true"
```
Default is `"false"` — env var now overrides to `"true"`.

### Safety Invariants (Static Verification)
| Invariant | File | Status |
|-----------|------|--------|
| `PAPER_TRADING_MODE = True` (hardcoded) | `config.py:135` | ✅ confirmed |
| `LIVE_EXECUTION_ENABLED` — paper path only | `phase20_executor.py` | ✅ confirmed |
| `place_order` — absent | All 5 overlay-path files | ✅ zero matches |
| `modify_order` — absent | All 5 overlay-path files | ✅ zero matches |
| `cancel_order` — absent | All 5 overlay-path files | ✅ zero matches |
| Only `kite.quote()` used (read-only) | `kite_quote_provider.py` | ✅ confirmed |
| `indicator_source = "yfinance_daily_bars"` (never changes) | `kite_ltp_overlay.py` | ✅ invariant enforced + tested |
| `ohlcv_source = "yfinance_daily_bars"` (never changes) | `kite_ltp_overlay.py` | ✅ invariant enforced + tested |
| LTP=0 rejected | `kite_ltp_overlay.py` | ✅ tested |
| LTP=None rejected | `kite_ltp_overlay.py` | ✅ tested |
| `flag=false` → zero Kite API calls | `kite_ltp_overlay.py` | ✅ tested |

### Test Suite Result (Post-Flag-Enable)
```
37 passed, 1 warning in 0.37s
```
One test (`test_missing_config_returns_false`) failed because the real env var is now `true`. 
**Fixed 2026-08-16**: changed `_remove_module("config")` to `sys.modules["config"] = None` (import sentinel) so the test properly simulates a broken import regardless of env state. All 37 now pass.

### Module Availability
```python
from kite_ltp_overlay import (
    is_overlay_enabled,      # reads KITE_LTP_OVERLAY_ENABLED from config
    fetch_ltp_overlay,       # bulk Kite quote call for all symbols
    build_symbol_overlay,    # per-symbol overlay dict from LTP result
    apply_overlay_to_rec,    # patches Phase7Recommendation in-place
)
# All 4 functions available — confirmed 2026-08-16
```

---

## Task 2 — Pre-Market Readiness Check

> **Run this before 09:15 IST on next trading day. Fill in results below.**

### Pre-Market Checklist
```
[ ] Kite Connect login complete at /kite-auth before 09:15 IST
[ ] System Readiness page (/system-readiness) returns GO or WARNING (not BLOCKED)
[ ] Kite session probe: kite.profile() returns HTTP 200
[ ] KITE_LTP_OVERLAY_ENABLED shows "true" in Live Data Health (/live-data-health)
[ ] Scheduler shows HEALTHY (last scan within 2× configured interval)
[ ] Circuit breaker: CLEAR
[ ] DB: writable + readable (pipeline_events INSERT succeeds)
[ ] No BLOCKED domains in System Readiness
```

### Pre-Market Report Template
```
Date/Time:              _______________
Readiness state:        GO / WARNING / NO-GO
Kite session status:    CONNECTED / UNAVAILABLE
KITE_LTP_OVERLAY_ENABLED: true (confirmed)
Price source (current): kite_live_ltp / yfinance_daily_bars
Price source (exec):    kite_live_ltp / yfinance_daily_bars
Indicator source:       yfinance_daily_bars (always)
Scheduler:              HEALTHY / DEGRADED / DOWN
Circuit breaker:        CLEAR / TRIPPED
DB writable:            YES / NO
Blocking issue:         NONE / [describe]
```

---

## Task 3 — First Market Scan Verification

> **Fill in after first market-hours scan. Run `/live-data-health` and inspect SYMBOL_SCANNED events.**

### Current DB Baseline (pre-session, 2026-08-14 last trading day)

**Last session event summary (last 2 trading days):**
| Event | Count |
|-------|-------|
| SYMBOL_SCANNED | 3,600 |
| STRATEGY_SELECTED | 3,600 |
| RISK_APPROVED | 3,503 |
| WATCH_GENERATED | 1,926 |
| IGNORE_GENERATED | 1,626 |
| BUY_GENERATED | 48 |
| ORDER_REJECTED | 201 |
| RISK_REJECTED | 97 |
| SCAN_STARTED | 72 |
| SCAN_COMPLETED | 72 |
| ORDER_SUBMITTED | 0 |
| ORDER_EXECUTED | 0 |
| EXPERIMENTAL_PAPER_TRADE_PLACED | 9 |

**Baseline note:** 0 ORDER_SUBMITTED on last trading day (2026-08-14). All 48 BUY_GENERATED were blocked — 201 rejections (position size / duplicate position) + 97 RISK_REJECTED. With SIZE_REDUCED_TO_CAP and Kite LTP overlay both active, execution rate should improve.

### First-Scan Symbol Table (fill in)
| Symbol | Action | Confidence | Opp Score | yfinance_last_close | kite_ltp | current_price_source | exec_price_source | indicator_source | ohlcv_source | quote_reliable | dq_indicators | dq_execution |
|--------|--------|------------|-----------|---------------------|----------|----------------------|-------------------|------------------|--------------|----------------|---------------|--------------|
| DRREDDY | | | | | | | | yfinance_daily_bars | yfinance_daily_bars | | | |
| TMPV | | | | | | | | yfinance_daily_bars | yfinance_daily_bars | | | |
| TMCV | | | | | | | | yfinance_daily_bars | yfinance_daily_bars | | | |
| BAJAJ-AUTO | | | | | | | | yfinance_daily_bars | yfinance_daily_bars | | | |
| GRASIM | | | | | | | | yfinance_daily_bars | yfinance_daily_bars | | | |
| BAJFINANCE | | | | | | | | yfinance_daily_bars | yfinance_daily_bars | | | |
| DIVISLAB | | | | | | | | yfinance_daily_bars | yfinance_daily_bars | | | |
| TRENT | | | | | | | | yfinance_daily_bars | yfinance_daily_bars | | | |
| RELIANCE | | | | | | | | yfinance_daily_bars | yfinance_daily_bars | | | |
| TCS | | | | | | | | yfinance_daily_bars | yfinance_daily_bars | | | |

**Expected when Kite session verified:**
- `indicator_source` = `yfinance_daily_bars` for ALL symbols (invariant)
- `ohlcv_source` = `yfinance_daily_bars` for ALL symbols (invariant)  
- `current_price_source` = `kite_live_ltp` for symbols where LTP returned
- `execution_price_source` = `kite_live_ltp` for symbols where LTP returned
- `quote_reliable` = `True` for symbols with Kite LTP

---

## Task 4 — EXIT_PENDING Resolution

### Current State (DB — 2026-08-16)
| Trade ID | Symbol | Fill Price | Qty | Stop Loss | Target | Exit Rule Set | Status |
|----------|--------|------------|-----|-----------|--------|---------------|--------|
| P20-4a5f909738 | BAJFINANCE | ₹1,100.05 | 8 | ₹1,037.67 | ₹1,280.59 | STALE_DATA_SAFETY | EXIT_PENDING |
| P20-83aa1be8f9 | GRASIM | ₹3,223.63 | 3 | ₹3,085.54 | ₹3,618.58 | STALE_DATA_SAFETY | EXIT_PENDING |
| P20-a205b1ef09 | DIVISLAB | ₹8,370.04 | 1 | ₹7,982.41 | ₹9,482.77 | STALE_DATA_SAFETY | EXIT_PENDING |
| P20-acad172b74 | TRENT | ₹3,082.42 | 3 | ₹2,931.53 | ₹3,370.34 | STALE_DATA_SAFETY | EXIT_PENDING |

**All 4 positions have `realized_pnl = NULL`** — blocked because `quote_reliable=False` (yfinance daily close is not LIVE quality).

### Resolution Mechanism (v4.0)
With `KITE_LTP_OVERLAY_ENABLED=true` and a verified Kite session:
1. `kite_ltp_overlay.fetch_ltp_overlay([BAJFINANCE, GRASIM, DIVISLAB, TRENT, ...])` runs after analysis
2. Each rec gets `kite_ltp_available=True`, `quote_reliable=True`, `data_quality_for_execution="LIVE"`
3. `phase20_exits.manage_open_positions()` evaluates all 8 exit rules with live LTP as `quote`
4. `_retry_pending()` forces `dq="LIVE"` → eligibility check passes → exit rules fire
5. The triggering exit rule closes the position and writes `realized_pnl`

**Do not force-close.** Only record exit if a rule actually triggers.

### Resolution Check (fill in after first scan)
| Symbol | Kite LTP | quote_reliable | Exit rule triggered? | Exit reason | Exit price | realized_pnl |
|--------|----------|----------------|----------------------|-------------|------------|--------------|
| BAJFINANCE | | | | | | |
| GRASIM | | | | | | |
| DIVISLAB | | | | | | |
| TRENT | | | | | | |

**If no exit triggers:** record which rules were evaluated and why they did not fire (e.g., current price is between stop and target → no STOP_LOSS_HIT and no TARGET_HIT; TIME_EXIT not yet due; TRAILING_STOP requires peak ≥ fill+2R first).

---

## Task 5 — Paper BUY Execution Proof

### BUY Execution Evidence Template
Fill in if a BUY candidate appears during the session:

```
Symbol:                    _______________
Scan ID:                   _______________
signal_price (daily bar):  ₹_____________
kite_ltp:                  ₹_____________
fill_price (kite ± slip):  ₹_____________
quantity:                   ___
SIZE_REDUCED_TO_CAP:       YES (cap_qty=___) / NO
evidence.signal_price_from_daily_bar:    ₹_____________
evidence.execution_price_from_kite_ltp:  ₹_____________
phase20_paper_trades row written:        YES / NO
trade_id (P20- prefix):    P20-___________
ORDER_SUBMITTED event:     YES / NO
ORDER_EXECUTED event:      YES / NO
place_order called:        NO (paper-only — confirmed)
```

### If No BUY — Top Candidate Gate Reasons (fill in)
| Rank | Symbol | Action | Confidence | Opp Score | R:R | Block reason |
|------|--------|--------|------------|-----------|-----|--------------|
| 1 | | | | | | WATCH / R:R_GAP (1.5–1.99) / CONFIDENCE_LOW / OPP_LOW / DUPLICATE / CIRCUIT_BREAKER / DATA |
| 2 | | | | | | |
| 3 | | | | | | |
| 4 | | | | | | |
| 5 | | | | | | |
| 6 | | | | | | |
| 7 | | | | | | |
| 8 | | | | | | |
| 9 | | | | | | |
| 10 | | | | | | |

**Most likely remaining gate:** signals with 1.5 ≤ R:R < 2.0 pass the scan gate but are blocked at the execution gate (`min_risk_reward=2.0` in settings). This is the primary remaining blocker after SIZE_REDUCED_TO_CAP fix. See SOP v4.0 §4.4.

---

## Task 6 — Post-Market Summary (fill in after 15:30 IST)

### Session Statistics
| Metric | Value |
|--------|-------|
| Scan count | |
| Symbols scanned | |
| BUY_GENERATED | |
| WATCH_GENERATED | |
| IGNORE_GENERATED | |
| RISK_APPROVED | |
| RISK_REJECTED | |
| ORDER_SUBMITTED | |
| ORDER_EXECUTED | |
| ORDER_REJECTED | |
| EXECUTION_SKIPPED | |
| Top rejection reason | |

### Portfolio State
| Metric | Value |
|--------|-------|
| Open positions | |
| Closed positions (today) | |
| Realized P&L (today) | |
| Portfolio cash remaining | |

### Clean Cycle Verdict
```
Signal → Paper Fill → Exit → P&L complete cycle:   YES / NO / PARTIAL
```

### Operator Analytics (/operator-analytics)
```
[Paste summary from /operator-analytics page]
```

### System Readiness (post-market)
```
Readiness state:      GO / WARNING / NO-GO
Overlay still active: YES / NO
Kite session state:   CONNECTED / EXPIRED
Any degraded domains: [list]
```

---

## Task 7 — Formal Assessment

### 1. Kite LTP Overlay Active
**Status: ✅ YES — flag set, module verified, 37/37 tests pass**

`KITE_LTP_OVERLAY_ENABLED=true` is live in the shared environment as of 2026-08-16. The `kite_ltp_overlay.py` module loads correctly. All Option A invariants are enforced in code and verified by tests. The overlay activates silently at Phase 2B of the scan loop after yfinance analysis completes. If Kite session is unavailable, it falls back to yfinance daily close without error.

### 2. Zerodha Session Verified
**Status: ⏳ PENDING — requires Kite Connect login before 09:15 IST**

Session proof requires `kite.profile()` to return HTTP 200 with a valid user object. This cannot be verified without an active login. The system handles the unavailable case gracefully — all 4 Exit_PENDING positions will remain pending until session is established.

**Action required before next market session:** Log in via the Kite Connect flow at `/kite-auth` before 09:15 IST.

### 3. First Scan Symbol-Level Proof
**Status: ⏳ PENDING — fill from first market-hours scan**

The `SYMBOL_SCANNED` pipeline events now carry `kite_ltp_available`, `current_price_source`, `execution_price_source`, `indicator_source`, and `quote_reliable` fields (added in v4.0). Query after first scan:

```sql
SELECT symbol, payload->>'action' as action,
       payload->>'kite_ltp' as kite_ltp,
       payload->>'current_price_source' as price_source,
       payload->>'indicator_source' as indicator_source,
       payload->>'quote_reliable' as quote_reliable
FROM pipeline_events
WHERE event_type = 'SYMBOL_SCANNED'
  AND scan_id = (SELECT scan_id FROM pipeline_events
                  WHERE event_type = 'SCAN_COMPLETED'
                  ORDER BY ts DESC LIMIT 1)
ORDER BY symbol;
```

### 4. EXIT_PENDING Positions Resolved
**Status: ⏳ PENDING — will run on first scan with Kite session**

DB confirms all 4 positions (BAJFINANCE, GRASIM, DIVISLAB, TRENT) are `EXIT_PENDING` with `realized_pnl = NULL`. The `_retry_pending()` path in `phase20_exits.py` will evaluate exit rules with live Kite LTP on the first scan after session login. Exit is only recorded if a rule triggers — no forced closes.

### 5. New Paper BUY Executed
**Status: ⏳ PENDING — depends on live signal quality + Kite session**

The SIZE_REDUCED_TO_CAP wiring bug is fixed (Bug Audit Task 1). The false CRITICAL pre-trade rejection is fixed (Bug Audit Task 2). The scanner threshold mismatch is fixed (Bug Audit Task 5). With Kite LTP overlay active, execution prices will be live LTP rather than yesterday's close.

**Primary remaining gate to watch:** `min_risk_reward=2.0` (settings default) vs scan gate `1.5`. Signals with 1.5 ≤ R:R < 2.0 pass scanning but are blocked at execution. If no BUY executes, check this gate first.

### 6. Gate Reasons for No Paper BUY
**Status: ⏳ PENDING — fill from session data**

Historical pattern (2026-08-14 baseline):
- 48 BUY_GENERATED → 0 ORDER_SUBMITTED
- 201 ORDER_REJECTED (position size / duplicate position)
- 97 RISK_REJECTED

With fixes active, the expected gating pattern on next session is:
1. SIZE_REDUCED_TO_CAP → proceeds (not rejected) ← **FIXED**
2. R:R gate 2.0 vs scan gate 1.5 → still blocking signals with R:R 1.5–1.99 ← **STILL OPEN**
3. Duplicate position (can't open second position same symbol) ← normal
4. Circuit breaker ← check pre-market

### 7. No Live Orders Placed
**Status: ✅ CONFIRMED — structural guarantee**

Four independent confirmations:
1. `PAPER_TRADING_MODE = True` — hardcoded in `config.py:135`, not an env var
2. `execute_buy()` calls `paper_trader.py`, not any Zerodha order API
3. `place_order`, `modify_order`, `cancel_order` absent from all 5 overlay-path files (grep confirmed)
4. Explicit unit test: `TestFeatureFlag::test_live_execution_remains_false` in `test_kite_ltp_overlay.py`

### 8. System Usable for Paper Intraday Observation
**Status: ✅ YES — with flag active**

With `KITE_LTP_OVERLAY_ENABLED=true`:
- All scan indicators remain on 6-month yfinance daily bars (unchanged quality)
- Execution prices use live Kite LTP → fills reflect actual NSE market price at scan time
- Exit quotes use live Kite LTP → EXIT_PENDING positions can resolve
- All safety controls unchanged: paper-only, no order placement, circuit breaker intact
- System is ready for intraday paper observation on next market session

### 9. Remaining Gap — True Intraday Candles Still Pending
**Status: ❌ OPEN — Option B is a separate project**

Option A (this implementation): Kite LTP overlays execution/exit price only. RSI, MACD, ADX, Bollinger, EMA are still computed from 6-month daily bars. This means:
- Signal generation quality is EOD-based (yesterday's close drives indicators)
- The platform does not adapt to intraday price moves within a session
- Stop/target distances are calibrated on daily ATR — suitable for multi-day holds, not tight intraday exits

**Option B (future):** True 1m/5m/15m Kite Historical API candles feed the indicator engine. All strategies need recalibration on short bars. Estimated 4–6 days of dedicated work. Do not implement without a full re-calibration run.

---

## Static Verification Artifacts

### Files Verified 2026-08-16
| File | Role | Verified |
|------|------|---------|
| `config.py` | `KITE_LTP_OVERLAY_ENABLED` env-var flag | ✅ lines 142–143 |
| `kite_ltp_overlay.py` | Overlay module — all 4 functions | ✅ imports OK |
| `live_scan_engine.py` | Phase 2B overlay loop | ✅ 14 new fields on Phase7Recommendation |
| `phase20_executor.py` | BUY fill price path | ✅ no place_order |
| `phase20_exits.py` | Exit quote + _retry_pending | ✅ no place_order |
| `phase27_readiness.py` | check_broker overlay context | ✅ non-blocking warning |
| `tests/unit/test_kite_ltp_overlay.py` | 37 unit tests | ✅ 37/37 passing |

### Test Regression Fix
```diff
- def test_missing_config_returns_false(self) -> None:
-     _remove_module("config")           # ← reimports from file, reads env=true → FAIL
+     sys.modules["config"] = None       # ← blocks import entirely → ImportError → False ✓
```
Fixed 2026-08-16. 37/37 tests pass post-fix.

### DB Snapshot (2026-08-16)
```
phase20_paper_trades: 4 rows (all EXIT_PENDING)
paper_portfolio: cash=₹50,000 (no closed-position P&L yet)
pipeline_events (last 2 trading days): 72 scans, 3,600 symbols, 48 BUY_GENERATED, 0 ORDER_EXECUTED
experimental_paper_trades: 0 rows (insert failure — separate open issue)
```

---

*Report generated 2026-08-16 IST. Market-hours sections (Tasks 2–6 results) to be filled in during next trading session. Static verification sections (Task 1, Task 7 items 1/7/9) are complete. No strategy parameters changed. No thresholds changed. PAPER ONLY.*
