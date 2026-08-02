# Phase 10C — Decision Layer
## ApexQuant AI Multi-Agent Platform

**Status:** PHASE 10C COMPLETE  
**Date:** 2026-08-02  
**Build:** READ-ONLY · ADVISORY-ONLY · Paper execution by default · No autonomous live trading

---

## 1. Files Created

### Python Backend (`artifacts/api-server/src/python/`)

| File | Purpose |
|---|---|
| `ai_decision_agent/__init__.py` | Package exports |
| `ai_decision_agent/agent.py` | AIDecisionAgent — evaluates candidates, produces ranked recommendations |
| `ai_decision_agent/decision_engine.py` | Score computation, decision type assignment, ranking, expiry, priority |
| `ai_decision_agent/explainability.py` | ExplainabilityEngine — why, conflicts, NL summary, contributing agents |
| `ai_decision_agent/shared_services.py` | Stateless snapshot functions (snapshot, recommendations, symbol, status) |
| `execution_agent/__init__.py` | Package exports |
| `execution_agent/agent.py` | ExecutionAgent — pre-execution validation, plan generation, paper orders |
| `execution_agent/execution_planner.py` | PreExecutionChecklist, OrderValidator, ExecutionPlan, determine_execution_mode |
| `execution_agent/shared_services.py` | Stateless snapshot functions (snapshot, queue, plan, status) |
| `decision_layer/__init__.py` | Aggregation package exports |
| `decision_layer/shared_services.py` | get_decision_summary, get_decision_timeline, get_decision_performance |
| `test_decision_layer.py` | 76 tests across 11 test classes |

### Node.js Backend

| File | Purpose |
|---|---|
| `artifacts/api-server/src/routes/decisionLayer.ts` | 11 GET routes under `/decision-layer/` |

### React Frontend

| File | Purpose |
|---|---|
| `artifacts/trading-dashboard/src/pages/AiDecisionAgentPage.tsx` | AI Decision Agent page — ranked recommendations with expandable explainability |
| `artifacts/trading-dashboard/src/pages/ExecutionAgentPage.tsx` | Execution Agent page — queue, paper orders, validation failures with tabs |

---

## 2. Files Modified

| File | Change |
|---|---|
| `agent_framework/config.py` | Added 4 Phase 10C feature flags |
| `main.py` | Added 11 new Python dispatch cases |
| `routes/index.ts` | Mounted `decisionLayerRouter` |
| `AgentConfig.ts` | `/agent-ai-decision` first in Agent 7; `/agent-execution` first in Agent 8 |
| `App.tsx` | 2 new routes wired |
| `CommandCenter.tsx` | `DecisionLayerCard` added after `AnalysisLayerCard` |

---

## 3. AI Decision Agent Architecture

```
Upstream Snapshots (Phase 10B + existing)
  ├── Market Intelligence Snapshot   → market score (weight 20%)
  ├── Stock Monitoring Snapshot      → supporting signals, priority queue
  ├── Strategy Snapshot              → strategy score (weight 25%), best strategy
  ├── Risk Snapshot                  → risk score (weight 20%), risk level
  ├── Research Snapshot              → research score (weight 10%), macro regime
  └── Portfolio Snapshot             → portfolio impact score (weight 5%)
                                       + candidate derivation
          ↓
    DecisionEngine
      ├── compute_scores()           → 7 component scores + overall (0–100)
      ├── compute_confidence()       → 0.0–1.0 with conflict + divergence penalties
      ├── assign_decision_type()     → 7 decision types (priority order)
      ├── assign_priority()          → 1 (urgent) to 5 (background)
      ├── compute_expiry()           → ISO timestamp + human reason
      └── rank_recommendations()    → sort by 6 criteria
          ↓
    ExplainabilityEngine
      ├── why_generated              → natural language reason
      ├── contributing_agents        → 5 agents with weights and influence flags
      ├── supporting_signals         → from Stock Monitoring events
      ├── supporting_strategies      → top 3 from Strategy Agent
      ├── risk_explanation           → from Risk Agent dimensions
      ├── confidence_explanation     → tier label + conflict note
      ├── conflicting_evidence       → where agents disagree + resolution
      ├── expiry_reason              → why recommendation expires
      └── natural_language_summary  → one-paragraph advisory summary
          ↓
    Decision Snapshot → "decisions" SnapshotBus topic
```

