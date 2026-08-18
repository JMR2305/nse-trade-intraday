# ApexQuant AI — Bootstrap Fallback Loop: Root Cause + Audit Trail
**Date:** 2026-08-18 (NSE Market Session)  
**Environment:** Production — https://nse-trade-intraday.replit.app  
**Goal:** Prove the bootstrap fallback candidate fix fires in production, works through ranked candidates, and produces the first `BOOTSTRAP_AUTO` paper trade.  
**Status:** Root cause found and fixed; awaiting publish to production.

---

## 1. Fixes in This Session

### Fix A — Fallback Loop (merged before session)
`run_bootstrap_auto_entry` in `phase20_executor.py` was rewritten from a single-candidate abort pattern into a **ranked fallback loop**. When the top candidate fails the R:R check after slippage, the executor advances to the next ranked candidate instead of aborting. Two new events: `BOOTSTRAP_CANDIDATE_REJECTED` and `BOOTSTRAP_ALL_CANDIDATES_REJECTED`.

### Fix B — TARGET_MISSING gate (Task #802, merged before session)
Null `target_price` in the scan snapshot now emits `BOOTSTRAP_CANDIDATE_REJECTED{gate=TARGET_MISSING}` and falls through to the next candidate, instead of silently computing R:R=0 and emitting a generic rejection.

### Fix C — `_build_row` NameError (root cause, found this session)
`_build_row` in `phase20_executor.py` (a module-level function) referenced `_kite_ltp_overlay_active`, `_signal_price_from_daily`, and `_kite_ltp_used` as if they were module globals. They are actually **local variables in `create_paper_entry`**. Every time the Risk Agent *approved* a candidate, `_build_row` raised `NameError`, silently killing the bootstrap loop.

**Why only approved cases failed:** When the Risk Agent *rejects* (R:R too low), `create_paper_entry` returns at line 496 before `_build_row` is ever called. When it *approves*, the code reaches `_build_row` (line 575) → `NameError` → exception propagates → caught by scheduler outer try-except → no trade, no event, no audit trail.

**Fix:** `_build_row` now receives these three values as explicit keyword parameters with safe defaults. Call site updated to pass them. 50/50 tests pass.

### Fix D — try-except around `create_paper_entry` (defensive, this session)
Added try-except around the `create_paper_entry` call in the fallback loop. Any future exception in `create_paper_entry` (e.g., transient Kite API issue) now emits `BOOTSTRAP_CANDIDATE_REJECTED{gate=CREATE_PAPER_ENTRY_EXCEPTION}` and falls through to the next candidate, instead of aborting the loop entirely.

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

## 6. What Needs to Happen Next

The fix is in the workspace but needs a **Publish** to reach the production server. Once published:

1. Next scan fires (~every 5 min during market hours)
2. Bootstrap claims the new scan_id
3. HDFCBANK (R:R ~1.546) → Risk Agent APPROVES → `_build_row` runs without NameError → `_insert_row` inserts into DB → `execute_buy` updates portfolio → **ORDER_EXECUTED emitted → first paper trade created**
4. Trade holds at OPEN status until the exit engine triggers at stop or target
5. On close: `realized_pnl` is recorded in `phase20_paper_trades`

---

## 7. Audit Checklist

| Claim | Evidence |
|---|---|
| Fallback loop runs in production | BOOTSTRAP_PAPER_TRADE_APPROVED events for HDFCBANK, HDFCLIFE, TMCV in sequence (scan 5ada78615b60) |
| Slippage-adjusted R:R rejection works | ORDER_REJECTED for HDFCBANK (1.31) and HDFCLIFE (1.19) with exact fill prices |
| Loop advances on rejection | `BOOTSTRAP_CANDIDATE_REJECTED{next_candidate=true}` for both |
| KV claim is atomic and per-scan | Each `bootstrap_scan:<id>` claimed exactly once |
| Old code never created a trade | 4 pre-deploy scans all hit ORDER_REJECTED with no fallback |
| No live broker orders | All events confirm "No live broker API called" in reason strings |
| Paper-only | trigger_source=BOOTSTRAP_AUTO, fill_model=bootstrap_paper |
| Root cause isolated | `_build_row` NameError reproducible — only fires when Risk Agent approves |
| Fix verified | 50/50 tests pass after Fix C + D |

---

## 8. Key SQL Queries

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

-- First paper trade (once deployed)
SELECT trade_id, symbol, status, fill_price, quantity, stop_loss, target,
  trigger_source, fill_model, confidence,
  created_at AT TIME ZONE 'Asia/Kolkata' AS created_ist
FROM phase20_paper_trades
WHERE trigger_source = 'BOOTSTRAP_AUTO'
ORDER BY created_at LIMIT 1;
```

---

*Section 6 will be updated with realized P&L once the trade opens, holds, and closes.*
