# APEXQUANT PHASE 0C — CORRECTED SAFETY ACCEPTANCE REPORT

**Date:** 2026-08-21  
**Status:** ⚠️ DEV IMPLEMENTED ONLY — Production deployment pending  
**Verified at:** 2026-08-21T08:16:08Z (13:46 IST)  
**Test command:** `python3 -m pytest tests/unit/test_phase0c_safety_fixes.py -v`  
**Test result:** 22 passed, 0 failed, 0 skipped, 0 xfailed, 1 warning · 1.20s  
**Controlling document:** APEXQUANT_PHASE0B_POST_CUTOFF_AND_EOD_ROOT_CAUSE_REPORT.md

---

## ISSUE 1 — SAFE STATE (Corrected)

The original report header was inconsistent with the body. This section contains
the authoritative proof for both environments.

### Correction

The operator re-enabled `auto_paper_entries=true` at 09:00 IST on 2026-08-21
(after Phase 0C implementation) on both environments. This was detected during
the acceptance review. Entries have been re-paused as of 2026-08-21T08:15:34Z
(Phase 0A Option C, already operator-approved).

### Verified Safe State — Production (`nse-trade-intraday.replit.app`)

Source: `GET /api/phase20/settings` at `2026-08-21T08:16:11Z`

| Field | Value |
|---|---|
| `auto_paper_entries` | `false` |
| `auto_paper_entries_confirmed_at` | `null` |
| `bootstrap_paper_enabled` | `false` |
| `auto_paper_exits` | `true` |
| `initial_capital` | `500000` (₹5,00,000) |
| `config_hash` | `81df262bfdbdaaf5` |

Source: `GET /api/phase20/bootstrap-status` at `2026-08-21T08:16:11Z`

```json
{ "success": true, "bootstrap_paper_enabled": false }
```

Source: `GET /api/phase20/positions` at `2026-08-21T08:16:11Z`

```json
{ "success": true, "positions": [] }
```

**Production: 0 OPEN positions confirmed.**

---

### Verified Safe State — Dev (`localhost:8080`)

Source: `GET /api/phase20/settings` at `2026-08-21T08:16:08Z`

| Field | Value |
|---|---|
| `auto_paper_entries` | `false` |
| `auto_paper_entries_confirmed_at` | `null` |
| `bootstrap_paper_enabled` | `false` |
| `auto_paper_exits` | `true` |
| `initial_capital` | `100000` (₹1,00,000) |
| `config_hash` | `cced4e9be73e79cd` |

Source: `GET /api/phase20/bootstrap-status` at `2026-08-21T08:16:08Z`

```json
{ "success": true, "bootstrap_paper_enabled": false }
```

Source: `GET /api/phase20/positions` at `2026-08-21T08:16:08Z`

```json
{ "success": true, "positions": [] }
```

**Dev: 0 OPEN positions confirmed.**

---

### Dev Database Ground Truth

Source: direct `SELECT` from `phase20_settings` table at `2026-08-21T08:16Z`

| Column | Value |
|---|---|
| `id` | `1` |
| `data.auto_paper_entries` | `False` |
| `data.bootstrap_paper_enabled` | `False` |
| `data.initial_capital` | `100000.0` |
| `data.auto_paper_exits` | `True` |
| `data.auto_paper_entries_confirmed_at` | `null` |
| `updated_at` | `2026-08-21 08:15:34.672395+00:00` |

```sql
SELECT COUNT(*) FROM phase20_paper_trades WHERE status='OPEN';
-- Result: 0
```

---

## ISSUE 2 — TEST COUNT (Corrected)

### Correction

The original test file header said "Covers all 14 required test cases" but the
file contained 17 tests (14 required + 3 bonus in `TestNoLiveOrderPathTouched`).
During acceptance, 5 further tests were added for Issues 4 and 5. The total is
now **22 tests**.

### Exact Test Inventory

```
Command:  python3 -m pytest tests/unit/test_phase0c_safety_fixes.py -v
File:     artifacts/api-server/src/python/tests/unit/test_phase0c_safety_fixes.py
Collected: 22
```

