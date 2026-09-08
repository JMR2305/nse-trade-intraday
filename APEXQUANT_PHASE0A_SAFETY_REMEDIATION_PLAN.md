# ApexQuant Phase 0A — Safety Remediation Plan

**Status:** **BLOCKED — plan only. No implementation authorization.**
**Prepared:** 21 August 2026
**Controlling evidence:** `APEXQUANT_PHASE0_HARD_VERIFICATION_AND_AUTHORITY_LOCK_REPORT.md`
**Scope:** Resolve Phase 0 blockers before any Phase 1 intraday or multi-agent work.

> **Phase 0A non-action confirmation:** This document changes no code, setting, threshold, database row, schema, migration, workflow, or broker behavior. It does not close TRENT or DRREDDY. It does not enable live orders or call any broker/order API. All proposed trade actions below are explicitly paper-only and require separate operator approval.

## 1. Blocking summary

Phase 1 remains blocked because the paper-trading control baseline is not safe to extend:

1. `P20-315e824378` (TRENT) and `P20-8fc829b8c3` (DRREDDY) are still `OPEN` after the 20 August session.
2. Their recorded fill times are 15:26:22 IST and 15:25:10 IST, respectively—after the documented 15:15 IST automatic-entry cutoff.
3. The current Phase 20 ledger and reviewed EOD evidence do not prove a successful market-close exit, a force-close, a pending transition, or a durable blocked outcome for either row.
4. Automatic paper entry and bootstrap are enabled in production, allowing further exposure while the discrepancy is unresolved.
5. Settings drift exists: ₹500,000 capital, NIFTY 50 active, LTIM active, and zero observed custom-universe rows conflict with prior operator intent.
6. `phase20_paper_trades` is operationally canonical but not database-immutable after closure.
7. Legacy stores, parallel portfolio projections, a separate live-order-capable bot, and an API-server live broker method lack an enforceable quarantine boundary.

**Phase 0A objective:** decide safe temporary settings, preserve evidence, explain the entry and EOD discrepancies, define future implementation controls/tests, and obtain operator sign-off. It does **not** make any change itself.

---

## 2. Immediate operator safety options

No option below is executed by this plan. A later approved operator action must record the settings snapshot before and after, operator identity, UTC and IST timestamps, configuration hash, and the exact confirmation text.

| Option | Exact effect | Risk remaining | Rollback | Required evidence before/after | Assessment |
|---|---|---|---|---|---|
| **A. Pause auto paper entries only** | Set `auto_paper_entries=false`. Normal `AUTO` entries stop. Because bootstrap also requires auto entries and the confirmation timestamp, `BOOTSTRAP_AUTO` is operationally blocked too, even if `bootstrap_paper_enabled` remains true. Exits/monitoring remain available. | The bootstrap flag remains truthy and can resume if auto entries are re-enabled without clearing it; operator intent is less obvious in UI/audit. | Restore `auto_paper_entries=true` only after a new explicit confirmation and remediation exit criteria. | Pre/post settings payload, config hash, confirmation fields, scheduler tick showing `entries` and `bootstrap` skipped, no new `OPEN` ledger row. | Safer than leaving enabled, but less clear than C. |
| **B. Pause bootstrap only** | Set `bootstrap_paper_enabled=false`. `BOOTSTRAP_AUTO` stops; normal `AUTO` can still open paper positions. | Normal auto entry can repeat the cutoff/EOD incident. | Restore bootstrap only after separate approval and new confirmation of evidence threshold policy. | Pre/post settings, config hash, scheduler output showing bootstrap skipped, entry audit proving normal AUTO is still intentionally enabled. | Not recommended while cutoff/EOD proof is unresolved. |
| **C. Pause both auto paper entries and bootstrap** | Set `auto_paper_entries=false` and `bootstrap_paper_enabled=false`; preserve auto exits/monitoring. No new `AUTO` or `BOOTSTRAP_AUTO` Phase 20 positions may be created. | Existing open positions still require approved remediation. Manual/internal bypasses must still be proved absent; no setting change alone creates immutability. | Restore each setting separately, with a fresh explicit confirmation after all unblock criteria are met. | Pre/post settings and config hashes; scheduler output shows normal entries and bootstrap skipped; zero post-pause canonical `OPEN` entries; exits still schedule/operate. | **Recommended safest temporary option.** It minimizes new exposure and expresses intent unambiguously. |
| **D. Leave both enabled** | No immediate change. `AUTO` and `BOOTSTRAP_AUTO` may continue while the current settings permit. | Highest risk: another post-cutoff or unclosed paper position can be created before the root cause is proved. | Not applicable. A later pause would not undo positions created in the interim. | Before retaining: proof of deployed build, clock, final admission gate, EOD execution, blocked-event durability, prior-session carry check, and clean test/production route evidence. | Not safe now. Consider only after all relevant Phase 0A acceptance criteria pass. |

### Recommended immediate operator decision

**Approve Option C: pause both automatic paper entries and bootstrap, while leaving paper exits/monitoring enabled.**

