# INTRADAY MASTER ARCHITECTURE

## Project Identity

| Field | Value |
|---|---|
| **Project Name** | NSE Intraday Paper-Trading Platform (ApexQuant) |
| **Repository Root** | `/` (workspace root) |
| **Branch** | `phase4a-controlled-paper-entry-framework-disabled` |
| **Commit** | `891288296f70ec52a917b46b0d906d4230153464` |
| **Audit Date** | 2026-08-23 (Asia/Kolkata) |
| **Auditor** | Static source inspection (no runtime access) |

---

## Artifact Inventory

| Artifact | Kind | Path | Preview |
|---|---|---|---|
| API Server | api | `artifacts/api-server` | `/api` |
| NSE Trading Dashboard | web | `artifacts/trading-dashboard` | `/trading-dashboard/` |
| NSE Trading Mobile | mobile | `artifacts/trading-mobile` | `/trading-mobile/` |
| Intraday Trade Hub | web | `artifacts/trading-document-hub` | `/trading-document-hub/` |
| NSE Trading Platform Video | video | `artifacts/project-video` | `/project-video/` |
| Canvas | design | `artifacts/mockup-sandbox` | `/__mockup` |

---

## Derived Counts (Source-Verified)

| Metric | Count | Source |
|---|---|---|
| **Web dashboard routes** (App.tsx `<Route path=...>`) | 118 static + 1 conditional (`/advisory` guarded by `isAdvisoryUiEnabled()`) = **119 total** | `artifacts/trading-dashboard/src/App.tsx` |
| **Mobile tab screens** | **7** (index/Dashboard, health/Health, signals/Signals, watchlist/Watchlist, positions/Positions, alerts/Alerts, ai-ops/Pipeline) | `artifacts/trading-mobile/app/(tabs)/` |
| **API router method declarations** (non-test route files) | **770** | `artifacts/api-server/src/routes/*.ts` (excluding *.test.ts files) |
| **API route files** (non-test) | **70** | `artifacts/api-server/src/routes/` |
| **Unique code-defined SQLite/Postgres table names** | **77** (excluding runtime-named `{TABLE}` placeholders) | `artifacts/api-server/src/python/*.py` (non-test) |
| **Page/field lineage rows** (one primary row for every route/tab plus source-proven subview rows) | **166** | `INTRADAY_PAGE_DATA_LINEAGE.csv` |
| **Explicit displayed-field lineage rows** (excluding page-summary and `UNKNOWN` rows) | **164** | `INTRADAY_PAGE_DATA_LINEAGE.csv`, `Displayed field` column |
| **API inventory rows** (one row per concrete router declaration) | **770** | `INTRADAY_API_MAP.csv` |
| **Data quality findings** | **39** | `INTRADAY_DATA_QUALITY_AUDIT.md` |

**⚠️ Database Runtime-Verification Caveat:** The 77 table count is code-defined (from `CREATE TABLE IF NOT EXISTS` statements). No database connection was made. Actual tables present in any live PostgreSQL or SQLite database cannot be confirmed from static analysis alone. PostgreSQL tables exist only when `DATABASE_URL` is set and the relevant Python module has executed its schema initialisation at least once.

---

## Reference Documents

| Document | Description |
|---|---|
| `INTRADAY_PAGE_DATA_LINEAGE.csv` | Complete inventory of all 119 web routes + 7 mobile tab screens: component, title, purpose, navigation, hooks, refresh interval, data classification |
| `INTRADAY_API_MAP.csv` | All 770 concrete router method declarations: endpoint, HTTP method, route file, handler line, Python handler / dependency, frontend state key |
| `INTRADAY_DATABASE_MAP.md` | Code-defined Postgres + SQLite table inventory with source file references, key columns, and runtime-verification caveat |
| `INTRADAY_BUSINESS_LOGIC_MAP.md` | End-to-end business logic for all 16 domains: ingestion, pre-open, universe, MTF, signals, risk, paper execution, positions, exits, P&L, alerts, replay, analytics, refresh, scheduler, external systems |
| `INTRADAY_DATA_QUALITY_AUDIT.md` | 39 source-evidenced findings across 9 categories: seeded/demo, hardcoded, stale, duplicated, unclear/dead, legacy paths, impossible-value, refresh, and error handling |

---

## High-Level Technology Stack

