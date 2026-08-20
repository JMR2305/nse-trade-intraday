# ApexQuant Full-System Phase, Agent, UI, and Architecture Inventory

**Status:** Architecture and inventory review only  
**Audit date:** 21 August 2026  
**Master brief:** `attached_assets/Pasted-FULL-SYSTEM-ARCHITECTURE-INVENTORY-REVIEW-EVERY-PHASE-U_1787258411558.txt`  
**Supersedes for inventory purposes:** `APEXQUANT_MULTI_AGENT_INTRADAY_ARCHITECTURE_PROPOSAL.md` is retained as a design proposal, but this report is the current inventory and consistency baseline.

> **Hard scope boundary:** This review made no application-code, schema, migration, threshold, workflow, setting, or environment change. It did not place, enable, modify, or cancel a broker order. All deployed route calls used for this review were read-only `GET` requests.

---

## 1. How to read this report

### 1.1 Evidence statuses

| Status | Meaning |
|---|---|
| **PRODUCTION-OBSERVED** | Verified through the currently deployed public API or production database on 21 August 2026. |
| **DEV-SCHEMA-OBSERVED** | Verified against the current development PostgreSQL schema. |
| **CODE-PROVEN** | Present in the current checked-out source and/or test suite. This does not prove a worker is running in production. |
| **IMPLEMENTED, RUNTIME UNKNOWN** | Code and often tests exist, but deployment configuration, scheduler activation, or live response was not proven. |
| **PARTIAL / CONFLICTING** | Evidence exists but conflicts with current behavior or another source. |
| **OBSOLETE / LEGACY** | Retained code, table, document, or older subsystem that must not become a second authority. |
| **UNKNOWN** | Not verified from current code, DB, deployed route, or deployment metadata. The report states how to verify. |

### 1.2 Review scope and methods

The review covered:

- Current source under `artifacts/api-server`, `artifacts/trading-dashboard`, `artifacts/trading-mobile`, and `intraday-trading-bot`.
- Current route registrations, agent modules, Phase 20 modules, stores, tests, documentation, reports, task documents, and recent Git history.
- Development and production PostgreSQL `information_schema` inventories and critical indexes.
- Deployment metadata and read-only production routes.
- Existing architecture/audit reports, including `docs/MASTER_ARCHITECTURE.md`, `docs/INTRADAY_ARCHITECTURE_REVIEW.md`, `AI_PAPER_TRADER.md`, `APEXQUANT_DATA_PATH_AND_INTRADAY_TRUTH_AUDIT.md`, and `TODAYS_TRADE_EXIT_QUALITY_AUDIT.md`.

This is a code-and-observation inventory, not a production certification. A successful response from a route does not prove the background scheduler, all agents, or every safety transition is operating continuously.

---

## 2. Current production and workspace snapshot

### 2.1 Deployment

| Item | Observation | Status |
|---|---|---|
| Deployment | Public Autoscale deployment exists at `https://nse-trade-intraday.replit.app` | **PRODUCTION-OBSERVED** |
| Current deployment build | Deployment metadata reports a successful build | **PRODUCTION-OBSERVED** |
| API health | `GET /api/healthz` returned HTTP 200 with `{"status":"ok"}` | **PRODUCTION-OBSERVED** |
| API server workflow in development | Workflow was not running at review time | **Workspace state only**; does not imply production is down |
| Dashboard workflow in development | Workflow was not running at review time | **Workspace state only**; does not imply production is down |

### 2.2 Production facts that supersede older assumptions

The following were returned by current deployed read endpoints. They are material architecture findings:

| Observation | Evidence | Impact |
|---|---|---|
| Automatic paper entries are enabled | `/api/phase20/bootstrap-status` returned `auto_paper_entries: true`; `/api/phase20/settings` also returned `auto_paper_entries: true` | The historic/default-off safety expectation is **not the current deployed setting**. Future design must preserve explicit enablement/confirmation and show this state prominently. |
| Bootstrap paper mode is enabled | `/api/phase20/bootstrap-status` returned `bootstrap_paper_enabled: true` and a confirmation timestamp | Bootstrap is active in production configuration, not merely a code path. |
| Current active universe is NIFTY 50 | `/api/ohlcv-cache/readiness` returned `active_universe.mode: UniverseMode.NIFTY_50`, 50 symbols | The low-price IT/Infra/Bank universe exists in code/data but is not the currently active production universe. |
| Deployed capital is ₹500,000 | `/api/ohlcv-cache/readiness` returned `configured_initial_capital: 500000` | The prior ₹100,000 migration report does not describe the current deployed setting. Treat current capital as **configuration drift requiring operator confirmation**, not an implementation defect by assumption. |
| Cache is live and warm | `/api/ohlcv-cache/status` returned 50 symbols, 100% hit rate, `LIVE: 50`, and a successful post-market refresh | Older report evidence of production cache-route 404 is stale. The current deployed cache routes are present and functioning. |
| Market scan is stale overnight but jobs are classified as non-market | `/api/live-data/scan/status` returned prior-day successful scan and zero current market scans; `/history` returned `SYSTEM_HEARTBEAT` / `NON_MARKET` / `entry_eligible:false` / `execution_eligible:false` | Off-market job classification is active in the observed response. Overnight staleness needs a session-aware UI label, not a generic error. |
| An open Phase 20 position was returned after market hours | `/api/phase20/positions` returned at least one prior-session `OPEN` position (`TRENT`) during the observed closed-market period | This is a **high-priority operational finding**. It is not sufficient to declare an EOD failure without inspecting its EOD/exit audit and scheduler trace, but it prevents claiming that EOD closure is fully proven. |
| Phase 20 EOD route exposes planned boundaries | `/api/phase20/eod-status` returned `squareoff_time_ist:"15:20 IST"` and post-close state fields | Response contract is production-observed; execution across a market close has not been observed in this review. |
| Pipeline evidence is live | `/api/pipeline/summary` returned a 362-event live-mode scan pipeline with SCANNER, RESEARCH, MARKET_INTELLIGENCE, MONITORING, STRATEGY and other stages | Pipeline projection is deployed; each underlying framework agent’s runtime activation is still not independently proven. |

### 2.3 Highest-priority consistency findings

1. **Configuration drift:** deployed paper capital is ₹500,000, not the historical ₹100,000 target cited in prior reports.
2. **Enabled automation:** deployed bootstrap and automatic paper entry are on. They remain paper-only, but should not be documented as “disabled by default” without distinguishing defaults from live settings.
3. **EOD outcome needs proof:** an overnight open position was visible. Inspect its exact `trade_id` replay, EOD events, and scheduler trace before changing any logic.
4. **Global broker-order absence is not provable:** the API-server Phase 20 path is paper-only, but the separate legacy `intraday-trading-bot` contains `place_order`, `modify_order`, and `cancel_order` abstractions. It must remain quarantined from ApexQuant’s production authority path.
5. **Closed-trade immutability is not database-enforced:** `phase20_executor.py` contains generic update/delete helpers and current production schema has no observed immutable-closed-row trigger. The intended rule is not yet proven as a storage invariant.
6. **The old cache-production-404 report is obsolete as a current status claim:** current production cache routes respond successfully.

---

## 3. Phase, batch, RC, and feature inventory

The inventory groups older documents where their precise historical task boundary cannot be reconstructed from code alone. “Production” means current runtime proof, not a report that once said “published.”

