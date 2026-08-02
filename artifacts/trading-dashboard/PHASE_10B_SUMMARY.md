# Phase 10B — Analysis Layer

**ApexQuant AI · NSE Intraday Trading Platform**
**Status: COMPLETE · READ-ONLY · ADVISORY-ONLY**
**Date: 2026-08-02**

---

## Architecture Overview

```
                         ┌──────────────────────────────────────┐
                         │         Phase 10B Analysis Layer      │
                         │    (4 agents — READ-ONLY / ADVISORY)  │
                         └────────────────┬─────────────────────┘
                                          │ SnapshotBus
                   ┌──────────────────────┼───────────────────────┐
                   ▼                      ▼                        ▼
        ┌──────────────────┐   ┌──────────────────┐   ┌─────────────────────┐
        │ Market Intell.   │   │ Stock Monitoring │   │  Strategy Agent     │
        │ Agent            │   │ Agent            │   │  (6 strategies)     │
        │ (regime/sectors/ │   │ (P1-P5 priority/ │   │  Pluggable registry │
        │  breadth/volat.) │   │  12 event types) │   │  Score 0-100 only   │
        └────────┬─────────┘   └────────┬─────────┘   └──────────┬──────────┘
                 │                       │                          │
                 └───────────────────────┴──────────────────────────┘
                                         │ reads from bus
                               ┌─────────▼──────────┐
                               │    Risk Agent        │
                               │ (9 risk dimensions) │
                               │ never writes         │
                               └─────────────────────┘
```

## Agent Dependency Diagram

```
market-data-agent (Phase 10A)
    └─► market-intelligence-agent   [topic: market_intelligence]
    └─► stock-monitoring-agent      [topic: stock_monitoring]
                                        ├─► SmartPriorityEngine (P1-P5)
                                        └─► EventDetector (12 types)

market-intelligence-agent
stock-monitoring-agent
    └─► strategy-agent              [topic: strategy]
                                        └─► StrategyRegistry
                                            ├── BreakoutStrategy
                                            ├── VWAPPullbackStrategy
                                            ├── ORBStrategy
                                            ├── MomentumStrategy
                                            ├── MeanReversionStrategy
                                            └── GapStrategy

market-intelligence-agent
strategy-agent
    └─► risk-agent                  [topic: risk]
                                        └─► 9 RiskDimension calculators
```

## Sequence Diagram (Per Cycle)

```
1. market-data-agent  → bus.publish("market_data", payload)
2. market-intelligence-agent reads from bus + market_intelligence_hub
   → bus.publish("market_intelligence", snapshot)
3. stock-monitoring-agent reads scan_state_store + portfolio_store
   → SmartPriorityEngine.build_priority_queue(P1..P5)
   → EventDetector.detect() × all symbols
   → bus.publish("stock_monitoring", snapshot)
4. strategy-agent reads scan_state_store + bus(market_intelligence)
   → StrategyRegistry.evaluate() × symbols × 6 strategies
   → bus.publish("strategy", snapshot)
5. risk-agent reads portfolio_store + bus(market_intelligence, strategy)
   → 9 dimension calculators
   → bus.publish("risk", snapshot)
6. analysis_layer.get_analysis_summary() aggregates all 4
7. HTTP GET /analysis-agents/{endpoint} → Node.js → Python main.py
```

## READ-ONLY / ADVISORY-ONLY Confirmation

| Agent | Writes to portfolio? | Places orders? | Modifies strategies? | Emits BUY/SELL? |
|-------|---------------------|----------------|---------------------|-----------------|
| MarketIntelligenceAgent | ✗ | ✗ | ✗ | ✗ |
| StockMonitoringAgent    | ✗ | ✗ | ✗ | ✗ |
| StrategyAgent           | ✗ | ✗ | ✗ | ✗ |
| RiskAgent               | ✗ | ✗ | ✗ | ✗ |

All 4 agents: **advisory_only: True**, **read_only: True**, **never_modifies_portfolio: True** in every snapshot payload.