This is a recommendation only. It must be enacted through a separate, explicit operator-approved settings change—not by this report or its author. The change must not alter capital, universe, LTIM, thresholds, or exit settings in the same request; doing so would blur the safety evidence.

---

## 3. Open-position remediation plan

### 3.1 Common paper-only operating rules

1. Freeze the forensic record first; do not issue a closing action merely because a row is old.
2. Capture the exact canonical ledger row, the paper portfolio state, current settings/config hash, scan context, pipeline events, notifications, relevant `phase20_kv` EOD claims, and scheduler state before any remediation.
3. Verify the paper portfolio actually contains the same quantity as the Phase 20 ledger. A forced ledger-only closure would create a cash/equity inconsistency.
4. If a paper close is approved, use only the existing paper-only endpoint `POST /api/phase20/force-eod-close`. It must be presented to the approving operator as an EOD paper-state action; it never calls a live broker order API.
5. A close action is not authorization to alter historical entry fields, delete a ledger row, or edit a realized P&L manually.

### 3.2 TRENT remediation record

| Field | Required value / action |
|---|---|
| Trade ID | `P20-315e824378` |
| Symbol | `TRENT` |
| Quantity | 5 |
| Entry/fill time | `2026-08-20T09:56:22Z` = **15:26:22 IST** |
| Entry/fill price | ₹2,971.45 |
| Trigger source | `BOOTSTRAP_AUTO` |
| Current status | `OPEN` |
| Missing exit evidence | No observed `CLOSED` ledger row with `MARKET_CLOSE_EXIT` or `POST_CLOSE_FORCE_EXIT`; no observed `EXIT_PENDING`; no observed durable `MARKET_CLOSE_EXIT_BLOCKED`; no observed `PAPER_TRADE_FORCE_CLOSED` event. A pipeline event is **not required** for a normal `MARKET_CLOSE_EXIT`, so the authoritative missing artifact is the closed ledger row. |
| Recommended action | Preserve evidence; approve Option C; then choose either (1) read-only root-cause completion before a later paper close, or (2) a separately approved paper-only force-close after the pre-action checklist below. |

**Exact pre-action evidence to capture**

1. Full `phase20_paper_trades` row for `P20-315e824378`, including all evidence JSON, entry/exit fields, `config_hash`, and timestamps.
2. Current canonical portfolio projection and underlying paper portfolio quantity/cash for TRENT.
3. All `pipeline_events` for trade ID, symbol, and scan ID from 20 August 09:00–18:30 IST, including event ID, timestamp, type, stage, dedupe key, and payload.
4. All `phase20_notifications` for the trade, symbol, and `MARKET_CLOSE_*` categories.
5. `phase20_kv` values for `eod_squareoff:2026-08-20`, `eod_squareoff_unresolved:2026-08-20`, `startup_overnight_check:2026-08-21`, and relevant scan/claim keys.
6. `phase20_scheduler_state` history/last state, owner/instance identifier, last attempt/success/error, and scan-run rows bracketing 15:15, 15:20, 15:30, and post-close.
7. Existing scan context and price provenance that a force-close would use. Do not substitute an unrecorded live price.

**Exact operator-approved action if force close is chosen**

> “Approve a paper-only EOD remediation for `P20-315e824378` / TRENT / quantity 5. Call `POST /api/phase20/force-eod-close` once after capturing the listed pre-action evidence. This may use the Phase 20 paper sell service and canonical ledger transition only; it must not call a real broker order API or alter any entry evidence.”

**Exact post-action evidence to capture**

1. HTTP response with request/correlation ID, result status, `force_closed`, `blocked`, and `unresolved` entries.
2. The canonical ledger row, showing either a single valid `CLOSED` transition with `POST_CLOSE_FORCE_EXIT`, or still `OPEN` with a durable blocked outcome. Do not accept a silent no-op.
3. Matching paper portfolio sell/state delta and canonical portfolio cash/equity recalculation.
4. `PAPER_TRADE_FORCE_CLOSED` event or `MARKET_CLOSE_EXIT_BLOCKED` event with event ID/payload. For a successful direct intraday market-close exit, ledger evidence remains primary.
5. Notification, EOD status response, scheduler/claim state, and a no-duplicate-open-position check.

### 3.3 DRREDDY remediation record

| Field | Required value / action |
|---|---|
| Trade ID | `P20-8fc829b8c3` |
| Symbol | `DRREDDY` |
| Quantity | 20 |
| Entry/fill time | `2026-08-20T09:55:10Z` = **15:25:10 IST** |
| Entry/fill price | ₹1,181.87 |
| Trigger source | `AUTO` |
| Current status | `OPEN` |
| Missing exit evidence | No observed `CLOSED` ledger row with EOD rule, `EXIT_PENDING`, durable blocked EOD event, or force-close event. As with TRENT, the absence of an intraday-close pipeline event alone is not conclusive because normal `MARKET_CLOSE_EXIT` is ledger-only. |
| Recommended action | Same ordered plan as TRENT. Do not close it independently without a matching pre/post evidence package. |

