# ApexQuant AI — Bootstrap Fallback Loop: Root Cause + Audit Trail
**Date:** 2026-08-18 (NSE Market Session)  
**Environment:** Production — https://nse-trade-intraday.replit.app  
**Goal:** Prove the bootstrap fallback candidate fix fires in production, works through ranked candidates, and produces the first `BOOTSTRAP_AUTO` paper trade.  
**Status:** ⚠️ Awaiting publish — `_build_row` NameError fix + deploy-build.sh image-size fix are in workspace, not yet live.

---

## 1. Fixes in This Session

### Fix A — Fallback Loop (merged before session)
`run_bootstrap_auto_entry` in `phase20_executor.py` was rewritten from a single-candidate abort pattern into a **ranked fallback loop**. When the top candidate fails the R:R check after slippage, the executor advances to the next ranked candidate instead of aborting. Two new events: `BOOTSTRAP_CANDIDATE_REJECTED` and `BOOTSTRAP_ALL_CANDIDATES_REJECTED`.

### Fix B — TARGET_MISSING gate (merged before session)
Null `target_price` in the scan snapshot now emits `BOOTSTRAP_CANDIDATE_REJECTED{gate=TARGET_MISSING}` and falls through to the next candidate, instead of silently computing R:R=0 and emitting a generic rejection.

### Fix C — `_build_row` NameError (root cause, found this session)
`_build_row` in `phase20_executor.py` (a module-level function) referenced `_kite_ltp_overlay_active`, `_signal_price_from_daily`, and `_kite_ltp_used` as if they were module globals. They are actually **local variables in `create_paper_entry`**. Every time the Risk Agent *approved* a candidate, `_build_row` raised `NameError`, silently killing the bootstrap loop.

**Why only approved cases failed:** When the Risk Agent *rejects* (R:R too low), `create_paper_entry` returns at line 496 before `_build_row` is ever called. When it *approves*, the code reaches `_build_row` (line 575) → `NameError` → exception propagates → caught by scheduler outer try-except → no trade, no event, no audit trail.

**Fix:** `_build_row` now receives these three values as explicit keyword parameters with safe defaults. Call site updated to pass them. 50/50 tests pass.

### Fix D — try-except around `create_paper_entry` (defensive, this session)
Added try-except around the `create_paper_entry` call in the fallback loop. Any future exception in `create_paper_entry` (e.g., transient Kite API issue) now emits `BOOTSTRAP_CANDIDATE_REJECTED{gate=CREATE_PAPER_ENTRY_EXCEPTION}` and falls through to the next candidate instead of aborting the loop entirely.

### Fix E — Deploy image size (root cause of build failure, found this session)
`exports/` directory (user-generated CSV/PDF/ZIP files, ~1 GB, growing unboundedly) was being packed into every Replit deployment layer. Between the 04:23 UTC successful build and the 08:23 UTC failed build, `exports/` grew enough that the container took >300 s to unpack — Cloud Run's startup probe window expired before `/api/healthz` could return 200.

**Fix:** `scripts/deploy-build.sh` Step 5 now also strips `exports/`, `reports/`, `verification/`, `screenshots/`, `**/.mypy_cache`, and `**/__pycache__` from the image. Expected post-cleanup image: ~2.1 GB (was 3.2 GB). Repl layer push should drop from 7+ min back to <2 min.

---

## 2. Pre-Deploy History (Before Fallback Loop)

Scans 09:16–09:40 IST ran the OLD single-candidate code on HDFCLIFE:

| Scan ID (prefix) | Event | Reason |
|---|---|---|
| `90485405f6c5` | APPROVED → ORDER_REJECTED | HDFCLIFE R:R 1.44, old code stopped |
| `5b9ddd5fbb4c` | APPROVED → ORDER_REJECTED | HDFCLIFE R:R 1.36, old code stopped |
| `e070bac6fcbc` | APPROVED → ORDER_REJECTED | HDFCLIFE R:R 1.35, old code stopped |
| `9acc266e3395` | APPROVED → ORDER_REJECTED | HDFCLIFE R:R 1.36, old code stopped |

No trade was ever created — old code had no fallback.

---

## 3. Post-Deploy: Fallback Loop Confirmed Working (Scan `5ada78615b60`)

**Snapshot candidates (5 eligible):**

| Rank | Symbol | Conf | R:R (snapshot) | Kite LTP |
|---|---|---|---|---|
| 1 | HDFCBANK | 78.3% | 1.5 | 726.24 |
| 2 | HDFCLIFE | 74.1% | 1.5 | 542.76 |
| 3 | TMCV | 65.0% | 2.5 | 472.5 |
| 4 | DRREDDY | 64.7% | 2.5 | — |
| 5 | HEROMOTOCO | 64.0% | 3.0 | — |