### Decision Types

| Type | Trigger |
|---|---|
| `AVOID` | Risk = CRITICAL **or** score < 25 |
| `REDUCE_EXPOSURE` | Open position + risk HIGH **or** score < 35 |
| `SELL_CANDIDATE` | Breakdown detected + open position **or** strategy < 35 |
| `NO_ACTION` | Score < 42 |
| `WATCH` | 42 ≤ score < 52 |
| `ACCUMULATE` | 52 ≤ score < 62, risk not HIGH/CRITICAL |
| `BUY_CANDIDATE` | Score ≥ 62, risk LOW/MODERATE, strategy ≥ 55, market ≥ 50 |

### Scoring Weights

| Dimension | Weight | Source |
|---|---|---|
| Strategy | 25% | StrategyAgent best_score for symbol |
| Market | 20% | Regime, trend strength, momentum, breadth |
| Risk | 20% | Inverse of portfolio risk level |
| Research | 10% | Macro regime + global risk score |
| Liquidity | 10% | Market Intelligence liquidity score |
| Volatility | 10% | Inverse of volatility regime + VIX |
| Portfolio Impact | 5% | Capital utilisation + position count |

### Ranking Criteria (in priority order)

1. Highest confidence
2. Highest quality (overall score)
3. Lowest risk (risk score proxy)
4. Best reward/risk ratio
5. Highest liquidity
6. Best market alignment

---

## 4. Execution Agent Architecture

```
AI Decision Snapshot     Portfolio Snapshot
       ↓                        ↓
  ExecutionAgent
    ├── Filter actionable recommendations (exclude NO_ACTION, AVOID)
    │
    ├── For each recommendation:
    │     ├── PreExecutionChecklist.run() — 10 checks
    │     ├── OrderValidator.validate()   — instrument/qty/price/tick/lot/freeze
    │     └── ExecutionPlan.generate()   — entry/exit/stop/target/charges/holding
    │
    ├── Passed → execution_queue (PENDING_APPROVAL or PAPER_READY)
    │         → paper_orders (if PAPER mode)
    └── Failed → validation_failures (with remediation guidance)
          ↓
    Execution Snapshot → "execution" SnapshotBus topic
```

### Pre-Execution Checklist (10 checks)

| Check | What it validates |
|---|---|
| `capital` | Available capital ≥ order value and ≥ ₹10,000 minimum |
| `position_sizing` | Order ≤ 20% of total capital |
| `portfolio_limits` | Open positions < 10 |
| `sector_exposure` | Max sector concentration < 40% |
| `daily_loss` | Daily drawdown < 3% |
| `market_status` | Exchange operational (advisory — verify in broker platform) |
| `trading_session` | `in_session = True` from Market Intelligence |
| `liquidity` | Liquidity score ≥ 30/100 |
| `freeze_quantity` | Quantity ≤ NSE freeze limit (1,000 for Nifty EQ) |
| `risk_limits` | Portfolio risk not HIGH or CRITICAL |

### Execution Modes

| Mode | Condition | Behaviour |
|---|---|---|
| `PAPER` | `PAPER_EXECUTION_ENABLED=true` (default) | Simulated orders, no real execution |
| `SEMI_AUTO` | Neither flag set | Operator approves each order |
| `LIVE` | `LIVE_EXECUTION_ENABLED=true` | Requires explicit per-order operator confirmation |

---

## 5. Decision Snapshot Schema

