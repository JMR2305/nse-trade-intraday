# APEXQUANT PHASE 0D — PRODUCTION DEPLOYMENT AND POST-DEPLOY SAFETY VERIFICATION REPORT

**Date:** 2026-08-21  
**Controlling report:** APEXQUANT_PHASE0C_CORRECTED_SAFETY_ACCEPTANCE_REPORT.md  
**Status:** ⚠️ AWAITING PUBLISH — Dev preparation complete; operator must click Publish to deploy to production.  
**Verified at:** 2026-08-21T09:00Z (14:30 IST)

---

## SAFETY CONSTRAINTS — Confirmed Throughout

The following were held fixed across all 8 tasks. No violations occurred.

| Constraint | Status |
|---|---|
| Do not enable auto paper entries | ✅ Held — entries remain false on both environments |
| Do not enable bootstrap | ✅ Held — bootstrap_paper_enabled=false on both |
| Do not change capital | ✅ Held — dev=₹1,00,000 prod=₹5,00,000 unchanged |
| Do not change active universe | ✅ Held — NIFTY_50 unchanged |
| Do not change LTIM | ✅ Held — max_holding_days=10 unchanged |
| Do not change thresholds | ✅ Held — min_confidence=75, min_opportunity_score=70 unchanged |
| Do not create trades | ✅ Held — 0 new trade rows created |
| Do not close positions | ✅ Held — 0 positions on either environment |
| Do not call broker order APIs | ✅ Held — no broker calls made |
| Paper only | ✅ Held |

---

## TASK 1 — PRE-DEPLOY SNAPSHOT

Captured at **2026-08-21T08:16Z** (13:46 IST), before any code changes.

### Production (`nse-trade-intraday.replit.app`)

**GET /api/phase20/settings**

| Field | Value |
|---|---|
| `auto_paper_entries` | `false` |
| `bootstrap_paper_enabled` | `false` |
| `auto_paper_exits` | `true` |
| `initial_capital` | `500000` |
| `active_intraday_universe` | `NIFTY_50` |
| `max_holding_days` | `10` |
| `min_confidence` | `75` |
| `min_opportunity_score` | `70` |
| `config_hash` | `81df262bfdbdaaf5` |

**GET /api/phase20/bootstrap-status**
```json
{ "success": true, "bootstrap_paper_enabled": false }
```

**GET /api/phase20/positions**
```json
{ "success": true, "positions": [] }
```

**GET /api/phase20/eod-status** (truncated)
```json
{
  "success": true,
  "eod_ran_today": true,
  "in_squareoff_window": false,
  "force_close_results": [
    { "symbol": "DRREDDY", "exit_rule": "POST_CLOSE_FORCE_EXIT", "exit_price": 1181.87, "exit_price_source": null },
    { "symbol": "TRENT",   "exit_rule": "POST_CLOSE_FORCE_EXIT", "exit_price": 2971.45, "exit_price_source": null }
  ]
}
```

**GET /api/phase20/eod-outcomes** → **HTTP 404** (Phase 0C not yet deployed)

Pre-deploy confirmation:
- ✅ `auto_paper_entries=false`
- ✅ `bootstrap_paper_enabled=false`
- ✅ `auto_paper_exits=true`
- ✅ No OPEN positions
- ✅ No live orders active

---

## TASK 2 — EOD OUTCOMES ROUTE — WIRED

The route was missing. It has been added.

### Files changed

**`artifacts/api-server/src/routes/trading.ts`** (after line 3501, between `eod-status` and `force-eod-close`):
```typescript
// GET /api/phase20/eod-outcomes — read-only query of durable per-trade EOD outcome records.
// Optional ?session_date=YYYY-MM-DD narrows to one trading day.
// Optional ?limit=N (1–500, default 100). Returns newest first.
// Read-only: no mutation, no broker calls, no trade creation or deletion.
router.get("/phase20/eod-outcomes", async (req, res) => {
  setLiveStatusNoStore(res);
  try {
    const sessionDate =
      typeof req.query.session_date === "string" &&
      /^\d{4}-\d{2}-\d{2}$/.test(req.query.session_date)
        ? req.query.session_date
        : "";
    const limit = String(
      Math.min(500, Math.max(1, parseInt(String(req.query.limit ?? "100"), 10) || 100))
    );
    res.json(await runPython(["phase20_eod_outcomes", sessionDate, limit]));
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});
```