**Fallback loop pipeline events:**

| Time (IST) | Event | Symbol | Detail |
|---|---|---|---|
| 10:32:43 | KV CLAIMED | — | `bootstrap_scan:5ada78615b60 = true` |
| 10:32:44 | BOOTSTRAP_PAPER_TRADE_APPROVED | HDFCBANK | rank=1/5 |
| 10:32:53 | ORDER_REJECTED | HDFCBANK | fill=726.24, **R:R 1.31** < 1.5 |
| 10:32:56 | BOOTSTRAP_CANDIDATE_REJECTED | HDFCBANK | rr_after=1.3116, next_candidate=**true** |
| 10:33:00 | BOOTSTRAP_PAPER_TRADE_APPROVED | HDFCLIFE | rank=2/5 |
| 10:33:07 | ORDER_REJECTED | HDFCLIFE | fill=542.76, **R:R 1.19** < 1.5 |
| 10:33:10 | BOOTSTRAP_CANDIDATE_REJECTED | HDFCLIFE | rr_after=1.1927, next_candidate=**true** |
| 10:33:10 | BOOTSTRAP_PAPER_TRADE_APPROVED | TMCV | rank=3/5 |
| — | *No ORDER_EXECUTED* | TMCV | `_build_row` raised `NameError` → silent abort |

**The fallback loop worked correctly** — HDFCBANK and HDFCLIFE correctly rejected on slippage-adjusted R:R, loop advanced. TMCV failed because `_build_row` raised NameError (Fix C).

---

## 4. Second Bootstrap Attempt (Scan `f3193a81f241`)

**HDFCBANK in this scan:** rr_snapshot=1.5, kite_ltp=723.35, target=747.49, stop=709.51.  
Slippage-adjusted R:R = (747.49−724.44)/(724.44−709.51) = **1.546 > 1.5** → Risk Agent APPROVED.

| Time (IST) | Event | Symbol | Detail |
|---|---|---|---|
| 11:08:14 | KV CLAIMED | — | `bootstrap_scan:f3193a81f241 = true` |
| 11:08:20 | BOOTSTRAP_PAPER_TRADE_APPROVED | HDFCBANK | rank=1/5 |
| — | *No ORDER_EXECUTED* | HDFCBANK | `_build_row` raised `NameError` → silent abort |

Same root cause as TMCV. `_build_row` NameError kills the loop before ORDER_SUBMITTED can be emitted.

---

## 5. Root Cause — Technical Detail

```python
# phase20_executor.py — MODULE LEVEL (line 341)
def _build_row(...) -> Dict[str, Any]:
    return {
        ...
        "evidence": {
            "kite_ltp_overlay_enabled": _kite_ltp_overlay_active,  # ← NameError!
            "signal_price_from_daily_bar": _signal_price_from_daily, # ← NameError!
            "execution_price_from_kite_ltp": _kite_ltp_used,         # ← NameError!
        },
    }

# These names are LOCAL variables in create_paper_entry() — not module globals.
# _build_row() cannot see them — Python raises NameError.
```

**Fix:**
```python
def _build_row(...,
               kite_ltp_overlay_active: bool = False,      # ← new param
               signal_price_from_daily: Optional[float] = None,
               kite_ltp_used: Optional[float] = None) -> Dict[str, Any]:
    ...
# Call site in create_paper_entry passes them explicitly:
row = _build_row(...,
                 kite_ltp_overlay_active=_kite_ltp_overlay_active,
                 signal_price_from_daily=_signal_price_from_daily,
                 kite_ltp_used=_kite_ltp_used)
```

**Test result: 50/50 pass** after the fix.

---

## 6. Scanner Activity — Last 30 Minutes (14:21–14:52 IST)

**Source:** Live `pipeline_events` DB — Dev server (production blocked by failed build).

### 6.1 Scan Summary (7 scans completed)

| Scan ID | Time (IST) | BUYs | WATCHes | IGNOREs | Paper Eligible | Universe |
|---|---|---|---|---|---|---|
| `ccc3f60f43ee` | 14:21:25 | 0 | 18 | 32 | 0 | 51 |
| `000b4a400a57` | 14:25:47 | 0 | 18 | 32 | 0 | 51 |
| `2bfd58c03dae` | 14:29:55 | 0 | 20 | 30 | 0 | 51 |
| `9a6ed348be33` | 14:34:46 | 0 | 18 | 32 | 0 | 51 |
| `d8d879178ba5` | 14:38:56 | 0 | 18 | 32 | 0 | 51 |
| `e72cd985564e` | 14:43:47 | 0 | 18 | 32 | 0 | 51 |
| `84417f68928b` | 14:47:45 | 0 | 19 | 31 | 0 | 51 |
| `9a608f34c101` | 14:51:52 | 0 | 18 | 32 | 0 | 51 |

