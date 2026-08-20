# ApexQuant Phase 0 — Hard Verification and Authority Lock Report

**Status:** Read-only Phase 0 verification. No implementation authorization.  
**Audit date:** 21 August 2026  
**Controlling inventory:** `APEXQUANT_FULL_SYSTEM_PHASE_AGENT_UI_ARCHITECTURE_INVENTORY.md`  
**Additional controls reconciled:**  

- `attached_assets/Pasted-PHASE-0-HARD-VERIFICATION-LOCK-CURRENT-AUTHORITY-SETTIN_1787259726448.txt`
- `attached_assets/Pasted-ADDITIONAL-CONTROL-INPUT-Also-use-apexquant-inventory-i_1787259739738.txt`
- `attached_assets/apexquant-inventory-inconsistency-findings_1787259787849.md`

> **Scope lock:** This report used source inspection, production read-only SQL, deployment metadata, and production `GET` routes. It made no code, database, migration, configuration, threshold, workflow, broker, or position change. It did not invoke any `POST`, `PUT`, `PATCH`, `DELETE`, scan-control, exit-control, setting, or broker order endpoint.

## Final Phase 0 recommendation: **BLOCKED**

Do **not** proceed to Phase 1 intraday/multi-agent implementation until the following current-control findings have an operator-approved disposition:

1. Two current Phase 20 paper positions are `OPEN` after market hours.
2. Both were entered **after the documented 15:15 IST no-new-entry cutoff**.
3. No Phase 20 pipeline exit/EOD trace was found for those open positions in the reviewed production evidence.
4. The intended canonical ledger is not audit-hardened: no production database trigger protects `CLOSED` rows, and generic update/delete helpers exist.
5. Current production settings conflict with historical plans: ₹500,000 capital, NIFTY 50 active, bootstrap and automatic paper entry enabled.
6. Legacy trade/portfolio stores and a separate order-capable bot remain present; their isolation is not yet a formal, testable authority lock.
7. No positive production proof was obtained for framework-agent registry contents, SnapshotBus topics, topic freshness, or heartbeats.

This is a paper-only safety block. It does **not** assert a live broker order was placed.

---

## 1. Normalized evidence-status taxonomy

Every status in this report uses one of the following exact values:

| Normalized status | Meaning |
|---|---|
| **PRODUCTION-OBSERVED** | Verified from the deployed public API, production database read replica, or deployment metadata during this audit. |
| **DEV-SCHEMA-OBSERVED** | Verified from current development database schema only. |
| **CODE-PROVEN** | Found in current source and/or tests. Runtime behavior is not inferred. |
| **IMPLEMENTED, RUNTIME UNKNOWN** | Code, routes, or reports exist, but the deployed worker/route/flow was not positively verified. |
| **PARTIAL / CONFLICTING** | Evidence exists but is incomplete, inconsistent, or contradicted by a current observation. |
| **OBSOLETE / LEGACY** | Superseded or competing implementation that is not approved as a current operational authority. |
| **UNKNOWN** | No sufficient current evidence. |
| **NOT PROVEN** | A required safety claim cannot be established from code, schema, or production evidence. |

### 1.1 Mapping of raw labels from the full-system inventory

| Raw inventory label | Normalized label | Reason / evidence source | Next verification |
|---|---|---|---|
| `PRODUCTION-OBSERVED` | **PRODUCTION-OBSERVED** | Already an exact taxonomy value | Maintain timestamp and route/DB evidence reference |
| `DEV-SCHEMA-OBSERVED` | **DEV-SCHEMA-OBSERVED** | Already an exact taxonomy value | Compare relevant production table/index/trigger where needed |
| `CODE-PROVEN` / `CODE-PROVEN documentation` | **CODE-PROVEN** | Current code or document exists | Positive production route/worker proof when operational |
| `IMPLEMENTED, RUNTIME UNKNOWN` | **IMPLEMENTED, RUNTIME UNKNOWN** | Already an exact taxonomy value | Runtime route/process/scheduler evidence |
| `IMPLEMENTED, PARTIAL` | **PARTIAL / CONFLICTING** | Undefined hybrid; implementation exists but proof is incomplete | Split into code, production, and unresolved evidence |
| `CODE-PROVEN / PRODUCTION-OBSERVED` | **PRODUCTION-OBSERVED** | Runtime observation is stronger; retain source-code reference as supporting evidence | Re-check after deployment changes |
| `CODE-PROVEN / TEST-PROVEN` | **CODE-PROVEN** | Tests prove behavior in test scope, not production | Add production event/route proof |
| `CODE-PROVEN / PARTIAL PRODUCTION` | **PARTIAL / CONFLICTING** | Production evidence is incomplete | List exact observed and unobserved fields |
| `DB-PROVEN` | **PRODUCTION-OBSERVED** or **DEV-SCHEMA-OBSERVED** | Use the environment actually queried | Record database environment and query |
| `LEGACY / FROZEN`, `LEGACY / REVIEWED` | **OBSOLETE / LEGACY** | Non-authoritative/legacy status | Quarantine or retire decision |
| `PROPOSAL ONLY` | **CODE-PROVEN** | Proposal artifact exists; it does not mean implemented | Mark lifecycle as “proposal only” in a separate field |
| `Enabled`, `Active`, `Inactive` | **PRODUCTION-OBSERVED** only when backed by a live setting/response; otherwise **UNKNOWN** | Lifecycle word is not an evidence status | Capture current route/database value |
| `Not ApexQuant production authority` | **OBSOLETE / LEGACY** | Explicit authority exclusion | Test/import/deployment quarantine |
| `NOT PROVEN` | **NOT PROVEN** | Already an exact taxonomy value | Follow the specific proof requirement |

### 1.2 Required row format for future inventories

Do not combine lifecycle and evidence in one label. Every future inventory row should use:

`item | raw status | normalized evidence status | lifecycle (active / legacy / proposal / retired) | evidence reference | checked-at | next verification`