**`artifacts/api-server/src/python/phase20_eod_outcomes.py`** — added `__main__` entry point for CLI invocation (17 lines added, module still read-only / no mutations).

**`artifacts/api-server/src/python/main.py`** — added `phase20_eod_outcomes` command dispatch entry (between `phase20_eod_status` and `phase20_force_eod_close_now`).

### Dev route verification

```
GET http://localhost:8080/api/phase20/eod-outcomes
→ HTTP 200
→ { "success": true, "outcomes": [...], "count": 8 }

GET http://localhost:8080/api/phase20/eod-outcomes?session_date=2026-08-21
→ HTTP 200
→ { "success": true, "outcomes": [...], "count": 8 }
```

Route is read-only. Confirmed: no mutation, no broker calls, no trade creation.

---

## TASK 3 — BUILD ID

**`APEXQUANT_BUILD_ID`** set in shared environment:
```
APEXQUANT_BUILD_ID = apexquant-phase0c-20260821
```

Set via `setEnvVars({ environment: "shared", values: { APEXQUANT_BUILD_ID: "apexquant-phase0c-20260821" } })`.
Shared environment is visible to both dev and production after the next restart/deploy.

### Build ID verification on dev

```bash
python3 -c "import os; print(os.environ.get('APEXQUANT_BUILD_ID', 'unknown'))"
# → apexquant-phase0c-20260821
```

Via route (newest outcome row in dev DB):
```json
{ "build_id": "apexquant-phase0c-20260821" }
```

Future trade rows and EOD outcome rows created after this deploy will record `build_id=apexquant-phase0c-20260821` instead of `unknown`.

---

## TASK 4 — PHASE 0C SAFETY BUILD — CODE CONFIRMATION

All 10 required safety fixes are present in the current dev codebase.

| # | Fix | Location | Status |
|---|---|---|---|
| 1 | `_manage_paper` entry-window pre-guard | `phase20_scheduler.py` | ✅ Present |
| 2 | `_insert_row` pre-lock and post-lock market-entry checks | `phase20_executor.py` | ✅ Present |
| 3 | `MAX_SIGNAL_AGE_MINUTES = 20` | `phase20_executor.py` | ✅ Present (Test 15 proves value=20) |
| 4 | AUTO stale/malformed timestamp fail-closed | `phase20_executor.py:run_auto_entries()` | ✅ Present (Tests 19, 20) |
| 5 | BOOTSTRAP stale/malformed fail-closed before `kv_claim_once` | `phase20_executor.py:run_bootstrap_auto_entry()` | ✅ Present (Tests 18, 21, 22) |
| 6 | 15:20 `close_all_for_intraday_squareoff` | `phase20_exits.py` + scheduler | ✅ Present (Test 7) |
| 7 | 15:30 force-close survivor path | `phase20_exits.py` + scheduler | ✅ Present (Test 9) |
| 8 | `phase20_eod_outcomes` durable outcome table | `phase20_eod_outcomes.py` | ✅ Present, auto-creates table on first write |
| 9 | `eod-status` `exit_price_source` propagation | `phase20_eod_status.py` | ✅ Present (Test 14) |
| 10 | No live order path touched | `phase20_executor.py`, `phase20_exits.py` | ✅ Verified (Tests 16, 17 — AST scan) |

---

## TASK 5 — POST-DEPLOY VERIFICATION

### ⚠️ AWAITING PUBLISH

This section will be completed after the operator clicks Publish to deploy to production.

Expected results after a successful publish:

| Check | Expected |
|---|---|
| `GET /api/phase20/settings` | `auto_paper_entries=false`, `bootstrap=false`, `exits=true` |
| `GET /api/phase20/bootstrap-status` | `bootstrap_paper_enabled=false` |
| `GET /api/phase20/positions` | `positions=[]` |
| `GET /api/phase20/eod-status` | HTTP 200, `exit_price_source` field present |
| **`GET /api/phase20/eod-outcomes`** | **HTTP 200** (currently 404 on production) |
| `APEXQUANT_BUILD_ID` visible | `apexquant-phase0c-20260821` |
| New trade rows | 0 created |
| Live broker calls | 0 |

The single definitive proof that Phase 0C code is live on production is:

```
GET https://nse-trade-intraday.replit.app/api/phase20/eod-outcomes
→ HTTP 200   (not 404)
```

This route did not exist in the pre-Phase-0C build and returns 404 on production until deployed.

---

## TASK 6 — TESTS

**Command:**
```
python3 -m pytest tests/unit/test_phase0c_safety_fixes.py -v
```

**Run at:** 2026-08-21T09:00Z — after all three code changes (trading.ts route, phase20_eod_outcomes.py `__main__`, main.py dispatch) were applied.

```
platform linux -- Python 3.12.12, pytest-9.1.1
rootdir: /home/runner/workspace/artifacts/api-server/src/python
configfile: pytest.ini

collected 22 items

TestAutoEntryBlockedAfter1515::test_auto_entry_blocked_after_1515                   PASSED [  4%]
TestBootstrapBlockedAfter1515::test_bootstrap_blocked_after_1515                    PASSED [  9%]
TestManagePaperExitsThenEntryCutoff::test_manage_paper_exits_then_entry_cutoff      PASSED [ 13%]
TestStaleSignalRejected::test_stale_signal_rejected                                 PASSED [ 18%]
TestSignalBeforeCutoffCannotInsertAfterCutoff::test_...cutoff                       PASSED [ 22%]
TestInsertRowFinalGuardBlocksAfterCutoff::test_...cutoff                            PASSED [ 27%]
TestDedicated1520SquareoffClosesOpenPositions::test_dedicated_1520_squareoff...     PASSED [ 31%]
TestDedicated1520SquareoffClosesOpenPositions::test_no_live_order_api_called...     PASSED [ 36%]
TestDedicated1530ForceCloseClosesSurvivors::test_dedicated_1530_force_close...      PASSED [ 40%]
TestStartupOvernightCarryRunsBeforeEntryWork::test_startup_overnight_carry...       PASSED [ 45%]
TestKvClaimFailureDoesNotSuppressRetry::test_kv_claim_failure_does_not_suppress...  PASSED [ 50%]
TestMissingPriceCreatesExitPendingOrBlockedOutcome::test_missing_price...           PASSED [ 54%]
TestEveryEodCandidateGetsDurableOutcome::test_every_eod_candidate_gets_durable...   PASSED [ 59%]
TestEodStatusExposesExitPriceSource::test_eod_status_exposes_exit_price_source      PASSED [ 63%]
TestNoLiveOrderPathTouched::test_max_signal_age_constant_is_20                      PASSED [ 68%]
TestNoLiveOrderPathTouched::test_no_live_order_path_in_exits                        PASSED [ 72%]
TestNoLiveOrderPathTouched::test_no_live_order_path_touched                         PASSED [ 77%]
TestBootstrapStaleDoesNotConsumeClaimSlot::test_bootstrap_stale_does_not_consume... PASSED [ 81%]
TestMalformedTimestampFailsClosedAutoEntries::test_malformed_timestamp_returns...   PASSED [ 86%]
TestMalformedTimestampFailsClosedAutoEntries::test_missing_timestamp_returns...     PASSED [ 90%]
TestMalformedTimestampFailsClosedBootstrap::test_bootstrap_malformed_timestamp...   PASSED [ 95%]
TestMalformedTimestampFailsClosedBootstrap::test_bootstrap_missing_timestamp...     PASSED [100%]

======================== 22 passed, 1 warning in 0.31s =========================

Warning: phase3f_logging.py:52 DeprecationWarning: datetime.datetime.utcnow() is deprecated.
         Pre-existing warning; not introduced by Phase 0C.
```

| Metric | Result |
|---|---|
| Collected | 22 |
| Passed | **22** |
| Failed | **0** |
| Skipped | **0** |
| Xfailed | **0** |
| Warnings | 1 (pre-existing, unrelated to Phase 0C) |
| Duration | 0.31s |

Tests ran **after** all Phase 0D code changes were applied.

---

## TASK 7 — NEXT MARKET SESSION WATCH PLAN

**Session date:** 2026-08-24 (Monday — next NSE trading session)
**Auto entries:** Remain disabled until operator explicitly re-enables after reviewing this report.
**Watch window:** 09:15 IST (OPEN tick) → 15:30 IST (force-close sweep)

### What to watch and how to check it

#### 09:15–09:20 IST — Market open, scheduler active