| Phase / batch / feature | Purpose and current code anchor | Status | DB / routes / UI / tests / reports | Dependencies and unresolved issues | Production status |
|---|---|---|---|---|---|
| Phase 0 | Isolation and architecture baseline; `docs/PHASE_0_ISOLATION_CHECKLIST.md` | **CODE-PROVEN documentation** | No direct DB/route/UI ownership | Older proposed separate-project isolation conflicts with current shared monorepo reality | **UNKNOWN** |
| Phases 1–3 | Early connectivity, validation, pre-market, and foundational paper work | **IMPLEMENTED, RUNTIME UNKNOWN** | `artifacts/api-server/docs/phase1-*`, `phase2*`, `phase3*`; related Python modules/tests | Historical report boundaries do not map one-to-one to current route ownership | **UNKNOWN** |
| Phase 4 / 4A | Controlled paper trading and session validation | **IMPLEMENTED, PARTIAL** | `phase4a_dashboard.py`, `routes/phase4a.ts`, `Phase4A_*` reports, dashboard session page | Must not compete with current Phase 20 ledger/portfolio projections | **UNKNOWN** |
| Phases 5A–5D.5 | Pre-open intelligence, execution quality, portfolio/strategy/AI/executive analytics | **IMPLEMENTED, PARTIAL** | `preopen_*`, `execution_quality/`, `portfolio_performance/`, `strategy_intelligence/`, `ai_performance/`, `executive_dashboard/`; pages and summary docs | Mostly analytics/advisory; source-of-truth mapping varies by page | **UNKNOWN** |
| Phases 6.1–6.5 | Paper validation, strategy/AI/risk optimisation and readiness | **IMPLEMENTED, PARTIAL** | `phase6*` docs, `strategy_optimisation/`, `ai_optimisation/`, `risk_optimisation/`, `live_readiness/` | Advisory outputs must not silently change active Phase 20 thresholds | **UNKNOWN** |
| Phase 7 | Canonical live scan and scan state | **CODE-PROVEN / PRODUCTION-OBSERVED endpoints** | `live_scan_engine.py`, `live_data_provider.py`, `scan_state_store.py`; `trading.ts` scan routes; `/live-data/scan/status`, `/history`, `/run` | Current evidence is daily OHLCV + optional LTP, not durable intraday candles | **Production endpoint active** |
| Phases 7.2–7.5 | Market intelligence, macro, explainability, research lab | **IMPLEMENTED, RUNTIME UNKNOWN** | Routes `market-intelligence.ts`, `macro-intelligence.ts`, `event-intelligence.ts`, `research-lab.ts`; summary docs | Need runtime proof of all component feeds | **UNKNOWN** |
| Phase 8 / 8.x | Observability, risk validation, operations, security, performance, deployment centres | **IMPLEMENTED, PARTIAL** | `observability_center/`, `risk_validation/`, `operations_center/`, `security_center/`, `performance_center/`, `deployment_center/`; route/page families | Several centres aggregate caches and may be stale; legacy readiness code may be superseded by Phase 27F | **UNKNOWN** |
| Phase 9.1–9.7 | Command Center, workspaces, timeline, executive reports, design system | **IMPLEMENTED, PARTIAL** | `command_center/`, dashboard pages/components, `PHASE_9_*` summaries | Current Mission Control/Command Center may show overlapping operational facts | **UNKNOWN** |
| RC / Batch 9 | Separate intraday-bot framework reviews | **LEGACY / FROZEN** | `intraday-trading-bot/reviews/Batch9*`, `RC9*` | Must not be wired as a second scheduler, portfolio, broker, or ledger | **Not ApexQuant production authority** |
| Phase 10A | Multi-agent framework | **CODE-PROVEN** | `agent_framework/`, `test_agent_framework.py`, `agentFramework.ts` | Registry and bus are in-process; runtime registration/agent loop activation needs proof | **UNKNOWN** |
| Phase 10B–10E | Analysis, decision, learning, collaboration/autonomous operations | **IMPLEMENTED, PARTIAL** | Agent directories, `decisionLayer.ts`, `learningLayer.ts`, collaboration/autonomous modules | Advisory/execution boundaries overlap Phase 20 and need hard ownership rules | **UNKNOWN** |
| RC / Batch 10 | Separate intraday-bot broker, execution and persistence batches | **LEGACY / REVIEWED** | `intraday-trading-bot/docs/RC10*`, migrations, reviews | Contains live-order-capable abstractions; high duplication risk | **Not proven active in ApexQuant** |
| Phase 11 | AI Paper Trader and autonomous paper views | **IMPLEMENTED, PARTIAL** | `phase11_autonomous.py`, `routes/phase11.ts`, Phase 11 dashboard pages | Must consume Phase 20 canonical ledger; legacy `paper_trades` must not leak into canonical calculations | **UNKNOWN** |
| Phases 12–14 | Intelligence, diagnostics, learning governance | **IMPLEMENTED, PARTIAL** | `routes/phase12.ts`–`phase14.ts`, pages and reports | Need current source contracts and production verification | **UNKNOWN** |
| Phase 15 | Data quality, stale scan, consistency | **IMPLEMENTED, PARTIAL** | `phase15_scan_context.py`, `routes/phase15.ts`, freshness reports | Current production scan-status route is no-store; page-level cache behavior still varies | **Partial production evidence** |
| Phases 16–19 / 19A–19C | Validation, QA, notebook, Kite OAuth/session and durable scans | **IMPLEMENTED, PARTIAL** | `routes/phase16.ts`–`phase19*`, Kite session/token modules, verification assets | Session validity requires authenticated probe; deployment runtime still needs periodic proof | **UNKNOWN** |
| Phase 20 | Scheduler, paper executor, exits, stores, bootstrap, EOD, circuit breaker | **CODE-PROVEN / PARTIALLY PRODUCTION-OBSERVED** | `phase20_scheduler.py`, `phase20_executor.py`, `phase20_exits.py`, `phase20_store.py`, `phase20_*_status.py`, `paper_entry_admission.py`; `trading.ts:3415–3756`; Phase 20 tests | Final paper authority by intent; immutability and EOD full closure not fully proven in production | **Active endpoints and settings observed** |
| Phase 21 | Advisory analytics/evidence | **IMPLEMENTED, PARTIAL** | `phase21*`, route and evidence data | Exact production consumption requires per-page/API tracing | **UNKNOWN** |
| Phase 22 | Kite session, evidence, pipeline enrichment | **IMPLEMENTED, PARTIAL** | `phase22*`, `phase22_evidence`, `routes/phase22.ts` | Kite verified status is production-observed, but session renewal/liveness over time is not | **Partial production evidence** |
| Phase 23 / 23.8 / 23.9 | Replay, simulation, validation/certification, portfolio reconstruction | **IMPLEMENTED, PARTIAL** | `replay_engine.py`, `routes/replay.ts`, `backtest_*`, `certification_*`, reports | Replay should be ledger/event-derived; do not create a parallel portfolio truth | **UNKNOWN** |
| Phase 24 | Learning engine and trade intelligence | **IMPLEMENTED, PARTIAL** | `phase24_engine.py`, `phase24_store.py`, `routes/phase24.ts`, four `phase24_*` tables | Current `intraday_candles` reference is conceptual/expected; table does not exist | **UNKNOWN** |
| Phase 25 / Mission Control | Operational command/Mission Control layers | **IMPLEMENTED, PARTIAL** | `MissionControl.tsx`, `CommandCenter.tsx`, `command_center/`, `pipeline.ts`, replay latest route/tests | Multiple centres and polling caches create duplicate/stale-display risk | **Partial production pipeline evidence** |
| Phase 26 / 26A / 26C / 26D | Pre-check visibility, E2E validation, scheduled validation, reporting | **IMPLEMENTED, PARTIAL** | `phase26_*`, stores, validation routes, summary reports | Production scheduler and daily scheduled execution must be verified | **UNKNOWN** |
| Phase 27 / 27C–27F | Explain/optimise, operator analytics, system readiness | **IMPLEMENTED, TEST-PROVEN** | `phase27*`, OperatorAnalytics/SystemReadiness pages and tests, verification reports | Read-only/advisory by design; deployment route/UI currency still needs browser proof | **UNKNOWN** |
| OHLCV cache migration | Cache-first daily OHLCV, company master, refresh state and readiness | **CODE-PROVEN / PRODUCTION-OBSERVED** | `ohlcv_cache_store.py`, `pre_market_data_readiness.py`, `post_market_data_refresh.py`, `routes/ohlcvCache.ts`, 3 cache tables | **Daily** cache is not intraday candle data | **Active and warm** |
| Kite LTP overlay | Optional current-price/execution-price overlay | **CODE-PROVEN / PARTIAL PRODUCTION** | `kite_ltp_overlay.py`, session/quote provider, overlay tests | It is a point quote, not 1m/5m/15m history; no order placement in API-server path | **Session/overlay reported enabled** |
| Bootstrap paper trading | Bounded bootstrap paper candidates/entries | **CODE-PROVEN / PRODUCTION-OBSERVED setting** | `run_bootstrap_auto_entry`, `phase20_bootstrap_status.py`, Phase 20 route/UI | Enabled now; must be framed as paper-only but operationally active | **Enabled** |
| EOD square-off / post-close force exit | Close/retry/force-close safety paths | **CODE-PROVEN** | `phase20_exits.py`, `phase20_scheduler.py`, `phase20_eod_status.py`, routes/tests | Overnight `OPEN` position means real-world end-to-end outcome still needs evidence | **Endpoint active; outcome not proven** |
| No-new-entry cutoff | Deny automatic entries after 15:15 IST | **CODE-PROVEN / TEST-PROVEN** | `market_hours.py`, `phase20_executor.py`, scheduler, `test_paper_entry_cutoff.py` | Need production-time event proof across cutoff | **UNKNOWN** |
| Off-market classification | Separate system jobs from market scans | **CODE-PROVEN / PRODUCTION-OBSERVED** | Scheduler and `test_task857_job_classification.py` | Current overnight API response shows expected `NON_MARKET` heartbeat classification | **Observed** |
| Build identity | Public build ID display / deployment identity labels | **CODE-PROVEN** | `APEXQUANT_PUBLIC_BUILD_ID_LABEL_FIX_REPORT.md`, dashboard build constant references | Current rendered label was not browser-verified in this review | **UNKNOWN** |
| Capital migration | Historical move to ₹100,000 | **PARTIAL / CONFLICTING** | `paper_capital_migration.py`, test, report | Production reports ₹500,000; operator must decide intended capital and reconcile report/config | **Current production: ₹500,000** |
| LTIM removal | Remove LTIM from active universe while retaining history | **PARTIAL / CONFLICTING** | Report and universe/cache code | Earlier report evidence still showed LTIM unavailable; current company-master set must be explicitly queried/confirmed before asserting removal | **UNKNOWN** |
| Quality allocation override | 2x/3x quality allocation policy | **IMPLEMENTED, RUNTIME UNKNOWN** | Quality allocation report and Phase 20 settings/gates | Current live activation/threshold selection must be checked from settings evidence | **UNKNOWN** |
| Low-price IT/Infra/Bank universe | Selectable custom paper universe | **CODE-PROVEN / DB-SCHEMA-OBSERVED** | `universe-custom.ts`, custom universe tables, settings | Production currently selects NIFTY 50 instead | **Implemented, inactive** |
| Dynamic intraday exit monitoring | Per-position evaluation and existing exit triggers | **PARTIAL** | `phase20_exits.py`, scheduler, executor recording | No durable intraday bars or per-trade high/low observation table; true multi-timeframe dynamic exit evidence is absent | **Baseline only** |
| Multi-agent intraday proposal | Earlier 15m/5m/1m future architecture | **PROPOSAL ONLY** | `APEXQUANT_MULTI_AGENT_INTRADAY_ARCHITECTURE_PROPOSAL.md` | Must be revised against this inventory; proposed tables are not created | **Not implemented** |