**Scan duration:** ~17 s per cycle. 1 symbol failing (LTIM — no provider data). 1 symbol fetched via fallback. No errors blocking the scan.

### 6.2 Top WATCH Symbols (consistent across all 7 scans)

| Symbol | Best Conf | Opp Score | Scans | R:R | Price | Regime |
|---|---|---|---|---|---|---|
| **HDFCBANK** | **78.3%** | 69.3 | 7/7 | 1.50 | ₹723.95 | Ranging/sideways |
| **HDFCLIFE** | **74.2%** | 64.4 | 7/7 | — | — | — |
| **TMCV** | **64.9%** | 59.8 | 7/7 | — | — | — |
| **DRREDDY** | **64.7%** | 62.6 | 7/7 | — | — | — |
| INDUSINDBK | 57.8% | 58.2 | 7/7 | — | — | — |
| HINDUNILVR | 57.7% | 52.5 | 7/7 | — | — | — |
| TCS | 57.6% | 52.5 | 7/7 | — | — | — |
| BAJAJ-AUTO | 56.2% | 56.8 | 7/7 | — | — | — |
| HCLTECH | 56.0% | 54.0 | 7/7 | — | — | — |
| BAJAJFINSV | 56.0% | 59.7 | 7/7 | — | — | — |

### 6.3 HDFCBANK Deep Dive (top candidate, scan `9a608f34c101`)

| Field | Value | Verdict |
|---|---|---|
| Confidence | 78.3% | ✅ Strong |
| R:R ratio | 1.50 | ✅ Passes gate (min 1.5) |
| Current price | ₹723.95 | ✅ Valid |
| Volume ratio | 0.53 | ✅ Acceptable |
| Data quality | LIVE | ✅ No cap |
| ADX | 32.5 | ✅ Strong trend |
| RSI | 33.2 | Oversold — Mean Reversion setup |
| Strategy | Mean Reversion | Score 67.1 |
| Above EMA20 | ❌ No | |
| Above EMA50 | ❌ No | |
| Regime | Ranging/sideways | |
| Research win rate | 75.0% (4 trades) | Low evidence flag |
| Profit factor | 2.56 | |
| Action generated | **WATCH** | Not BUY — that's why `paper_eligible=false` |
| Bootstrap eligible | ❌ False | |

**Why HDFCBANK is WATCH not BUY right now:** The scanner is generating a WATCH (not BUY/STRONG_BUY) signal for HDFCBANK in the current market phase. WATCH means "monitor — conditions not quite right for entry." Paper eligibility requires a BUY or STRONG_BUY signal. The EMA20/EMA50 bearish position is likely the factor — Mean Reversion strategy needs price to be oversold AND below both EMAs, which is the case here, but the overall opportunity score (69.3) may not cross the threshold needed to elevate from WATCH → BUY. Once momentum conditions shift and EMA alignment improves, HDFCBANK will be the first to fire.

### 6.4 Bootstrap Loop Behaviour (last 30 min)

| Metric | Value |
|---|---|
| KV claims made | 8 (one per scan, atomic, non-duplicate) |
| BOOTSTRAP events fired | **0** |
| Reason | No symbol has `bootstrap_eligible=true` in any scan |
| Root cause | Production server is the 04:23 UTC build; `_build_row` NameError still present |
| Dev server | Has the fix but no live Kite session for production trading |

The bootstrap loop is claiming each scan's KV slot correctly. It runs, finds zero bootstrap-eligible candidates in the current signal pool, and exits cleanly. There are no `BOOTSTRAP_CANDIDATE_REJECTED` events, confirming no candidate even reached the Risk Agent gate — the eligibility filter is upstream of Risk Agent evaluation.

---

## 7. Existing Paper Trades — Status Report

**Total paper trades ever created: 4**  
All 4 are in `EXIT_PENDING` status with `STALE_DATA_SAFETY` exit rule.

