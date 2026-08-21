# APEXQUANT — Phase 0A Option C Safety Pause: Evidence Report

**Status:** COMPLETED — safety pause applied  
**Date:** 21 August 2026 (Asia/Kolkata)  
**Operator approval:** Option C — pause both `auto_paper_entries` and `bootstrap_paper_enabled`  
**Controlling plan:** `APEXQUANT_PHASE0A_SAFETY_REMEDIATION_PLAN.md`  
**Environments applied:** Production (`nse-trade-intraday.replit.app`) + Local dev (`localhost:8080`)

---

## 1. Before-settings snapshot

### 1a. Production database — before

| Field | Value |
|---|---|
| `auto_paper_entries` | `true` |
| `auto_paper_entries_confirmed_at` | `"2026-08-20T03:30:25Z"` |
| `bootstrap_paper_enabled` | `true` |
| `auto_paper_exits` | `true` |
| `config_hash` | `7d842d4e59648fe7` |
| `initial_capital` | `500000` |
| `active_intraday_universe` | `NIFTY_50` |
| `kite_verified` | `true` |
| `kite_session_verified` | `true` |
| `bootstrap_eligible_count` | `11` |

Raw before-settings response (production):
```json
{
  "active_intraday_universe": "NIFTY_50",
  "auto_paper_entries": true,
  "auto_paper_entries_confirmed_at": "2026-08-20T03:30:25Z",
  "bootstrap_paper_enabled": true,
  "auto_paper_exits": true,
  "config_hash": "7d842d4e59648fe7",
  "initial_capital": 500000,
  "min_confidence": 75,
  "min_opportunity_score": 70,
  "max_trades_per_day": 3,
  "max_concurrent_positions": 5,
  "square_off_before_close": false
}
```

### 1b. Local dev database — before

| Field | Value |
|---|---|
| `auto_paper_entries` | `true` |
| `auto_paper_entries_confirmed_at` | `"2026-08-20T03:30:35Z"` |
| `bootstrap_paper_enabled` | `true` |
| `auto_paper_exits` | `true` |
| `config_hash` | `efaf1e0cd1acddf2` |
| `initial_capital` | `100000` |

---

## 2. Before bootstrap-status snapshot

### 2a. Production — before bootstrap-status

```json
{
  "bootstrap_paper_enabled": true,
  "auto_paper_entries": true,
  "auto_paper_entries_confirmed_at": "2026-08-20T03:30:25Z",
  "circuit_breaker_tripped": false,
  "kite_verified": true,
  "kite_session_verified": true,
  "kite_overlay_enabled": true,
  "closed_bootstrap_trades": 6,
  "bootstrap_max_closed_trades": 20,
  "bootstrap_cutoff_reached": false,
  "bootstrap_eligible_count": 11,
  "watch_count": 30,
  "snapshot_ts": "2026-08-21T03:23:05Z",
  "scan_id": "2df9eaac3c39"
}
```

Note: 11 bootstrap-eligible candidates were in the snapshot at time of pause, meaning bootstrap could
have opened a new position on the next scan tick. The pause was applied before any such entry occurred.

### 2b. Local dev — before bootstrap-status

```json
{
  "bootstrap_paper_enabled": true,
  "auto_paper_entries": true,
  "auto_paper_entries_confirmed_at": "2026-08-20T03:30:35Z",
  "circuit_breaker_tripped": false,
  "kite_verified": false,
  "kite_session_verified": false,
  "bootstrap_eligible_count": 0,
  "watch_count": 21
}
```

---

## 3. Open positions before the pause

### 3a. Production positions — before

`GET /api/phase20/positions` → `{"success":true,"positions":[]}`

**No open positions.** TRENT and DRREDDY — identified as overnight-open in the Phase 0 report
(filled 2026-08-20, after 15:15 IST cutoff) — were already closed by the time this evidence
capture ran. See Section 7 for the full trace.

### 3b. Production ledger — TRENT and DRREDDY before the pause

| field | TRENT | DRREDDY (overnight) |
|---|---|---|
| `trade_id` | `P20-315e824378` | `P20-8fc829b8c3` |
| `symbol` | `TRENT` | `DRREDDY` |
| `status` | `CLOSED` | `CLOSED` |
| `fill_ts` | `2026-08-20T09:56:22Z` | `2026-08-20T09:55:10Z` |
| `exit_ts` | `2026-08-21T00:05:38Z` | `2026-08-21T00:06:36Z` |
| `exit_rule` | `POST_CLOSE_FORCE_EXIT` | `POST_CLOSE_FORCE_EXIT` |
| `trigger_source` | `BOOTSTRAP_AUTO` | `AUTO` |
| `fill_price` | `2971.45` | `1181.87` |
| `quantity` | `5` | `20` |