This preserves the requested eight-value taxonomy while allowing “proposal” or “merged” to remain a lifecycle fact rather than an undefined evidence label.

---

## 2. Production settings lock

### 2.1 Current values

| Required setting/fact | Current production value | Expected operator-plan value, if known | Drift / status | Required operator decision |
|---|---|---|---|---|
| Configured initial capital | **₹500,000** from `phase20_settings.data.initial_capital` and `GET /api/phase20/settings` | ₹100,000 in earlier migration plan/report | **PRODUCTION-OBSERVED; PARTIAL / CONFLICTING** | Choose ₹100,000, ₹500,000, or a new explicit value. Do not infer from historical report. |
| Current cash | Direct canonical cash field was **not returned** by `GET /api/phase20/positions` | Not known | **UNKNOWN** direct value | Expose/read canonical portfolio projection before operational use. A non-authoritative ledger-derived estimate is ₹461,180.42: ₹500,000 − ₹38,494.65 open notional − ₹46.19 open charges − ₹278.74 closed realized P&L. This assumes realized P&L is already net; it must not replace canonical portfolio calculation. |
| Auto paper entries | `true` | Older material describes default off/confirmation-required | **PRODUCTION-OBSERVED; PARTIAL / CONFLICTING** | Keep enabled only after EOD/cutoff proof, or explicitly pause through approved settings action. |
| Bootstrap paper mode | `true` | Previously a bounded bootstrap feature, not a confirmed production policy | **PRODUCTION-OBSERVED; PARTIAL / CONFLICTING** | Keep, pause, or retire while normal paper-entry evidence is repaired. |
| Bootstrap/auto-entry confirmation | `2026-08-20T03:30:25Z` | No alternative current operator value known | **PRODUCTION-OBSERVED** | Confirm the person/policy that authorizes this persisted confirmation. |
| Active universe mode | `NIFTY_50` | Low-price IT/Infrastructure/Bank custom universe was previously requested | **PRODUCTION-OBSERVED; PARTIAL / CONFLICTING** | Select and document one active policy. |
| Active symbol count | 50 cache/universe symbols in prior current production readiness response | No conflicting target known | **PRODUCTION-OBSERVED** | Confirm whether 50 is expected with current NIFTY policy. |
| LTIM status | `nifty50_company_master`: `symbol=LTIM`, `is_active=true`, `index_membership=NIFTY_50`, last verified 18 August | Earlier plan said remove LTIM from active universe while preserving history | **PRODUCTION-OBSERVED; PARTIAL / CONFLICTING** | Resolve whether LTIM should be active. Current production data says it is active. |
| Low-price custom universe availability | Production `custom_universe_master` returned zero rows in this audit | Earlier plan says a low-price universe was added | **PRODUCTION-OBSERVED; PARTIAL / CONFLICTING** | Decide whether its data was never published, removed, or intentionally inactive. |
| Maximum daily trades | `3` | No conflicting target known | **PRODUCTION-OBSERVED** | Confirm policy after capital/automation decision. |
| Maximum concurrent positions | `5` | No conflicting target known | **PRODUCTION-OBSERVED** | Confirm policy; two positions are currently open. |
| No-new-entry cutoff | Code policy: **15:15 IST** | 15:15 IST | **CODE-PROVEN, but runtime control is PARTIAL / CONFLICTING** | Investigate observed 15:25/15:26 entries before relying on the gate. |
| Market-close exit time | `15:20 IST` from `GET /api/phase20/eod-status` | 15:20 IST | **PRODUCTION-OBSERVED** | Obtain prior-session EOD outcome proof. |
| Post-close force-exit state | `square_off_before_close=false`; current-day endpoint reports no force-close results/blocked events at 02:45 IST on 21 August | Existing design requires force path after 15:30 IST | **PARTIAL / CONFLICTING** | Confirm intended setting and obtain 20 August execution/retry trace. Current-day response cannot prove prior-day handling. |
| Automatic paper exits | `true` | No conflicting target known | **PRODUCTION-OBSERVED** | The setting does not prove exits actually ran; resolve open positions. |
| Auto scan / interval | `true` / 5 minutes | Existing operating plan | **PRODUCTION-OBSERVED** | Keep distinct from data-candle interval and EOD task proof. |

### 2.2 Current production configuration hash and safeguards

- Current settings response includes `config_hash: 7d842d4e59648fe7`.
- It contains the exact confirmation text: “I understand this will automatically create simulated paper trades only. No real orders will be placed.”
- Current bootstrap status reports `kite_verified:true`, `kite_session_verified:true`, `kite_overlay_enabled:true`, and 11 bootstrap-eligible candidates.
- These are **PRODUCTION-OBSERVED settings/status values**, not approval for new architecture or live execution.

---

## 3. Open-position and EOD trace investigation

### 3.1 Current open positions

`GET /api/phase20/positions` and production SQL both returned the following current open ledger rows:

| Trade ID | Symbol | Quantity | Entry/fill time | Entry/fill price | Trigger source | Status | Portfolio impact |
|---|---:|---:|---|---:|---|---|---|
| `P20-315e824378` | TRENT | 5 | `2026-08-20T09:56:22Z` = **15:26:22 IST** | ₹2,971.45 | `BOOTSTRAP_AUTO` | `OPEN` | Open notional ₹14,857.25; entry charges ₹17.83 |
| `P20-8fc829b8c3` | DRREDDY | 20 | `2026-08-20T09:55:10Z` = **15:25:10 IST** | ₹1,181.87 | `AUTO` | `OPEN` | Open notional ₹23,637.40; entry charges ₹28.36 |

### 3.2 Critical cutoff discrepancy

The intended no-new-entry rule is **15:15 IST**, proved in source and tests. Both observed open entries occurred after that boundary:

- DRREDDY: 10 minutes and 10 seconds after cutoff.
- TRENT: 11 minutes and 22 seconds after cutoff.