**Exact pre-action evidence to capture:** the seven TRENT items above, substituting `P20-8fc829b8c3` and DRREDDY. Include the documented nearby sizing notification (98 to 21, final ledger quantity 20) to preserve the admission/sizing evidence chain.

**Exact operator-approved action if force close is chosen**

> “Approve a paper-only EOD remediation for `P20-8fc829b8c3` / DRREDDY / quantity 20. Call `POST /api/phase20/force-eod-close` once after the full pre-action evidence package is captured. No real broker order API is authorized.”

**Exact post-action evidence to capture:** the five TRENT post-action items above, substituting the DRREDDY trade ID and symbol.

### 3.4 Escalation rule

If either force-close response contains `blocked` or `unresolved`, do **not** retry blindly. Preserve the response, claim state, and event ID, determine whether the paper sell or ledger update failed, and open a separate reconciliation/remediation decision. The retry path must never issue a duplicate sell after a terminal ledger close or durable blocked event.

---

## 4. Root-cause plan: post-15:15 AUTO and BOOTSTRAP_AUTO entries

### 4.1 What current source proves

Current source is designed to deny new automatic paper entries after 15:15 IST:

- `market_hours.automatic_paper_entry_status()` uses `Asia/Kolkata`, requires `OPEN`, and blocks at `PAPER_ENTRY_CUTOFF = 15:15`.
- `phase20_executor._insert_row()` calls `_market_entry_status()` before admission and repeats the check immediately before the durable insert, after the advisory lock.
- The final insert boundary applies to an `OPEN` row regardless of whether it originated from normal auto entry or bootstrap.
- `run_bootstrap_auto_entry()` requires the same auto-entry confirmation and creates canonical paper positions through the ordinary paper-entry infrastructure.
- `phase20_scheduler._manage_paper()` invokes normal auto entry and bootstrap only when persisted auto-entry confirmation is present.

Therefore, the observed post-cutoff rows are not a reason to weaken the current intended rule. They establish a **production/code discrepancy** that must be explained with deployment and forensic evidence.

### 4.2 Root-cause candidates and proof plan

| Candidate | Exact files/functions involved | Why it remains plausible | Evidence needed to prove or rule it out | Proposed remediation if proved |
|---|---|---|---|---|
| **Deployed build/version predates the final ledger-time cutoff guard** | `market_hours.py`, `phase20_executor._insert_row()`, `run_auto_entries()`, `run_bootstrap_auto_entry()` | Current source contains two final checks, yet production ledger shows late entries. The observations may predate their deployment. | Production deployment/build ID at 20 August entry time; release/deploy history; hash of deployed Python artifact; current public build label; source commit containing the two checks. | Deploy the verified guard build after test suite passes; record build ID in every entry’s evidence. |
| **Server clock/time-zone disagreement** | `market_hours.now_ist()`, `automatic_paper_entry_status()`, `_iso()`/entry timestamp creation in executor, scheduler process clock | The check uses server `datetime.now(IST)`, while ledger timestamps are UTC. A bad host clock or different execution process clock could create a false pass. | Scheduler host/instance time and timezone around 15:15; structured admission log with both UTC and IST; database `now()` versus process timestamp; historical deployment logs. | Add admission audit fields for `checked_at_utc`, `checked_at_ist`, market state, cutoff, and build ID; fail closed on clock/DB skew beyond approved tolerance. |
| **Alternative entry writer/bypass path** | `phase20_executor._insert_row()`, all `INSERT INTO phase20_paper_trades` call sites, routes/jobs, manual tools | A direct writer could avoid the guarded executor, despite the intended single writer boundary. | Static call map of every Phase 20 insert; production DB role/audit logs; route/job invocation history; verify no manual SQL/maintenance tool wrote the row. | Enforce database insert provenance; deny direct production inserts except trusted service role; add import/call test. |
| **Bootstrap-specific path passed an old/unpatched runtime module** | `run_bootstrap_auto_entry()`, scheduler `_manage_paper()` | TRENT uses `BOOTSTRAP_AUTO`; bootstrap may have been running in a process with stale module/deployment. | Bootstrap event payload, process/instance ID, deployed module version, scan ID/claim timestamps, method call trace. | Route bootstrap through the same admission contract only; assert `trigger_source` does not bypass the final guard in tests. |
| **Stale signal time was confused with actual decision/fill time** | Ledger `signal_ts`, `decision_ts`, `simulated_order_ts`, `fill_ts`; `run_auto_entries()`/bootstrap evidence | Both signals may originate before 15:15, but that must never permit a later decision/insert. | All four timestamp fields, event timestamps, database insert timestamp, scheduler tick start/end, scan snapshot timestamp. | Test and log that decision and durable insert time—not signal time—govern admission. |
| **Manual/override/internal route** | Phase 20 routes, command routes, executor helpers, maintenance scripts | No positive evidence yet identifies a manual action; the source tree must be exhaustively searched. | HTTP/access audit for actor/request ID, route logs, operator command records, SQL audit logs. | Make manual paper entry a separately labeled feature with the same cutoff or a break-glass approval token and audit trail. |
| **Early gate existed but final gate was not active/failed open in deployed build** | `_market_entry_status()`, exception handling, database admission branch | Current code fails closed on status error; an older build might not. | Deployed source artifact plus any exception/log record from the entry time. | Keep fail-closed final gate; test failure of market-hours provider and no `OPEN` insert. |