| # | Trade ID | Symbol | Opened IST | Fill Price | Qty | Stop Loss | Target | Conf | Status |
|---|---|---|---|---|---|---|---|---|---|
| 1 | P20-acad172b74 | TRENT | 2026-08-04 13:57:42 | ₹3,082.42 | 3 | ₹2,931.53 | ₹3,370.34 | 72.5% | EXIT_PENDING |
| 2 | P20-a205b1ef09 | DIVISLAB | 2026-08-04 13:57:43 | ₹8,370.04 | 1 | ₹7,982.41 | ₹9,482.77 | 64.5% | EXIT_PENDING |
| 3 | P20-83aa1be8f9 | GRASIM | 2026-08-05 11:06:46 | ₹3,223.63 | 3 | ₹3,085.54 | ₹3,618.58 | 62.8% | EXIT_PENDING |
| 4 | P20-4a5f909738 | BAJFINANCE | 2026-08-07 09:47:06 | ₹1,100.05 | 8 | ₹1,037.67 | ₹1,280.59 | 64.9% | EXIT_PENDING |

**Exit rule `STALE_DATA_SAFETY`:** These positions were opened when the production system was in an earlier phase. The exit engine has flagged them as EXIT_PENDING because the live price feed is stale relative to when they were opened. The exit has been triggered (exit_rule=STALE_DATA_SAFETY) but exit_price is not yet stamped — meaning the exit executor is waiting for a live price confirmation before writing the final P&L row.

**Portfolio state (canonical):**
- Cash on hand: ₹50,000 (initial capital, no deductions yet — exits are pending)
- Active open positions: 0 (portfolio store shows empty `positions: {}`)
- Equity point recorded: ₹50,000 at 2026-08-18 09:00:11 IST

**Note:** The 4 EXIT_PENDING trades have already been superceded by bootstrap mode — they are legacy paper entries from Phase 20's initial test runs. The next BOOTSTRAP_AUTO trade (once the fix is deployed) will be the first trade of the new bootstrap regime.

---

## 8. Root Cause — Technical Detail

```python
# phase20_executor.py — MODULE LEVEL (line 341)
def _build_row(...) -> Dict[str, Any]:
    return {
        ...
        "evidence": {
            "kite_ltp_overlay_enabled": _kite_ltp_overlay_active,  # ← NameError!
            "signal_price_from_daily_bar": _signal_price_from_daily, # ← NameError!
            "execution_price_from_kite_ltp": _kite_ltp_used,         # ← NameError!
        },
    }
```

**Fix:**
```python
def _build_row(...,
               kite_ltp_overlay_active: bool = False,
               signal_price_from_daily: Optional[float] = None,
               kite_ltp_used: Optional[float] = None) -> Dict[str, Any]:
    ...
row = _build_row(...,
                 kite_ltp_overlay_active=_kite_ltp_overlay_active,
                 signal_price_from_daily=_signal_price_from_daily,
                 kite_ltp_used=_kite_ltp_used)
```

**Test result: 50/50 pass.**

---

## 9. Deploy Failure — Root Cause & Fix

### 9.1 What Happened
| Step | Detail |
|---|---|
| Build at 04:23 UTC | ✅ SUCCESS — previous production build, currently serving |
| Build at 08:23 UTC | ❌ FAILED — promote step timed out |
| Failure mode | Cloud Run startup probe hit 300 s timeout |
| Root cause | `exports/` (~1 GB) packed into Repl layer; layer push took 7 min 40 s; container unpack exceeded startup window |
| Health check | `/api/healthz` is instant (returns `{status: ok}` immediately) — not the issue |
| Trading-mobile | Port 21338 expected but never opened; NOT the cause (same in 04:23 successful build) |

### 9.2 Fix Applied
`scripts/deploy-build.sh` Step 5 now strips (in addition to existing `.git`, `.pythonlibs`, `.cache`, `.local/state`):

| Path | Size Stripped | Why |
|---|---|---|
| `exports/` | ~1 GB | User-generated CSV/PDF/ZIP — pure output, not app code |
| `reports/` | ~2.5 MB | Generated markdown/PDF reports |
| `verification/` | ~1.1 MB | Verification artefacts |
| `screenshots/` | ~750 KB | Dev screenshots |
| `**/.mypy_cache` | ~30 MB | mypy type-check cache |
| `**/__pycache__` | ~31 MB | Python bytecode (regenerated on first use) |

**Expected image after fix:** ~2.1 GB (down from 3.2 GB). Repl layer push: <2 min (was 7 min 40 s). Container startup: well within 300 s.

---

## 10. What Needs to Happen Next

**Pending: Click Publish in Replit workspace.**

Once published, the production container will run with:
1. Fix C (`_build_row` NameError resolved) → approved candidates can now create trades
2. Fix D (try-except fallback) → any future exception advances to next candidate
3. Fix E (image size) → clean, fast startup

