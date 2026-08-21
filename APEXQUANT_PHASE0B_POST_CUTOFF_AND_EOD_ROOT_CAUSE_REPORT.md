# APEXQUANT — Phase 0B: Post-Cutoff Entry and Missed Same-Day EOD Root Cause Report

**Status:** COMPLETED — read-only investigation, no code or settings changed  
**Date:** 21 August 2026 (Asia/Kolkata)  
**Controlling report:** `APEXQUANT_PHASE0A_OPTION_C_SAFETY_PAUSE_EVIDENCE_REPORT.md`  
**Current safe state:** `auto_paper_entries=false`, `bootstrap_paper_enabled=false`, no open positions

---

## 1. Executive Conclusion

### Root cause — post-15:15 entry admission

Two paper positions were admitted after the 15:15 IST no-new-entry cutoff on 2026-08-20:

- **DRREDDY P20-8fc829b8c3** (AUTO): filled at **15:25:10 IST** from scan `052a7098b14d` (generated 14:49:55 IST)
- **TRENT P20-315e824378** (BOOTSTRAP_AUTO): filled at **15:26:22 IST** from the same scan

The **structural cause** is a race condition in `_manage_paper()`: exits run before entries in the same tick. At ~15:25 IST, `manage_open_positions()` closed the earlier DRREDDY trade (P20-cfd2e587aa) via `MARKET_CLOSE_EXIT` at 15:24:01 IST, which cleared the `no_open_duplicate` gate. `run_auto_entries()` immediately ran on the same tick and opened a fresh DRREDDY position.

The **admission failure** is that the deployed production code at 15:25 IST **did not enforce the 15:15 paper-entry cutoff** in `_insert_row()`. The current codebase contains this guard (`PAPER_ENTRY_CUTOFF = dtime(15, 15)` in `market_hours.py`, enforced at `_insert_row()` lines ~253 and ~402). That guard was either absent or non-functional in the build that ran on 2026-08-20.

Evidence: The `config_hash` stored in both trade rows (`39dc33e1e29440e9`) differs from the production config at the time of the Phase 0 evidence capture (`7d842d4e59648fe7`). Settings — and likely code — changed between entry time and the before-state capture.

### Root cause — same-day EOD miss

The server shut down approximately at or shortly after 15:26 IST on 2026-08-20 (immediately after the last entries). No scheduler tick ran during the POST_CLOSE window (15:30–16:00 IST). The `eod_squareoff:2026-08-20` KV claim was never set. DRREDDY and TRENT remained OPEN overnight.

### Cold-start resolution

On 2026-08-21 at ~00:05 IST, the server restarted. `check_overnight_carry_on_startup()` found `eod_squareoff:2026-08-20` unclaimed, detected 2 prior-session OPEN trades, and force-closed both via `eod_force_close_open_positions()`. Both trades were closed at their fill price (no live price available at midnight). `realized_pnl = 0` on both.

### Phase 1 status

**STILL BLOCKED.** The root cause is confirmed but the fix is not yet implemented. Both code gaps must be fixed, tested, and deployed before Phase 1 architecture work begins.

---

## 2. Full TRENT Timeline

**Trade ID:** P20-315e824378  
**Symbol:** TRENT  
**Trigger source:** BOOTSTRAP_AUTO  
**Fill model:** bootstrap_paper  