---

## 4. Existing bot, agent, scheduler, and authority inventory

### 4.1 Shared framework

| Component | Exact path and primary class/function | Current responsibility | Topics / persistence / UI | Authority and recommended treatment |
|---|---|---|---|---|
| Base agent | `agent_framework/base_agent.py`, `BaseAgent` | Registration, lifecycle, metrics and topic publishing | Uses singleton `SnapshotBus`; no durable storage proven | **Reuse** for advisory agents only |
| Registry | `agent_framework/agent_registry.py`, `AgentRegistry` | In-process agent registry and health metadata | No independent trading state | **Reuse**; production registration **UNKNOWN** |
| Snapshot bus | `agent_framework/snapshot_bus.py`, `SnapshotBus` | Latest-envelope topic bus with sequence numbers and subscriber callbacks | In-memory only; example market-data topic | **Reuse**, but never as sole durable audit record |
| Framework scheduler | `agent_framework/scheduler.py` | Agent scheduling/lifecycle helper | Runtime activation unknown | **Reuse only if it does not duplicate Phase 20 schedule ownership** |
| Heartbeat / health / metrics | `heartbeat_service.py`, `health_monitor.py`, `metrics.py`, `lifecycle_manager.py` | Agent status and instrumentation | Consumed through agent/framework routes and dashboards | **Reuse** for supervision |

### 4.2 Current framework agents

| Agent | Exact implementation | Published topic proven from code | Responsibility | DB read/write status | UI/API surface | Advisory/execution status | Recommended treatment and duplication risk |
|---|---|---|---|---|---|---|---|
| Market Data | `market_data_agent/agent.py:MarketDataAgent`; `shared_services.py` | `market_data` | Data availability, watchlist and scan context | Reads scan/watchlist sources; direct table map **UNKNOWN**; no trade write found | `agentFramework.ts`; Agent Operations surfaces | Advisory | **Reuse** as data-quality publisher |
| Research | `research_agent/agent.py:ResearchAgent`; `shared_services.py` | `research` | Research/event/macro context | Direct table map **UNKNOWN**; no trade write found | Agent/API routes, research pages | Advisory | **Reuse** |
| Market Intelligence | `market_intelligence_agent/agent.py:MarketIntelligenceAgent`; `shared_services.py` | `market_intelligence` | Regime, breadth, sector, volatility/session context | Direct table map **UNKNOWN** | Agent/market-intelligence UI | Advisory | **Modify** for future 15m context; no execution authority |
| Stock Monitoring | `stock_monitoring_agent/agent.py:StockMonitoringAgent`; `SmartPriorityEngine`; `EventDetector` | `stock_monitoring` | Symbol priority and monitoring events | Direct table map **UNKNOWN** | Agent/operations UI | Advisory | **Modify** for 1m timing evidence; never become exit executor |
| Strategy | `strategy_agent/agent.py:StrategyAgent`; Breakout/VWAP/ORB/Momentum/MeanReversion/Gap strategies | `strategy` | Candidate setup/rationale | Direct durable output table absent | Strategy/decision UI | Advisory | **Modify** for 5m setup provenance |
| Risk | `risk_agent/agent.py:RiskAgent`; `shared_services.py` | `risk` | Exposure, sizing, sector/correlation, heat/drawdown views | Reads portfolio/trades by design; direct write map **UNKNOWN** | Risk/portfolio pages | Advisory | **Reuse** for advisory calculation; Phase 20 must revalidate |
| AI Decision | `ai_decision_agent/agent.py:AIDecisionAgent`; `decision_engine.py`; `explainability.py` | `decisions` | Candidate aggregation, conflicts and explainability | Direct table write **UNKNOWN**; no Phase 20 ledger write intended | `/decision-layer/ai-decision/*`, decision pages | Advisory | **Modify** into evidence coordinator; do not grant execution |
| Execution | `execution_agent/agent.py:ExecutionAgent`; `execution_planner.py`; `shared_services.py` | `execution` | Execution planning and validation view | Direct trade write should be absent; runtime enforcement **UNKNOWN** | `/decision-layer/execution/*`, execution page | Planning only | **Retain advisory only**; high risk of second executor |
| Learning | `learning_agent/agent.py:LearningAgent`; `learning_engine.py` | Topic/static publication not fully proven | Outcomes, patterns and lessons | Reads trade/analytics evidence; active config mutation not found | Learning pages/routes | Advisory | **Reuse** after immutable audit data exists |
| Knowledge | `knowledge_agent/agent.py:KnowledgeAgent`; `knowledge_engine.py` | Topic/static publication not fully proven | Trade memory and knowledge indexing | Direct table ownership **UNKNOWN** | Knowledge pages/routes | Advisory | **Reuse** |
| Supervisor | `supervisor_agent/supervisor.py:SupervisorAgent` | Reads configured pipeline topics | Agent dependency/freshness/health observation | No trade state mutations | Supervisor/Command/Operations UI | Advisory/control-plane | **Reuse unchanged**; never auto-trade or auto-restart |

### 4.3 Agent-equivalent and overlapping subsystems

| Module / group | Path | Responsibility | Authority risk | Required disposition |
|---|---|---|---|---|
| Canonical scan | `live_scan_engine.py`, `live_data_provider.py`, `market_scanner.py` | Data fetch, analysis, scan recommendation and canonical scan snapshot | Can be mistaken for an entry executor | Retain as scan/data authority |
| Phase 20 scheduler | `phase20_scheduler.py` | Scheduled market/system jobs, scans, exits, bootstrap and automatic-entry orchestration | Must remain only scheduler that triggers Phase 20 entries/exits | Retain; do not add parallel agent scheduler |
| Phase 20 executor | `phase20_executor.py`, `paper_entry_admission.py` | Simulated entry, admission, fill and ledger recording | Intended final paper-entry authority | Retain as the only entry writer; add immutability proof later |
| Phase 20 exits | `phase20_exits.py` | Stop/target/recommendation/trailing/time/risk/stale/EOD exits and pending handling | Must not be replaced by Stock Monitoring/Execution Agent | Retain as sole operational exit authority |
| Phase 11 autonomous | `phase11_autonomous.py` | Legacy/autonomous paper views and compatibility logic | May read legacy stores and overlap Phase 20 | Quarantine from ledger authority; make consumers canonical-only |
| Paper trader / legacy store | `paper_trader.py`, `portfolio_store.py`, `paper_trades`, `paper_portfolio` | Legacy simulated portfolio/trades | Competes with Phase 20 canonical truth | Legacy/derived only; do not mix with Phase 20 calculations |
| Event-sourced portfolio/execution | `src/execution/*`, `src/portfolio/*`, `portfolio_events`, `portfolio_snapshots` | Parallel execution/portfolio model | High duplicate-authority risk; wiring to Phase 20 not proven | Inventory and either integrate behind explicit bridge or retire from trading path |
| Autonomous operations / collaboration | `autonomous_operations/`, `collaboration_engine/`, `collaboration_layer/` | Operational coordination, graph, alerts and lineage | May appear to orchestrate trades | Keep advisory/observability only |
| Pre-/post-market workers | `pre_market_data_readiness.py`, `post_market_data_refresh.py`, preopen schedulers | Readiness and cache refresh | Must not be described as intraday strategy agents | Retain as data operations |
| Reconciliation | `eod_reconciliation.py`, `broker_reconciliation_*` | Compare/reconcile state and record discrepancy | Must remain observational; do not submit orders | Retain as read-only verification |
| Separate intraday bot | `intraday-trading-bot/` | Full separate bot architecture, brokers, orders, repositories, timeframes, strategies | **Critical:** includes order gateway/client methods capable of `place_order`, `modify_order`, `cancel_order` | Keep isolated; use only pure concepts after contract-level adaptation |