### 4.3 Investigation sequence

1. Freeze and export both full ledger rows plus correlated scan, event, scheduler, notification, and claim evidence.
2. Establish one timeline in UTC and IST for each trade: signal, scan completion, scheduler tick start/end, decision, simulated order, fill/insert, and all EOD events.
3. Identify the production build and process owner that inserted each row.
4. Compare deployed source/artifact to the current two-check admission contract.
5. Map every Phase 20 `INSERT` writer and every route/job that can invoke it.
6. Compare application clock, database clock, and stored timestamps.
7. Only then select the smallest corrective implementation plan.

### 4.4 Fix plan (future, not implemented)

1. Make `_insert_row()` the sole production creation boundary and reject any unrecognized writer/provenance.
2. Persist a non-editable admission audit record for both accepted and rejected entries: timestamp in UTC/IST, market state, cutoff, trigger source, build ID, process/instance ID, settings/config hash, scan ID, and correlation ID.
3. Ensure normal and bootstrap entry paths call the exact same final admission predicate under the existing advisory lock.
4. Require a durable terminal rejection event for every candidate blocked by cutoff; failed event emission must not permit an insert.
5. Add deployment/version verification to the release checklist before automation is unpaused.

### 4.5 Tests required

- Unit tests for `automatic_paper_entry_status()` at 15:14:59, 15:15:00, 15:20, 15:30, holiday, and DST-irrelevant IST conditions.
- `AUTO` admission test: a candidate begun before 15:15 but blocked on advisory lock until after 15:15 cannot insert.
- `BOOTSTRAP_AUTO` equivalent admission test.
- Test that a stale signal timestamp before cutoff cannot authorize a decision/fill after cutoff.
- Test that market-hours import/status failure fails closed.
- Test that every `OPEN` insert path, including direct/internal scheduler paths, reaches the final admission guard.
- Production-route/deploy test that records current build ID and demonstrates a post-cutoff candidate yields an explicit terminal rejection without a ledger insert.

---

## 5. Root-cause plan: EOD and force-close gap

### 5.1 What current source proves

- `phase20_exits.manage_open_positions()` should request `MARKET_CLOSE_EXIT` at or after 15:20 IST while market state is `OPEN`.
- If its quote is not reliable, it transitions to `EXIT_PENDING`; it must not fabricate a fill.
- `phase20_scheduler.py` has a POST_CLOSE/CLOSED path that claims `eod_squareoff:<IST-date>` and invokes `eod_force_close_open_positions()`.
- `eod_force_close_open_positions()` should force-close with fresh current-session price when available, otherwise an honest fill-price fallback; if it cannot close, it should write a deduplicated `MARKET_CLOSE_EXIT_BLOCKED` event.
- `check_overnight_carry_on_startup()` is a next-day safety net if the prior day never claimed EOD square-off. It should emit `MARKET_CLOSE_OVERNIGHT_CARRY_DETECTED` and invoke the force-close function for prior-session positions.
- `phase20_eod_status.py` treats the ledger as the authoritative result for successful EOD closures. `MARKET_CLOSE_EXIT` normally does **not** emit a pipeline event, so an absent normal-close event does not prove the scheduled exit did not run.

### 5.2 Evidence interpretation correction

For each open trade, the exact missing expected artifacts are:

| Scenario | Required durable artifact | Current finding |
|---|---|---|
| `MARKET_CLOSE_EXIT` succeeds | `phase20_paper_trades` row becomes `CLOSED` with `exit_rule='MARKET_CLOSE_EXIT'` | Missing for both trade IDs |
| Normal exit has no reliable quote | Ledger becomes `EXIT_PENDING` with pending rule/context | Missing for both trade IDs |
| `POST_CLOSE_FORCE_EXIT` succeeds | Ledger becomes `CLOSED` with `exit_rule='POST_CLOSE_FORCE_EXIT'`; `PAPER_TRADE_FORCE_CLOSED` event is expected best-effort evidence | Missing for both trade IDs |
| Force-close cannot sell/update/price | Durable `MARKET_CLOSE_EXIT_BLOCKED` event, one deduped outcome per trade/session | Missing for both trade IDs in reviewed evidence |
| Startup detects missed prior EOD | `MARKET_CLOSE_OVERNIGHT_CARRY_DETECTED` plus remediation result | Missing/not proven in reviewed evidence |

**Exact missing event IDs:** none can be named because no matching rows were found. The forensic query must return the actual primary/event IDs, dedupe keys, timestamps, payloads, and database errors—not fabricate identifiers in a report.