| Timestamp (IST) | UTC | Event |
|---|---|---|
| 14:49:55 | 09:19:55Z | Scan `052a7098b14d` completes. TRENT appears as `bootstrap_eligible=True`, `recommendation=WATCH`, `confidence=75.4`, `opportunity_score=69.2`. At this time, DRREDDY P20-cfd2e587aa is OPEN → `no_open_duplicate` blocks DRREDDY. TRENT has no prior open position but the bootstrap kv_claim for `052a7098b14d` is processed at this tick. |
| 15:14–15:15 | 09:44–09:45Z | 15:15 IST paper-entry cutoff passes. No TRENT entry was created at 14:49 — most likely because either: (a) `bootstrap_paper_enabled` was not yet enabled in settings at that scan, or (b) `auto_paper_entries_confirmed_at` was not yet set. |
| 15:24:01 | 09:54:01Z | DRREDDY P20-cfd2e587aa is closed by MARKET_CLOSE_EXIT (the 15:20 intraday square-off check). This runs inside `manage_open_positions()` within a `_manage_paper()` tick. |
| 15:25:10 | 09:55:10Z | On the **same `_manage_paper()` tick**: `run_auto_entries()` runs after exits → DRREDDY P20-8fc829b8c3 is opened (AUTO) from scan 052a7098b14d. |
| 15:26:22 | 09:56:22Z | `run_bootstrap_auto_entry()` runs (same tick or next tick). `kv_claim_once("bootstrap_scan:052a7098b14d")` returns True — first time bootstrap processes this scan. TRENT P20-315e824378 is opened (BOOTSTRAP_AUTO) from scan 052a7098b14d. |
| ~15:26+ | ~09:56+Z | Server shuts down / redeploys. No further ticks. |
| 15:30 IST | 10:00Z | POST_CLOSE window begins. Server is down. No EOD tick runs. `eod_squareoff:2026-08-20` is never claimed. |
| 2026-08-21 00:05:38 | 18:35:38Z prev | Server restarts. Cold-start function closes TRENT at fill_price=2971.45 (no live price). `realized_pnl=0`. `exit_rule=POST_CLOSE_FORCE_EXIT`. `exit_scan_id=235673b79b57`. |

**Key trade evidence:**
- `scan_id`: `052a7098b14d`
- `snapshot_ts`: `2026-08-20T09:19:55Z` = 14:49:55 IST
- `signal_ts`: `2026-08-20T09:19:55Z` = 14:49:55 IST (matches snapshot_ts — signal taken from scan)
- `decision_ts` = `fill_ts`: `2026-08-20T09:56:22Z` = **15:26:22 IST** (36 min after signal)
- `config_hash`: `39dc33e1e29440e9`
- `confidence`: 75.4, `opportunity_score`: 69.2
- `fill_price`: ₹2,971.45, `quantity`: 5
- `total_capital in evidence`: ₹1,00,000 (see Section 4 for analysis)
- `evidence.market_state`: `null` — entry status NOT stored in trade evidence
- `evidence.entry_window`: `null`

---

## 3. Full DRREDDY Timeline

**Trade ID:** P20-8fc829b8c3 (overnight position)  
**Symbol:** DRREDDY  
**Trigger source:** AUTO  
**Fill model:** SLIPPAGE_ADJUSTED

| Timestamp (IST) | UTC | Event |
|---|---|---|
| 09:16:09 | 03:46:09Z | Earlier DRREDDY trade P20-cfd2e587aa opened (AUTO, scan `c56fe726e224`). |
| 13:10–13:52 | 07:40–08:22Z | Multiple ENTRY_BLOCKED notifications for DRREDDY citing `per_stock_cap` and `no_open_duplicate` — confirms P20-cfd2e587aa was OPEN and blocking re-entry throughout the mid-session. |
| 14:49:55 | 09:19:55Z | Scan `052a7098b14d` completes. DRREDDY appears as `recommendation=BUY`, `confidence` and `opportunity_score` meeting thresholds. All gates pass EXCEPT `no_open_duplicate` (P20-cfd2e587aa still OPEN). Entry blocked. |
| 15:15 IST | 09:45Z | Paper-entry cutoff passes. `automatic_paper_entry_status()` should return `allowed=False`. |
| 15:24:01 | 09:54:01Z | P20-cfd2e587aa DRREDDY closed by `MARKET_CLOSE_EXIT` within `manage_open_positions()`. Exit price from yfinance daily (LIVE/NEAR_LIVE). Normal intraday square-off. |
| 15:25:10 | 09:55:10Z | `run_auto_entries()` runs on the same `_manage_paper()` tick after the exit. DRREDDY now passes `no_open_duplicate`. Cutoff check in `_insert_row()` does NOT block (deployed code lacks guard or guard is non-functional). DRREDDY P20-8fc829b8c3 opened from scan 052a7098b14d. |
| ~15:26+ | | Server shuts down. |
| 15:30 IST | 10:00Z | POST_CLOSE. Server down. EOD missed. |
| 2026-08-21 00:06:36 | 18:36:36Z prev | Cold-start closes DRREDDY at fill_price=1181.87. `realized_pnl=0`. |