### 4.4 Production activation status

The deployed API demonstrates scan pipeline stages and Phase 20 endpoints. It does **not** demonstrate that every class above is continuously instantiated as a long-running framework agent. Until registry snapshots, process lifecycle logs, and topic freshness are captured in production:

- All concrete framework-agent **runtime activation** is **UNKNOWN**.
- `SnapshotBus` is process-local and therefore is not a durable cross-process contract on Autoscale by itself.
- Future multi-agent work must persist decision/audit evidence outside the bus.

---

## 5. Current end-to-end market-data-to-paper-trade map

| # | Current flow step | File / function boundary | Inputs | Output / persistent source | Event / API / UI |
|---|---|---|---|---|---|
| 1 | Universe selection | Watchlist/config readers; custom-universe route/store | Configured active universe | NIFTY 50 or custom-universe symbol set | `/phase20/settings`, `/ohlcv-cache/readiness`; Watchlist/Settings UI |
| 2 | Daily cache lookup | `ohlcv_cache_store.py` | Symbol/date/history request | `daily_ohlcv_cache`, `daily_ohlcv_refresh_state` | `/ohlcv-cache/status`, `/readiness` |
| 3 | Historical fallback | `live_data_provider.py` | Missing/insufficient cached OHLCV | yfinance fetched daily bars and quality metadata | Scan response/provenance |
| 4 | Current quote overlay | `kite_ltp_overlay.py` | Verified Kite session and symbols | Current/execution-price overlay with reliability | Scan/recommendation context; no broker order |
| 5 | Data quality gate | `live_scan_engine.py`, provider quality code | Cache/provider age, availability, symbol facts | `LIVE`/`NEAR_LIVE`/`STALE`/`UNAVAILABLE` eligibility facts | Scan state/events; stale/unavailable caps action |
| 6 | Canonical scan | `live_scan_engine.py` | Complete symbol batch | One `scan_id`, `snapshot_ts`, recommendations | `scan_state`, `phase20_scan_runs`, `pipeline_events`; scan routes |
| 7 | Scan persistence/lock | `scan_state_store.py`, `scan_lock` | Scan result and scheduler identity | Canonical snapshot/history and lease state | Scan status/history; Mission Control/Command Center |
| 8 | Pipeline stages | Scan/analysis agent-equivalent modules | Symbol facts and scan result | Research, intelligence, monitoring, strategy and decision evidence | `pipeline_events`, `/pipeline/summary`; Mission Control |
| 9 | Advisory strategy and AI decision | Strategy, Risk, AI Decision agents | Scan/research/portfolio context | Candidate/rationale/risk information | SnapshotBus topics; decision-layer API; dashboards |
| 10 | Bootstrap eligibility | `phase20_bootstrap_status.py`, `run_bootstrap_auto_entry` | Scan candidates, settings, evidence | Bootstrap candidate status | `/phase20/bootstrap-status`; AI Paper Trader/Mission Control |
| 11 | Market-window gate | `market_hours.automatic_paper_entry_status`, executor/scheduler | IST timestamp and market state | Allowed/blocked entry state | Automatic entry returns explicit refusal if unavailable/late |
| 12 | Final entry admission | `paper_entry_admission.py`, `phase20_executor.py` | Candidate, settings, capital, positions, risk/quality | Atomic/canonical simulated entry decision | `phase20_paper_trades`, pipeline terminal events |
| 13 | Paper fill | `phase20_executor.py` / paper-trader support | Admitted quantity/fill model/quote | Simulated fill price, costs and evidence | Ledger row and positions API |
| 14 | Portfolio projection | `canonical_portfolio.py` | Phase 20 canonical ledger | Positions, cash, equity, P&L, history | Portfolio/Phase 20/replay UI; legacy fallbacks are prohibited for canonical view |
| 15 | Open-position monitoring | `phase20_exits.manage_open_positions` | Canonical open trades, scan/price data, settings | Hold/exit/pending evaluation | Phase 20 exit state; pipeline evidence |
| 16 | Normal exit recording | `phase20_executor.record_exit` | Exit decision plus reliable price | Closed trade P&L/exit fields | `phase20_paper_trades`; `paper.trade.recorded` from exit route |
| 17 | Unsafe-price exit | `phase20_exits.py` | Exit trigger with no safe price | `EXIT_PENDING`, retry/recovery evidence | EOD/exit UI and events; full resolution lifecycle needs runtime proof |
| 18 | EOD and post-close | Scheduler/EOD modules | IST market time, open trades, retry state | Market-close exit/force-close/recovery outcome | `/phase20/eod-status`, force-close route, scheduler state |
| 19 | Replay, learning and UI | `replay_engine.py`, `pipeline_events.py`, Learning/Knowledge, React/Expo | Ledger plus events/snapshots | Read-only operational and learning projections | Mission Control, AI Paper Trader, replay/analytics/mobile views |

### 5.1 Important flow limitations

- The data foundation is **daily OHLCV plus a current LTP overlay**. A five-minute scheduler cadence is not a five-minute candle feed.
- No current API-server store contains canonical durable 1-minute, 5-minute, or 15-minute candles.
- No current dedicated model captures timestamped per-trade high-water/low-water observations.
- Existing exit logic is richer than a simple stop/target path, but its forensic intraday evidence cannot claim exact post-entry excursion without a new append-only observation stream.

---

## 6. UI inventory

### 6.1 Registration and runtime caveat

`artifacts/trading-dashboard/src/App.tsx:148–267` registers all routes below in the application router. Therefore they are production-addressable when the matching deployment build is serving, but route registration alone does not prove each page’s API response, cache freshness, or canonical source.

### 6.2 Registered dashboard route manifest