### 5.3 Likely root-cause candidates

| Candidate | Why plausible | Evidence required | Future corrective action |
|---|---|---|---|
| Scheduler did not tick during the 15:20–post-close windows | Scheduler scans/events around the period are incomplete; Autoscale/restart timing matters | Scheduler run/instance history, deployment uptime, platform logs, durable heartbeat, scan-run records around 15:15–18:00 IST | Add durable scheduled-job start/result records and alert on missed windows. |
| EOD KV claim was consumed without a result/retry record | EOD execution is claim-gated; a bad claim sequence can suppress retry | Raw `phase20_kv` values/timestamps for 20 August claim/retry keys; scheduler error/log sequence | Claim only after imports/readiness, release on unpersisted outcome, persist outcome state transactionally. |
| `auto_paper_exits` was false at execution time | Force-close respects the exit setting even though current settings show true | Historic settings/audit snapshot, config hash stored on execution, notification/event evidence | Audit setting changes and record evaluated settings in every EOD result. |
| Intraday exit was not called because `_manage_paper()` did not run during final OPEN tick | Normal exit management is invoked from scheduler paths; a last-tick/session transition race exists in source comments | Tick timeline, `ran_scan`, `_manage_paper` result, task logs | Schedule an explicit 15:20 EOD exit job independent of scan cadence. |
| Paper sell service rejected due to portfolio divergence | EOD code leaves ledger `OPEN` intentionally if `execute_sell()` rejects | Paper portfolio state/history, `execute_sell` error, reconciler result, blocked event | Enforce ledger/portfolio reconciliation and persist sell/ledger dual-write outcomes. |
| Ledger close update failed after a successful paper sell | Source has a specific blocked path for this desync | Paper sell trace plus ledger update exception, blocked event | Transactional reconciliation / idempotent compensation and alert. |
| EOD audit-event persistence failed | Source retains unresolved outcomes to avoid silence, but exact persistence/claim outcome must be proven | Event-store/database error, retry-key data, subsequent retry result | Persist event/outcome before final claim; periodically reconcile pending audit writes. |
| Startup carry safety net never ran or was precluded by stale claim | Next-day code should address prior-session rows | Startup logs/claim, process lifecycle, current overnight event query | Run startup carry check before any new-entry work; alert if it does not complete. |

### 5.4 Investigation sequence

1. Query the canonical ledger by both trade IDs and all EOD exit rules.
2. Query `pipeline_events` by trade ID/symbol/date for `MARKET_CLOSE_EXIT_BLOCKED`, `PAPER_TRADE_FORCE_CLOSED`, `MARKET_CLOSE_OVERNIGHT_CARRY_DETECTED`, and `EXECUTION_SKIPPED_WITH_REASON`.
3. Query notifications and `phase20_kv` claims/retry keys.
4. Reconstruct scheduler instance lifecycle and all tick outcomes from 15:15 to 18:00 IST, including post-close early-return path.
5. Compare the paper portfolio trade/position state to the ledger before any proposed close.
6. Verify historic settings at the actual EOD execution point, not merely the setting value observed today.
7. Identify whether the failure is not-invoked, skipped, paper-sell rejected, ledger-write failed, audit-write failed, or unobserved due to retention/log gaps.

### 5.5 Fix plan (future, not implemented)

1. Add a durable per-trade EOD outcome record (attempted, close, pending, blocked, error) keyed by `session_date + trade_id`, independent of best-effort notifications.
2. Invoke an explicit EOD exit task at 15:20 and an explicit force-close task at 15:30, rather than coupling first attempt to scan cadence.
3. Make KV claim/outcome persistence retry-safe: no terminal claim without either a ledger close or durable blocked/pending outcome.
4. Run startup overnight-carry detection before any automatic entry and block entries if it cannot complete.
5. Surface previous-session EOD status, not only today’s EOD window, on the operator UI.
6. Add a reconciliation alarm if paper portfolio and Phase 20 ledger disagree on an `OPEN` trade.

### 5.6 Tests required

- 15:20 scheduler transition closes an `OPEN` row with a reliable quote.
- 15:20 stale/no-price case creates `EXIT_PENDING` with no fabricated price.
- 15:30 force-close closes using valid fallback and records provenance.
- Force-close paper-sell failure leaves row open and writes exactly one blocked outcome.
- Ledger close write failure after paper sell produces durable reconciliation-required outcome.
- Failed event audit write remains retryable without issuing a second sell.
- Restart/missed EOD window causes startup carry detection and a single remediation attempt.
- EOD claim is not permanently consumed on import/function/DB failure.
- Previous-session result is visible in route/UI data.

---

## 6. Settings reconciliation form

No setting is selected or applied in this plan. The operator must choose one option in each group and sign/record the resulting configuration snapshot.

### 6.1 Operator decision form