This is **PRODUCTION-OBSERVED behavior conflicting with a CODE-PROVEN safety rule**. Possible explanations include a time-zone/clock path defect, a bootstrap-specific bypass, an outdated deployed code path, or an incorrect documented cutoff. The audit does not guess which. It is a blocking investigation item.

### 3.3 TRENT trace

| Required trace item | Evidence | Status |
|---|---|---|
| Trade, symbol, quantity, time, price, trigger | See row above; production ledger query and `/phase20/positions` | **PRODUCTION-OBSERVED** |
| Signal/snapshot time | `2026-08-20T09:19:55Z` | **PRODUCTION-OBSERVED** |
| Decision/simulated-order time | `2026-08-20T09:56:22Z` | **PRODUCTION-OBSERVED** |
| Why it was admitted | `BOOTSTRAP_PAPER_TRADE_APPROVED`: bootstrap low-evidence path; Kite LTP, hard gates; normal buy path had been blocked by low evidence | **PRODUCTION-OBSERVED** |
| Pipeline entry/portfolio evidence | `ORDER_SUBMITTED`, `PRECHECK_APPROVED`, `ORDER_EXECUTED`, `POSITION_OPENED` present in `pipeline_events` | **PRODUCTION-OBSERVED** |
| `MARKET_CLOSE_EXIT` attempted | No matching observed pipeline event or trade exit field | **NOT PROVEN** |
| `POST_CLOSE_FORCE_EXIT` attempted | No matching observed pipeline event or trade exit field | **NOT PROVEN** |
| `EXIT_PENDING` | Row remains `OPEN`; no observed `EXIT_PENDING` transition | **NOT PROVEN** |
| `MARKET_CLOSE_EXIT_BLOCKED` | No matching observed pipeline event or current eod-status blocked event | **NOT PROVEN** |
| Scheduler around 15:20/15:30 IST | Scheduler’s latest successful scan is 15:21:18 IST. It subsequently reported market closed/system heartbeat jobs. No direct exit-attempt record was found in reviewed scheduler/pipeline evidence. | **PARTIAL / CONFLICTING** |
| EOD reconciliation | Notification at 16:03:33 IST says clean paper reconciliation, 4 paper orders checked, 0 discrepancies. It does not prove Phase 20 positions were closed. | **PRODUCTION-OBSERVED, insufficient for closure proof** |
| Replay trace | Canonical replay endpoint exists, but it was not called because this audit avoids additional potentially costly/evaluative controls; direct ledger/event evidence is shown above. | **UNKNOWN** |

### 3.4 DRREDDY trace

| Required trace item | Evidence | Status |
|---|---|---|
| Trade, symbol, quantity, time, price, trigger | See row above; production ledger query and `/phase20/positions` | **PRODUCTION-OBSERVED** |
| Signal/snapshot time | `2026-08-20T09:19:55Z` | **PRODUCTION-OBSERVED** |
| Decision/simulated-order time | `2026-08-20T09:55:10Z` | **PRODUCTION-OBSERVED** |
| Why it was admitted | `AUTO` entry. A nearby notification documents sizing reduction from 98 to 21 under per-stock cap; ledger result is quantity 20. | **PRODUCTION-OBSERVED** |
| `MARKET_CLOSE_EXIT` / force exit / pending/block | No observed matching pipeline exit event, exit field, pending row, or EOD blocked event | **NOT PROVEN** |
| Scheduler/EOD trace | Same evidence limitation as TRENT | **PARTIAL / CONFLICTING** |
| Replay trace | Not independently fetched in this no-mutation audit | **UNKNOWN** |

### 3.5 What is known—and not known—about why positions remain open

**Known:** Both rows are current `OPEN` rows with null exit fields; the scheduler later classified the market as closed; current-day EOD status reports no result; no close/pending/block event was found in the inspected event window; and a reconciliation notice does not establish closure.

**Unknown:** Whether an EOD/force-exit job was never invoked, failed before evidence emission, ran in another process without durable evidence, intentionally skipped due to a gate, or had another cause.

**Do not silently close either position.** If urgent cleanup is needed, the exact operator action is the existing paper-only `POST /api/phase20/force-eod-close`, but it was intentionally **not called** by this audit. Use it only after the operator approves a remediation decision and captures a before/after evidence record.

---

## 4. Canonical authority lock

### 4.1 Current authority statements

| Domain | Current authority | Lock statement | Audit qualification |
|---|---|---|---|
| Paper trade ledger | `phase20_paper_trades`, written by `phase20_executor.py` | **Phase 20 is the intended canonical paper ledger and remains the operational source of truth.** | It is **not fully audit-hardened** until EOD outcome proof and closed-row immutability are verified. |
| Portfolio projection | `canonical_portfolio.py` derived from Phase 20 ledger | Intended canonical projection for current positions/cash/equity/P&L | Direct production cash projection was not returned by the checked positions route. |
| Scan state | `scan_state` via `scan_state_store.py` | Canonical latest scan snapshot/lock state | Current scan freshness is separate from background-agent proof. |
| Pipeline evidence | `pipeline_events` via `pipeline_events.py` | Canonical append-oriented pipeline event stream | Production dedupe-index parity and full EOD event coverage need verification. |
| Phase 20 settings | `phase20_settings` via `phase20_store.py` | Canonical persisted current setting document | JSON fallback must not become production authority. |
| EOD status | `phase20_eod_status.py` projection from ledger/scheduler/claims/events | Canonical **operational EOD status projection** | It is not a durable substitute for a complete per-trade EOD audit trail. |

### 4.2 Competing and legacy stores