| Layer | Technology |
|---|---|
| API Server | Node.js + Express (TypeScript), port 5000 |
| Business Logic | Python 3 (subprocess via `spawn`), 744 non-test modules |
| Databases | PostgreSQL (`DATABASE_URL`) + SQLite (`trade_intelligence.db`) |
| Frontend (Web) | React 18 + Vite + TypeScript, wouter router, TanStack Query |
| Frontend (Mobile) | React Native + Expo Router, Expo tabs |
| Broker Integration | Zerodha Kite Connect API (OAuth2) |
| Market Data Fallback | yfinance (Python) |
| Push Notifications | Expo Push Notification Service |
| Real-Time Transport | Server-Sent Events (SSE) `/stream` endpoint |
| Agent Framework | 12-agent pipeline (supervisor, market_data, research, market_intelligence, monitoring, strategy, risk, ai_decision, execution, learning, knowledge, operations) |

---

## Mermaid Architecture Diagrams

### Diagram A — High-Level System Overview

```mermaid
graph TB
    subgraph "Clients"
        WEB["Web Dashboard\n119 routes\nReact+Vite"]
        MOB["Mobile App\n7 tabs\nReact Native+Expo"]
    end
    subgraph "API Server (Node.js)"
        ROUTES["70 Route Files\n770 endpoints"]
        SCHED["Scan Scheduler\n1-min tick"]
        SSE["SSE Stream\n/stream"]
        PUSH["Push Notifier\nExpo FCM/APNs"]
    end
    subgraph "Python Business Logic"
        MAIN["main.py\ndispatch hub"]
        SCAN["live_scan_engine\nOHLCV+Signals"]
        RISK["Risk Gate\nPhase15"]
        EXEC["Paper Executor\nPhase20"]
        AGENT["12-Agent\nPipeline"]
    end
    subgraph "Storage"
        PG[("PostgreSQL\n~50 tables")]
        SQ[("SQLite\ntrade_intelligence.db")]
        JSON["JSON Flat Files\n~20 caches"]
    end
    subgraph "External"
        KITE["Zerodha Kite\nOAuth2+REST"]
        YFIN["yfinance\nFallback"]
        NSE["NSE Pre-Open\nData"]
    end

    WEB -->|HTTP REST| ROUTES
    MOB -->|HTTP REST| ROUTES
    WEB <-->|SSE| SSE
    ROUTES --> MAIN
    SCHED --> MAIN
    MAIN --> SCAN
    MAIN --> RISK
    MAIN --> EXEC
    MAIN --> AGENT
    SCAN --> PG
    EXEC --> PG
    EXEC --> SQ
    SCAN --> JSON
    SCAN --> KITE
    SCAN --> YFIN
    SCHED --> PUSH
    NSE --> SCAN
```

### Diagram B — End-to-End Trade Flow

```mermaid
sequenceDiagram
    participant SCHED as Scan Scheduler
    participant OHLCV as OHLCV Cache
    participant SCAN as Signal Engine
    participant AI as AI Decision
    participant RISK as Risk Gate (Ph15)
    participant EXEC as Paper Executor (Ph20)
    participant DB as PostgreSQL
    participant SSE as SSE Stream
    participant UI as Dashboard

    SCHED->>OHLCV: Check cache freshness
    OHLCV-->>SCHED: Cache OK / Backfill needed
    SCHED->>SCAN: Trigger scheduled_scan_tick
    SCAN->>SCAN: Load active universe symbols
    SCAN->>OHLCV: Fetch OHLCV per symbol
    SCAN->>SCAN: Compute trade quality (4 TF)
    SCAN->>AI: Request AI decision
    AI->>AI: Calibration + TF alignment (≥3/4)
    AI->>RISK: Pre-trade risk gate check
    RISK-->>AI: PASS / BLOCK
    AI-->>SCAN: Decision + confidence
    SCAN->>DB: Write signals_cache
    SCAN-->>SCHED: Scan complete
    SCHED->>EXEC: Run exit management
    EXEC->>DB: Update phase20_paper_trades
    SCHED->>SSE: Emit scan-complete event
    SSE->>UI: Push update notification
    UI->>UI: React Query invalidate/refetch
```

### Diagram C — Frontend / Backend Route Mapping

```mermaid
graph LR
    subgraph "Web App Routes (selected)"
        R1["/ → TradeDecisions"]
        R2["/signals → Signals"]
        R3["/broker-execution → BrokerExecution"]
        R4["/risk → RiskManagement"]
        R5["/paper-trading-portfolio → Phase11Portfolio"]
        R6["/replay → ReplayModePage"]
        R7["/agent-operations → AgentOperations"]
    end
    subgraph "API Endpoints"
        A1["GET /ai-decisions\n GET /decision-layer/ai-decision/*"]
        A2["GET /signals\nGET /live-data/scan"]
        A3["GET /kite/status\nGET /broker/reconciliation"]
        A4["GET /risk-validation/*\nGET /phase20/circuit-breaker"]
        A5["GET /portfolio/open-positions\nGET /phase20/positions"]
        A6["GET /replay/sessions/*"]
        A7["GET /agent-framework/agents\nGET /agent-framework/*"]
    end

    R1 --> A1
    R2 --> A2
    R3 --> A3
    R4 --> A4
    R5 --> A5
    R6 --> A6
    R7 --> A7
```