| # | Class | Test | Result |
|---|---|---|---|
| 1 | `TestAutoEntryBlockedAfter1515` | `test_auto_entry_blocked_after_1515` | PASSED |
| 2 | `TestBootstrapBlockedAfter1515` | `test_bootstrap_blocked_after_1515` | PASSED |
| 3 | `TestManagePaperExitsThenEntryCutoff` | `test_manage_paper_exits_then_entry_cutoff` | PASSED |
| 4 | `TestStaleSignalRejected` | `test_stale_signal_rejected` | PASSED |
| 5 | `TestSignalBeforeCutoffCannotInsertAfterCutoff` | `test_signal_before_cutoff_cannot_insert_after_cutoff` | PASSED |
| 6 | `TestInsertRowFinalGuardBlocksAfterCutoff` | `test_insert_row_final_guard_blocks_after_cutoff` | PASSED |
| 7 | `TestDedicated1520SquareoffClosesOpenPositions` | `test_dedicated_1520_squareoff_closes_open_positions` | PASSED |
| 8 | `TestDedicated1520SquareoffClosesOpenPositions` | `test_no_live_order_api_called_in_squareoff` | PASSED |
| 9 | `TestDedicated1530ForceCloseClosesSurvivors` | `test_dedicated_1530_force_close_closes_survivors` | PASSED |
| 10 | `TestStartupOvernightCarryRunsBeforeEntryWork` | `test_startup_overnight_carry_runs_before_entry_work` | PASSED |
| 11 | `TestKvClaimFailureDoesNotSuppressRetry` | `test_kv_claim_failure_does_not_suppress_retry` | PASSED |
| 12 | `TestMissingPriceCreatesExitPendingOrBlockedOutcome` | `test_missing_price_creates_exit_pending_or_blocked_outcome` | PASSED |
| 13 | `TestEveryEodCandidateGetsDurableOutcome` | `test_every_eod_candidate_gets_durable_outcome` | PASSED |
| 14 | `TestEodStatusExposesExitPriceSource` | `test_eod_status_exposes_exit_price_source` | PASSED |
| 15 | `TestNoLiveOrderPathTouched` | `test_max_signal_age_constant_is_20` | PASSED |
| 16 | `TestNoLiveOrderPathTouched` | `test_no_live_order_path_in_exits` | PASSED |
| 17 | `TestNoLiveOrderPathTouched` | `test_no_live_order_path_touched` | PASSED |
| 18 | `TestBootstrapStaleDoesNotConsumeClaimSlot` | `test_bootstrap_stale_does_not_consume_claim_slot` | PASSED *(new — Issue 4)* |
| 19 | `TestMalformedTimestampFailsClosedAutoEntries` | `test_malformed_timestamp_returns_invalid_signal_timestamp` | PASSED *(new — Issue 5)* |
| 20 | `TestMalformedTimestampFailsClosedAutoEntries` | `test_missing_timestamp_returns_invalid_signal_timestamp` | PASSED *(new — Issue 5)* |
| 21 | `TestMalformedTimestampFailsClosedBootstrap` | `test_bootstrap_malformed_timestamp_fails_closed_no_claim` | PASSED *(new — Issue 5)* |
| 22 | `TestMalformedTimestampFailsClosedBootstrap` | `test_bootstrap_missing_timestamp_fails_closed_no_claim` | PASSED *(new — Issue 5)* |

### Full Pytest Summary

```
platform linux -- Python 3.12.12, pytest-9.1.1
rootdir: /home/runner/workspace/artifacts/api-server/src/python

======================== 22 passed, 1 warning in 1.20s =========================

Warning:
  phase3f_logging.py:52: DeprecationWarning: datetime.datetime.utcnow() is
  deprecated. Pre-existing warning in phase3f_logging.py. Not introduced by
  Phase 0C. Not a test failure.
```

**Tests were run AFTER the final code state**, including the Issue 5 fail-closed
fix. All 22 tests cover the current code as it exists in the workspace.

---

## ISSUE 3 — PRODUCTION DEPLOYMENT STATUS

### Status: DEV IMPLEMENTED ONLY

Phase 0C code changes exist in the workspace (dev API server). They have **not**
been deployed to production.

#### Evidence

| Check | Dev | Production |
|---|---|---|
| `GET /api/phase20/eod-outcomes` | N/A (route not yet wired in TS router) | **HTTP 404** |
| `GET /api/scheduler/status` | N/A (route not yet in TS router) | **HTTP 404** |
| `exit_price_source` on EOD results | N/A (no trades today) | `null` — old code closed DRREDDY/TRENT |
| `phase20_eod_outcomes` table | Exists (4 test rows in dev DB) | Unknown — Phase 0C not deployed |
| Entry window pre-guard in `_manage_paper()` | ✅ Code present (line 1831) | ❌ Not deployed |
| 15:20 squareoff trigger | ✅ Code present (line 1546) | ❌ Not deployed |
| Fail-closed timestamp guard | ✅ Code present (line 1419, 1660) | ❌ Not deployed |