| Store | Owner/current use | Current UI use | Conflict with Phase 20 | Lock decision |
|---|---|---|---|---|
| `paper_trades` | `portfolio_store.py` legacy buy/sell store; write SQL at `portfolio_store.py:452`; archival/mutation helpers also exist | Phase 11 and generated portfolio paths read it; Phase 11 autonomous explicitly reads it | High: represents trade history separate from Phase 20 | **OBSOLETE / LEGACY — quarantine.** It may be shown only with an explicit legacy label; do not use for Phase 20 positions/cash/equity. |
| `paper_portfolio` | Legacy JSON cash/positions/history store in `portfolio_store.py` | Legacy portfolio-manager/Phase 11-family consumers | High: mutable portfolio state can disagree with ledger-derived projection | **OBSOLETE / LEGACY — quarantine.** No Phase 20 risk/position view may fall back to it. |
| `experimental_paper_trades` | `paper_exploration_engine.py`; scheduler uses it only in exploration mode | Experimental/analytics consumers; exact page list incomplete | Medium: independent open/close lifecycle | **OBSOLETE / LEGACY — quarantine from portfolio authority.** Preserve only for clearly labeled experiments. |
| `portfolio_events` | Separate `PortfolioEventRepository`/`PortfolioService` event model | `/portfolio/snapshot` and Portfolio Live consumers | High: a parallel event-sourced portfolio model may diverge from Phase 20 | **PARTIAL / CONFLICTING — bridge or quarantine.** Do not call it canonical until explicit Phase 20 bridge/reconciliation exists. |
| `portfolio_snapshots` | Separate `PortfolioSnapshotRepository`/`PortfolioService` checksummed projection | Portfolio Live consumers | High: snapshot can disagree with Phase 20 ledger | **PARTIAL / CONFLICTING — bridge or quarantine.** |
| `phase11_price_snapshots` | Phase 11 price observations | Phase 11/legacy reporting; exact current UI route unknown | Medium: may be mistaken for Phase 20 price/excursion tracking | **OBSOLETE / LEGACY — read-only compatibility only.** |
| `phase11_capital_topups` | Present in production but absent from audited development schema list | UI owner not proven | High if it changes displayed capital independently | **UNKNOWN — quarantine pending owner/writer/UI trace.** |

### 4.3 Authority rules to approve before Phase 1

1. Only `phase20_executor.py` may create the final Phase 20 paper-entry ledger row.
2. Only the Phase 20 exit path may transition that row through `OPEN → EXIT_PENDING → CLOSED`.
3. `canonical_portfolio.py` is the only source for current paper portfolio quantities/cash/equity after it is independently verified against production.
4. Phase 11, legacy portfolio, experiments, and the separate bot cannot write, calculate, or override Phase 20 authority.
5. Any bridge into a legacy view must be one-way and labeled as a projection, never a fallback authority.

---

## 5. Writer trace

| Target | Exact writer(s) | What is written | Active / production reachability | Canonical-state mutation | Safety recommendation |
|---|---|---|---|---|---|
| `phase20_paper_trades` | `phase20_executor._insert_row()`; reached by `record_entry()` and Phase 20 scheduler/scan paths | New simulated paper trade and entry evidence | Auto entry is **PRODUCTION-OBSERVED** active; settings confirmation and admission code exist | Yes; intended final paper-entry writer | Keep single writer; retain partial unique open-symbol index; add immutable audit event for every entry. |
| `phase20_paper_trades` | `phase20_executor._update_row()`; `record_exit()`; `phase20_exits.manage_open_positions()` and pending recovery; scheduler and exit-tick path can invoke | `OPEN → EXIT_PENDING → CLOSED`, exit values/P&L | Code-reachable; current runtime exit attempt not proven | Yes | Add DB transition allowlist and history/audit row; prohibit edits after `CLOSED`. |
| `phase20_paper_trades` | `phase20_executor._delete_row()`; entry rollback/cleanup caller near executor line 1310 | Deletes by `trade_id` | No public direct delete route found, but private execution path is reachable | Yes | Remove production delete or replace with correction/tombstone event; DB trigger should deny direct deletion. |
| `paper_trades` | `portfolio_store.py` insertion SQL near line 452; archive update near 276; metadata update near 58 | Legacy buy/sell rows, metadata, archive status | Runtime activation **UNKNOWN** | No intended Phase 20 mutation, but competing record truth | Quarantine. Test/disable all production writers unless expressly retained for legacy reporting. |
| `experimental_paper_trades` | `paper_exploration_engine.record_exploration_entry()`; `manage_exploration_exits()` update path | Experimental entry and close/MFE/MAE data | Settings default `paper_exploration_mode=false`; production activation **UNKNOWN** | No intended canonical mutation | Quarantine from canonical portfolio; add immutable history if experimentation remains. |
| `portfolio_events` | `PortfolioEventRepository._db_save_many()` via `PortfolioService._persist_event()` | Append-oriented event records, idempotency keys | Runtime linkage to Phase 20 **UNKNOWN**; failures can fall back to memory | Parallel portfolio state | Do not allow it to become a second trading ledger. Alert on DB fail-open fallback; retain audit metadata for pruning. |
| `portfolio_snapshots` | `PortfolioSnapshotRepository._db_save()` via `PortfolioService` | Checksummed portfolio snapshots | Runtime linkage to Phase 20 **UNKNOWN** | Parallel projection | Quarantine or bridge explicitly; never use as silent fallback for Phase 20. |
| `phase20_settings` | `phase20_store._persist_settings()` / `update_settings()`; `trading.ts` setting mutation; daily session manager and capital migration callers | Persisted configuration JSON | Settings route is production-reachable; current values observed | Yes; governing configuration | Add actor/time/old-value/new-value audit; production must not rely on writable local JSON fallback. |

**Test-only writers:** Several test modules issue cleanup deletes against non-canonical legacy tables. They do not prove production reachability, but tests must continue using isolated data so they cannot pollute real paper evidence.

---

## 6. Closed-trade immutability verification