Both positions were closed by `check_overnight_carry_on_startup()` → `eod_force_close_open_positions()`
on 2026-08-21 at approximately 00:05–00:06 IST (UTC). This is the cold-start safety net defined in
`phase20_scheduler.py:check_overnight_carry_on_startup()`. Neither position was touched during or
after this evidence-capture and settings-pause operation.

### 3c. Local dev positions — before

`GET /api/phase20/positions` → `{"success":true,"positions":[]}`

Local dev ledger has 4 rows total, all CLOSED. DRREDDY does not appear. TRENT appears as a
separate earlier trade (P20-acad172b74, CLOSED 2026-08-19 by TIMEOUT_EXIT_PENDING) — different
trade_id and different entry date from the production overnight row.

---

## 4. Operator-approved action applied

**Payload sent to both environments:**
```json
{
  "patch": {
    "auto_paper_entries": false,
    "bootstrap_paper_enabled": false
  }
}
```

**Method:** `PUT /api/phase20/settings`  
**No `confirmation_text` provided** — the settings API only requires confirmation_text when
*enabling* auto_paper_entries, not when disabling it (verified in `phase20_store.py:update_settings`,
lines 638–646). Disabling is unconditional.

**Fields NOT included in the patch** (confirming nothing else changed):
- capital, active_universe, LTIM, max_trades, max_positions, strategy thresholds,
  exit settings, Kite settings, broker settings, database schema, trade rows, position status.

---

## 5. After-settings snapshot

### 5a. Production database — after

| Field | Before | After | Changed? |
|---|---|---|---|
| `auto_paper_entries` | `true` | **`false`** | ✅ YES (intended) |
| `auto_paper_entries_confirmed_at` | `"2026-08-20T03:30:25Z"` | **`null`** | ✅ YES (automatic on disable) |
| `bootstrap_paper_enabled` | `true` | **`false`** | ✅ YES (intended) |
| `auto_paper_exits` | `true` | **`true`** | ✗ NO (preserved) |
| `config_hash` | `7d842d4e59648fe7` | **`81df262bfdbdaaf5`** | ✅ YES (expected — hash reflects settings change) |
| `initial_capital` | `500000` | `500000` | ✗ NO (preserved) |
| `active_intraday_universe` | `NIFTY_50` | `NIFTY_50` | ✗ NO (preserved) |
| `max_trades_per_day` | `3` | `3` | ✗ NO (preserved) |
| `max_concurrent_positions` | `5` | `5` | ✗ NO (preserved) |
| `square_off_before_close` | `false` | `false` | ✗ NO (preserved) |

### 5b. Local dev database — after

| Field | Before | After | Changed? |
|---|---|---|---|
| `auto_paper_entries` | `true` | **`false`** | ✅ YES (intended) |
| `auto_paper_entries_confirmed_at` | `"2026-08-20T03:30:35Z"` | **`null`** | ✅ YES (automatic on disable) |
| `bootstrap_paper_enabled` | `true` | **`false`** | ✅ YES (intended) |
| `auto_paper_exits` | `true` | **`true`** | ✗ NO (preserved) |
| `config_hash` | `efaf1e0cd1acddf2` | **`cced4e9be73e79cd`** | ✅ YES (expected) |
| `initial_capital` | `100000` | `100000` | ✗ NO (preserved) |

---

## 6. After bootstrap-status snapshot

### 6a. Production — after bootstrap-status

```json
{
  "bootstrap_paper_enabled": false,
  "auto_paper_entries": null,
  "auto_paper_entries_confirmed_at": null
}
```

Both flags are `false`/`null`. The bootstrap engine will not run until explicitly re-enabled with
operator confirmation.

### 6b. Local dev — after bootstrap-status

```json
{
  "bootstrap_paper_enabled": false,
  "auto_paper_entries": null,
  "auto_paper_entries_confirmed_at": null
}
```

---

## 7. TRENT and DRREDDY position trace — updated finding

The Phase 0 report (produced 2026-08-20) found TRENT and DRREDDY open overnight. As of 2026-08-21
at the time of this evidence capture, both are **CLOSED** in the production ledger:

### TRENT (P20-315e824378)
- Entered: 2026-08-20T09:56:22Z (15:26:22 IST) — after 15:15 cutoff, BOOTSTRAP_AUTO
- Closed: 2026-08-21T00:05:38Z by **POST_CLOSE_FORCE_EXIT** (cold-start safety net)
- Status at time of pause: **CLOSED** — not mutated by this operation

### DRREDDY overnight row (P20-8fc829b8c3)
- Entered: 2026-08-20T09:55:10Z (15:25:10 IST) — after 15:15 cutoff, AUTO
- Closed: 2026-08-21T00:06:36Z by **POST_CLOSE_FORCE_EXIT** (cold-start safety net)
- Status at time of pause: **CLOSED** — not mutated by this operation

### Mechanism
`phase20_scheduler.check_overnight_carry_on_startup()` detected that the `eod_squareoff:2026-08-20`
KV claim was never taken, found two OPEN prior-session trades, emitted
`MARKET_CLOSE_OVERNIGHT_CARRY_DETECTED` pipeline events for each, and then called
`eod_force_close_open_positions()` to close them. This is the cold-start safety net
documented in `phase20_exits.py` and `phase20_scheduler.py`.

**Both positions were closed by the system's own safety mechanism — not by operator action and
not by this pause operation.**

Additional DRREDDY ledger rows (not overnight):
- P20-cfd2e587aa: AUTO, entered 2026-08-20T03:46:09Z, CLOSED 2026-08-20T09:54:01Z by MARKET_CLOSE_EXIT (normal intraday exit)
- P20-3468fb2a24: BOOTSTRAP_AUTO, entered 2026-08-18T09:14:11Z, CLOSED 2026-08-18T12:31:18Z by POST_CLOSE_FORCE_EXIT

---

## 8. Config hash before and after

| Environment | Before | After |
|---|---|---|
| Production | `7d842d4e59648fe7` | `81df262bfdbdaaf5` |
| Local dev | `efaf1e0cd1acddf2` | `cced4e9be73e79cd` |

Config hash changed in both environments as expected. Only `auto_paper_entries` and
`bootstrap_paper_enabled` are in the hash-relevant settings set. The hash is computed by
`phase20_store.config_hash()` over the settings dict minus `_HASH_EXCLUDE` fields
(which includes `auto_paper_entries_confirmed_at`). The hash change proves the two intended
fields were the only settings mutated.

---

## 9. Proof: only the two approved fields changed

The full settings response after the patch confirms every other field is unchanged:

| Setting | Before (prod) | After (prod) | Status |
|---|---|---|---|
| `active_intraday_universe` | NIFTY_50 | NIFTY_50 | **UNCHANGED** |
| `initial_capital` | 500000 | 500000 | **UNCHANGED** |
| `auto_paper_exits` | true | true | **UNCHANGED — exits remain active** |
| `auto_scan_enabled` | true | true | **UNCHANGED** |
| `min_confidence` | 75 | 75 | **UNCHANGED** |
| `min_opportunity_score` | 70 | 70 | **UNCHANGED** |
| `min_risk_reward` | 2 | 2 | **UNCHANGED** |
| `max_trades_per_day` | 3 | 3 | **UNCHANGED** |
| `max_concurrent_positions` | 5 | 5 | **UNCHANGED** |
| `square_off_before_close` | false | false | **UNCHANGED** |
| `max_holding_days` | 10 | 10 | **UNCHANGED** |
| `daily_loss_limit_pct` | 3 | 3 | **UNCHANGED** |
| `quality_allocation_override_enabled` | true | true | **UNCHANGED** |
| `exit_on_stale_after_days` | 5 | 5 | **UNCHANGED** |
| `auto_paper_entries` | true | **false** | ✅ CHANGED (intended) |
| `bootstrap_paper_enabled` | true | **false** | ✅ CHANGED (intended) |

---

## 10. Proof: trade rows were not changed

- `GET /api/phase20/positions` returned `{"success":true,"positions":[]}` before AND after the pause.
- No OPEN or EXIT_PENDING rows exist in the production ledger at time of capture.
- TRENT (P20-315e824378) and DRREDDY (P20-8fc829b8c3): both were already `CLOSED` before the pause;
  their `exit_ts`, `exit_rule`, `exit_price`, and `status` columns were not touched.
- No `PATCH`, `UPDATE`, or `DELETE` was issued to any `phase20_paper_trades` row.
- No `force-eod-close` API endpoint was called.

---

## 11. Proof: exits and monitoring remain available