| Decision | Current observed value | Operator selection (choose one) | Required evidence |
|---|---|---|---|
| **Capital** | ₹500,000 | ☐ Keep ₹500,000  ☐ Restore ₹100,000  ☐ Set another approved amount: ₹________ | Current capital projection, open exposure, closed P&L, config hash, reason, effective date. Capital change must not be bundled with exit remediation. |
| **Active universe** | `NIFTY_50`; 50 active symbols observed | ☐ Keep NIFTY 50  ☐ Switch to low-price IT/Infra/Bank  ☐ Populate/publish custom universe first, then switch | Current universe master/membership snapshots, symbol count, sector/price criteria, history preservation plan, coverage validation. |
| **LTIM** | Active in `nifty50_company_master` | ☐ Keep active  ☐ Remove from active universe while preserving historical membership | Before/after active membership and history snapshot; reason and effective date. |
| **Auto paper entries** | Enabled/confirmed | ☐ Pause until safety proof  ☐ Keep enabled after all Phase 0A acceptance criteria pass | Settings payload/config hash; cutoff/EOD proofs; explicit confirmation; no unsafe change bundled. |
| **Bootstrap** | Enabled | ☐ Pause until safety proof  ☐ Keep enabled after all Phase 0A acceptance criteria pass  ☐ Retire | Settings payload/config hash; evidence threshold policy; distinct explanation from normal auto entry. |

### 6.2 Settings acceptance criteria

Before resuming any automatic entry:

- chosen capital and active universe have a single documented authority;
- LTIM choice is reflected in current universe plus preserved history;
- any custom universe is populated, versioned, and coverage-validated;
- deployed entry build and EOD route evidence pass;
- no prior-session `OPEN` or unresolved EOD `BLOCKED` rows remain without explicit operator disposition;
- a fresh confirmation is recorded after—not before—the safety proof.

---

## 7. Closed-trade immutability implementation plan

This section is a future design/implementation plan only. It does not create a migration or trigger.

### 7.1 Storage contract

| Requirement | Proposed enforcement |
|---|---|
| Entry provenance cannot change | Immutable ledger fields after insert: identity, symbol, side, quantity, scan/signal/decision/fill timestamps, entry price/costs, strategy, model/rule/config versions, trigger source, and entry evidence. |
| Allowed lifecycle | Only `OPEN → EXIT_PENDING → CLOSED`. Permit `EXIT_PENDING → CLOSED` when a valid exit resolution is recorded. Deny all other status changes absent controlled break-glass correction. |
| Closed rows are immutable | PostgreSQL `BEFORE UPDATE OR DELETE` trigger rejects any direct update/delete where old status is `CLOSED`. |
| No direct deletion | Replace executor delete/rollback behavior for durable records with a pre-insert rollback transaction or append-only cancellation/correction record; no historical trade deletion. |
| Correction mechanism | New append-only `phase20_trade_corrections` record referencing immutable original `trade_id`, correction type, field delta, reason, evidence, actor, approvals, timestamp, and correlation ID. It never overwrites history. |
| Audit metadata | Add an append-only `phase20_trade_audit_events` table or event-stream entries for all insert/transition/correction/rejected mutation attempts: actor, role/source, route/job/agent, correlation/request ID, scan ID, build ID, old/new status, payload hash, timestamp, outcome. |
| Migration exception | A separate database maintenance role can bypass only in an approved, time-bounded migration transaction with migration ID, actor, approvals, and a matching immutable audit event. Normal API/scheduler roles cannot disable the trigger. |

### 7.2 Future migration sequence

1. Inventory all actual Phase 20 writer roles and existing closed rows.
2. Add audit/correction storage and backfill only non-destructive baseline audit metadata.
3. Replace application delete paths with safe pre-insert rollback or correction handling.
4. Add transition-aware trigger and test it against every current exit path.
5. Deploy in observe-only/audit mode if necessary; validate against paper EOD and pending-resolution flows.
6. Enforce trigger for the service role; verify direct SQL update/delete is rejected.

### 7.3 Required tests

- `CLOSED` row update is rejected by database trigger, including generic helper path.
- `CLOSED` row delete is rejected by database trigger.
- Valid `OPEN → EXIT_PENDING → CLOSED` and `OPEN → CLOSED` EOD transitions succeed only with required audit data.
- Invalid backward/skipped transitions are rejected.
- Entry rollback before durable commit remains possible without deleting historical rows.
- Correction creates a new append-only record and does not alter original row.
- Migration role exception is time-bounded, logged, and unavailable to application role.
- Concurrent exit/retry process cannot create duplicate transition/audit records.

---

## 8. Legacy-store and live-order quarantine plan

### 8.1 Formal authority boundary

Only the Phase 20 ledger and its verified canonical portfolio projection may determine current Phase 20 position, cash, equity, P&L, EOD status, risk exposure, or entry eligibility. No legacy or experimental store may supply fallback truth.