### Diagram D — Database Architecture

```mermaid
graph TB
    subgraph "PostgreSQL (DATABASE_URL)"
        PG1["signals_cache\nsignal_snapshots"]
        PG2["phase20_paper_trades\nphase20_eod_outcomes\nphase20_settings\nphase20_kv\nphase20_scan_runs"]
        PG3["paper_portfolio\npaper_trades"]
        PG4["scan_state\nscan_lock"]
        PG5["signal_validation_*\n(10 tables)"]
        PG6["preopen_*\n(11 tables)"]
        PG7["broker_reconciliation_*"]
        PG8["custom_universe_*\nnifty50_company_master\ndaily_ohlcv_*"]
        PG9["phase22_evidence\nphase24_*\nphase26_*"]
        PG10["portfolio_config_overrides\npipeline_events\nportfolio_decisions"]
    end
    subgraph "SQLite (trade_intelligence.db)"
        SQ1["trade_intelligence\nhistorical_knowledge_trades"]
        SQ2["hypotheses\nmodel_versions\nproposed_adjustments"]
        SQ3["prediction_snapshots\ntrade_evaluations"]
        SQ4["feature_importance_snapshots\nfeature_weights"]
        SQ5["sim_scenarios\nsim_runs"]
        SQ6["validation_v2_runs\nvalidation_v2_*"]
        SQ7["alert_deliveries\nsession_archives"]
    end
    subgraph "JSON Files (Python dir)"
        J1["signals_cache.json"]
        J2["market_context_cache.json"]
        J3["intelligence_cache.json"]
        J4["calibration_state.json"]
        J5["strategy_weights.json"]
    end
```

### Diagram E — Scheduler & Event Flow

```mermaid
flowchart TD
    START["Node.js setInterval\n1-minute tick"]
    GATE{"OHLCV cold-start\npending?"}
    CHECK["Python: scheduled_scan_tick\nCheck market hours (IST)\nCheck scan interval setting"]
    LOCK["Acquire scan_lock\n(distributed Postgres lock)"]
    SCAN["live_scan_engine.py\nLoad universe → OHLCV → Signals → AI → Risk"]
    EXIT["Paper exit management\nphase20_executor.py"]
    ENTRY{"auto_paper_entries\nEnabled AND Phase22 gate?"}
    BUY["Execute auto paper entries"]
    NOTIFY["dispatchSignalPushNotifications\nprocessPushDeliveryQueue"]
    SSE2["Emit SSE events\nto connected clients"]

    START --> GATE
    GATE -- Yes --> START
    GATE -- No --> CHECK
    CHECK -- Not due or market closed --> START
    CHECK -- Due --> LOCK
    LOCK --> SCAN
    SCAN --> EXIT
    EXIT --> ENTRY
    ENTRY -- Yes --> BUY
    ENTRY -- No --> NOTIFY
    BUY --> NOTIFY
    NOTIFY --> SSE2
    SSE2 --> START
```

### Diagram F — Pre-Open Intelligence Flow

```mermaid
sequenceDiagram
    participant NSE as NSE Pre-Market
    participant PREOPEN as preopen_db.py
    participant RANK as Ranking Engine
    participant DB as PostgreSQL
    participant API as /preopen/* routes
    participant UI as PreOpenIntelligence page

    Note over NSE,UI: 09:00–09:15 IST Window
    NSE->>PREOPEN: Pre-open prices + volumes
    PREOPEN->>PREOPEN: Gap analysis + momentum
    PREOPEN->>RANK: Score symbols
    RANK->>DB: Write preopen_rankings\npreopen_snapshots
    Note over DB,UI: Market opens 09:15
    DB->>API: Serve preopen/rankings
    API->>UI: Top symbols by score
    Note over DB,UI: Post-market validation
    DB->>DB: Compare predictions vs actuals
    DB->>DB: Write preopen_candidate_outcomes\npreopen_daily_reports
```

### Diagram G — Trading Session Flow