| Required question | Finding | Status |
|---|---|---|
| Can code update a `CLOSED` Phase 20 trade? | `_update_row()` builds generic dynamic `UPDATE phase20_paper_trades SET … WHERE trade_id = …` without a status guard or field allowlist. `record_exit()` uses this for normal closure. | **NOT PROVEN** immutable |
| Can code delete a `CLOSED` Phase 20 trade? | `_delete_row()` is unconditional by `trade_id`. It is private, but reachable from executor cleanup flow. | **NOT PROVEN** immutable |
| Are generic helpers reachable from routes/jobs? | Update path is reached from exit management, scheduler and `POST /api/phase20/exits/tick`. Delete has no direct public route found but is inside execution flow. | **CODE-PROVEN** |
| Is there a database trigger/constraint protecting `CLOSED` rows? | Production `information_schema.triggers` returned no triggers for `phase20_paper_trades`; repository search found no trigger/migration definition. | **PRODUCTION-OBSERVED / NOT PROVEN** |
| Is there a mutation audit trail? | Pipeline events/notifications may accompany surrounding work, but no DB-enforced per-row Phase 20 change history was found. | **NOT PROVEN** |

### Exact policy to approve before implementation

1. **Immutable entry fields:** after insert, `trade_id`, scan/signal/decision/fill provenance, symbol, side, quantity, entry price, entry costs, strategy, model/rule/config versions, trigger source, and entry evidence cannot change.
2. **Allowed operational transitions only:** `OPEN → EXIT_PENDING → CLOSED`; any other status transition is denied unless a pre-approved break-glass correction process exists.
3. **Closed-row prohibition:** direct `UPDATE` and `DELETE` of a `CLOSED` row are rejected at storage level.
4. **Correction model:** data correction is an append-only `TRADE_CORRECTION` audit event referencing the original trade; it never erases the original evidence.
5. **Audit fields/events:** every attempted insert/update/delete/transition records actor, route/job/agent, request/correlation ID, scan ID, before/after values, reason, timestamp, and success/failure.
6. **Migration exceptions:** only a separately approved maintenance role, with a documented migration ID and audit event, can bypass a storage trigger. Normal API/scheduler roles cannot.

No trigger, migration, or policy was implemented in this audit.

---

## 7. Live-order quarantine verification

### 7.1 Found order-capable code

| Location | Capability | ApexQuant production authority reachability | Quarantine status |
|---|---|---|---|
| `artifacts/api-server/src/python/broker_client.py`, `ZerodhaBrokerClient.place_order_live()` | Calls `_kite.place_order` | No current API-server Phase 20 route/scheduler/agent caller was found in source trace; full import/call-graph proof remains incomplete | **PARTIAL / CONFLICTING.** Treat as unsafe until a forbidden-import/call test proves the production entrypoint cannot reach it. |
| `artifacts/api-server/src/python/broker_client.py`, `MockBrokerClient` | Simulated broker behavior | Phase 20 paper path is designed to use paper/mock behavior | **CODE-PROVEN** paper-only intent |
| `intraday-trading-bot/src/api/routers/orders.py`, `POST /trading/place_order` | Calls `ExecutionService.execute_order()`; route can select live gateway under five gates | Separate legacy service; would be reachable if independently deployed/configured | **OBSOLETE / LEGACY; high-risk quarantine required** |
| `intraday-trading-bot/src/api/routers/orders.py`, `POST /trading/cancel_order` | Calls `ExecutionService.cancel_order()` | Separate legacy service | **OBSOLETE / LEGACY; high-risk quarantine required** |
| `intraday-trading-bot` broker/gateway/audit layers | `modify_order`, broker-order abstractions and order audit references | Exact service-call reachability not fully traced | **OBSOLETE / LEGACY / UNKNOWN** |

### 7.2 Quarantine conclusion

- The **current ApexQuant Phase 20 path is code-proven paper-only by design** and this audit made no broker call.
- It is **not valid** to claim that the repository contains no live broker-order API capability.
- Legacy `intraday-trading-bot` order routes must have no imports, shared scheduler, shared authority database path, or deployment configuration connection to the ApexQuant API artifact.
- Before any later architecture work, add a production-boundary test that fails if a Phase 20/scheduler/agent module imports or calls `ZerodhaBrokerClient.place_order_live`, `kite.place_order`, `modify_order`, or `cancel_order`.

---

## 8. Agent runtime proof

### 8.1 Positive and negative production evidence

`GET /api/pipeline/summary` returned recent pipeline stage projections for `SUPERVISOR`, `SCANNER`, `RESEARCH`, `MARKET_INTELLIGENCE`, `MONITORING`, `STRATEGY`, `RISK`, `AI_DECISION`, and `EXECUTION`. This proves **pipeline events were persisted**.

It does **not** prove the corresponding framework classes were registered/running as independent long-lived agents.

The attempted production registry call `GET /api/agent-framework/agents` timed out. Direct non-canonical paths `/api/agent-framework/supervisor` and `/api/agent-framework/health` returned “Cannot GET.” Therefore no successful production evidence was obtained for registry contents, topic freshness, SnapshotBus topics, or heartbeat fields.

| Component | Source/protocol evidence | Positive production runtime proof | Current status | Exact next proof |
|---|---|---|---|---|
| Market Data Agent | `market-data-agent` / `market_data` topic; snapshot/status routes exist | Pipeline `SCANNER` is not equivalent proof | **IMPLEMENTED, RUNTIME UNKNOWN** | Successful `/agent-framework/agents` and market-data status/snapshot response with heartbeat/freshness |
| Research Agent | `research-agent` / `research` topic | `RESEARCH` pipeline events exist | **PARTIAL / CONFLICTING** | Registry and topic envelope proof |
| Market Intelligence Agent | `market-intelligence-agent` / `market_intelligence` topic | `MARKET_INTELLIGENCE` pipeline events exist | **PARTIAL / CONFLICTING** | Registry/topic proof |
| Stock Monitoring Agent | monitoring class/topic | `MONITORING` stage events exist | **PARTIAL / CONFLICTING** | Registry/topic proof |
| Strategy Agent | `strategy-agent` / `strategy` topic | `STRATEGY` stage events exist | **PARTIAL / CONFLICTING** | Registry/topic proof |
| Risk Agent | `risk-agent` / `risk` topic | `RISK` stage events exist | **PARTIAL / CONFLICTING** | Registry/topic proof |
| AI Decision Agent | `ai-decision-agent`; decision-layer routes | `AI_DECISION` stage events exist | **PARTIAL / CONFLICTING** | Decision status + registry/topic proof |
| Execution Agent | `execution-agent`; execution-layer routes | `EXECUTION` stage events exist | **PARTIAL / CONFLICTING** | Execution status + registry/topic proof; also prove no ledger writer role |
| Learning Agent | `learning_agent`; learning-layer routes | No successful runtime response obtained | **IMPLEMENTED, RUNTIME UNKNOWN** | Learning status/snapshot and registry proof |
| Knowledge Agent | `knowledge_agent`; knowledge-layer routes | No successful runtime response obtained | **IMPLEMENTED, RUNTIME UNKNOWN** | Knowledge status/snapshot and registry proof |
| Supervisor | `SupervisorAgent`; supervisor snapshot/alert routes | Pipeline has `SUPERVISOR` events but direct tested path was wrong and 404 | **PARTIAL / CONFLICTING** | `/api/agent-framework/supervisor/snapshot` response including topic freshness |