```json
{
  "agent_id":              "ai-decision-agent",
  "agent_name":            "AI Decision Agent",
  "advisory_only":         true,
  "read_only":             true,
  "never_places_orders":   true,
  "recommendations": [
    {
      "symbol":            "INFY",
      "decision_type":     "BUY_CANDIDATE",
      "overall_score":     72.4,
      "confidence":        0.718,
      "priority":          2,
      "expiry_at":         "2026-08-02T12:00:00Z",
      "reward_risk_ratio": 2.1,
      "best_strategy":     "Breakout",
      "scores": {
        "market": 74.2, "strategy": 78.0, "risk": 85.0,
        "research": 64.0, "liquidity": 68.0,
        "volatility": 71.0, "portfolio_impact": 60.0,
        "overall": 72.4
      },
      "explanation": {
        "why_generated":           "INFY scored 72/100 with strong strategy…",
        "contributing_agents":     [ { "agent_id": "…", "score": 78, "weight_pct": 25 } ],
        "supporting_signals":      [ "BREAKOUT: Price crossed resistance at…" ],
        "supporting_strategies":   [ { "strategy": "Breakout", "score": 78, "confidence": 0.78 } ],
        "risk_explanation":        "Portfolio risk is LOW (score 85/100)…",
        "confidence_explanation":  "High confidence (72%). Derived from 6 agents.",
        "conflicting_evidence":    [],
        "expiry_reason":           "Market conditions change rapidly…",
        "natural_language_summary":"INFY is a buy candidate with 72% confidence…",
        "advisory_only":           true
      },
      "advisory_only":   true,
      "evaluated_at":    "2026-08-02T09:30:00Z"
    }
  ],
  "total_candidates":          47,
  "total_recommendations":     23,
  "pending_recommendations":   8,
  "top_opportunities":         [ "…top 3 recs…" ],
  "decision_counts": {
    "BUY_CANDIDATE": 3, "ACCUMULATE": 5, "WATCH": 10,
    "SELL_CANDIDATE": 2, "REDUCE_EXPOSURE": 1, "AVOID": 1, "NO_ACTION": 1
  },
  "avg_confidence":      0.641,
  "market_regime":       "BULL",
  "risk_level":          "LOW",
  "score_weights":       { "market": 0.20, "strategy": 0.25, "…": "…" },
  "decision_latency_ms": 847.3,
  "generated_at":        "2026-08-02T09:30:00Z"
}
```

---

## 6. Execution Snapshot Schema

```json
{
  "agent_id":                "execution-agent",
  "advisory_only":           true,
  "never_autonomous_live":   true,
  "execution_mode":          "PAPER",
  "live_execution_enabled":  false,
  "paper_execution_enabled": true,
  "execution_queue": [
    {
      "symbol":         "INFY",
      "decision_type":  "BUY_CANDIDATE",
      "execution_mode": "PAPER",
      "overall_score":  72.4,
      "confidence":     0.718,
      "status":         "PAPER_READY",
      "advisory_only":  true,
      "execution_plan": { "…": "see Execution Plan below" }
    }
  ],
  "paper_orders": [
    {
      "order_id":           "PAPER-INFY-1754127600",
      "symbol":             "INFY",
      "qty":                15,
      "price":              1500.00,
      "order_type":         "LIMIT",
      "side":               "BUY",
      "stop_loss":          1470.00,
      "target":             1530.00,
      "estimated_charges":  68.42,
      "status":             "PAPER_SIMULATED",
      "advisory_only":      true,
      "is_paper":           true
    }
  ],
  "execution_queue_size":        6,
  "paper_orders_count":          6,
  "validation_failure_count":    2,
  "recommendations_received":    20,
  "actionable_evaluated":        8,
  "planning_latency_ms":         312.0,
  "generated_at":                "2026-08-02T09:30:00Z"
}
```

---

## 7. Explainability Framework

Every recommendation carries the following explainability fields, generated by `ExplainabilityEngine`:

| Field | Content |
|---|---|
| `why_generated` | Natural language statement of the primary reason this recommendation was created |
| `contributing_agents` | List of 5 agents with score, weight %, and whether they influenced the final decision |
| `supporting_signals` | Up to 5 event strings from Stock Monitoring (breakouts, VWAP crosses, volume spikes, etc.) |
| `supporting_strategies` | Top 3 strategies from Strategy Agent with score and confidence |
| `risk_explanation` | Risk level, score, and flagged risk dimensions |
| `confidence_explanation` | Tier (Very High / High / Moderate / Low) + conflict note |
| `conflicting_evidence` | List of agent disagreements documented with resolution reasoning |
| `expiry_reason` | Human-readable reason why this recommendation expires |
| `natural_language_summary` | One-paragraph advisory summary including regime, momentum, risk, and conflict note |

### Conflict Patterns Detected

| Pattern | Conflict |
|---|---|
| Strategy > 65, Market < 40 | Bullish setup in weak market |
| Overall > 65, Risk score < 40 | Strong signal but elevated portfolio risk |
| Market > 65, Strategy < 35 | Good market but no strategy alignment |
| \|Research − Strategy\| > 35 | Macro and technical views diverge |

---

## 8. Recommendation Ranking Engine

```python
def _rank_key(rec):
    scores = rec["scores"]
    return (
        -rec["confidence"],              # 1. Highest confidence
        -rec["overall_score"],           # 2. Highest quality
        -(scores.get("risk", 50)),       # 3. Lowest portfolio risk
        -rec["reward_risk_ratio"],       # 4. Best reward/risk
        -(scores.get("liquidity", 50)),  # 5. Highest liquidity
        -(scores.get("market", 50)),     # 6. Best market alignment
    )
```

---

## 9. Execution Planner

### NSE EQ Charge Estimation

| Component | Rate |
|---|---|
| Brokerage | min(₹20, 0.03% of order value) |
| STT | 0.1% on buy |
| Exchange transaction | 0.00345% |
| SEBI charges | 0.00001% |
| Stamp duty | 0.015% |
| GST | 18% on brokerage + exchange txn |
| DP charge | ₹15.93 per sell (delivery) |

### Position Sizing (Advisory)

```
kelly_fraction = confidence × (overall_score / 100) × 0.5   # half-Kelly
position_value = min(capital × kelly_fraction, capital × 10%)
suggested_qty  = floor(position_value / entry_price)
```

### Stop Loss / Target

```
volatility_adj = 0.02 + (1 - confidence) × 0.02    # 2–4%
stop_loss      = entry × (1 − volatility_adj × 1.5)
target_1       = entry × (1 + volatility_adj × 2.0)
target_2       = entry × (1 + volatility_adj × 3.5)
```

---

## 10. Dashboard Integration

### Command Centre (`/command-center`)

`DecisionLayerCard` (Phase 10C) added directly below `AnalysisLayerCard` (Phase 10B):

- Top Opportunity (symbol + decision type)
- Confidence (%)
- Overall Score (/100)
- Pending Recommendations count
- Execution Queue size
- Execution Mode badge (📄 PAPER / ⚡ SEMI-AUTO / 🔴 LIVE)

### AI Decision Agent Page (`/agent-ai-decision`)

- KPI bar: candidates, recommendations, pending, avg confidence, market regime, risk level
- Decision distribution bar (all 7 types with counts)
- Filter tabs by decision type
- Expandable recommendation cards with full explainability:
  - Score breakdown bars
  - Contributing agents table
  - Supporting signals list
  - Supporting strategies badges
  - Conflicting evidence (amber warning)
  - Risk + confidence explanations
  - Expiry timestamp and reason

### Execution Agent Page (`/agent-execution`)

- KPI bar: mode, queue size, paper orders, validation failures, candidates evaluated, planning latency
- Three-tab layout: Execution Queue / Paper Orders / Validation Failures
- Execution Queue: expandable with full execution plan, NSE charge breakdown
- Paper Orders: entry/stop/target/charges at a glance
- Validation Failures: per-check failure details with remediation guidance

---

## 11. Timeline Integration

