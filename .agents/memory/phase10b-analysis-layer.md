---
name: Phase 10B Analysis Layer
description: 4 read-only advisory agents — MarketIntelligenceAgent, StockMonitoringAgent, StrategyAgent, RiskAgent; architecture, key pitfalls, test results
---

# Phase 10B — Analysis Layer

## Architecture
- 4 agents inherit `BaseAgent` from `agent_framework/base_agent.py`
- All inter-agent data flows via `SnapshotBus.publish/latest` only (no direct calls)
- Topics: `market_intelligence`, `stock_monitoring`, `strategy`, `risk`
- Aggregation layer: `analysis_layer/shared_services.py` → 3 endpoints (summary, timeline, performance)
- Routes: `artifacts/api-server/src/routes/analysisAgents.ts` — 12 GET routes mounted in `routes/index.ts`

## Key Design Rules
- **advisory_only: True** and **read_only: True** must appear in every snapshot payload
- **RiskAgent**: `never_modifies_portfolio: True` — never calls any write method
- **StrategyAgent**: 0–100 scores only; no BUY/SELL anywhere in any result
- **EventDetector**: 12 event types; returns `advisory_only: True` in every event dict
- **SmartPriorityEngine**: P1 < P2 < P3 < P4 < P5 in `EVAL_FREQUENCY` (P1=60s, P5=900s)

## Feature Flags (all default true)
- `MARKET_INTELLIGENCE_AGENT_ENABLED`
- `STOCK_MONITORING_AGENT_ENABLED`
- `STRATEGY_AGENT_ENABLED`
- `RISK_AGENT_ENABLED`

## StrategyRegistry (pluggable)
6 strategies in `strategy_agent/agent.py`: Breakout, VWAP Pullback, Opening Range Breakout,
Momentum, Mean Reversion, Gap Strategy. Register more via `registry.register(strategy)`.

## DataTable column convention
Use `label` (not `header`) in `TableColumn<Record<string,unknown>>` columns.
For type-safe renders, use `Number(v)`, `String(v)` casts since render receives `unknown`.

## Test Results
85/85 passing in `test_analysis_agents.py` (42s).

## **Why:**
Phase 10B provides the analytical intelligence layer on top of Phase 10A infrastructure.
Strict READ-ONLY/ADVISORY-ONLY prevents any accidental order placement from analysis logic.