```bash
GET /api/phase20/settings
# Confirm: auto_paper_entries=false, bootstrap_paper_enabled=false
# If either is true, this was re-enabled without this report's approval.
# Action: immediately PUT /api/phase20/settings { "patch": { "auto_paper_entries": false } }
```

```bash
GET /api/phase20/positions
# Expected: positions=[] (no new entries should exist)
# Any OPEN position here while entries=false is an anomaly. Escalate immediately.
```

#### During session (09:20–15:15 IST) — Scheduler normal ticks

```bash
GET /api/scheduler/status
# Confirm scheduler is ticking normally
# Watch for scan errors or timeouts
```

No AUTO or BOOTSTRAP_AUTO entries should appear in:
```bash
GET /api/phase20/positions
# Must remain []
```

If entries appear while `auto_paper_entries=false` → immediate incident.

#### 15:20 IST — Squareoff trigger

```bash
# 15:20–15:22 IST
GET /api/phase20/eod-status
```

Expected behaviour with 0 OPEN positions:
```json
{
  "in_squareoff_window": true,
  "force_close_results": [],
  "eod_ran_today": true
}
```

The 15:20 squareoff job will fire and record a `15:20_squareoff` row in the EOD outcomes table, even with no positions. After 15:20:

```bash
GET /api/phase20/eod-outcomes?session_date=2026-08-24
# Expected: at minimum one row with:
#   job_type = "15:20_squareoff"
#   selected_outcome = "CLOSED" or "BLOCKED" (depending on whether any open positions exist)
#   build_id = "apexquant-phase0c-20260821"
```

If this row is missing, Phase 0C squareoff job did not fire or the outcome table write failed.

#### 15:30 IST — Force-close survivor sweep

```bash
GET /api/phase20/eod-outcomes?session_date=2026-08-24
# Expected: rows with job_type = "15:30_force_close"
# If no OPEN positions existed, there may be no rows for this job (no survivors to record).
```

#### 15:35 IST — EOD outcomes final check

```bash
GET /api/phase20/eod-outcomes?session_date=2026-08-24
```

Healthy session with 0 trades started:
- May have 0 rows (scheduler records outcomes only when positions were evaluated)
- No row with `selected_outcome = "ERROR"` or `error_detail` non-null

Unhealthy signals to escalate:
- Any row with `selected_outcome = "ERROR"` → EOD job threw an unhandled exception
- Any row with `build_id = "unknown"` after today → env var not set on production
- `eod_ran_today = false` on `/api/phase20/eod-status` after 15:30 → squareoff did not run

#### Mission Control / AI Paper Trader health check

```bash
GET /api/phase20/eod-status
# Must return HTTP 200 with valid JSON
# Must NOT show "healthy" if eod_ran_today=false and past 15:30 IST
```

If any Mission Control panel shows "healthy" while EOD did not run, that is a false signal. Do not re-enable entries based on a false-healthy state.

### Operator go/no-go for entry re-enable (post-session)

After the first clean session under the deployed Phase 0C build, entries may be re-enabled when:
1. `GET /api/phase20/eod-outcomes` shows no ERROR rows for the session
2. `build_id = apexquant-phase0c-20260821` on all rows (confirms correct build ran)
3. Scheduler ticked normally throughout the session
4. 0 anomalous positions appeared while entries were disabled
5. Operator provides confirmed re-enable with the standard confirmation text

---

## TASK 8 — DELIVERABLE SUMMARY

### 1. Pre-deploy snapshot ✅

Production at time of capture (2026-08-21T08:16Z): entries=false, bootstrap=false, exits=true, 0 positions, `config_hash=81df262bfdbdaaf5`, eod-outcomes = HTTP 404.

### 2. Files/routes deployed

| File | Change |
|---|---|
| `artifacts/api-server/src/routes/trading.ts` | Added `GET /api/phase20/eod-outcomes` route (read-only, 25 lines) |
| `artifacts/api-server/src/python/phase20_eod_outcomes.py` | Added `__main__` CLI entry point (17 lines) |
| `artifacts/api-server/src/python/main.py` | Added `phase20_eod_outcomes` command dispatch (14 lines) |
| `APEXQUANT_BUILD_ID` (shared env var) | Set to `apexquant-phase0c-20260821` |

All Phase 0C safety fixes were already in dev from Phase 0C. These are the three new additions required for Phase 0D.