| Asset | Label / handling | Block from Phase 20 authority | Future tests | UI warning / later retirement |
|---|---|---|---|---|
| `paper_trades` | **LEGACY PAPER-TRADE STORE** | Cannot feed Phase 20 positions/cash/equity/entry/exit/risk; read-only migration/report use only | Static import test; runtime source-tag assertion; no Phase 20 route response may contain its rows as canonical | Label Portfolio/Phase 11 surfaces; retire after read-only export/reconciliation window |
| `paper_portfolio` | **LEGACY PORTFOLIO STATE** | Cannot be fallback source for canonical projection or EOD state | Prohibit imports from Phase 20 path; divergence test | Strong legacy banner; retire after verified ledger projection replaces all consumers |
| `experimental_paper_trades` | **EXPERIMENTAL / NON-CANONICAL** | Cannot affect real paper capital, positions, risk, exit or readiness | Scheduler mode test; assertion experiments never call canonical writer | Experimental label; retain only if research value remains |
| `portfolio_events` | **PARALLEL PORTFOLIO PROJECTION** | Cannot become a second ledger or override Phase 20 | Bridge contract test; fail if event-sourced projection is used as fallback | Source badge; later keep only as one-way derived view or retire |
| `portfolio_snapshots` | **PARALLEL SNAPSHOT / NON-AUTHORITATIVE** | Cannot override ledger-derived equity/positions | Snapshot-vs-canonical reconciliation test | Source badge; retire or rebuild as canonical cache |
| `phase11_price_snapshots` | **PHASE 11 LEGACY PRICE HISTORY** | Cannot be treated as intraday Phase 20 price/exit provenance | Import/source scan | Legacy data source label; retain historical reporting only |
| `phase11_capital_topups` | **UNOWNED LEGACY CAPITAL DATA — QUARANTINED** | Cannot alter/display Phase 20 capital until writer/owner/history are established | Schema/writer/UI ownership test | Prominent unknown-source label; retire or migrate only after owner decision |
| `intraday-trading-bot` order routes | **QUARANTINED LIVE-CAPABLE LEGACY SERVICE** | No deployment, import, scheduler, shared route gateway, or Phase 20 DB authority connection | CI boundary test across projects; deployment manifest check; no exposed route in ApexQuant artifact | Not shown as a Phase 20 control; retire/deploy separately only with an independent approval |
| `broker_client.py` live order method | **FORBIDDEN FROM PHASE 20** | No Phase 20/scheduler/agent code may import, instantiate, or call `ZerodhaBrokerClient.place_order_live` | AST/import/call-graph test blocks `place_order_live`, `kite.place_order`, `modify_order`, `cancel_order` from all Phase 20 reachability roots | No UI access; preserve only behind a separate non-ApexQuant boundary or retire |

### 8.2 Required enforcement work after approval

1. Create an explicit source-tag enum/response field: `CANONICAL_PHASE20`, `LEGACY_PHASE11`, `EXPERIMENTAL`, `PARALLEL_PROJECTION`, or `UNKNOWN`.
2. Fail builds when a Phase 20 entry, exit, scheduler, agent, or canonical portfolio module imports a prohibited legacy store or live-order symbol.
3. Add a deployment boundary check: only the API-server/trading dashboard/mobile artifacts may be part of ApexQuant; the legacy bot cannot share its scheduler or app route surface.
4. Add database-role or connection ownership documentation so legacy writers cannot mutate Phase 20 authority tables.
5. Maintain a one-way, explicitly labeled bridge only where historic reporting needs a legacy display.

---

## 9. UI safety visibility plan

No UI is changed by this plan. Future UI work must show source, freshness, state, and operator control truth—not merely a green aggregate status.

| Surface | Required safety visibility | Data/source rule |
|---|---|---|
| **Mission Control** | Persistent safety strip: auto entries on/off, bootstrap on/off, active capital, active universe/version, source badge, scheduler/EOD state, latest scan freshness, count and list of prior-session opens, `EXIT_PENDING`, unresolved EOD blocked outcomes | Phase 20 settings, `canonical_portfolio`, Phase 20 ledger, EOD outcome record, canonical scan state. Do not synthesize from legacy portfolio or only pipeline counts. |
| **AI Paper Trader** | Entry-control panel with explicit confirmation status, cutoff time/current IST time, bootstrap status, active capital/universe, per-position entry date/session badge, `OPEN`/`EXIT_PENDING`, EOD rule/outcome, force-close requires explicit operator confirmation UI | Phase 20 routes only; `/phase20/positions` quantity is canonical; no hidden generated/legacy fallback. |
| **Portfolio / Risk pages** | Visible `Canonical Phase 20` or `Legacy/Parallel Projection` badge on every summary. Warn whenever displaying Phase 11/portfolio snapshot data. Prior-session/open/pending and EOD errors must be visible next to risk/exposure decisions. | Legacy pages cannot claim live Phase 20 truth. Migrate their current exposure cards to canonical projection before using them as operational controls. |
| **Mobile Positions** | Offline/stale banner must include source timestamp and “not safe for trade control.” Display auto/bootstrap flags, capital/universe, prior-session open warning, `EXIT_PENDING`, EOD outcome, and source badge. | Cache cannot hide a newer server error or previous-session EOD blocked outcome; cached payload must preserve source metadata. |