#### Claim clarification

No production safety claims are made. The statement "production deployment
pending" in the original report header is confirmed accurate. The body of the
original report correctly described dev-only implementation. The header is the
source of the inconsistency and is corrected here.

#### Production trades today

Despite `auto_paper_entries=true` being active on production from 09:00 IST to
13:45 IST on 2026-08-21, **0 trades were executed** on production. Reason:
production thresholds are elevated (`min_confidence=75`, `min_opportunity_score=70`)
and no candidate cleared both gates during that window.

The elevated thresholds provided passive protection, but they are not a
substitute for Phase 0C deployment.

---

## ISSUE 4 — BOOTSTRAP STALE SIGNAL CLAIM ORDER (Corrected)

### Correction

The original report's body text said "Never blocks on parsing failure"
(from the old code comment) and did not explicitly state the claim order.
The original report did correctly state the guard is "Checked BEFORE
kv_claim_once" but lacked a test to prove it. The claim order is now
test-proven.

### Actual Code Order (phase20_executor.py)

```
run_bootstrap_auto_entry():
  Line 1628  — feature flag check (bootstrap_paper_enabled)
  Line 1634  — operator confirmation guard
  Line 1643  — circuit breaker check
  Line 1653  — Kite LTP safety check
  Line 1660  — ── EARLY STALE SIGNAL GUARD ──  ← checked HERE
              │   if not _snap_ts_early → INVALID_SIGNAL_TIMESTAMP (NEW)
              │   if age > 20 min       → STALE_SIGNAL_BLOCKED
              │   if parse fails        → INVALID_SIGNAL_TIMESTAMP (NEW)
  Line 1697  — kv_claim_once()          ← only reached if signal is fresh+valid
```

The stale/invalid timestamp guard fires before `kv_claim_once`. A stale or
malformed scan **does not consume** the `bootstrap_scan:{scan_id}` claim slot.

### Test Proof

**Test 18** — `TestBootstrapStaleDoesNotConsumeClaimSlot::test_bootstrap_stale_does_not_consume_claim_slot`

Method: injects a tracked `kv_claim_once` into the `phase20_store` stub.
Passes a snapshot 30 min old (> 20 min limit). Asserts `STALE_SIGNAL_BLOCKED`
AND that `kv_claim_once` call count = 0.

Result: **PASSED**

```
Expected: reason == "STALE_SIGNAL_BLOCKED"  ✅
Expected: kv_claim_calls == 0               ✅  (claim slot preserved for retry)
```

---

## ISSUE 5 — MALFORMED TIMESTAMP FAIL-CLOSED (Corrected)

### Correction

The original code had `except Exception: pass` in both stale signal guards,
causing a malformed or absent `snapshot_ts` to silently proceed. This allowed
an AUTO or BOOTSTRAP_AUTO entry to be created from a signal of unknown age.

### Code Fix Applied

Two locations changed in `phase20_executor.py`:

**Location 1 — `run_auto_entries()` (line ~1419):**

Before:
```python
if _snap_ts:
    try:
        ...
    except Exception:
        pass  # parsing failure → proceed
```

After:
```python
if not _snap_ts:
    return { "ran": False, "reason": "INVALID_SIGNAL_TIMESTAMP",
             "detail": "snapshot_ts is missing or None ..." }
try:
    ...
except Exception:
    return { "ran": False, "reason": "INVALID_SIGNAL_TIMESTAMP",
             "detail": f"snapshot_ts could not be parsed: {_snap_ts!r}" }
```

**Location 2 — `run_bootstrap_auto_entry()` early guard (line ~1664):**

Same pattern applied. Both `None`/missing and parse-failure paths return
`INVALID_SIGNAL_TIMESTAMP` before `kv_claim_once` is called.

### Behavior Matrix