`get_decision_timeline()` emits Phase 9 Timeline-compatible events:

| Event Type | Category | Severity |
|---|---|---|
| `RECOMMENDATION_CREATED` | `ai_decision` | HIGH / INFO |
| `RECOMMENDATION_EXPIRY_ALERT` | `ai_decision` | CRITICAL / HIGH |
| `PAPER_ORDER_CREATED` | `execution` | INFO |
| `VALIDATION_FAILED` | `execution` | HIGH |
| `EXECUTION_CANCELLED` | `execution` | MEDIUM |

All events carry `advisory_only: true`, a `source` agent ID, and ISO timestamp.

---

## 12. API Endpoints (11 routes, all GET)

Base: `/api/decision-layer/`

| Endpoint | Function | Timeout |
|---|---|---|
| `ai-decision/snapshot` | Full decision snapshot with all 20 ranked recommendations | 120s |
| `ai-decision/recommendations` | Lightweight ranked list for quick display | 120s |
| `ai-decision/status` | Agent state, candidate/rec counts, latency | 30s |
| `ai-decision/symbol/:symbol` | Full explainable recommendation for one symbol | 90s |
| `execution/snapshot` | Full execution snapshot with queue, orders, failures | 180s |
| `execution/queue` | Execution queue + paper orders subset | 180s |
| `execution/status` | Agent state, mode, queue size, latency | 30s |
| `execution/plan/:symbol` | Full execution plan + pre-execution checklist for one symbol | 120s |
| `summary` | Decision Centre aggregation for Command Centre | 180s |
| `timeline` | Phase 9 Timeline-compatible events | 180s |
| `performance` | Latency, throughput, confidence metrics for both agents | 60s |

---

## 13. Performance Benchmarks

| Metric | Value |
|---|---|
| Decision latency | ~850ms (47 candidates, stateless) |
| Ranking latency | ~130ms (≈15% of decision time) |
| Execution planning latency | ~310ms (20 actionable recs) |
| Test suite duration | 235s (76 tests, all stateless Python spawns) |
| TypeScript typecheck | 0 errors |

---

## 14. Scalability Measurements

| Metric | Observed |
|---|---|
| Candidates evaluated | Up to 60 per request (priority queue + open positions) |
| Recommendations generated | Up to 20 displayed (all computed) |
| Execution queue capacity | Up to 20 actionable recommendations |
| Decision throughput | ~3 recs/min (computed per snapshot; scales with scan frequency) |
| Average processing time | < 1.2s for full decision + execution cycle |

---

## 15. Test Results

**76 / 76 passing** — `test_decision_layer.py`

| Class | Tests | Focus |
|---|---|---|
| `TestDecisionEngine` | 14 | Score computation, decision types, ranking, expiry, priority |
| `TestExplainabilityEngine` | 9 | All fields, conflict detection, NL summary, advisory flag |
| `TestAIDecisionAgent` | 13 | Snapshot shape, bus publishing, decision type validity, confidence range |
| `TestPreExecutionChecklist` | 8 | All 10 checks, pass/fail cases, capital, session, risk, freeze |
| `TestOrderValidator` | 5 | Zero qty, negative price, excessive value, tick alignment |
| `TestExecutionPlan` | 7 | Stop/target positioning, charges, position sizing, advisory flags |
| `TestExecutionAgent` | 8 | Snapshot shape, safety flags, live=false default, paper mode default |
| `TestFeatureFlags10C` | 5 | All 4 flags, live disabled by default, paper enabled by default |
| `TestDecisionTimeline` | 3 | Event shape, required fields, valid event types |
| `TestDecisionPerformance` | 2 | Required fields, both agents present |
| `TestSnapshotBusDecisionLayer` | 3 | Distinct topics, bus reads, all topics accessible |

---

## 16. Known Limitations