### UI acceptance tests

- With auto entries/bootstrapping paused, all listed surfaces show the disabled state consistently.
- With an open prior-session position, all operator-facing positions pages show a blocking warning.
- With `EXIT_PENDING`, the status is visible and cannot be represented as a normal open position.
- With EOD force-close blocked/unresolved, display the event/reason and no false “healthy” badge.
- With stale/offline data, display age/source and prevent a user from mistaking it for current authority.
- Any legacy/parallel source shows a clear non-canonical label.

---

## 10. Exact unblock test and production-proof plan

### 10.1 Automated tests

| # | Required test | Expected proof |
|---:|---|---|
| 1 | No `AUTO` entry after 15:15 IST | Final ledger insert is rejected and terminal cutoff reason is recorded. |
| 2 | No `BOOTSTRAP_AUTO` entry after 15:15 IST | Same final insert rejection; bootstrap cannot bypass it. |
| 3 | Stale signal before cutoff cannot create a decision/fill after cutoff | Decision/insert time governs; no `OPEN` row. |
| 4 | Scheduler EOD closes `OPEN` positions from 15:20 | Valid price produces exactly one `MARKET_CLOSE_EXIT` closure. |
| 5 | Post-close force-close after 15:30 | Surviving open row becomes `POST_CLOSE_FORCE_EXIT` with price provenance/fallback marker. |
| 6 | `EXIT_PENDING` escalates/retries correctly | No fabricated fill; fresh quote resolves once; timeout behaves deterministically. |
| 7 | No duplicate open position | Partial unique index and application guard reject duplicate symbol under concurrent ticks. |
| 8 | `CLOSED` trade cannot be updated or deleted | Storage-level trigger rejects both, not merely application code. |
| 9 | Legacy stores cannot affect Phase 20 portfolio | Canonical projection is unchanged when legacy/experimental/parallel data changes. |
| 10 | Live-order methods cannot be imported/called from Phase 20/scheduler/agent path | AST/import/call test fails CI for forbidden symbols/reachability. |
| 11 | UI shows prior-session-open warning | Mission Control, AI Paper Trader, Portfolio/Risk, and Mobile Positions render explicit warning/state/source. |
| 12 | Production route proof after deployment | Production-safe verification demonstrates build ID, setting truth, cutoff rejection, EOD outcome visibility, source badges, and no prior-session unresolved rows. |

### 10.2 Required non-test production evidence

1. Deployment/build ID and artifact revision proving the verified admission code is live.
2. Controlled paper-only post-cutoff test in a safe/non-trading test mode or time-injected environment—not by creating a real production exposure.
3. A controlled paper EOD lifecycle test with a disposable/sandboxed trade fixture, complete before/after ledger/event/portfolio reconciliation.
4. Production route responses showing settings, canonical source metadata, EOD outcome state, and runtime agent registry/topic proof.
5. A signed operator decision record for capital, universe, LTIM, automation, and bootstrap.

---

## 11. Phase 0A acceptance criteria

Phase 1 can be reconsidered only when all of the following are true:

- [ ] Option C or an equally safe, explicitly approved temporary safety control has been applied and evidenced.
- [ ] TRENT and DRREDDY have an operator-approved disposition with complete before/after evidence; no row was silently modified.
- [ ] The post-15:15 root cause is proven, not guessed, and the corrected deployed build is verified.
- [ ] EOD/force-close execution has durable per-trade outcomes and replayable evidence.
- [ ] All required automated tests pass, including storage-level immutability and prohibited live-order reachability.
- [ ] Capital, universe, LTIM, auto-entry, and bootstrap decisions are recorded and reflected in the authoritative settings/universe data.
- [ ] Legacy stores and live-capable legacy bot code are quarantined by enforceable tests/deployment boundaries.
- [ ] Operator UI displays current authority, stale/pending/EOD/prior-session risks accurately.
- [ ] Production evidence is captured without calling a real broker order API.

---

## 12. Exact recommended next operator action

1. **Approve Option C in writing:** pause both auto paper entries and bootstrap, retaining paper exits/monitoring.
2. Capture the common pre-action evidence package for TRENT and DRREDDY before any trade action.
3. Decide whether to authorize the paper-only `POST /api/phase20/force-eod-close` for both positions, once, with the pre/post evidence rules in Section 3.
4. Do not resume automation or begin Phase 1 while the root-cause and EOD proof investigations remain open.

This is the smallest safe next step because it prevents further automated paper exposure without erasing the evidence required to explain the existing two positions.

---

## 13. Final confirmations

- No application code was changed.
- No settings were changed.
- No positions were changed or closed.
- No migration or schema change was created.
- No strategy threshold was changed.
- No live order was enabled.
- No broker/order API was called.
- The deliverable is this planning document only: `APEXQUANT_PHASE0A_SAFETY_REMEDIATION_PLAN.md`.