### 8.2 What a valid runtime proof must contain

The production response must show:

- registry `available:true` and concrete agent records;
- agent state, `last_heartbeat`, interval, health score, registered/started timestamps;
- `SnapshotBus` topic envelopes (`topic`, publisher, published time, sequence);
- supervisor topic facts: `available`, `age_seconds`, `stale`, `never_published`, and error;
- source process/instance identity because AgentRegistry and SnapshotBus are in-process singletons.

### 8.3 Pipeline-stage naming footnote

`SCANNER`, `MONITORING`, and `STRATEGY` in `/pipeline/summary` are **event-stage projections**, not a one-to-one registry taxonomy:

- `SCANNER` maps to canonical scan execution (`live_scan_engine.py` / `market_scanner.py`), not a framework class named “Scanner Agent.”
- `MONITORING` maps most closely to the stock-monitoring analysis surface/topic, but stage evidence alone does not prove the class is registered.
- `STRATEGY` maps most closely to the Strategy Agent/strategy implementations, but again does not prove a separately scheduled agent process.

Pipeline events establish evidence flow; they must not be used to infer independent agent lifecycle, execution authority, or heartbeat health.

---

## 9. Critical UI source audit

| Surface | Traced routes/data | Canonical vs legacy assessment | Cache/stale behavior | Quantity/EOD/pending/open warning assessment | Status |
|---|---|---|---|---|---|
| Mission Control | `/health/live`, `/pipeline/summary`, `/pipeline/events`, `/ohlcv-cache/status`, scan history/status, `/phase20/bootstrap-status`, `/phase20/eod-status`, `/portfolio/snapshot`, custom-universe and replay routes; shared `/phase20/ledger` | Mixed Phase 20, pipeline, portfolio, live-data, replay, and legacy-family projections | Explicit 60s cache status, 30s scan history, 30s bootstrap/EOD; monotonic scan display suppresses regressions and emits stale warning | Explicit EOD banners/status, `EXIT_PENDING` count, overnight-carry/open warning; exact quantity field per widget not fully traced | **PARTIAL / CONFLICTING** |
| AI Paper Trader | Phase 20 settings, capital migration status, cadence, bootstrap, pipeline, exit-pending alert and additional Phase 20 queries | Primarily Phase 20; later coexisting endpoint sources not fully traced | Multiple 5s–120s React Query poll/stale combinations | Open uses `p.quantity`; closed uses null-safe canonical quantity helper; explicit `EXIT_PENDING` panel; dedicated EOD outcome banner not confirmed | **PARTIAL / CONFLICTING** |
| Portfolio Live | `/phase11/snapshot`, `/portfolio/snapshot`, health/config and position-stop controls | Legacy Phase 11 snapshot and parallel portfolio service; Phase 20 source is not explicit | 60s legacy snapshot; other periodic refetch plus manual timers | Uses `pos.quantity` from portfolio snapshot; open exposure warnings visible; EOD/`EXIT_PENDING` not traced | **PARTIAL / CONFLICTING** |
| Portfolio Manager | Generated manager API plus embedded `Phase20OpenPositions` | Mixed legacy/generated manager data; embedded Phase 20 lifecycle is canonical-position surface | Generated-hook cache defaults unknown; manual refresh retains last good data | Main manager uses holdings quantity; embedded Phase 20 component shows `OPEN`/`EXIT_PENDING` lifecycle | **PARTIAL / CONFLICTING** |
| Portfolio Risk Analytics | `/risk/analytics`, position-stop mutation | Header identifies Phase 11b/legacy analytics, not visible Phase 20 source | Mount-only load, no visible periodic refetch | `recommended_quantity`; sector warnings; no traced EOD/pending warning | **OBSOLETE / LEGACY** for current Phase 20 risk authority |
| Live Data Health | `/live-data/health`, `/live-data/scan`, `/live-data/health-v2`; reconnect/scan control routes exist | Live-data/scan view; not Phase 20 | Single initial load; live-stream behavior not fully traced | Data-quality warnings exist; no quantity/EOD/pending/current-position source | **IMPLEMENTED, RUNTIME UNKNOWN** |
| System Readiness | Phase 27F report/history query/mutation | Readiness projection, not direct Phase 20 | Both queries poll 60s; exact endpoint/cache settings partly unknown | READY/WARNING/BLOCKED/UNKNOWN counts; no traced EOD/pending/open warning | **IMPLEMENTED, RUNTIME UNKNOWN** |
| Agent Operations | Agent Framework, Ops Centre, analysis routes | Agent/ops projections; no Phase 20 source | Detail 5s, agents 45s, diagnostics 60s, ops 30s with explicit stale times | No quantity or EOD/pending/open warning traced | **IMPLEMENTED, RUNTIME UNKNOWN** |
| Mobile Positions | `/phase20/positions`; generated trades query; offline snapshots | Phase 20 positions plus generated/legacy trade fallback/display | 60s poll; live → cached fallback, stale banner | Shows `item.qty ?? item.quantity`; explicit EOD/pending/overnight banner not traced | **PARTIAL / CONFLICTING** |
| Mobile AI Ops | `/ops-centre/snapshot`; offline snapshot | Ops aggregate, not Phase 20 directly | 30s page refresh; 60s request timeout; stale banner after >2 minutes | Warnings/status badges; no Phase 20 quantity/EOD/pending proof | **IMPLEMENTED, RUNTIME UNKNOWN** |