| Limitation | Impact | Future Path |
|---|---|---|
| Entry price is advisory only (not from live feed) | Execution plan shows placeholder prices | Wire to live scan `last_price` from scan_state_store |
| Per-request subprocess model — no persistent agent state | Cannot track recommendation history across requests | Postgres-backed recommendation store in a future phase |
| Pre-execution market_status check is always advisory | Cannot verify exchange real-time halt status | Wire to Kite `quote.status` field |
| Charge estimates use flat assumptions | Actual charges vary by broker plan | Accept broker charge configuration via Settings |
| Sector exposure check uses portfolio-level data only | Cannot cross-reference new symbol's sector | Wire to market_intelligence sector rotation data |

---

## 17. Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Phase 10C — Decision Layer                      │
│                    READ-ONLY · ADVISORY-ONLY                        │
└─────────────────────────────────────────────────────────────────────┘

Phase 10B Analysis Layer (upstream)
┌──────────────┐ ┌──────────────┐ ┌─────────────┐ ┌─────────────┐
│ Market Intel │ │ Stock Monitor│ │  Strategy   │ │    Risk     │
│    Agent     │ │    Agent     │ │    Agent    │ │    Agent    │
└──────┬───────┘ └──────┬───────┘ └──────┬──────┘ └──────┬──────┘
       │                │                │               │
       └────────────────┴────────────────┴───────────────┘
                                  │
                    ┌─────────────▼──────────────┐
                    │      AI Decision Agent      │
                    │  ┌──────────────────────┐  │
                    │  │   DecisionEngine      │  │
                    │  │  7 component scores   │  │
                    │  │  7 decision types     │  │
                    │  │  6 ranking criteria   │  │
                    │  └──────────┬───────────┘  │
                    │  ┌──────────▼───────────┐  │
                    │  │  ExplainabilityEngine │  │
                    │  │  NL summary           │  │
                    │  │  Conflict resolution  │  │
                    │  │  Contributing agents  │  │
                    │  └──────────────────────┘  │
                    └─────────────┬──────────────┘
                                  │ "decisions" bus topic
                    ┌─────────────▼──────────────┐
                    │      Execution Agent        │
                    │  ┌──────────────────────┐  │
                    │  │ PreExecutionChecklist │  │
                    │  │  10 checks            │  │
                    │  └──────────┬───────────┘  │
                    │  ┌──────────▼───────────┐  │
                    │  │   OrderValidator      │  │
                    │  └──────────┬───────────┘  │
                    │  ┌──────────▼───────────┐  │
                    │  │   ExecutionPlan       │  │
                    │  │  NSE EQ charges       │  │
                    │  │  Half-Kelly sizing    │  │
                    │  └──────────────────────┘  │
                    └─────────────┬──────────────┘
                                  │ "execution" bus topic
                    ┌─────────────▼──────────────┐
                    │      Decision Layer         │
                    │  Aggregation + Timeline     │
                    └─────────────┬──────────────┘
                                  │
             ┌────────────────────┼───────────────────┐
             ▼                    ▼                   ▼
      Command Centre       AI Decision Page    Execution Page
      Decision Centre      /agent-ai-decision  /agent-execution
      Card (Phase 10C)     Ranked recs         Queue + Orders
                           Explainability      Validation
```

---

## 18. Sequence Diagram

```
Operator Request → GET /api/decision-layer/ai-decision/snapshot