```mermaid
stateDiagram-v2
    [*] --> PRE_OPEN: 09:00 IST
    PRE_OPEN --> OPEN: 09:15 IST
    OPEN --> SCAN_TICK: Every 1–15 min (configurable)
    SCAN_TICK --> SIGNALS_GENERATED: Scan completes
    SIGNALS_GENERATED --> RISK_CHECK: Pre-trade gate
    RISK_CHECK --> ENTRY_BLOCKED: Kill switch or risk limit
    RISK_CHECK --> PAPER_ENTRY: All gates pass + auto_entries on
    PAPER_ENTRY --> POSITION_OPEN
    POSITION_OPEN --> EXIT_CHECK: Next scan tick
    EXIT_CHECK --> STOP_LOSS_HIT: Price ≤ stop_loss
    EXIT_CHECK --> TARGET_HIT: Price ≥ target
    EXIT_CHECK --> STILL_OPEN: Neither
    STOP_LOSS_HIT --> CLOSED
    TARGET_HIT --> CLOSED
    OPEN --> EOD: 15:30 IST
    EOD --> EOD_EXIT: All open positions
    EOD_EXIT --> CLOSED
    CLOSED --> [*]
```

### Diagram H — Order / Paper Trade Lifecycle

```mermaid
stateDiagram-v2
    [*] --> SIGNAL_GENERATED: Signal score ≥ 60
    SIGNAL_GENERATED --> AI_DECISION: Confidence + TF alignment
    AI_DECISION --> RISK_GATE: Pre-trade risk check
    RISK_GATE --> BLOCKED: Kill switch / limits exceeded
    RISK_GATE --> PAPER_PENDING: All checks pass
    PAPER_PENDING --> PAPER_OPEN: execute_buy() writes phase20_paper_trades
    PAPER_OPEN --> PAPER_CLOSED: Exit trigger
    PAPER_CLOSED --> PNL_RECORDED: phase20_eod_outcomes
    PNL_RECORDED --> KNOWLEDGE_BASE: historical_knowledge_builder
    KNOWLEDGE_BASE --> [*]
```

### Diagram I — Portfolio & Risk Flow

```mermaid
graph LR
    subgraph "Inputs"
        POS["Open Positions\nphase20_paper_trades"]
        CFG["Portfolio Config\nportfolio_config_overrides"]
        MKT["Market Data\nKite / yfinance"]
    end
    subgraph "Risk Engine"
        SECTOR["Sector Exposure\nrv_sector"]
        CORR["Correlation\nrv_correlation"]
        STRESS["Stress Test\nrv_stress"]
        VAR["VaR / Tail\nrv_tail"]
        DRIFT["Regime Drift\nrv_drift"]
    end
    subgraph "Controls"
        KILL["Kill Switch\nphase20_kv"]
        CB["Circuit Breaker\nphase20_kv"]
        LIMITS["Capital Limits\nconfig.py"]
    end
    subgraph "Outputs"
        ALERT["Risk Alerts\nrv_alerts"]
        REPORT["Risk Decision Report\nphase15_risk_decision_report"]
        AUDIT["Audit Log\nphase15_audit"]
    end

    POS --> SECTOR
    POS --> CORR
    MKT --> STRESS
    MKT --> VAR
    CFG --> LIMITS
    SECTOR --> ALERT
    VAR --> ALERT
    LIMITS --> KILL
    ALERT --> REPORT
    REPORT --> AUDIT
    CB --> KILL
```

### Diagram J — Replay & Research Flow

```mermaid
graph TB
    subgraph "Session Capture"
        SCAN2["Completed Scan Session"]
        ARC["session_archives\n(Postgres)"]
        SNAP["signal_snapshots\n(Postgres)"]
    end
    subgraph "Replay Engine"
        RE["replay_engine.py\nStep-through reconstruction"]
        INT["/replay/sessions/:id/integrity\nVerification"]
    end
    subgraph "Research"
        BT["backtesting_engine.py"]
        WF["walk-forward\nvalidation_v2_engine"]
        SIM["simulation_lab.py\nMonte-Carlo"]
        HYP["hypothesis_engine.py"]
    end
    subgraph "Knowledge Extraction"
        HK["historical_knowledge_builder.py\nhistorical_knowledge_trades"]
        PI["predictive_intelligence.py"]
        ROOT["root_cause_engine.py\nfeature weights"]
    end

    SCAN2 --> ARC
    SCAN2 --> SNAP
    ARC --> RE
    RE --> INT
    ARC --> BT
    BT --> WF
    WF --> SIM
    SIM --> HYP
    HK --> PI
    PI --> ROOT
    ROOT --> HK
```