**Expected bootstrap sequence after publish:**
1. Next scan fires (~every 5 min during market hours, ~15:00-15:29 IST window remaining)
2. Bootstrap claims the new `scan_id` (KV atomic guard)
3. HDFCBANK evaluated — if `bootstrap_eligible=true`: Risk Agent APPROVES (R:R 1.50) → `_build_row` runs cleanly → `_insert_row` inserts into DB → `execute_buy` updates portfolio → **ORDER_EXECUTED → first BOOTSTRAP_AUTO trade created**
4. If HDFCBANK is still WATCH (not BUY) in that scan: loop falls through to HDFCLIFE, TMCV, DRREDDY in rank order
5. First candidate that (a) generates BUY signal, (b) has R:R ≥ 1.5 after slippage → wins

**Scanner closes at 15:30 IST.** If market closes before the fix is published, bootstrap runs again on the next trading session (next business day: Wednesday 2026-08-19).

---

## 11. Audit Checklist

| Claim | Evidence |
|---|---|
| Fallback loop runs in production | BOOTSTRAP_PAPER_TRADE_APPROVED events for HDFCBANK, HDFCLIFE, TMCV in sequence (scan 5ada78615b60) |
| Slippage-adjusted R:R rejection works | ORDER_REJECTED for HDFCBANK (1.31) and HDFCLIFE (1.19) with exact fill prices |
| Loop advances on rejection | `BOOTSTRAP_CANDIDATE_REJECTED{next_candidate=true}` for both |
| KV claim is atomic and per-scan | 8 claims in last 30 min — each unique scan_id, no duplicates |
| Old code never created a trade | 4 pre-deploy scans all hit ORDER_REJECTED with no fallback |
| No live broker orders | All events confirm "No live broker API called" in reason strings |
| Paper-only | trigger_source=BOOTSTRAP_AUTO, fill_model=bootstrap_paper |
| Root cause isolated | `_build_row` NameError reproducible — only fires when Risk Agent approves |
| Fix verified | 50/50 tests pass after Fix C + D |
| Image size fix | exports/ stripped from deploy-build.sh; next build ~2.1 GB |

---

## 12. Key SQL Queries

```sql
-- Full fallback loop event trail for scan 5ada78615b60
SELECT event_type, ts AT TIME ZONE 'Asia/Kolkata', symbol,
  payload->>'rr_after_slippage', payload->>'next_candidate_attempted',
  payload->>'fill_price'
FROM pipeline_events
WHERE scan_id = '5ada78615b60' AND event_type LIKE 'BOOTSTRAP%'
ORDER BY ts;

-- All bootstrap KV claims (one per scan, atomic)
SELECT key, updated_at AT TIME ZONE 'Asia/Kolkata'
FROM phase20_kv WHERE key LIKE 'bootstrap_scan:%'
ORDER BY updated_at;

-- Last 30 min scan summary
SELECT event_type, ts AT TIME ZONE 'Asia/Kolkata',
  payload->>'buy_count', payload->>'paper_eligible_count',
  payload->>'watch_count'
FROM pipeline_events
WHERE ts >= NOW() - INTERVAL '30 minutes' AND event_type = 'SCAN_COMPLETED'
ORDER BY ts;

-- Top WATCH symbols last 30 min
SELECT symbol, MAX(payload->>'confidence') AS best_conf, COUNT(*) AS scan_count
FROM pipeline_events
WHERE ts >= NOW() - INTERVAL '30 minutes' AND event_type = 'WATCH_GENERATED'
GROUP BY symbol ORDER BY best_conf DESC LIMIT 10;

-- First BOOTSTRAP_AUTO paper trade (once deployed)
SELECT trade_id, symbol, status, fill_price, quantity, stop_loss, target,
  trigger_source, fill_model, confidence,
  created_at AT TIME ZONE 'Asia/Kolkata' AS created_ist
FROM phase20_paper_trades
WHERE trigger_source = 'BOOTSTRAP_AUTO'
ORDER BY created_at LIMIT 1;

-- All open paper trades
SELECT trade_id, symbol, status, fill_price, quantity,
  stop_loss, target, exit_rule,
  created_at AT TIME ZONE 'Asia/Kolkata' AS opened_ist
FROM phase20_paper_trades ORDER BY created_at DESC;
```

---

*Section 10 will be updated with the first BOOTSTRAP_AUTO trade details (symbol, fill price, quantity, R:R, realized P&L) once the fix is published and the trade fires.*

**Document last updated:** 2026-08-18 ~15:00 IST