### UI lock

For current paper-trading truth, only components backed by `Phase20Lifecycle` (`GET /phase20/positions`, `/phase20/ledger`, evaluation/replay) should be presented as canonical Phase 20 lifecycle sources. Other portfolio/risk/Phase 11 views must be labeled legacy, projection, or non-canonical until a one-way bridge is verified.

---

## 10. Phase-numbering gap review

| Missing item in prior inventory | Result | Evidence | Normalized status | Required follow-up |
|---|---|---|---|---|
| Phase 23.1 | Exists/merged: canonical pipeline event store and Live Command Center | `reports/phase23/PHASE23_SUMMARY.md` | **CODE-PROVEN** | Production route proof if operational status is needed |
| Phase 23.2 | Exists/merged: historical backtest engine | `PHASE23_PARTS2_3_VERIFICATION.md` | **CODE-PROVEN** | Runtime proof if needed |
| Phase 23.3 | Exists/merged: Investigation Center | Same Parts 2/3 report; `/investigation-center` | **CODE-PROVEN** | Browser/runtime route proof |
| Phase 23.4 | Exists/merged: advanced replay | `PHASE23_PARTS4_5_VERIFICATION.md` | **CODE-PROVEN** | Production replay proof |
| Phase 23.5 | Exists/merged: AI Decision Explorer/trade story/search/replay verification | Same Parts 4/5 report | **CODE-PROVEN** | Production proof |
| Phase 23.6 | Exists/merged: Strategy Lab/optimisation | `strategy_lab.py`, Parts 6/7 reports | **CODE-PROVEN** | Production route proof |
| Phase 23.7 | Exists/merged: institutional analytics/performance | Parts 6/7 reports | **IMPLEMENTED, RUNTIME UNKNOWN** | Production route/UI proof |
| Phase 26B | Exists/merged: live monitor, cross-page validator, issue store | `PHASE26_SUMMARY.md` | **IMPLEMENTED, RUNTIME UNKNOWN** | Scheduler/liveness proof |
| Phase 27A | Exists/merged: backtest requirements/read-only verification | `PHASE27_VERIFICATION.md` | **IMPLEMENTED, RUNTIME UNKNOWN** | Production route/UI proof |
| Phase 27B | Exists/merged: Live Command Center | `PHASE27_VERIFICATION.md` | **IMPLEMENTED, RUNTIME UNKNOWN** | Production route/UI proof |

The full-system inventory must not continue to imply that 23.1–23.7, 26B, 27A, or 27B were skipped. They were collapsed/omitted from its main phase table; this report restores their status.

---

## 11. Normalized inventory map

This is the compact normalization map for the full-system inventory. It preserves the original grouping while ensuring every current family is assigned a valid evidence status.

| Inventory family | Raw label(s) used previously | Normalized label | Reason / evidence source | Next verification |
|---|---|---|---|---|
| Phases 0–3 | `CODE-PROVEN documentation`, `IMPLEMENTED, RUNTIME UNKNOWN` | **CODE-PROVEN** / **IMPLEMENTED, RUNTIME UNKNOWN** | Docs and historical code exist; current runtime generally not shown | Route/test/deployment evidence by phase |
| Phase 4/4A | `IMPLEMENTED, PARTIAL` | **PARTIAL / CONFLICTING** | Code/docs exist; current Phase 20 authority overlaps legacy session path | Prove projection-only use |
| Phases 5A–6.5 | `IMPLEMENTED, PARTIAL` | **PARTIAL / CONFLICTING** | Analytics/readiness modules exist; authoritative source/runtime varies | Per-page source and runtime proof |
| Phase 7 / cache migration | mixed code+production labels | **PRODUCTION-OBSERVED** | Scan/cache routes and production DB/status observed | Intraday-bar limitation remains separate |
| Phases 7.2–9.7 | `IMPLEMENTED, PARTIAL` | **PARTIAL / CONFLICTING** | Implemented centre/page families, not all runtime/feed sources proven | Per-centre route and cache proof |
| RC/Batches 9–10 | `LEGACY / FROZEN`, `LEGACY / REVIEWED` | **OBSOLETE / LEGACY** | Separate bot review stack | Quarantine/import/deployment proof |
| Phase 10A | `CODE-PROVEN` | **CODE-PROVEN** | Framework classes, bus and tests exist | Registry/topic production proof |
| Phases 10B–10E | `IMPLEMENTED, PARTIAL` | **PARTIAL / CONFLICTING** | Advisory agent code exists; lifecycle/runtime not proven | Agent proof matrix in Section 8 |
| Phase 11 | `IMPLEMENTED, PARTIAL` | **PARTIAL / CONFLICTING** | Legacy and Phase 20 reads coexist | Quarantine and UI source lock |
| Phases 12–19 | `IMPLEMENTED, PARTIAL` | **PARTIAL / CONFLICTING** | Routes/docs exist, operational proof varies | Targeted current route checks |
| Phase 20 | `CODE-PROVEN / PARTIALLY PRODUCTION-OBSERVED` | **PARTIAL / CONFLICTING** | Operational source of truth, but cutoff/EOD and immutability safety conflict | Resolve blocking findings |
| Phases 21–22 | `IMPLEMENTED, PARTIAL` | **PARTIAL / CONFLICTING** | Evidence/analytics implemented; current consumption varies | Route/UI source proof |
| Phases 23.1–23.7 | Grouped/partially omitted | See Section 10 | Code/reports establish existence | Runtime as needed |
| Phases 23.8–24 | `IMPLEMENTED, PARTIAL` | **PARTIAL / CONFLICTING** | Validation/learning built; no new live intraday table proof | Schema/runtime proof |
| Mission Control / Phase 25 | `IMPLEMENTED, PARTIAL` | **PARTIAL / CONFLICTING** | Production pipeline response exists, overlapping view sources remain | UI source lock |
| Phases 26A–D | `IMPLEMENTED, PARTIAL` | **PARTIAL / CONFLICTING** | Code/docs/test evidence; scheduler runtime unknown | Include 26B and liveness proof |
| Phases 27A–F | `IMPLEMENTED, TEST-PROVEN` | **IMPLEMENTED, RUNTIME UNKNOWN** | Tests/reports prove artifacts, not current production UI | Route/browser proof |
| Legacy stores / legacy bot | `LEGACY`, `not production authority` | **OBSOLETE / LEGACY** | Competing tables and order-capable separate service | Quarantine lock |
| Proposed intraday candles/tracking | `PROPOSAL ONLY` | **CODE-PROVEN** lifecycle: proposal only | No production/dev table exists | Operator approval and later migration design |
| Core Phase 20 safety claims | mixes `CODE/TEST-PROVEN`, `DB-PROVEN`, `NOT PROVEN` | **CODE-PROVEN**, **PRODUCTION-OBSERVED**, or **NOT PROVEN** per Section 6 | Prevents status hybrids | Storage-level hardening and runtime evidence |