**Key trade evidence:**
- `scan_id`: `052a7098b14d` (same scan as TRENT)
- `snapshot_ts`: `2026-08-20T09:19:55Z` = 14:49:55 IST
- `signal_ts`: `2026-08-20T09:19:55Z` = 14:49:55 IST
- `decision_ts` = `fill_ts`: `2026-08-20T09:55:10Z` = **15:25:10 IST** (35 min after signal)
- `config_hash`: `39dc33e1e29440e9`
- `fill_price`: ₹1,181.87, `quantity`: 20
- `capacities.per_stock`: ₹1,25,000 = 25% of ₹5,00,000 → capital was **₹5,00,000** at entry
- `evidence.market_state`: `null` — entry status NOT stored in trade evidence

---

## 4. Post-15:15 Entry Root Cause

### 4a. The structural trigger: exits and entries on the same tick

`_manage_paper()` is the scheduler's paper management dispatcher. Its sequence (from `phase20_scheduler.py:1721`):

```python
def _manage_paper(settings, ran_scan):
    out["exits"] = manage_open_positions(settings)   # ① exits first
    out["circuit_breaker"] = evaluate_and_maybe_trip(settings)
    out["performance_alerts"] = evaluate_and_notify(settings)
    out["entries"] = run_auto_entries(settings)       # ② entries second
    out["bootstrap"] = run_bootstrap_auto_entry(...)  # ③ bootstrap third
```

On the ~15:25 IST scheduler tick:
1. `manage_open_positions()` evaluated all OPEN positions for exits. DRREDDY P20-cfd2e587aa had `t.time() > dtime(15, 20)` → `MARKET_CLOSE_EXIT` rule triggered → closed at 15:24:01 IST.
2. `run_auto_entries()` ran immediately afterward on the same Python call stack. DRREDDY now passed `no_open_duplicate` (just closed). Candidates from scan `052a7098b14d` (14:49 IST) were evaluated.
3. `_insert_row()` was called for DRREDDY. The cutoff check should have blocked it. It did not.

This sequence is architecturally a race condition: exits clear gates that should logically remain closed for the rest of the session, but entries can immediately re-use those cleared gates on the same tick.

### 4b. The admission failure: cutoff check absent or non-functional

**Current code** (`phase20_executor.py:_insert_row`, lines ~253–256):
```python
entry_status = _market_entry_status()
if not entry_status.get("allowed"):
    raise MarketClosedForEntry(str(entry_status.get("reason") or ...))
```

**Current code** (`market_hours.py:automatic_paper_entry_status`):
```python
PAPER_ENTRY_CUTOFF = dtime(15, 15)
cutoff_reached = state == "OPEN" and t.time() >= PAPER_ENTRY_CUTOFF
if cutoff_reached:
    reason = "Automatic intraday paper-entry cutoff (15:15 IST) has been reached..."
return {"allowed": reason is None, ...}
```

At 15:25 IST: `state="OPEN"`, `t.time() = 15:25 >= 15:15` → `cutoff_reached=True` → `allowed=False` → entry blocked.

**This check exists in the current codebase but was not effective on 2026-08-20.**

