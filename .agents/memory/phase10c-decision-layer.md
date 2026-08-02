---
name: Phase 10C Decision Layer
description: AI Decision Agent + Execution Agent architecture, safety guarantees, and key implementation decisions.
---

## Architecture

Two new agents extending BaseAgent:

**AIDecisionAgent** (`ai_decision_agent/`)
- Consumes: market_intelligence, stock_monitoring, strategy, risk, research, portfolio snapshots
- Produces: ranked recommendations on "decisions" bus topic
- Decision types: WATCH | ACCUMULATE | BUY_CANDIDATE | SELL_CANDIDATE | REDUCE_EXPOSURE | AVOID | NO_ACTION
- 7 component scores with weights (market 20%, strategy 25%, risk 20%, research 10%, liquidity 10%, volatility 10%, portfolio_impact 5%)
- Explainability: all fields including conflicting_evidence, NL summary, contributing agents, supporting signals

**ExecutionAgent** (`execution_agent/`)
- Consumes: decision snapshot + portfolio + risk + market_intelligence
- Produces: execution plans + paper orders on "execution" bus topic
- Pre-execution checklist: 10 checks (capital, position_sizing, portfolio_limits, sector_exposure, daily_loss, market_status, trading_session, liquidity, freeze_quantity, risk_limits)
- Order validation: instrument, qty, price, tick size, lot size, freeze limits, market timing
- Execution plan: entry, exit, stop, target_1, target_2, breakeven, charges (NSE EQ), holding time

**decision_layer/** — aggregation module
- `get_decision_summary()` → Command Centre Decision Centre card
- `get_decision_timeline()` → Phase 9 Timeline-compatible events (5 types)
- `get_decision_performance()` → latency, throughput, confidence metrics

## Safety

- `LIVE_EXECUTION_ENABLED` defaults to `false` — paper only by default
- `PAPER_EXECUTION_ENABLED` defaults to `true`
- `determine_execution_mode()` in execution_planner.py reads env vars at call time
- `never_autonomous_live: true` + `never_places_orders: true` enforced as snapshot fields
- All pre-execution checklist failures block plan generation

## Feature Flags (agent_framework/config.py)

- `AI_DECISION_AGENT_ENABLED` (default true)
- `EXECUTION_AGENT_ENABLED` (default true)
- `LIVE_EXECUTION_ENABLED` (default false)
- `PAPER_EXECUTION_ENABLED` (default true)

## API Routes (12 total, all GET)

Under `/api/decision-layer/`:
- `ai-decision/snapshot`, `ai-decision/recommendations`, `ai-decision/status`, `ai-decision/symbol/:symbol`
- `execution/snapshot`, `execution/queue`, `execution/status`, `execution/plan/:symbol`
- `summary`, `timeline`, `performance`

Node.js router: `artifacts/api-server/src/routes/decisionLayer.ts`
Python dispatch cases: `agent_ai_decision_snapshot`, `agent_ai_decision_recommendations`, `agent_ai_decision_status`, `agent_ai_decision_symbol`, `agent_execution_snapshot`, `agent_execution_queue`, `agent_execution_status`, `agent_execution_plan`, `agent_decision_summary`, `agent_decision_timeline`, `agent_decision_performance`

## Frontend

New pages:
- `/agent-ai-decision` → `AiDecisionAgentPage.tsx` (ranked recommendations with expandable explainability cards)
- `/agent-execution` → `ExecutionAgentPage.tsx` (execution queue, paper orders, validation failures with tabs)

Added to navigation (AgentConfig.ts):
- Agent 7 first page: `/agent-ai-decision`
- Agent 8 first page: `/agent-execution`

Command Centre: `DecisionLayerCard` added after `AnalysisLayerCard` (Phase 10B)

## Tests

File: `test_decision_layer.py` — **76/76 passing**
Classes: TestDecisionEngine (14), TestExplainabilityEngine (9), TestAIDecisionAgent (13), TestPreExecutionChecklist (8), TestOrderValidator (5), TestExecutionPlan (7), TestExecutionAgent (8), TestFeatureFlags10C (5), TestDecisionTimeline (3), TestDecisionPerformance (2), TestSnapshotBusDecisionLayer (3)

**Why:**
- Stateless per-request: same pattern as Phase 10B — no singleton state in shared_services, fresh computation per call
- Open positions always evaluated first (derive_candidates inserts positions at head of queue)
- AVOID triggered first before all other decision types when risk=CRITICAL or score<25
- Charges estimated using NSE EQ delivery schedule (STT 0.1%, brokerage flat ₹20, DP ₹15.93)