| Category | Route → component |
|---|---|
| Core trading | `/` → `TradeDecisions`; `/portfolio-manager` → `PortfolioManager`; `/portfolio-live` → `PortfolioLive`; `/dashboard` → `Dashboard`; `/market` → `MarketOverview`; `/market-scanner` → `MarketScanner`; `/signals` → `Signals`; `/signal-history` → `SignalHistory`; `/trades` → `Trades`; `/watchlist` → `Watchlist`; `/broker-execution` → `BrokerExecution` |
| Scan, replay, testing | `/market-replay` → `MarketReplay`; `/trade-replay` → `TradeReplay`; `/replay` → `ReplayModePage`; `/backtest` → `Backtest`; `/validate` → `Validate`; `/simulation-lab` → `SimulationLab`; `/validation-dashboard` → `ValidationDashboard`; `/paper-basket-test` → `PaperBasketTest`; `/walk-forward` → `WalkForwardValidation` |
| Strategy, research, learning | `/strategy-lab` → `StrategyLab`; `/optimization-lab` → `OptimizationLab`; `/optimizer` → `Optimizer`; `/strategy-evolution` → `StrategyEvolution`; `/strategy-intelligence` → `StrategyIntelligence`; `/strategy-optimisation` → `StrategyOptimisation`; `/research-intelligence` → `ResearchIntelligence`; `/research-notebook` → `ResearchNotebook`; `/research-lab` → `ResearchLab`; `/historical-knowledge` → `HistoricalKnowledge`; `/learning-insights` → `LearningInsights`; `/learning-review` → `LearningReview`; `/learning` → `LearningGovernance`; `/pattern-quality` → `PatternQuality`; `/feature-importance` → `FeatureImportance`; `/experiments` → `ExperimentManager` |
| Data, pre-market, readiness | `/live-data-health` → `LiveDataHealth`; `/live-readiness` → `LiveReadiness`; `/data-quality` → `DataQuality`; `/preopen-intelligence` → `PreOpenIntelligence`; `/preopen-accuracy` → `PreOpenAccuracy`; `/signal-validation` → `SignalValidationPage`; `/phase4a-session` → `Phase4ASession`; `/system-validation` → `SystemValidation`; `/system-readiness` → `SystemReadiness`; `/operator-status` → `OperatorStatus` |
| Risk, quality, analytics | `/risk` → `RiskManagement`; `/portfolio-risk` → `PortfolioRiskAnalytics`; `/risk-validation` → `RiskValidation`; `/risk-decision-report` → `RiskDecisionReportPage`; `/portfolio-performance` → `PortfolioPerformance`; `/performance-analytics` → `PerformanceAnalytics`; `/execution-quality` → `ExecutionQualityPage`; `/trading-quality` → `TradingQuality`; `/paper-analytics` → `PaperAnalytics`; `/institutional-analytics` → `InstitutionalAnalytics`; `/operator-analytics` → `OperatorAnalytics`; `/ai-performance` → `AIPerformanceIntelligence`; `/ai-optimisation` → `AIOptimisation`; `/risk-optimisation` → `RiskOptimisation`; `/executive-dashboard` → `ExecutiveDashboard` |
| Intelligence / Phase pages | `/phase12` → `Phase12Intelligence`; `/phase13` → `Phase13Intelligence`; `/market-intelligence` → `MarketIntelligenceHub`; `/event-intelligence` → `EventIntelligence`; `/macro-intelligence` → `MacroIntelligence`; `/explainable-ai` → `ExplainableAI`; `/ai-decision` → `AiDecision`; `/ai-copilot` → `AiCopilot` |
| Operations / centres | `/observability` → `ObservabilityCenter`; `/operations-center` → `OperationsCenter`; `/security-center` → `SecurityCenter`; `/performance-center` → `PerformanceCenter`; `/deployment-center` → `DeploymentCenter`; `/command-center` → `CommandCenter`; `/live-command-center` → `LiveCommandCenter`; `/mission-control` → `MissionControl`; `/ai-operations-centre` → `AIOperationsCentrePage`; `/ai-investigation` → `AIInvestigationCentre`; `/investigation-center` → `InvestigationCenter`; `/automation` → `AutomationHealth`; `/system-health` → `SystemHealthPage`; `/scalability-dashboard` → `ScalabilityDashboardPage`; `/workspace` → `Workspace`; `/trading-timeline` → `TradingTimeline`; `/executive-reports` → `ExecutiveReports`; `/design-system` → `DesignSystem` |
| Multi-agent/collaboration | `/agent-operations` → `AgentOperations`; `/agent-ai-decision` → `AiDecisionAgentPage`; `/agent-execution` → `ExecutionAgentPage`; `/agent-learning` → `LearningAgentPage`; `/agent-knowledge` → `KnowledgeAgentPage`; `/pattern-explorer` → `PatternExplorerPage`; `/lessons-library` → `LessonsLibraryPage`; `/knowledge-search` → `KnowledgeSearchPage`; `/trade-memory` → `TradeMemoryPage`; `/collab-graph` → `CollaborationGraphPage`; `/decision-lineage` → `DecisionLineagePage`; `/autonomous-ops` → `AutonomousOpsPage`; `/agent-comm-monitor` → `AgentCommMonitorPage`; `/collab-alerts` → `CollaborationAlertsPage`; `/supervisor-extended` → `SupervisorExtendedPage` |
| Paper trading / Phase 11 | `/validation` → `PaperTradingValidation`; `/paper-trading-summary` → `Phase11SummaryPage`; `/paper-trading-portfolio` → `Phase11PortfolioPage`; `/paper-trading-recommendations` → `Phase11RecommendationQueuePage`; `/paper-trading-replay` → `Phase11ReplayPage`; `/paper-trading-reports` → `Phase11ReportsPage`; `/paper-trading-timeline` → `Phase11TimelinePage`; `/ai-paper-trader` → `AIPaperTraderPage`; `/paper-learning` → `PaperLearningMode` |
| Settings/support | `/settings` → `Settings`; `/kite-connect` → `KiteConnect`; `/notifications` → `Notifications`; `/operational-intelligence` → `OperationalIntelligence` |

### 6.3 Required user-facing surfaces and source assessment

| Page / component | Frontend location | Verified backend data source | Canonical/fallback assessment | Cache/staleness and architecture impact |
|---|---|---|---|---|
| Landing / trade decisions | `pages/TradeDecisions.tsx` | Exact endpoint map **UNKNOWN** without per-hook trace | Must use canonical scan/decision evidence | Must show data freshness and no-entry reason under revised architecture |
| Mission Control | `pages/MissionControl.tsx`; `components/mission/*` | Pipeline/replay/ops routes; `/pipeline/summary` verified active | Must use canonical scan/ledger/replay counts; do not duplicate agent state | Existing tests cover freshness/pipeline/bootstrap; polling/cache can retain stale panels |
| AI Paper Trader | `pages/AIPaperTraderPage.tsx` | `/phase20/bootstrap-status`, `/phase20/positions`, `/phase20/eod-status`, replay-related routes | Must render canonical Phase 20 positions/closed trades, never legacy fallback as truth | 15s stale time / 30s polling observed in code; must surface source timestamp, entry enablement and EOD pending state |
| Live Scanner | `pages/MarketScanner.tsx` | `/live-data/scan*` family | Canonical scan source | Status/history routes are no-store in production; page query cache still needs session-aware freshness |
| Live Data Health | `pages/LiveDataHealth.tsx` | Live-data health/cache/readiness route family | Provider/cache quality view | Must distinguish daily OHLCV freshness from intraday-candle freshness |
| System Readiness | `pages/SystemReadiness.tsx` | Readiness/Phase 27 surfaces | Read-only readiness/operational projection | Must flag enabled auto-entry and EOD unresolved position when applicable |
| Operator Analytics | `pages/OperatorAnalytics.tsx` | Phase 27/operator analytics APIs | Advisory analytics | Registered/tested; data freshness must be explicit |
| Portfolio / Risk | `PortfolioLive.tsx`, `PortfolioManager.tsx`, `PortfolioRiskAnalytics.tsx` | Portfolio/Phase 20 routes, exact query mapping varies | Canonical source must be `phase20_paper_trades` through `canonical_portfolio.py` | Any `paper_trades`/file cache fallback should be visibly marked non-canonical |
| Pre-market | `PreOpenIntelligence.tsx`, `PreOpenAccuracy.tsx`, `Phase4ASession.tsx` | Preopen/readiness APIs | Separate pre-market data flow | Must not be represented as intraday-bar evidence |
| Agent configuration/operations | `AgentOperations.tsx`, agent detail pages, `AgentConfig.ts` | `agentFramework.ts`, decision/learning routes | Framework snapshots are advisory | Must show topic freshness/runtime UNKNOWN rather than assume agents are live |
| Bootstrap card/settings | `AIPaperTraderPage.tsx`, `Phase20Settings.tsx` | `/phase20/bootstrap-status`, `/phase20/settings` | Current production values are authoritative settings | Must prominently show enabled status, confirmation time, active universe and capital |
| Universe/cache cards | Watchlist/Settings/LiveDataHealth components | `/ohlcv-cache/status`, `/readiness`, `/company-master`, universe route | Daily cache and universe data | Must not label daily cache as 1m/5m/15m intraday coverage |
| Open/closed trade tables | AI Paper Trader / Trades / Phase 11 pages | `/phase20/positions`, `/phase20/ledger`, `/phase20/replay/:tradeId` | Phase 20 ledger is intended canonical | Show quantity, source timestamps, `EXIT_PENDING`, EOD status and any legacy-source disclaimer |
| EOD status | AI Paper Trader/Mission Control/Phase 20 components | `/phase20/eod-status` | Current production response exists | Must surface open prior-session positions and force-close/retry evidence |

### 6.4 Component families reviewed

The dashboard component tree contains reusable families for:

- `components/mission/` (9 files), `components/replay/` (6), `components/workspace/` (7), `components/riskReport/` (7), `components/layout/` (4), `components/brand/` (6), `components/ds/` (17), `components/ui/` (55), and Phase 15/20/21/22 panels.
- Shared operational components including `DataFreshnessBar`, `LiveMarketTicker`, `Phase20Lifecycle`, `Phase20Settings`, `ReconciliationWidget`, `HistoricalEvidence`, `EvidenceExpansionSection`, and delivery/notification components.

They are display components, not separate trading authorities. Future work must add information to these existing families instead of creating duplicate “intraday control” screens.

### 6.5 Mobile

The Expo application registers:

- `app/(tabs)/index.tsx` (home/portfolio), `signals.tsx`, `alerts.tsx`, `ai-ops.tsx`, `health.tsx`, `positions.tsx`, and `watchlist.tsx`.
- Shared data/freshness modules: `lib/monitorApi.ts`, `lib/offlineCache.ts`, `lib/cacheSchema.ts`, `lib/freshnessCompute.ts`, `lib/dataStatus.ts`, `components/FreshnessLabel.tsx`, and `components/StaleBanner.tsx`.

Mobile intentionally follows `live → memory → offline cache → none`. It marks cached state stale, but prominent stale presentation in AI Ops is delayed until five minutes. Therefore mobile is a **stale-display risk** for positions/operational state during outages. It does not presently expose the full Mission Control/replay/EOD detail surface.

---

## 7. Database and store inventory

### 7.1 Current physical schema

Development and production both contain the primary tables below. Production additionally contains `phase11_capital_topups`, which was not observed in the development table list. The core schemas and indexes for Phase 20, scans, cache, custom universe, pipeline, portfolio, Phase 22/24/26, backtest, and validation were inspected through `information_schema` and `pg_indexes`.