---

## 12. Master-brief coverage check

The prior full-system inventory covered the original master brief **at a high level**: phase/bot inventory, flow, UI, database/store groups, route groups, safety matrix, gaps, revised architecture, implementation plan, operator questions, and no-code/no-live-order confirmation.

It did **not fully satisfy** the master brief’s requested level of detail:

1. It grouped many phases rather than enumerating every task/change/file.
2. It did not provide a per-phase changed-files/DB-routes-UI-tests/Git map.
3. It omitted/collapsed Phase 23.1–23.7, 26B, 27A, and 27B in the main phase table.
4. Its route inventory was family-level rather than every route/response/cache/consumer.
5. Its UI inventory was a route manifest plus selected pages, not every page/component hook/fallback/cache trace.
6. Its database inventory grouped tables instead of mapping every table’s migration, retention, mutation, and writer/reader status.
7. It correctly marked some safety conditions as not proven, so it cannot serve as final safety certification.

This Phase 0 report resolves the highest-risk authority/control gaps but does not claim to replace a future exhaustive changed-file/Git provenance manifest.

---

## 13. Operator decision table

| # | Decision required | Current production fact | Choices requiring explicit approval |
|---:|---|---|---|
| 1 | Paper capital | ₹500,000; historical target ₹100,000 | Keep ₹500,000; restore ₹100,000; choose another amount |
| 2 | Active universe | NIFTY 50 active; LTIM active; custom universe has zero rows | NIFTY 50; restore/publish low-price universe; another policy |
| 3 | Automatic paper entries | Enabled; two post-cutoff open positions observed | Pause pending proof; keep enabled with explicit exception policy; change only after approval |
| 4 | Bootstrap | Enabled and created TRENT after cutoff | Pause; retain with an explicitly tested cutoff/EOD contract; retire |
| 5 | Current TRENT/DRREDDY positions | Both `OPEN` overnight | Investigate only; approved paper force-close; approved remediation after trace |
| 6 | Legacy stores | Legacy paper/portfolio stores and parallel events/snapshots exist | Quarantine; bridge one-way; retire selected surfaces |
| 7 | Intraday candle source | No canonical 1m/5m/15m live store exists | Choose provider/entitlement/retention/correction policy before implementation |
| 8 | Deployment model | Autoscale deployment observed | Keep Autoscale with durable external scheduling; use always-on worker; a different operations model |
| 9 | Profit-lock defaults | No approved new defaults | Define only after durable intraday/trade tracking exists |
| 10 | Future live-order boundary | Legacy bot/API client has live capability; ApexQuant Phase 20 is paper-only by intent | Maintain permanent no-live boundary; any future change requires separate approved architecture/security review |
| 11 | Closed-trade correction policy | No immutability trigger/audit history | Approve append-only correction and storage-level closed-row protection |
| 12 | Agent runtime bar | No positive registry/topics/heartbeat response obtained | Require runtime proof before treating agent architecture as active |

---

## 14. Required evidence to unblock Phase 1

1. Operator decides the intended capital, active universe, auto-entry setting, and bootstrap setting.
2. A read-only reconciliation explains both overnight-open positions and the post-15:15 entry discrepancy.
3. If positions require cleanup, an operator explicitly authorizes the exact paper-only action and captures before/after evidence.
4. The actual deployed cutoff/clock/bootstrap path is traced and made consistent with the stated policy before any new entry logic.
5. Closed-row storage policy is approved; then a later implementation task may add DB-level immutability/audit controls.
6. Legacy store and legacy bot quarantine is documented as an enforceable import/deployment/database boundary.
7. Canonical portfolio cash/equity is exposed or independently verified from `canonical_portfolio.py`.
8. Successful production agent/ops responses establish which agents and topics are actually active.
9. UI pages that show positions/risk/EOD are labeled canonical, legacy, stale, pending, or unknown according to their real source.

---

## 15. Final confirmations

- No application code was changed.
- No database schema, migration, row, configuration, threshold, workflow, secret, or environment variable was changed.
- No position was closed, changed, or otherwise mutated.
- No live order was enabled.
- No broker order API was called.
- The current ApexQuant Phase 20 path remains intended to be paper-only, but repository-wide live-order capability exists in quarantined legacy code and must not be ignored.
- The sole deliverable from this Phase 0 request is `APEXQUANT_PHASE0_HARD_VERIFICATION_AND_AUTHORITY_LOCK_REPORT.md`.