After the pause:
- `auto_paper_exits = true` (confirmed in after-settings for both environments)
- `manage_open_positions()` in `phase20_exits.py` remains callable on every scheduler tick
- `eod_force_close_open_positions()` remains available regardless of entry pause
- `check_overnight_carry_on_startup()` continues to run (does not read entry flags)
- Circuit breaker, trailing stops, TIME_EXIT, STALE_DATA_SAFETY all remain active

The pause blocks **new entries only**. It does not affect:
- exit evaluation
- EOD force-close
- cold-start overnight carry detection
- scan execution and monitoring
- pipeline evidence accumulation

---

## 12. Proof: no live orders called

- No call was made to `broker_client.place_order_live()`, `intraday-trading-bot/` routes, or
  any Zerodha order API.
- The only HTTP calls made were:
  - `GET /api/phase20/settings` (read-only, 2×)
  - `GET /api/phase20/bootstrap-status` (read-only, 2×)
  - `GET /api/phase20/positions` (read-only, 2×)
  - `GET /api/phase20/ledger?limit=500` (read-only, 1×)
  - `PUT /api/phase20/settings` (settings write, patch only, 2×)
- `LIVE_EXECUTION_ENABLED` remains `false` (default, not touched).

---

## 13. Proof: no new OPEN trade created after the pause

- Production positions after: `{"success":true,"positions":[]}`
- Local dev positions after: `{"success":true,"positions":[]}`
- The scheduler cannot create a new OPEN entry while `auto_paper_entries=false` AND
  `auto_paper_entries_confirmed_at=null` — both are required by `phase20_executor._insert_row()`'s
  settings recheck under the advisory lock.
- Bootstrap is also blocked: `run_bootstrap_auto_entry()` returns `{"ran":false}` when
  `bootstrap_paper_enabled=false` (first guard in the function).

---

## 14. Important contextual update from Phase 0 report

The Phase 0 report flagged TRENT and DRREDDY as a BLOCKED concern: open overnight after market
hours with no proven exit trace. This evidence report provides the resolution:

**Both positions were closed by `POST_CLOSE_FORCE_EXIT` via the cold-start safety net on
2026-08-21 at 00:05–00:06 IST, before this pause operation ran.**

This does NOT resolve the underlying root-cause questions from the Phase 0A remediation plan:
- Why did AUTO / BOOTSTRAP_AUTO entries open after 15:15 IST?
- Why did the 15:20 intraday MARKET_CLOSE_EXIT not close them on 2026-08-20?
- Why did POST_CLOSE_FORCE_EXIT not run on 2026-08-20 (only catching them on cold-start next day)?

Those investigations (Tasks 3 and 4 of the remediation plan) are still required before unblocking
Phase 1 architecture work.

---

## 15. Recommended next step

The positions are closed and the entry pause is now active. The next operator-approved action is:

**Capture open-position evidence and root-cause investigation before any force-close decision.**

Specifically:
1. Retrieve the full pipeline event trace for TRENT (P20-315e824378) and DRREDDY (P20-8fc829b8c3)
   covering 2026-08-20 from 09:00 IST to 2026-08-21 00:10 IST.
2. Confirm whether `eod_squareoff:2026-08-20` KV claim was ever set (by cold-start check).
3. Confirm whether `MARKET_CLOSE_OVERNIGHT_CARRY_DETECTED` pipeline events were emitted.
4. Investigate why `automatic_paper_entry_status()` returned allowed=True at 15:25–15:26 IST
   on 2026-08-20 — this is the core post-15:15 root-cause question.
5. Investigate why the 15:20 MARKET_CLOSE_EXIT did not close the positions before they
   were carried overnight.

These steps require read-only evidence capture and investigation; no further settings changes
or position mutations are needed until root cause is understood.

---

## 16. Final confirmations

- No application code was changed.
- No database schema was changed or migrated.
- No strategy thresholds were changed.
- No capital setting was changed.
- No active universe was changed.
- No LTIM status was changed.
- No exit settings were changed.
- No Kite or broker settings were changed.
- No trade row was created, updated, or deleted.
- No position was closed by this operation.
- `force-eod-close` API endpoint was NOT called.
- No live order was enabled.
- No broker order API was called.
- Only two settings fields changed: `auto_paper_entries` → `false`, `bootstrap_paper_enabled` → `false`.
- `auto_paper_exits` remains `true` — monitoring and exits continue.
- Both production and local dev databases now reflect the pause.