### 7.2 Core execution and canonical/legacy stores

| Table / store | Key schema/authority | Owner/read-write paths | Canonical / mutation status | Production / retention concern |
|---|---|---|---|---|
| `phase20_paper_trades` | Trade IDs; scan/signal/fill timestamps; prices; quantity; stop/target; confidence; strategy; status; exit fields; `evidence`; config/version fields | Owner: `phase20_executor.py`; reads: exits, portfolio/replay/analytics/routes | **Intended canonical Phase 20 ledger**. Unique partial production index `phase20_open_symbol_uidx(symbol) WHERE status='OPEN'` proves one open row per symbol. Generic update/delete helpers exist, so immutable completed rows are **not proven**. | Exists in dev/prod. Retention/append-only policy not DB-enforced. |
| `paper_trades` | Buy/sell row, quantity, price, metadata | Legacy `portfolio_store.py`/paper trader consumers | **Legacy; not canonical for Phase 20 portfolio** | Exists dev/prod; must not be mixed into canonical calculations. |
| `paper_portfolio` | Cash, JSON positions and P&L history | Legacy paper portfolio support | **Legacy state projection** | Exists dev/prod; one mutable row pattern. |
| `experimental_paper_trades` | Separate paper trade/simulation fields, MFE/MAE | Experimental/admission analytics | **Derived/experimental**; own open-symbol index | Exists dev/prod; competing truth risk. |
| `portfolio_events` / `portfolio_snapshots` | Event identity/idempotency, portfolio facts and snapshots | Separate portfolio/event-sourcing model | **Parallel model, Phase 20 wiring unproven** | Exists dev/prod; do not treat as Phase 20 authority until bridged. |
| `phase11_price_snapshots` | Scan/symbol/price timestamp | Phase 11 compatibility/price tracking | Derived/legacy observation | Exists dev/prod; not a full per-trade high/low model. |
| `phase11_capital_topups` | Production-only observed table | Exact owner **UNKNOWN** | Legacy/Phase 11 related | Exists production only; schema reconciliation needed. |

### 7.3 Scan, settings, scheduler, pipeline, and notification stores

| Table / store | Schema / owner | Read/write and safety | Canonical role |
|---|---|---|---|
| `scan_state` | One scan snapshot/status/quality record, `snapshot` JSON; `scan_state_store.py` | Current scan read/write and freshness | **Canonical current scan snapshot** |
| `scan_lock` | Lease holder/acquired/expiry; `scan_state_store.py` | Prevent overlapping scans | Coordination state, not business history |
| `phase20_scan_runs` | Scan/job type, market state, eligibility, counts, errors, timings/details | `phase20_store.py`/scheduler writes; routes read | Durable scheduler/scan history |
| `phase20_scheduler_state` | Heartbeat, due/success/error/owner/process info | Scheduler writes; health reads | Scheduler coordination |
| `phase20_settings` | Single JSON settings document | Settings routes/store read/write | Current configuration authority; no schema-level field constraints |
| `phase20_kv` | Key/JSON value/timestamp | Scheduler idempotency/claims/state | Coordination; must use atomic claim patterns |
| `phase20_notifications` | Severity/title/body/context/read state | Notification producers/UI | Derived operator notifications |
| `pipeline_events` | Timestamp, mode/run/scan IDs, event type/stage/symbol/payload/dedupe key | `pipeline_events.py` appends; pipeline/replay/Mission Control read | Append-oriented pipeline evidence. Dev has a dedupe unique index; production index list did not show it, so index parity must be checked. |
| `alert_deliveries`, `push_subscriptions` | Alert/push delivery support | Node notification services | Communication state, not trading authority |

### 7.4 Market-data and universe stores

| Table / store | Schema / owner | Canonical role | Concern |
|---|---|---|---|
| `daily_ohlcv_cache` | Symbol/date OHLCV, source, fetched/updated timestamp, quality; `ohlcv_cache_store.py` | **Canonical daily cache** | Not intraday candle storage. Unique `(symbol, trading_date)` index exists dev/prod. |
| `daily_ohlcv_refresh_state` | Refresh date/type/status, symbols, errors and duration | Cache refresh status | Last refresh is operational evidence, not live quote freshness |
| `nifty50_company_master` | Symbol/provider symbols/sector/index/active/source | NIFTY universe metadata | Must verify active membership and LTIM state separately |
| `custom_universe_master` | Symbol/provider mapping, allowed universe, price/volume/active/reasons | Custom-universe master | Exists dev/prod; production currently selects NIFTY 50 |
| `custom_universe_membership_history` | Snapshot timestamp/date/symbol/universe/active | Historical membership truth | Correct basis for no-look-ahead backtests |
| `preopen_*` family | Candidate outcomes, reports, factors, provider health, rankings, sessions, snapshots, validation, watchlists | Pre-market intelligence | Separate from intraday candle/position evidence |

### 7.5 Validation, replay, learning, research, and compliance stores

| Group | Tables present in dev/prod | Role and authority |
|---|---|---|
| Backtest | `backtest_candles`, `backtest_candle_meta`, `backtest_corporate_actions`, `backtest_runs`, `backtest_trades` | Isolated backtest data. `backtest_candles` supports interval/timestamp OHLCV but is not the current live intraday evidence store. |
| Validation V2 | `validation_v2_runs`, `validation_v2_decisions`, `validation_v2_trades`, `validation_v2_missed`, `validation_v2_optimizer_runs` | Validation/replay outputs; derived, not live ledger authority. |
| Phase 22 evidence | `phase22_evidence` | Append-oriented decision/outcome evidence; unique `(scan_id, symbol)` index. |
| Phase 24 learning | `phase24_trade_intelligence`, `phase24_missed_opps`, `phase24_recommendations`, `phase24_reports` | Advisory intelligence/reports; do not tune active policy automatically. |
| Phase 26 / certification | `phase26_validation_runs`, `phase26c_results`, `phase26_daily_reports`, `phase26_live_snapshots`, `phase26_issues`, `certification_runs` | Validation/certification reporting; derived. |
| Reconciliation | `broker_reconciliation_runs`, `broker_reconciliation_discrepancies`, `reconciliation_runs`, `preopen_reconciliation` | Observation/reconciliation only; no order authority. |
| Signals/data-quality | `signals_cache`, `signal_*`, `data_quality_runs`, `session_archives` | Analytics/derived evidence; exact ownership of all tables requires per-module trace. |
| Overrides | `portfolio_config_overrides` | Durable configuration override state | Must not be confused with runtime default settings. |

### 7.6 Required-but-not-created future tables

The following are **not present** in development or production schema inventories:

- `intraday_candles`
- `paper_trade_price_tracking`
- `strategy_agent_outputs`
- `entry_decision_audit`
- `exit_decision_audit`

They remain architectural proposals only. They must not be created until the data-provider, retention, ownership, and Phase 20 integration decisions are approved.

---

## 8. API route inventory

All API routes are mounted under `/api`. “Cache” reflects source/production spot checks where available; it is not a universal CDN guarantee.