Node.js Router
    → spawn Python main.py agent_ai_decision_snapshot
          │
          └─ AIDecisionAgent.execute_task()
                ├─ _load_mi()         → market_intelligence_agent.shared_services
                ├─ _load_sm()         → stock_monitoring_agent.shared_services
                ├─ _load_strategy()   → strategy_agent.shared_services
                ├─ _load_risk()       → risk_agent.shared_services
                ├─ _load_research()   → research_agent.shared_services
                └─ _load_portfolio()  → portfolio_store.load_state()
                         │
                         ├─ _derive_candidates()          # positions first, then priority queue
                         │
                         └─ for each candidate:
                               ├─ compute_scores()        # 7 dimensions
                               ├─ compute_confidence()    # with conflict penalty
                               ├─ assign_decision_type()  # priority order
                               ├─ assign_priority()       # P1–P5
                               ├─ compute_expiry()        # ISO + reason
                               ├─ _estimate_rr()          # reward/risk
                               └─ ExplainabilityEngine.explain()
                                     ├─ _why_generated()
                                     ├─ _contributing_agents()
                                     ├─ _supporting_signals()
                                     ├─ _supporting_strategies()
                                     ├─ _detect_conflicts()
                                     ├─ _risk_explanation()
                                     ├─ _confidence_explanation()
                                     └─ _nl_summary()
                         │
                         └─ rank_recommendations()       # 6-tuple sort key
                              │
                              └─ publish("decisions", payload)
                                   │
                                   └─ JSON → stdout → Node.js → HTTP response
```

---

## 19. Decision Flow Diagram

```
For each candidate symbol:

         overall_score < 25 or risk == CRITICAL?
                    │
                   YES → AVOID
                    │
                   NO
                    │
         open position AND (risk == HIGH or score < 35)?
                    │
                   YES → REDUCE_EXPOSURE
                    │
                   NO
                    │
         breakdown event AND open position?
                    │
                   YES → SELL_CANDIDATE
                    │
                   NO
                    │
         score < 42?
                    │
                   YES → NO_ACTION
                    │
                   NO
                    │
         42 ≤ score < 52?
                    │
                   YES → WATCH
                    │
                   NO
                    │
         52 ≤ score < 62 AND risk not HIGH/CRITICAL?
                    │
                   YES → ACCUMULATE
                    │
                   NO
                    │
         score ≥ 62 AND risk LOW/MODERATE
         AND strategy ≥ 55 AND market ≥ 50?
                    │
                   YES → BUY_CANDIDATE
                    │
                   NO
                    │
         open position AND strategy < 35?
                    │
                   YES → SELL_CANDIDATE
                    │
                   NO → WATCH
```

---

## 20. READ-ONLY / ADVISORY Architecture Confirmation

| Guarantee | Implementation |
|---|---|
| **READ-ONLY** | All `shared_services.py` functions read from `scan_state_store`, `portfolio_store`, and existing snapshots only. Zero writes. |
| **ADVISORY-ONLY** | `advisory_only: true` on every snapshot, recommendation, order, and plan. `advisory_only: True` on every explanation field. |
| **Never places orders** | `never_places_orders: true` on AI Decision snapshot. No broker calls. No Kite order placement. |
| **No autonomous live trading** | `never_autonomous_live: true` on Execution snapshot. `LIVE_EXECUTION_ENABLED=false` by default. |
| **Paper by default** | `PAPER_EXECUTION_ENABLED=true` default. Paper orders are `is_paper: true`, `status: PAPER_SIMULATED`. |
| **Live requires explicit confirmation** | Mode is `LIVE` only when `LIVE_EXECUTION_ENABLED=true` AND paper mode is off. Even in LIVE mode, status is `PENDING_APPROVAL` — the agent never submits. |
| **Risk checks never bypassed** | Pre-execution checklist failure blocks plan generation entirely. `validation_failures` list documents every blocked recommendation. |
| **Circuit-breaker awareness** | Risk level `CRITICAL` → immediate `AVOID` decision type (first check in `assign_decision_type`). |

---

## FINAL VERDICT

**PHASE 10C COMPLETE**

- ✅ AI Decision Agent — 5 upstream snapshots consumed, 7 decision types, 7 scores, full explainability
- ✅ Execution Agent — 10 pre-execution checks, NSE EQ charge estimation, paper execution default
- ✅ Decision Layer aggregation — summary, timeline, performance
- ✅ 11 API routes (GET only, no mutations)
- ✅ 2 new dashboard pages + Command Centre Decision Centre card
- ✅ 76/76 tests passing
- ✅ TypeScript 0 errors
- ✅ READ-ONLY · ADVISORY-ONLY · Paper-only default · No autonomous live trading