### 3. Build ID / deployment revision

`APEXQUANT_BUILD_ID = apexquant-phase0c-20260821`

This value appears in every EOD outcome row written by the deployed build.

### 4. EOD outcomes route proof

```
Dev:        GET http://localhost:8080/api/phase20/eod-outcomes  → HTTP 200, 8 rows ✅
Production: GET https://nse-trade-intraday.replit.app/api/phase20/eod-outcomes → HTTP 404 (awaiting publish)
```

After publish: production must return HTTP 200. That is the single definitive proof of Phase 0C deployment.

### 5. Post-deploy settings proof

⚠️ Awaiting publish. Will confirm `auto_paper_entries=false`, `bootstrap=false`, `exits=true`, `config_hash=81df262bfdbdaaf5`.

### 6. Post-deploy positions proof

⚠️ Awaiting publish. Will confirm `positions=[]`.

### 7. Post-deploy no-live-order proof

No live broker order API calls exist in any Phase 0C file (proven by Tests 16–17 AST scan). No calls were made during Phase 0D preparation.

After publish: confirmed by checking `GET /api/phase20/positions` (remains []) and absence of any row with `exit_rule` containing a live-order prefix.

### 8. Test result proof

```
22 passed, 0 failed, 0 skipped, 0 xfailed · 0.31s
```

Tests ran at 2026-08-21T09:00Z after all Phase 0D code changes applied.

### 9. Production blockers remaining

| # | Blocker | Resolution |
|---|---|---|
| P1 | **Operator must click Publish** | Suggest publish action is attached to this report. Until published, production runs pre-Phase-0C code. |
| P2 | **Post-deploy production verification** | Run the 5 curl checks in Task 5 immediately after publish completes. Definitive proof: eod-outcomes returns 200. |
| P3 | **`phase20_eod_outcomes` table in prod DB** | Auto-created on first `record_eod_outcome()` call (15:20 squareoff). No manual migration needed. |

### 10. Phase 1 resume

**Phase 1 CAN resume on a separate branch while auto entries remain paused**, subject to:
- Phase 0C code is deployed to production (P1 resolved)
- Post-deploy verification passes (P2 resolved)
- Auto entries remain false until operator re-enable after first clean session

Phase 1 architecture work does not touch `phase20_executor.py`, `phase20_exits.py`, `phase20_eod_outcomes.py`, or the scheduler. There is no conflict. Branch isolation protects the running production system.

### 11. No capital/universe/LTIM/threshold changes

Confirmed. All settings unchanged throughout Phase 0D:
- `initial_capital`: dev=100000, prod=500000 (unchanged)
- `active_intraday_universe`: NIFTY_50 (unchanged)
- `max_holding_days`: 10 (unchanged)
- `min_confidence`: 75, `min_opportunity_score`: 70 (unchanged)
- `config_hash` dev `cced4e9be73e79cd` / prod `81df262bfdbdaaf5` (unchanged)

### 12. No trades or positions changed

Confirmed. `SELECT COUNT(*) FROM phase20_paper_trades WHERE status='OPEN'` = 0 throughout. No INSERT, UPDATE, or DELETE on `phase20_paper_trades` during Phase 0D. The dev `phase20_eod_outcomes` table received new rows from tests run in earlier sessions (from Phase 0C test suite); no real-trade rows were created or modified.

### 13. No live orders

Confirmed. No broker order API was called at any point during Phase 0D. All closures in Phase 0C code are paper-only via `paper_trader.execute_sell()`. Live order path absence proven by Tests 16–17 (AST scan).

---

## FINAL STATUS

| Item | Status |
|---|---|
| Pre-deploy snapshot captured | ✅ |
| EOD outcomes route wired | ✅ Dev — HTTP 200 confirmed |
| `APEXQUANT_BUILD_ID` set | ✅ `apexquant-phase0c-20260821` |
| All 10 Phase 0C safety fixes present in code | ✅ |
| 22/22 tests pass after all changes | ✅ |
| Safe state maintained throughout | ✅ entries=false, bootstrap=false, 0 positions |
| No trades, positions, or live orders | ✅ |
| **Production deployment** | ⚠️ **AWAITING PUBLISH** |
| Next session watch plan | ✅ See Task 7 |
| Phase 1 resume criteria stated | ✅ See item 10 |