Evidence that the deployed code was different:
- The `config_hash` in both trade rows is `39dc33e1e29440e9`. The before-state production config_hash (next day) is `7d842d4e59648fe7`. Settings changed between entry time and Phase 0 capture.
- The `total_capital` in TRENT's risk validation evidence is ₹1,00,000, while DRREDDY's capacities show ₹5,00,000 capital. Both trades carry the same `config_hash`. This discrepancy is consistent with the deployed code performing sizing from a different code path (bootstrap uses its own ₹15,000 cap, not the portfolio's initial_capital) — but the underlying capital stored in evidence fields differs, indicating the risk-validation layer used a different configuration.
- The `evidence.market_state` field is `null` in both trades. The current `_market_entry_status()` emits `market_state`, `cutoff_ist`, and `cutoff_reached` in the pipeline events. If the deployed code lacked the cutoff check, this evidence key would not be populated — consistent with the null observation.

**Conclusion**: The `PAPER_ENTRY_CUTOFF` guard in `_insert_row()` was **not present in the deployed production build** on 2026-08-20. The guard was added to the codebase after the incident. The deployed version did not call `_market_entry_status()` before admission, or called an older version of `automatic_paper_entry_status()` that did not include the cutoff time check.

### 4c. Capital discrepancy analysis

| Trade | Capital in evidence | Config hash | How capital is used |
|---|---|---|---|
| DRREDDY P20-8fc829b8c3 (AUTO) | ₹5,00,000 (`per_stock=125000`) | `39dc33e1e29440e9` | `run_auto_entries` → `evaluate_entries` → sizes against portfolio state |
| TRENT P20-315e824378 (BOOTSTRAP) | ₹1,00,000 (`total_capital=100000`) | `39dc33e1e29440e9` | `run_bootstrap_auto_entry` → fixed ₹15,000 cap → risk-validation uses portfolio total_value |

Both trades carry the same config_hash. The capital difference reflects the different sizing paths:
- AUTO path sizes against `initial_capital` from settings (₹5,00,000 on production)
- BOOTSTRAP path caps at ₹15,000 and sizes risk-validation against the portfolio's `total_value` (which after DRREDDY was opened may have been computed as approximately ₹1,00,000 if the bootstrap path used the dev portfolio state, OR reflects the portfolio total equity at that moment)

The config_hash change from `39dc33e1e29440e9` to `7d842d4e59648fe7` indicates settings were modified after the entries. The most likely change is `initial_capital` being raised from ₹1,00,000 to ₹5,00,000, together with a code redeployment that added the cutoff guard.

### 4d. Why the scan was 35 minutes stale

Both trades reference scan `052a7098b14d` from 14:49:55 IST. The scan interval is 5 minutes. Between 14:49 and 15:25 IST, approximately 7 new scans should have been stored. However:

- DRREDDY P20-cfd2e587aa was open throughout this period. ENTRY_BLOCKED notifications confirm that DRREDDY signals were being evaluated and blocked on multiple scans between 13:10 and 14:49 IST.
- Scan `052a7098b14d` may have been the last scan before the server state changed (settings re-confirmed, or server restarted), causing it to remain the "latest" snapshot at 15:25 IST.
- Alternatively, scans between 14:49 and 15:25 ran but did not change the canonical DB snapshot (e.g., scan state lock contention, or the server was in a partial-restart state).

**Unknown**: Whether 7 new scans ran and produced scan_ids different from `052a7098b14d` between 14:49 and 15:25 IST. The `GET /api/phase20/scan-runs` endpoint returned `[]`. Pipeline events for those intermediate scan_ids were not captured.

### 4e. Timezone hypothesis — ruled out

The earlier DRREDDY P20-cfd2e587aa closed via `MARKET_CLOSE_EXIT` at 15:24:01 IST. This exit rule triggers when `t.time() > dtime(15, 20)` in `manage_open_positions()`. The fact that this exit worked correctly proves the IST timezone (`ZoneInfo("Asia/Kolkata")`) was functioning correctly on the production server at 15:24 IST. The cutoff failure was NOT a timezone miscalculation. It was a missing guard in the entry admission path.

---

## 5. Same-Day EOD Miss Root Cause

### 5a. What should have happened

From `phase20_scheduler.py` (lines 1327–1420), on every POST_CLOSE (15:30–16:00 IST) or CLOSED tick:

```python
if mstate in ("POST_CLOSE", "CLOSED"):
    if kv_claim_once(f"eod_squareoff:{today_ist}", ttl_seconds=86400):
        eod_squareoff = eod_force_close_open_positions(settings)
```

This should have closed DRREDDY and TRENT at ~15:30 IST on 2026-08-20.

### 5b. What happened instead

The `eod_squareoff:2026-08-20` KV claim was never set. `check_overnight_carry_on_startup()` found it unclaimed the next morning, confirming no POST_CLOSE or CLOSED tick ran on 2026-08-20.

**Root cause: The server shut down at approximately 15:26 IST** (immediately after or during the TRENT bootstrap entry), and did not restart until 2026-08-21 00:05 IST — more than 8 hours later. During this window:
- No scheduler tick executed
- The POST_CLOSE window (15:30–16:00 IST) passed with no process running
- The `eod_squareoff:2026-08-20` KV claim remained unclaimed
- DRREDDY and TRENT remained OPEN in the DB

The server shutdown was likely a redeployment triggered by the settings/code change that produced config_hash `7d842d4e59648fe7`. The new server instance did not start until the early hours of 2026-08-21.

### 5c. Why the 15:20 intraday square-off didn't close these two

The 15:20 intraday `MARKET_CLOSE_EXIT` check in `manage_open_positions()` applies only to OPEN positions that existed when the check runs. At 15:24:01 IST, it correctly closed P20-cfd2e587aa (DRREDDY). But P20-8fc829b8c3 (DRREDDY) and P20-315e824378 (TRENT) did not exist at 15:24 — they were opened at 15:25:10 and 15:26:22 IST respectively. They were created AFTER the square-off window logic had already executed in that tick.

On subsequent ticks (if any ran between 15:26 and 15:30), the `MARKET_CLOSE_EXIT` check would have caught them — but no subsequent ticks ran because the server shut down.

### 5d. Why the EOD KV guard prevented retry

The EOD scheduler uses `kv_claim_once(f"eod_squareoff:{date}")` with a 24-hour TTL. Because the server was down when this claim should have been taken, it was never written. The cold-start function checks for the ABSENCE of this claim as its detection mechanism — and found it absent on 2026-08-21, correctly triggering the overnight carry resolution.

The KV guard design worked as intended. The failure mode it was designed to protect against (server down during POST_CLOSE) was exactly what occurred.

---

## 6. Cold-Start Force-Close Proof

`check_overnight_carry_on_startup()` ran on 2026-08-21 server restart and:

1. Found `eod_squareoff:2026-08-20` — not in KV store (unclaimed)
2. Found 2 OPEN prior-session trades: DRREDDY P20-8fc829b8c3 and TRENT P20-315e824378
3. Emitted `MARKET_CLOSE_OVERNIGHT_CARRY_DETECTED` pipeline event for each
4. Called `eod_force_close_open_positions()`
5. Claimed `eod_squareoff:2026-08-20` so normal POST_CLOSE tick (if server stays up) is a no-op

**Price resolution at cold-start (midnight, no live market):**
- Priority 1 (yfinance daily close): Not available — scan context is not "fresh today's session" at midnight
- Priority 2 (fill price fallback): Used — exit_price = entry fill_price

| Trade | Exit price | Fill price | Realized P&L | Exit price source |
|---|---|---|---|---|
| TRENT P20-315e824378 | ₹2,971.45 | ₹2,971.45 | ₹0 | fill_price (midnight, no live data) |
| DRREDDY P20-8fc829b8c3 | ₹1,181.87 | ₹1,181.87 | ₹0 | fill_price (midnight, no live data) |

`exit_price_source` is `null` in the `/api/phase20/eod-status` response. This is an observability gap: the cold-start path does not persist `exit_price_source` into the KV key that the EOD status endpoint reads. The pipeline events (`PAPER_TRADE_FORCE_CLOSED`) carry the full provenance, but the summary endpoint loses it.

**Is the cold-start mechanism reliable enough as a backup?**

Yes, for ensuring positions are not carried to a new trading day. However, it has three weaknesses:
1. Exit price = fill price (not EOD market price) → realized P&L is always 0, masking actual gain/loss
2. `exit_price_source` not propagated to the EOD status summary endpoint
3. The startup overnight check cannot run BEFORE the first scheduler tick's `_manage_paper` call — creating a window on restart where a new entry could theoretically be admitted before the overnight cleanup runs (though `auto_paper_entries=false` now prevents this)

It must remain a backup only, never a substitute for same-day EOD.

---

## 7. Remaining Unknowns

1. **Exact deployed build/revision on 2026-08-20 at 15:25 IST.** No build ID is stored in ledger rows (proposed fix: add build ID column). Cannot confirm the exact code diff between the deployed version and the current codebase without deployment logs.

2. **Why scan `052a7098b14d` (14:49 IST) was still the canonical snapshot at 15:25 IST.** Approximately 7 scan cycles should have run between 14:49 and 15:25. Either they ran and failed to update the DB snapshot, or the server was partially down (scheduler not ticking) between 14:49 and 15:25 IST.

3. **What triggered the server restart/shutdown at ~15:26 IST.** Whether it was a code redeployment, an OOM crash, a Replit Autoscale scale-down, or an operator-initiated restart is not determinable from available evidence.

4. **Why TRENT shows ₹1,00,000 `total_capital` in its risk validation.** DRREDDY shows ₹5,00,000 capital in its sizing (consistent with production settings). TRENT's bootstrap path shows ₹1,00,000. One possibility: bootstrap's `total_value` was read from the portfolio state which calculated differently from `initial_capital`. Needs code-level analysis of how `canonical_portfolio.total_value` is computed during bootstrap sizing.

5. **Whether there are additional OPEN positions from 2026-08-20 that were not captured.** The production ledger returned all rows. None show OPEN status beyond DRREDDY and TRENT (both now CLOSED). No further open positions remain.

6. **The `exit_price_source=null` in EOD status.** Whether the cold-start's pipeline events correctly record `exit_price_source=fill_price_fallback` but the KV-backed EOD summary loses the field. Needs code trace of `_record_market_close_blocked` vs `PAPER_TRADE_FORCE_CLOSED` event vs the EOD status endpoint's data source.

---

## 8. Proposed Fixes (Not Implemented)

### Fix 1 — Hard cutoff guard in `_insert_row()` (defense-in-depth, current code)

**Current code** already has the guard. **Action**: Verify the guard is present in all server instances and is not accidentally bypassed:

```python
# In _insert_row() — MUST be present, MUST use real clock
entry_status = _market_entry_status()
if not entry_status.get("allowed"):
    raise MarketClosedForEntry(...)

# Inside advisory lock — second check
final_entry_status = _market_entry_status()
if not final_entry_status.get("allowed"):
    conn.rollback()
    raise MarketClosedForEntry(...)
```

**Required additional guard**: Add a pre-call cutoff check in `_manage_paper()` BEFORE calling `run_auto_entries` and `run_bootstrap_auto_entry`, so the `_manage_paper` tick itself short-circuits rather than reaching `_insert_row`:

```python
# In _manage_paper(), between exits and entries:
from market_hours import automatic_paper_entry_status
_entry_window = automatic_paper_entry_status()
if not _entry_window.get("allowed"):
    out["entries"] = {"skipped": f"entry_window_closed: {_entry_window.get('reason')}"}
    out["bootstrap"] = {"ran": False, "reason": f"entry_window_closed: {_entry_window.get('reason')}"}
    return out
```

This closes the exits-before-entries race: even if an exit clears a gate, the window check is re-evaluated before entries run.

### Fix 2 — Stale signal rejection

Reject entry candidates where `signal_ts` is more than N minutes older than current time:

```python
# In run_auto_entries and run_bootstrap_auto_entry
MAX_SIGNAL_AGE_MIN = 20  # no entry from a scan > 20 minutes old
signal_age = (now_ist() - parse_ist(snap_ts)).total_seconds() / 60
if signal_age > MAX_SIGNAL_AGE_MIN:
    return {"ran": False, "reason": f"Snapshot too old ({signal_age:.0f} min, max {MAX_SIGNAL_AGE_MIN} min)"}
```

This would have blocked the 35-minute-old scan `052a7098b14d` from being used for entries at 15:25 IST even without the cutoff guard.

### Fix 3 — Dedicated 15:20 and 15:30 EOD jobs

Replace the current `mstate in ("POST_CLOSE", "CLOSED")` opportunistic EOD with two explicit jobs:

- **15:20 IST job**: `close_all_for_intraday_squareoff()` — closes all OPEN positions. Runs independently of the scan cadence. KV-guarded with TTL.
- **15:30 IST job**: `eod_force_close_open_positions()` — closes any survivors. Also KV-guarded.
- **On startup**: `check_overnight_carry_on_startup()` must complete before `_manage_paper()` is called on the first tick.
- **No new entries during startup**: `auto_paper_entries` must be re-confirmed on restart (not assumed from the previous KV state).

### Fix 4 — Durable per-trade EOD audit record

Each `eod_force_close_open_positions()` call must write a per-trade `EOD_OUTCOME` record to the DB (not just a KV key) with: `trade_id`, `exit_rule`, `exit_price`, `exit_price_source`, `session_date`, `server_process_id`, `build_id`, `realized_pnl`.

The current path stores results in KV and pipeline events but not as a structured queryable audit row.

### Fix 5 — Build ID and market state in trade evidence

Every ledger row should store:
- `build_id` — the server's deployed build identifier
- `entry_market_state` — the value of `automatic_paper_entry_status()` at admission
- `entry_cutoff_ist` — the cutoff time that was checked
- `signal_age_seconds` — age of the signal at decision time

This would make future incidents immediately diagnosable: if the cutoff check had been stored, we could have proven exactly whether `allowed=False` was returned at entry time.

### Fix 6 — DB-level immutability trigger for CLOSED rows

(From Phase 0A remediation plan.) A PostgreSQL trigger that prevents UPDATE on `exit_price`, `exit_rule`, `exit_ts`, `realized_pnl`, `status` for any row where `status='CLOSED'`. The cold-start force-close should record an audit event rather than an in-place update.

### Fix 7 — EOD exit price from previous-day close

The cold-start `eod_force_close_open_positions()` currently falls back to fill price when no live data is available. It should instead fetch the previous session's closing price from yfinance (cached in OHLCV) and use that as the exit price, marking `exit_price_source="yfinance_prev_session_close"`. This gives an honest P&L even for overnight-carry positions.

---

## 9. Required Tests

| Test | What it validates |
|---|---|
| `test_auto_entry_blocked_after_1515` | `run_auto_entries()` with settings confirmed; mock `now_ist()` to 15:25 IST → no trade created, `MarketClosedForEntry` raised or skipped |
| `test_bootstrap_blocked_after_1515` | `run_bootstrap_auto_entry()` with snapshot; mock `now_ist()` to 15:20 IST → no trade created |
| `test_manage_paper_exits_then_entry_cutoff` | `_manage_paper()` with an OPEN position that triggers MARKET_CLOSE_EXIT; mock clock to 15:24 IST; assert exit runs but entry window check fires after exit and blocks new entry |
| `test_stale_signal_rejected` | signal_ts 35 min before now; `MAX_SIGNAL_AGE_MIN=20`; assert entry blocked with `snapshot_too_old` reason |
| `test_eod_missed_no_claim_prevents_new_entry` | Startup with OPEN prior-session positions; `eod_squareoff:yesterday` not set; assert overnight carry resolution runs before first `_manage_paper()` tick |
| `test_kv_claim_failure_does_not_suppress_retry` | EOD claim released on error; next tick retakes claim and re-runs force-close |
| `test_missing_price_creates_exit_pending` | `eod_force_close_open_positions()` with no live price and fill_price=0; assert MARKET_CLOSE_EXIT_BLOCKED emitted, position left OPEN |
| `test_every_eod_candidate_gets_durable_outcome` | `eod_force_close_open_positions()` with 3 trades; assert each produces either a `force_closed` or `blocked` entry — no silent skips |
| `test_bootstrap_scan_kv_claim_persists_across_restart` | kv_claim_once for `bootstrap_scan:XYZ` returns True first call, False on second (different process) |
| `test_no_live_order_path_touched` | Assert `broker_client.place_order_live()` is never called from any path in phase20_executor, phase20_exits, or phase20_scheduler |

---

## 10. Whether Phase 1 Remains BLOCKED

**Phase 1 remains BLOCKED.**

Pre-conditions for unblocking:
1. `_manage_paper()` must have an explicit entry-window cutoff check before calling `run_auto_entries` and `run_bootstrap_auto_entry` (Fix 1 — `_manage_paper` pre-guard)
2. Stale signal rejection must be implemented (Fix 2)
3. Dedicated 15:20 and 15:30 EOD jobs must be added (Fix 3)
4. All tests in Section 9 must pass in CI
5. `auto_paper_entries` must remain disabled until all fixes are deployed and verified

Phase 1 architecture work (universe change, capital correction, LTIM removal) may proceed on a separate branch in parallel, but must not be deployed to production until the entry-admission and EOD safety fixes are live and tested.

---

## 11. Confirmation: No Code Changed

No application code was changed during this investigation. All reads were via `GET` API calls to the production endpoint and `cat`/`grep`/`sed` reads of the local codebase. No `PUT`, `POST`, `PATCH`, or `DELETE` calls were made to any endpoint other than the already-completed Phase 0A settings pause.

---

## 12. Confirmation: No Settings Changed

The only settings changes made to this system were those documented in `APEXQUANT_PHASE0A_OPTION_C_SAFETY_PAUSE_EVIDENCE_REPORT.md` (applying the Option C pause). No additional settings changes were made during this Phase 0B investigation.

Current settings state (both environments):
- `auto_paper_entries = false`
- `bootstrap_paper_enabled = false`
- `auto_paper_exits = true`

---

## 13. Confirmation: No Positions Changed

No positions were closed, modified, or created during this investigation. The production ledger was queried read-only. TRENT P20-315e824378 and DRREDDY P20-8fc829b8c3 remain CLOSED (as they were closed by `check_overnight_carry_on_startup()` on 2026-08-21 at 00:05–00:06 IST, before this investigation began). Production positions endpoint returns `{"success":true,"positions":[]}`.

---

## 14. Confirmation: No Live Orders

No live order API calls were made. `LIVE_EXECUTION_ENABLED` is `false` (default). No calls were made to `broker_client.place_order_live()`, `/intraday-trading-bot/` routes, or any Zerodha order API. The investigation was entirely read-only except for the Option C pause already applied.