| Route family | Exact source | Key response/source | Read/mutate | Cache / frontend use / safety |
|---|---|---|---|---|
| `/healthz` | `routes/health.ts:37` | `{status}` health response | Read | Production HTTP 200, `private`; dashboard/mobile usage varies |
| `/live-data/scan`, `/status`, `/history`, `/run`, `/abort`, `/health-v2` | `routes/trading.ts` (status 1326, history 1397, run 1464) | Scan snapshot, history, job classification and operation controls | Read plus scan-control mutations | Production status/history `no-store`; manual scan must remain market-hours gated |
| `/phase20/settings` | `routes/trading.ts:3415`, `PUT` 3517 | Current JSON setting document | Read / mutate | Production read is `private`; settings can materially enable paper automation |
| `/phase20/bootstrap-status` | `routes/trading.ts:3480` | Bootstrap/auto-entry settings, candidate status, Kite verification | Read | Production `no-store`; currently reports enabled bootstrap and auto entries |
| `/phase20/eod-status`, `/force-eod-close` | `routes/trading.ts:3494` and adjacent route | Clock, EOD outcomes, block/retry state | Read / destructive safety action | Status is `no-store`; force-close is mutating and must remain operator-confirmed |
| `/phase20/scheduler/health`, `/scan-history` | `routes/trading.ts:3646`, 3655 | Scheduler status and scan job history | Read | Used by operational views; must distinguish market/system jobs |
| `/phase20/ledger`, `/positions`, `/exits/tick`, `/replay/:tradeId` | `routes/trading.ts:3698–3737` | Canonical intended ledger, open positions, exit evaluation/replay | Read except exit tick | `/positions` production `private`; exit tick is mutating and must never be triggered by an advisory agent |
| `/phase20/circuit-breaker`, `/resume` | `routes/trading.ts:3746, 3756` | Circuit state/resume control | Read / mutating resume | Resume needs manual-review safety |
| `/ohlcv-cache/status`, `/readiness`, `/company-master`, `/company-master/bootstrap` | `routes/ohlcvCache.ts:82,103,110,116` | Daily-cache health, readiness, universe metadata | Read / mutating bootstrap | First three production routes active; status/readiness `no-store`; daily cache must not be labeled intraday bars |
| `/pipeline/events`, `/pipeline/summary` | `routes/pipeline.ts:47,72` | Durable pipeline event history/summary | Read | Production summary active (`private`); Mission Control/Replay consumer |
| `/agent-framework/*` | `routes/agentFramework.ts` | Supervisor, list/detail, data/research/monitoring snapshots/status | Read/control varies | Framework-state consumer; runtime agent availability must be explicit |
| `/decision-layer/ai-decision/*`, `/decision-layer/execution/*` | `routes/decisionLayer.ts` | Agent snapshot/recommendations/queue/status | Read | Must remain advisory and never issue direct Phase 20 writes |
| `/learning-layer/*` | `routes/learningLayer.ts` | Learning/knowledge snapshot, insight, memory and status | Read | Advisory only |
| `/portfolio/*`, `/trades`, `/analytics/*`, `/risk/*` | `routes/portfolio.ts`, trading and analytics route families | Portfolio/trade/risk analytics | Read plus selected configuration actions | UI must label canonical vs legacy source |
| `/paper-analytics/*` | `routes/paper-analytics.ts` | Summary/trades/strategies/risk/portfolio/learning/preopen | Read | Tab-gated frontend queries can be stale |
| `/replay/*`, `/backtest/*`, `/simulation/*`, `/validation*`, `/certification/*` | Corresponding route files | Replay, backtest, simulation, validation and certification | Mixed | Derived systems; not ledger authority |
| `/universe-custom/*` | `routes/universe-custom.ts` | Custom low-price universe administration | Mixed | Custom universe exists but is inactive in observed production setting |
| `/kite/*` | `routes/kite.ts` | Read-only broker positions/quotes/health display | Read | Keep read-only boundary; not a live-order API |
| `/broker/*` | Broker route family | Paper/health/readiness/preview/confirm controls | Mixed | Requires separate per-route confirmation and explicit paper-mode enforcement |
| `/ops-centre/*`, `/command-center/*`, `/observability/*`, `/operations/*` | Corresponding route files | Operational aggregate snapshots | Read/control varies | Long-lived caches can create stale panels |

### 8.1 Route-schema and cache risks

1. The current deployed scan/cache routes are current enough to return new status fields, but this does not prove every route returns the latest schema.
2. Several important read routes return `private`, while scan/cache status responses return `no-store`. Frontend React Query polling/stale-time remains an independent cache layer.
3. Mutating routes exist for settings, scan controls, forced EOD action, exit tick, and circuit resume. The revised architecture must ensure no advisory agent can invoke them automatically.

---

## 9. Current safety contract: proof matrix

| Safety contract | Evidence | Status | Gap / exact next verification |
|---|---|---|---|
| Paper-only Phase 20 execution | `phase20_executor.py` documents simulated/paper execution; deployed API exposes paper settings/status | **CODE-PROVEN / partial production observed** | Verify runtime logs/config guard for every production execution path |
| No API-server live broker order placement | API-server market-data/Phase 20 modules do not expose Kite order placement; Kite route is read-only | **CODE-PROVEN for intended ApexQuant path** | Repository-wide claim is false/not provable because legacy `intraday-trading-bot` has real order methods |
| No live order was called during this review | Only deployment metadata, SQL metadata, source reads, and `GET` routes were used | **PROVEN for this review** | None |
| One intended canonical Phase 20 writer | `phase20_executor.py` writes `phase20_paper_trades`; route and portfolio architecture reference it | **PARTIALLY PROVEN** | Legacy tables and parallel event-sourced models remain; audit all writers before claiming global uniqueness |
| No duplicate open position per symbol | Production/dev partial unique index `phase20_open_symbol_uidx(symbol) WHERE status='OPEN'` | **DB-PROVEN** | `EXIT_PENDING` rows are not included in this partial index; confirm admission semantics for pending rows |
| No automatic entry after 15:15 IST | `market_hours.automatic_paper_entry_status`; executor guard; `test_paper_entry_cutoff.py` | **CODE/TEST-PROVEN** | Observe scheduler/admission event at cutoff in production |
| Market-close exit from 15:20 IST | EOD status code/route and production response show 15:20 boundary | **CODE-PROVEN / response observed** | Observe actual close event/replay; overnight open position makes end-to-end proof incomplete |
| Post-close force exit after 15:30 IST | Scheduler and EOD code paths/reference docs | **CODE-PROVEN** | Observe production force-close/retry trace |
| Fail-closed market-state before admission | Executor market-entry status and scheduler market job classification | **CODE-PROVEN** | Add a production negative test/trace for state lookup failure |
| Unsafe exit uses `EXIT_PENDING` | Phase 20 exits/validation code recognizes pending state | **CODE-PROVEN** | Prove terminal/retry escalation and operational alerting in production |
| Completed trade cannot mutate | Intent/report says historical trades are evidence | **NOT PROVEN** | `phase20_executor.py` has generic `UPDATE` and `DELETE`; create/verify an immutable-close storage policy before claiming this |
| Learning/Knowledge advisory only | Learning/Knowledge agent roles and design reports | **CODE-PROVEN intent** | Verify no settings mutation or executor call paths at runtime |
| Agents cannot write trades directly | Framework roles are advisory; Phase 20 intended writer | **PARTIALLY PROVEN** | Exhaustively trace all agent/shared-service write calls and runtime routes before formal certification |
| Supervisor never trades/restarts automatically | `supervisor_agent/supervisor.py` reads registry/bus and observes | **CODE-PROVEN** | Confirm production deployment uses this supervisor class/version |

---

## 10. Architecture consistency gaps and legacy risks

| Finding | Evidence / risk | Required architectural decision |
|---|---|---|
| Multiple portfolio/trade stores | `phase20_paper_trades`, `paper_trades`, `experimental_paper_trades`, `paper_portfolio`, event-sourced portfolio stores, Phase 11 snapshots | Declare `phase20_paper_trades`/`canonical_portfolio.py` as the only current paper-trading read authority; bridge or retire competitors. |
| Multiple execution-like layers | Phase 20 executor, Execution Agent planner, Phase 11 autonomous, separate intraday bot broker/execution stack | One final paper entry writer and one exit manager only. |
| Legacy bot contains live-order capability | `intraday-trading-bot/src/brokers/zerodha/client.py` has `place_order`, `modify_order`, `cancel_order` | Keep physically/logically isolated; no shared scheduler, database authority, or imports into ApexQuant execution path. |
| Agent framework is not durable | `SnapshotBus` is process-local latest-envelope state | Persist decisions/audits/events outside bus before relying on it across Autoscale processes. |
| “Dynamic intraday” evidence absent | No `intraday_candles` or per-trade tracking table | Do not claim 1m/5m/15m strategies or exact profit capture until data foundation exists. |
| EOD proof incomplete | Production open Phase 20 position observed overnight | Investigate replay/EOD events before modifying exit thresholds or scheduler behavior. |
| Production configuration contradicts historical reports | Current auto entry/bootstrap enabled; ₹500k capital; NIFTY active | Treat configuration as a first-class observable state in Mission Control/AI Paper Trader. |
| Cache report conflict resolved | Older report showed prod 404; current routes work | Mark earlier deployment state historical, not current. |
| Data freshness is fragmented | Server cache headers, React Query, page poll intervals, mobile offline cache | Define a shared freshness contract and show source timestamp/age/quality in every operational page. |
| Table/index parity uncertainty | Production has an extra Phase 11 table; pipeline dedupe index appears in dev index list but not observed in production list | Compare schema/index parity before new migrations. |
| UI duplication | Mission Control, Command Center, Operations Centre, Live Command Center, Phase 11, AI Paper Trader show related state | Assign each a clear role and reuse shared canonical query layer. |
| Production activation unknown | Agent process lifecycles and scheduler ownership not proven by source | Add read-only health/freshness proof before increasing automation. |

---

## 11. Revised multi-agent structure fitted to the current code

This is a revised, current-code-aware architecture. It does not create a clean-room replacement.