## Files Created / Modified

### Python Backend
- `market_intelligence_agent/__init__.py`
- `market_intelligence_agent/agent.py`         — MarketIntelligenceAgent
- `market_intelligence_agent/shared_services.py`
- `stock_monitoring_agent/__init__.py`
- `stock_monitoring_agent/agent.py`             — StockMonitoringAgent + SmartPriorityEngine + EventDetector
- `stock_monitoring_agent/shared_services.py`
- `strategy_agent/__init__.py`
- `strategy_agent/agent.py`                     — StrategyAgent + StrategyRegistry + 6 strategies
- `strategy_agent/shared_services.py`
- `risk_agent/__init__.py`
- `risk_agent/agent.py`                         — RiskAgent + 9 calculators
- `risk_agent/shared_services.py`
- `analysis_layer/__init__.py`
- `analysis_layer/shared_services.py`           — aggregation + timeline + performance
- `agent_framework/config.py`                   — +4 feature flags
- `main.py`                                     — +13 dispatch cases
- `test_analysis_agents.py`                     — 85/85 tests

### Node.js Backend
- `artifacts/api-server/src/routes/analysisAgents.ts`   — 12 GET routes
- `artifacts/api-server/src/routes/index.ts`            — mounted analysisAgentsRouter

### React Frontend
- `artifacts/trading-dashboard/src/pages/AgentOperations.tsx`  — Analysis Layer section added
- `artifacts/trading-dashboard/src/pages/CommandCenter.tsx`     — AnalysisLayerCard added

## API Endpoints (12 routes)

| Method | Path | Purpose |
|--------|------|---------|
| GET | /analysis-agents/market-intelligence/snapshot | MI agent snapshot |
| GET | /analysis-agents/market-intelligence/status   | MI agent health status |
| GET | /analysis-agents/stock-monitoring/snapshot    | SM agent snapshot |
| GET | /analysis-agents/stock-monitoring/events      | All detected events |
| GET | /analysis-agents/stock-monitoring/priority    | Priority queue |
| GET | /analysis-agents/strategy/snapshot            | Strategy snapshot |
| GET | /analysis-agents/strategy/symbol/:symbol      | Per-symbol strategy eval |
| GET | /analysis-agents/risk/snapshot                | Risk snapshot |
| GET | /analysis-agents/risk/detail                  | Detailed risk breakdown |
| GET | /analysis-agents/summary                      | Aggregated summary |
| GET | /analysis-agents/timeline                     | Timeline events |
| GET | /analysis-agents/performance                  | Agent performance metrics |

## Test Results

```
85 passed in 42.61s

TestMarketIntelligenceAgent     — 12 tests
TestSmartPriorityEngine         — 7 tests
TestEventDetector               — 12 tests
TestStockMonitoringAgent        — 6 tests
TestStrategyImplementations     — 9 tests
TestStrategyAgent               — 8 tests
TestRiskAgent                   — 12 tests
TestAnalysisLayer               — 6 tests
TestFeatureFlags10B             — 6 tests
TestSnapshotBusIntegration      — 3 tests
TestHeartbeatHealth10B          — 4 tests
```

## Benchmarks (observed, fresh scan)

| Operation | Latency |
|-----------|---------|
| MarketIntelligenceAgent.execute_task() | ~2-3s (yfinance multi-TF) |
| StockMonitoringAgent.execute_task()    | ~500ms (scan cache) |
| StrategyAgent.execute_task()           | ~200ms (pure calc) |
| RiskAgent.execute_task()               | ~100ms (portfolio store) |
| get_analysis_summary()                 | ~3-4s (full chain) |

## Feature Flags

| Flag | Default |
|------|---------|
| MARKET_INTELLIGENCE_AGENT_ENABLED | true |
| STOCK_MONITORING_AGENT_ENABLED    | true |
| STRATEGY_AGENT_ENABLED            | true |
| RISK_AGENT_ENABLED                | true |