| Condition | Before fix | After fix |
|---|---|---|
| `snapshot_ts` is `None` | Guard skipped — entry may proceed | `INVALID_SIGNAL_TIMESTAMP` — blocked |
| `snapshot_ts` is `""` (empty string) | Guard skipped — entry may proceed | `INVALID_SIGNAL_TIMESTAMP` — blocked |
| `snapshot_ts` is malformed (`"NOT-A-DATE"`) | `except: pass` — entry may proceed | `INVALID_SIGNAL_TIMESTAMP` — blocked |
| `snapshot_ts` is valid, age ≤ 20 min | Entry may proceed | Entry may proceed (unchanged) |
| `snapshot_ts` is valid, age > 20 min | `STALE_SIGNAL_BLOCKED` | `STALE_SIGNAL_BLOCKED` (unchanged) |

No entry is created from a signal whose age cannot be verified.

### Test Proofs (Tests 19–22)

| Test | Scenario | Path | Result |
|---|---|---|---|
| 19 | Malformed timestamp in `run_auto_entries` | auto-entry | PASSED — `INVALID_SIGNAL_TIMESTAMP` |
| 20 | `None` timestamp in `run_auto_entries` | auto-entry | PASSED — `INVALID_SIGNAL_TIMESTAMP` |
| 21 | Malformed timestamp in bootstrap | bootstrap (no claim) | PASSED — `INVALID_SIGNAL_TIMESTAMP`, 0 claim calls |
| 22 | `None` timestamp in bootstrap | bootstrap (no claim) | PASSED — `INVALID_SIGNAL_TIMESTAMP`, 0 claim calls |

---

## LIVE ORDER CONFIRMATION

No live broker order API calls exist in any Phase 0C changed file.

Verified by Test 17 (`test_no_live_order_path_touched`) — AST scan of
`phase20_executor.py` for:
- `execute_order(` — not found ✅
- `kite.place_order(` — not found ✅
- `broker.buy(` — not found ✅
- `broker.sell(` — not found ✅
- `live_order(` — not found ✅
- `place_live` — not found ✅

Verified by Test 16 (`test_no_live_order_path_in_exits`) — same scan of
`phase20_exits.py` — not found ✅

All closes are paper-only via `paper_trader.execute_sell()`.

---

## UPDATED REMAINING BLOCKERS

| # | Blocker | Severity | Action |
|---|---|---|---|
| B1 | **Phase 0C not deployed to production** | 🔴 Critical | Publish the app. Until deployed, production runs without entry window pre-guard, 15:20 squareoff, stale signal guard, or durable outcome table. |
| B2 | **`/api/phase20/eod-outcomes` HTTP route not wired** | 🟡 High | Add route to TypeScript router before next EOD so the Safety Status dashboard card (task #877) has data. |
| B3 | **`APEXQUANT_BUILD_ID` not set in production** | 🟡 Medium | Set in production env before entries are re-enabled. Without it, all trade evidence rows will record `build_id="unknown"`. |
| B4 | **`phase20_eod_outcomes` table not created in prod DB** | 🟡 Medium | Resolved by deploying Phase 0C — `record_eod_outcome()` auto-creates the table on first call. |

---

## PHASE 1 READINESS

**Phase 1 is blocked until B1 is resolved.**

Once production is deployed and the following are confirmed:
- `GET /api/phase20/eod-outcomes` returns 200 on production (confirms new code is live)
- `GET /api/phase20/settings` still shows `auto_paper_entries=false`
- 15:20 IST squareoff fires cleanly on first post-deploy market session

Phase 1 (universe change, dev capital correction to ₹1L, architecture work)
may proceed.

---

## SUMMARY

| Check | Status |
|---|---|
| Safe state — both environments paused | ✅ Confirmed at 2026-08-21T08:15:34Z |
| 0 OPEN positions — both environments | ✅ Confirmed at 2026-08-21T08:16Z |
| bootstrap_paper_enabled=false — both | ✅ Confirmed |
| Test count | ✅ 22 tests (not 17 or 16) |
| All tests pass against final code | ✅ 22/22 passed, 0 failed |
| Tests run after final code state | ✅ Yes — includes fail-closed fix |
| No skipped / xfailed | ✅ 0 skipped, 0 xfailed |
| Production deployment | ⚠️ DEV IMPLEMENTED ONLY |
| Bootstrap stale guard before kv_claim_once | ✅ Test 18 proves it |
| Malformed timestamp fails closed | ✅ Tests 19–22 prove it |
| No live broker order calls | ✅ Tests 16, 17 prove it |