| Proposed role | Reuse / modify / new / defer | Exact existing files and tables | Events / UI impact | Why safest |
|---|---|---|---|---|
| Universe Coordinator | **Reuse + modify contract** | Watchlist/settings, `nifty50_company_master`, `custom_universe_master`, `custom_universe_membership_history`, `universe-custom.ts` | Publish/version universe metadata; display in Settings, Live Data Health, AI Paper Trader | Uses current universe sources and makes active selection explicit |
| Data Quality Coordinator | **Modify existing boundary** | `live_data_provider.py`, `ohlcv_cache_store.py`, `kite_ltp_overlay.py`, `pre_market_data_readiness.py`, `post_market_data_refresh.py` | New data-quality snapshot references; surface in scanner/Mission Control | Prevents LTP/daily-cache evidence from masquerading as intraday bars |
| 15-minute Context Agent | **Modify existing Market Intelligence** | `market_intelligence_agent/`, `live_scan_engine.py`, future closed-bar source | Topic/snapshot with context freshness; show in Market Intelligence/Decision pages | Reuses existing regime/breadth role, no trading authority |
| 5-minute Setup Agent | **Modify existing Strategy Agent** | `strategy_agent/agent.py`, strategy implementations | Versioned setup evidence; strategy/decision UI | Retains current strategies but makes inputs/provenance explicit |
| 1-minute Timing Agent | **New narrow advisory module** | Extend `stock_monitoring_agent/` only after bar foundation exists | Timing confirmation/rejection event and display | Prevents a new independent bot/executor |
| Entry Decision Coordinator | **Modify AI Decision contract** | `ai_decision_agent/`, future audit projection | Explainable candidate/rejection event; Trade Decisions/Mission Control chain | AI decision remains advisory; final authority stays Phase 20 |
| Risk & Sizing Gate | **Reuse Risk + Phase 20 final gate** | `risk_agent/`, `phase20_executor.py`, `paper_entry_admission.py`, `phase20_settings` | Carry evidence references and final refusal reasons | Ensures advisor cannot bypass atomic capital/duplicate/time gates |
| Paper Ledger Executor | **Reuse unchanged authority** | `phase20_executor.py`, `phase20_paper_trades`, `canonical_portfolio.py` | Existing execution/pipeline events; canonical portfolio/UI | One writer avoids duplicate trades |
| Position / Exit Coordinator | **Modify existing Phase 20 exits** | `phase20_exits.py`, scheduler, executor exit recording | Detailed hold/pending/exit audit and UI evidence | Keeps existing EOD/pending logic and avoids a new exit bot |
| EOD Safety Coordinator | **Reuse unchanged safety; improve visibility only** | `market_hours.py`, `phase20_scheduler.py`, `phase20_eod_status.py`, `phase20_store.py` | EOD/retry/force-close evidence in AI Paper Trader/Mission Control | No new competing EOD worker |
| Audit & Learning Coordinator | **New append-only projections + reuse Learning/Knowledge** | `pipeline_events.py`, replay, learning/knowledge agents; future audit stores | Entry/exit evidence links, post-market insights | Separates immutable evidence from mutable operating settings |
| Supervisor | **Reuse unchanged + new topic contracts** | `supervisor_agent/`, `AgentRegistry`, `SnapshotBus` | Freshness/dependency warnings in ops pages | Observes safety without executing trades |

### 11.1 New modules/tables required only after approval

1. `intraday_bar_store.py` and deterministic aggregation support for **closed** 1m → 5m/15m facts.
2. `paper_trade_tracking_store.py` for append-only price/high-low evidence linked to `phase20_paper_trades`.
3. `decision_audit_store.py` for entry/exit decision projections, not order commands.
4. Typed `intraday_contracts.py` snapshots/events with scan/session/universe/version/freshness references.

No module above should be created in this review phase.

---

## 12. Safe phased implementation plan

| Phase | Goal | Files / DB / API / UI | Verification gate | Rollback and publish requirement |
|---|---|---|---|---|
| 0 — Architecture lock | Accept this inventory, resolve authority/configuration conflicts | Documentation, targeted production checks only | Operator confirms canonical ledger, desired capital, active universe, automation policy, legacy-bot isolation | No production change |
| 1 — Intraday data foundation | Store quality-labeled closed bars only | New bar store/contract; no executor changes; read-only readiness/UI visibility | Deterministic aggregation, no use of future bars, stale data blocks entry candidates | Feature flag off; no new orders/trades |
| 2 — Per-trade high/low tracking | Append price observations without changing ledger economics | Tracking store, Phase 20 observation writer, read-only UI | Append-only proof, no completed trade mutation, safe retention | Disable writer; retain existing ledger |
| 3 — Exit manager/profit protection evidence | Give current exit manager reliable historical context | Modify `phase20_exits.py`; add exit-audit projection | `EXIT_PENDING`, EOD/retry and trigger-priority tests pass | Disable new audit/consumer; retain existing exits |
| 4 — UI observability | Show data, decision, exit and EOD freshness | Mission Control, AI Paper Trader, mobile labels | Browser tests show stale/pending/blocked sources truthfully | UI feature flags; no behavior change |
| 5 — Advisory 15m/5m/1m agents | Publish context/setup/timing, no execution | Extend existing MI/Strategy/Monitoring agents and bus contracts | Stale/mismatched evidence rejected; no ledger writes | Disable consumers; keep Phase 20 current flow |
| 6 — Entry Decision integration | Pass evidence references to Phase 20 final gate | AI Decision output/audit + executor input extension | Same candidate cannot bypass 15:15, risk, quality, duplicate or capital checks | Disable new reference requirement; preserve current admission |
| 7 — Risk sizing/allocation integration | Carry risk evidence through final sizing | Risk Agent and Phase 20 admission; no threshold changes without approval | Atomic admission and concurrent-entry tests | Disable new evidence consumer; no settings rewrite |
| 8 — Learning/post-market review | Learn from immutable outcomes in advisory mode | Learning/Knowledge consumers, reports/UI | No automatic settings/strategy changes; replay parity | Disable insight publishing; retain evidence |

**Production publication prerequisite for each phase:** development type/tests pass, relevant browser/API verification passes, deployment schema diff is reviewed, production route/schema is checked after publish, and rollback is tested without deleting or altering historical Phase 20 rows.

---

## 13. Open operator decisions before final architecture approval

1. What is the intended **current** paper capital: ₹100,000, ₹500,000, or another value? Production currently reports ₹500,000.
2. Should automatic paper entry/bootstrap remain enabled in production? If yes, what visible operator acknowledgement and daily guard is required?
3. Which universe is active by policy: NIFTY 50 or low-price IT/Infra/Bank? Production currently reports NIFTY 50.
4. Is LTIM removed from the active universe and historical data preserved? Verify against `nifty50_company_master` and active config before deciding.
5. Which intraday candle provider is authorized, including entitlement, retention, correction, and outage behavior?
6. What bar intervals/retention are required for 1m facts and 5m/15m aggregates?
7. What profit-lock/trailing/partial-exit behavior is desired, especially when quantity is one?
8. Which VWAP/ORB/EMA/momentum strategies are eligible, and are they only advisory until paper shadow validation succeeds?
9. What time stops and late-entry gates are desired beyond the existing 15:15/15:20/15:30 safety contract?
10. What evidence of scheduler and EOD success is required before automatic entry can continue after an overnight open position is found?
11. Which legacy Phase 11/event-sourced/`intraday-trading-bot` modules are to be retired, quarantined, or explicitly bridged?
12. Should Autoscale remain the deployment model for minute-level observation, or is an always-on worker/VM required? This is a product/operations decision, not an implementation assumption.
13. What is the permanent future boundary for live orders? This report recommends no live-order integration; existing legacy order-capable code must remain isolated.

---

## 14. Required verification before changing trading logic

1. Query production `phase20_paper_trades` and replay the observed overnight-open trade to determine whether it is an EOD exception, pending exit, or genuine closure failure.
2. Compare dev/prod schema and indexes, especially `pipeline_events` dedupe behavior and the extra production `phase11_capital_topups` table.
3. Trace all production writers to `phase20_paper_trades`, `paper_trades`, `experimental_paper_trades`, `portfolio_events`, and `portfolio_snapshots`.
4. Capture actual agent-framework list/detail/freshness responses during a production market session.
5. Capture scheduler health and scan history across 15:15, 15:20 and 15:30 IST.
6. Browser-test Mission Control, AI Paper Trader, scanner, portfolio and mobile views against live stale/pending/open-position conditions.
7. Prove whether all closed Phase 20 rows are immutable or add an approved storage-level policy before relying on them as append-only audit evidence.
8. Confirm production build ID visually and through the compiled deployed asset before marking build identity fully verified.

---

## 15. Final confirmation

- This report was created after reviewing the available architecture notes, phase reports, task documents, backend/frontend source, route registrations, agent/bot modules, database schema, tests, Git history, deployment metadata, and read-only production API responses.
- Where evidence could not prove current behavior, the report uses **UNKNOWN** instead of assuming the earlier documentation is current.
- No application code was changed.
- No database migration or table was created.
- No trading threshold, active setting, workflow, secret, or environment variable was changed.
- No live order capability was enabled.
- No broker order API was called.
- The only new deliverable from this master inventory request is `APEXQUANT_FULL_SYSTEM_PHASE_AGENT_UI_ARCHITECTURE_INVENTORY.md`.