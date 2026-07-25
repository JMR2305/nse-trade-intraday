# Phase 2A — ApexQuant AI System Dependency Graph

## Overview

This Mermaid flowchart shows the complete data flow from market ingestion through
portfolio output and audit. Each node is one of the 15 audited subsystems; each
edge is labelled with the data object that crosses it.

## Full Data-Flow Graph

```mermaid
flowchart TD
    %% ── External inputs ────────────────────────────────────────────────
    YF["Yahoo Finance\n(yfinance 1.5.1)"]
    KT["Zerodha Kite\n(session required)"]
    DB[("PostgreSQL\n(DATABASE_URL)")]

    %% ── Subsystem nodes ────────────────────────────────────────────────
    MD["① Market Data\n✅ HEALTHY\nRC-6 live_data_provider\nyfinance bulk fetch"]
    SC["② Scanner\n✅ HEALTHY\nlive_scan_engine\nscan_state_store"]
    SE["③ Signal Engine\n✅ HEALTHY\nsignal_engine\nsignals_store"]
    AI["④ AI Advisory\n✅ HEALTHY\nphase15 · copilot_engine\nai_decision (read-only)"]
    RE["⑤ Risk Engine\n⚠️ DEGRADED\nphase11_risk · phase15_risk_gate\nPortfolioConfig (pydantic MISSING)"]
    PE["⑥ Paper Execution\n✅ HEALTHY\nRC-7 paper_trader\nphase20_executor"]
    PF["⑦ Portfolio\n✅ HEALTHY\nportfolio_store · portfolio_snapshot\nPaper mode only"]
    PL["⑧ P&L\n✅ HEALTHY\npnl_history · drawdown_pct\nrealised + unrealised"]
    TJ["⑨ Trade Journal\n✅ HEALTHY\npaper_trades table\ntrade_intelligence"]
    AL["⑩ Audit Logs\n✅ HEALTHY\nphase13_audit\nengine attribution"]
    RV["⑪ Recovery\n✅ HEALTHY\nhealthz · health/live\nhealth/ready"]
    MB["⑫ Mobile App\n⚠️ DEGRADED\nExpo React Native\napiConfig.ts (Phase 1A)"]
    DB2["⑬ Dashboard\n✅ HEALTHY\nVite · React Query\napiConfig.ts (Phase 1A)"]
    API["⑭ API Server\n✅ HEALTHY\nExpress · port 8080\n10 route files"]
    DATABASE["⑮ Database\n✅ HEALTHY\nPostgreSQL\n6/6 tables present"]

    %% ── Data flow edges ────────────────────────────────────────────────

    %% Market ingestion
    YF -->|"OHLCV prices\n(50 NSE symbols)"| MD
    KT -.->|"Live quotes\n(session required)"| MD

    %% Scan pipeline
    MD -->|"ScanSnapshot\n(scan_id, snapshot_ts,\nOHLCV per symbol)"| SC
    SC -->|"ScanMeta + ScanSnapshot\n(48/50 symbols)"| SE
    SC <-->|"scan_state row\n(durable lock)"| DATABASE

    %% Signal → AI
    SE -->|"Signal[]\n(symbol, signal_type,\nconfidence, price)"| AI
    SE -->|"signals_cache row"| DATABASE

    %% Risk gate
    AI -->|"AIDecision[]\n(decision, confidence,\nregime, plain_english)"| RE
    RE -->|"RiskDecision\n(allowed, risk_msg,\nlimit checks)"| PE

    %% Paper execution
    PE -->|"PaperOrder\n(symbol, qty, fill_price,\nstrategy_id, stop_loss,\ntarget, evidence)"| PF
    PE <-->|"phase20_paper_trades row\n(OPEN/CLOSED)"| DATABASE
    PE -->|"paper_portfolio row\n(cash, positions)"| PF

    %% Portfolio → P&L
    PF -->|"PortfolioSnapshot\n(equity, cash, positions,\ninitial_capital)"| PL
    PF <-->|"paper_portfolio row"| DATABASE

    %% P&L → Journal
    PL -->|"RealizedPnL\n(pnl_pct, exit_type,\nholding_days)"| TJ
    TJ <-->|"paper_trades rows\n(append-only)"| DATABASE

    %% Journal → Audit
    TJ -->|"TradeRecord\n(FIFO-matched,\nentry+exit metadata)"| AL
    AL -->|"AuditReport\n(phase, label, mode)"| API

    %% Recovery monitors
    RV -->|"HealthCheck\n(uptime, python_runtime,\nscan_cache)"| API

    %% API serves UI clients
    API -->|"JSON responses\n(all endpoints)"| DB2
    API -->|"JSON responses\n(all endpoints)"| MB

    %% SSE stream
    SC -->|"SSE events\n(scan_complete,\nportfolio_update)"| API
    API -->|"EventStream\n(text/event-stream)"| DB2

    %% DB connectivity
    DATABASE <-->|"paper_portfolio\npaper_trades\nsignals_cache\nscan_state / scan_lock\nphase20_paper_trades\nsignal_snapshots"| PF
    DATABASE <-->|"signals_cache row"| SE

    %% ── Style ──────────────────────────────────────────────────────────
    classDef healthy  fill:#16a34a,color:#fff,stroke:#15803d
    classDef degraded fill:#d97706,color:#fff,stroke:#b45309
    classDef external fill:#6366f1,color:#fff,stroke:#4338ca
    classDef storage  fill:#0f172a,color:#fff,stroke:#1e293b

    class MD,SC,SE,AI,PE,PF,PL,TJ,AL,RV,DB2,API,DATABASE healthy
    class RE,MB degraded
    class YF,KT external
    class DB storage
```