### Diagram K — Navigation (Web & Mobile)

```mermaid
graph LR
    subgraph "Web App (AppLayout)"
        SB["Sidebar Navigation"]
        SB --> GROUP1["Trading\n/ /trades /signals\n/broker-execution /risk"]
        SB --> GROUP2["Portfolio\n/portfolio-manager\n/portfolio-live\n/portfolio-performance"]
        SB --> GROUP3["Intelligence\n/market /preopen-intelligence\n/market-intelligence\n/macro-intelligence /event-intelligence"]
        SB --> GROUP4["AI & Agents\n/agent-operations /ai-decision\n/ai-copilot /ai-operations-centre"]
        SB --> GROUP5["Research\n/backtest /strategy-lab\n/simulation-lab /research-lab\n/walk-forward /experiments"]
        SB --> GROUP6["Phase 11 Paper Trading\n/paper-trading-summary\n/paper-trading-portfolio\n/paper-trading-recommendations"]
        SB --> GROUP7["Operations\n/operations-center /security-center\n/command-center /observability"]
        SB --> GROUP8["Learning\n/learning /learning-insights\n/agent-learning /agent-knowledge"]
        SB --> GROUP9["Analytics\n/performance-analytics\n/paper-analytics /data-quality"]
    end
    subgraph "Mobile App (Tab Bar)"
        TB["Tab Bar"]
        TB --> T1["Dashboard (index)\nPortfolio + Status"]
        TB --> T2["Health\nSystem monitors"]
        TB --> T3["Signals\nScan + Recommendations"]
        TB --> T4["Watchlist\nSymbol management"]
        TB --> T5["Positions\nOpen trades + P&L"]
        TB --> T6["Alerts\nNotifications"]
        TB --> T7["Pipeline\nAgent status"]
    end
```

### Diagram L — Cross-Page Data Dependencies

```mermaid
graph LR
    subgraph "Data Sources"
        S1["signals_cache (Postgres)"]
        S2["phase20_paper_trades (Postgres)"]
        S3["scan_state (Postgres)"]
        S4["phase20_kv / settings (Postgres)"]
        S5["Kite API"]
        S6["risk-validation (Python)"]
    end
    subgraph "Primary Consumers"
        P1["/signals\n/market-scanner\nmobile-signals"]
        P2["/portfolio-manager\n/portfolio-live\nmobile-positions\nmobile-dashboard"]
        P3["/live-data-health\nmobile-health\n/automation"]
        P4["/settings\n/risk\n/operator-status\nmobile-health"]
        P5["/broker-execution\nmobile-health"]
        P6["/risk\n/portfolio-risk\n/risk-validation"]
    end

    S1 --> P1
    S2 --> P2
    S3 --> P3
    S4 --> P4
    S5 --> P5
    S6 --> P6
    S1 -.->|"also consumed by"| P2
    S2 -.->|"also consumed by"| P6
```

---

## Audit Methodology & UNKNOWN Boundaries

### Methodology
1. **Route enumeration:** `App.tsx` parsed for all `<Route path=...>` declarations (deterministic grep).
2. **Mobile tabs:** `(tabs)/` directory listed; `_layout.tsx` inspected for tab names and screen components.
3. **API count:** `grep -cE 'router\.(get|post|put|patch|delete)\('` run across all non-test `.ts` files in routes/; sum verified as 770.
4. **Database tables:** `grep -rn "CREATE TABLE IF NOT EXISTS"` across non-test Python files; unique names deduplicated.
5. **Business logic:** Source files traced via route handlers → Python dispatch → module imports.
6. **Data quality:** Pattern search for seeding, hardcoded constants, stale-data patterns, error handling.

### UNKNOWN Boundaries
- **Runtime state:** No database was queried; no live API calls were made.
- **`collaborationEngine.ts` and `autonomousOps.ts`:** Zero router declarations found; internal logic UNKNOWN.
- **`trading.db`:** SQLite file exists but source origin UNKNOWN (no matching CREATE TABLE in source).
- **Custom universe table name:** Runtime-configured via f-string; static analysis cannot resolve.
- **Phase 16 / 17 / 18 UI consumers:** Routes registered but no corresponding App.tsx page imports found.
- **Exact content of `validation_runs/wf_result.json` and experiment JSON files:** Not read; may contain stale data.
- **Stuck scan-lock TTL:** Exact value in `scan_state_store.py` not fully read.
- **Advisory UI flag value:** `isAdvisoryUiEnabled()` is a runtime function; whether `/advisory` route is active in production is UNKNOWN.