## Simplified Critical Path

The minimal path from market data to a completed paper trade:

```mermaid
flowchart LR
    A["Yahoo Finance\n(yfinance)"] -->|OHLCV| B["Market Data\n①"]
    B -->|ScanSnapshot| C["Scanner\n②"]
    C -->|Signal| D["Signal Engine\n③"]
    D -->|AIDecision| E["AI Advisory\n④"]
    E -->|RiskDecision| F["Risk Engine\n⑤"]
    F -->|PaperOrder| G["Paper Execution\n⑥"]
    G -->|Position| H["Portfolio\n⑦"]
    H -->|PnL| I["P&L\n⑧"]
    I -->|TradeRecord| J["Trade Journal\n⑨"]
    J -->|AuditEntry| K["Audit Logs\n⑩"]
```

## Data Objects Glossary

| Object | Producer | Consumer | Description |
|--------|----------|----------|-------------|
| `ScanSnapshot` | Market Data | Scanner | Full OHLCV + indicators per symbol, stamped with `scan_id` and `snapshot_ts` |
| `ScanMeta` | Scanner | Signal Engine / DB | Lightweight: scan_id, status, coverage, missing symbols |
| `Signal[]` | Signal Engine | AI Advisory | `{symbol, signal_type, confidence, price, reasons[]}` — pure observation, no execution advice |
| `AIDecision[]` | AI Advisory | Risk Engine | `{stock, decision, confidence, regime, target, stop_loss, rr_ratio, plain_english}` — advisory_only always true |
| `RiskDecision` | Risk Engine | Paper Execution | `{allowed: bool, risk_msg}` — enforces position limits, daily loss, sector exposure |
| `PaperOrder` | Paper Execution | Portfolio | `{trade_id, symbol, qty, fill_price, stop_loss, target, evidence, status: OPEN}` |
| `PortfolioSnapshot` | Portfolio | P&L / API | `{equity, cash, open_positions[], realised_pnl_today, unrealised_pnl, drawdown_pct}` |
| `RealizedPnL` | P&L | Trade Journal | `{pnl, pnl_pct, exit_type, holding_days}` stamped at SELL |
| `TradeRecord` | Trade Journal | Audit Logs | Full FIFO-matched round-trip with entry + exit metadata |
| `AuditReport` | Audit Logs | API | Phase 13 engine attribution, PAPER label, mode |
| `HealthCheck` | Recovery | API | `{status, uptime_s, python_runtime, scan_cache}` |
| `SSEEvent` | Scanner / Portfolio | Dashboard | `{type: scan_complete\|portfolio_update, payload}` |

## Subsystem Status Summary

| # | Subsystem | Status | Key Module(s) |
|---|-----------|--------|---------------|
| 1 | Market Data | ✅ HEALTHY | `live_data_provider.py`, `market_data.py`, yfinance |
| 2 | Scanner | ✅ HEALTHY | `live_scan_engine.py`, `scan_state_store.py` |
| 3 | Signal Engine | ✅ HEALTHY | `signal_engine.py`, `signals_store.py` |
| 4 | AI Advisory | ✅ HEALTHY | `phase15_*.py`, `copilot_engine.py`, `ai_decision.py` |
| 5 | Risk Engine | ⚠️ DEGRADED | `phase11_risk.py`, `phase15_risk_gate.py`, `PortfolioConfig` |
| 6 | Paper Execution | ✅ HEALTHY | `paper_trader.py`, `phase20_executor.py` |
| 7 | Portfolio | ✅ HEALTHY | `portfolio_store.py`, `portfolio_snapshot.py` |
| 8 | P&L | ✅ HEALTHY | `portfolio_snapshot.py` (drawdown, pnl fields) |
| 9 | Trade Journal | ✅ HEALTHY | `paper_trades` table, `trade_intelligence.py` |
| 10 | Audit Logs | ✅ HEALTHY | `phase13_audit.py` |
| 11 | Recovery | ✅ HEALTHY | `health.ts` (healthz, health/live, health/ready) |
| 12 | Mobile App | ⚠️ DEGRADED | Expo workflow (port conflict), `lib/apiConfig.ts` |
| 13 | Dashboard | ✅ HEALTHY | Vite dev server, `src/lib/apiConfig.ts` |
| 14 | API Server | ✅ HEALTHY | `app.ts`, 10 route files, port 8080 |
| 15 | Database | ✅ HEALTHY | PostgreSQL, psycopg2, 6/6 tables present |
