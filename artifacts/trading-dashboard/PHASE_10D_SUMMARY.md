# Phase 10D — Learning Layer
## ApexQuant AI Multi-Agent Platform

**Final Verdict: PHASE 10D COMPLETE ✅**

---

## 1. Files Created

### Python Backend
| File | Description |
|------|-------------|
| `learning_agent/__init__.py` | Package exports |
| `learning_agent/agent.py` | LearningAgent class — stateless, per-request |
| `learning_agent/learning_engine.py` | 9 metric computations, insights engine, pattern discovery |
| `learning_agent/shared_services.py` | `get_learning_snapshot/metrics/insights/status` |
| `knowledge_agent/__init__.py` | Package exports |
| `knowledge_agent/agent.py` | KnowledgeAgent class — stateless, per-request |
| `knowledge_agent/knowledge_engine.py` | Indexing, NL search, trade memory, lessons library |
| `knowledge_agent/shared_services.py` | `get_knowledge_snapshot/search/patterns/lessons/memory/status` |
| `learning_layer/__init__.py` | Package exports |
| `learning_layer/shared_services.py` | `get_learning_summary/timeline/performance` |
| `test_learning_layer.py` | 109/109 tests across 14 test classes |

### Node.js Backend
| File | Description |
|------|-------------|
| `src/routes/learningLayer.ts` | 13 GET routes under `/learning-layer/` |

### React Frontend (6 new pages)
| File | Route | Description |
|------|-------|-------------|
| `pages/LearningAgentPage.tsx` | `/agent-learning` | Metrics, insights, sector performance, patterns |
| `pages/KnowledgeAgentPage.tsx` | `/agent-knowledge` | Dashboard + lessons + entry sample |
| `pages/PatternExplorerPage.tsx` | `/pattern-explorer` | Pattern cards with confidence bars |
| `pages/LessonsLibraryPage.tsx` | `/lessons-library` | 5-category lessons display |
| `pages/KnowledgeSearchPage.tsx` | `/knowledge-search` | NL search with example queries |
| `pages/TradeMemoryPage.tsx` | `/trade-memory` | Full trade memory records |

---

## 2. Files Modified

| File | Change |
|------|--------|
| `agent_framework/config.py` | Added 4 Phase 10D flags |
| `main.py` | Added 13 dispatch cases |
| `src/routes/index.ts` | Mounted `learningLayerRouter` |
| `src/App.tsx` | Added 6 imports + 6 routes |
| `src/components/layout/AgentConfig.ts` | Added 6 pages to Agent 9 — Learning |
| `src/pages/CommandCenter.tsx` | Added `LearningLayerCard` |

---

## 3. Learning Agent Architecture

**Class:** `LearningAgent` (stateless, per-request)
**Agent ID:** `learning_agent`
**Version:** `10D.1`

### Consumes
- Decision Snapshot (via `ai_decision_agent.shared_services`)
- Execution Snapshot (implicit via paper portfolio)
- Paper Trading Results (via `portfolio_store.load_portfolio`)
- Trading Timeline (via `decision_layer.shared_services`)
- Risk Snapshot (via `risk_agent.shared_services`)
- Strategy Snapshot (via `strategy_agent.shared_services`)

### Produces: Learning Snapshot
```json
{
  "agent_id": "learning_agent",
  "advisory_only": true,
  "read_only": true,
  "auto_model_updates": false,
  "auto_strategy_tuning": false,
  "metrics": { ...9 learning metrics... },
  "insights": { ...8 insight fields... },
  "patterns": [ ...pattern observations... ],
  "learning_health": "HEALTHY | DEGRADED | NEEDS_REVIEW",
  "learning_latency_ms": 0.0,
  "generated_at": "2024-01-01T10:00:00Z"
}
```

---

## 4. Knowledge Agent Architecture

**Class:** `KnowledgeAgent` (stateless, per-request)
**Agent ID:** `knowledge_agent`
**Version:** `10D.1`

### Consumes
- Research Snapshot
- Timeline Events
- Learning Snapshot
- Decision Snapshot
- Paper Trades
- Operator Annotations (extensible hook — currently empty list)

### Produces: Knowledge Snapshot
```json
{
  "agent_id": "knowledge_agent",
  "advisory_only": true,
  "read_only": true,
  "knowledge_base_size": 0,
  "trades_learned": 0,
  "recommendations_analysed": 0,
  "patterns_identified": 0,
  "entries_sample": [ ...first 10 entries... ],
  "trade_memory": [ ...full memory records... ],
  "lessons_library": { ...5 lesson categories... },
  "patterns": [ ...pattern observations... ],
  "indexing_latency_ms": 0.0,
  "generated_at": "2024-01-01T10:00:00Z"
}
```

---

## 5. Learning Snapshot Schema

| Field | Type | Description |
|-------|------|-------------|
| `metrics.recommendation_accuracy` | float | % of recs that reached target |
| `metrics.strategy_win_rate` | float | % of closed trades profitable |
| `metrics.confidence_calibration` | float 0–1 | 1=perfect calibration |
| `metrics.avg_holding_minutes` | float | Average trade holding time |
| `metrics.avg_reward_risk` | float | Average reward/risk ratio |
| `metrics.sector_performance` | dict | Per-sector win rate + avg P&L |
| `metrics.regime_performance` | dict | Per-regime win rate + avg P&L |
| `metrics.risk_prediction_accuracy` | float | Risk warning materialization rate |
| `metrics.execution_validation_accuracy` | float | Pre-exec check pass rate |
| `auto_model_updates` | bool | **Always false — hardcoded** |
| `auto_strategy_tuning` | bool | **Always false — hardcoded** |

---

## 6. Knowledge Snapshot Schema

| Field | Type | Description |
|-------|------|-------------|
| `knowledge_base_size` | int | Total indexed entries |
| `trades_learned` | int | Completed trades in memory |
| `patterns_identified` | int | Active pattern count |
| `entries_sample` | list | First 10 entries for preview |
| `trade_memory` | list | Full trade memory records |
| `lessons_library.what_worked` | list[str] | Advisory — what succeeded |
| `lessons_library.what_failed` | list[str] | Advisory — what failed |
| `lessons_library.what_to_review` | list[str] | Advisory — review items |
| `lessons_library.what_to_monitor` | list[str] | Advisory — monitor items |
| `lessons_library.open_questions` | list[str] | Advisory — research questions |

---

## 7. Pattern Discovery Framework

5 built-in pattern detectors (all advisory, none trigger automated action):

| Pattern ID | Category | Trigger Condition |
|-----------|----------|------------------|
| `GAP_BREAKOUT` | PRICE_ACTION | ≥2 trades with gap_pct > 1.5% and positive P&L |
| `HIGH_VIX_FALSE_BREAKOUT` | VOLATILITY | ≥2 losses when VIX > 18 at entry |
| `MORNING_MOMENTUM_FADE` | TIME_BASED | ≥2 losses with holding_minutes < 60 |
| `SECTOR_ROTATION` | SECTOR | Activity across ≥3 distinct sectors |
| `REPEATED_RISK_FAILURES` | RISK | ≥2 trades flagged by risk pre-checks |
| `BASELINE_OBSERVATION` | META | Fallback when no patterns detected |

Each pattern includes: name, description, occurrences, confidence (0–1), category, and advisory observation text.

---

## 8. Knowledge Search Implementation

**Algorithm:** Keyword tokenization + intent expansion + relevance scoring

### Search Pipeline
1. Tokenise query → lowercase words
2. Expand intent tokens (`banking` → `["BANKING", "FINANCIALS", "BANK"]`)
3. Score each entry: `hits / query_token_count` (0.0–1.0)
4. Apply confidence threshold filter (e.g. "above 80%")
5. Boost exact symbol matches (+0.3) and label matches (+0.2)
6. Sort by relevance descending; return top 20

### Supported NL Queries
- "Show all successful banking breakouts"
- "Show every recommendation above 80% confidence"
- "What happened after RBI announcements?"
- "Which strategy performs best during high volatility?"
- "Show similar market conditions"

---

## 9. Lessons Library

5 auto-generated categories, derived from trade memory + metrics + insights:

| Category | Populated From |
|----------|---------------|
| What Worked | Best strategy win rate, best sector P&L, R:R ratio |
| What Failed | Worst strategy losses, weakest sector, low win rate |
| Review Required | Low win rate (<40%), confidence calibration, repeated rejections |
| Monitor Closely | Pattern observations, recurring risk warnings |
| Open Research Questions | 2 static + dynamic questions from session data |

---

## 10. Trade Memory Architecture

For every completed paper trade, stores:

| Field | Source |
|-------|--------|
| `memory_id` | MD5 hash of symbol + exit_time |
| `symbol`, `sector`, `strategy` | Portfolio store |
| `outcome` (WIN/LOSS) | Derived from pnl_pct |
| `pnl_pct` | Portfolio store |
| `decision_type`, `decision_confidence` | AI Decision Agent snapshot |
| `ai_explanation_summary` | Decision Agent explainability |
| `supporting_signals` | Decision Agent |
| `entry_price`, `exit_price`, `quantity` | Portfolio store |
| `entry_time`, `exit_time` | Portfolio store |
| `risk_pct`, `stop_loss` | Portfolio store |
| `lessons_learned` | Generated per outcome (WIN/LOSS/break-even) |
| `related_research` | From recommendation supporting strategies |

---

## 11. Dashboard Integration

### Command Centre (Phase 9.1)
Added `LearningLayerCard` showing:
- Trades Learned Today
- Recommendation Accuracy
- Knowledge Base Size
- Patterns Identified
- Top Insight (best strategy)
- Learning Health badge

### Agent 9 — Learning (AgentConfig.ts)
6 new pages registered:
- `/agent-learning` — Learning Agent
- `/agent-knowledge` — Knowledge Agent
- `/pattern-explorer` — Pattern Explorer
- `/lessons-library` — Lessons Library
- `/knowledge-search` — Knowledge Search
- `/trade-memory` — Trade Memory

---

## 12. Timeline Integration

Phase-9-compatible timeline via `get_learning_timeline()`.

5 event types (backwards-compatible):

| Event Type | Color | Source |
|-----------|-------|--------|
| `LEARNING_COMPLETED` | emerald | Learning Agent |
| `PATTERN_DETECTED` | violet | Learning Agent per pattern |
| `LESSON_GENERATED` | blue | Knowledge Agent (worked + review) |
| `KNOWLEDGE_INDEXED` | teal | Knowledge Agent |
| `TRADE_LEARNED` | indigo | Knowledge Agent per trade |

Events include: `event_id`, `event_type`, `title`, `description`, `source`, `severity`, `timestamp`. Sorted newest first.

---

## 13. Performance Benchmarks

| Metric | Design Target |
|--------|--------------|
| Learning latency | Proportional to trade/rec count; sub-second for empty session |
| Knowledge indexing latency | Sub-second for empty session |
| Search latency | ~15% of indexing latency (pure in-memory) |
| Pattern detection | ~25% of learning latency |
| Memory growth | ~2 KB per knowledge record |

All latencies are measured and reported in every snapshot response.

---

## 14. Scalability Measurements

Reported live in `get_learning_performance()`:

| Metric | Reported Field |
|--------|---------------|
| Trades indexed | `scalability.trades_indexed` |
| Knowledge records | `scalability.knowledge_records` |
| Patterns stored | `scalability.patterns_stored` |
| Search throughput | "~20 results per query" |
| Learning throughput | "~N trades/session" (dynamic) |
| Memory usage estimate | "~N KB" (dynamic, 2 KB/record) |

---

## 15. Test Count

**109 tests across 14 test classes**

---

## 16. Test Results

```
109 passed in 0.20s
```

| Class | Tests | Description |
|-------|-------|-------------|
| `TestLearningMetrics` | 10 | compute_learning_metrics |
| `TestLearningInsights` | 10 | compute_learning_insights |
| `TestPatternDiscovery` | 6 | discover_patterns |
| `TestLearningAgent` | 10 | LearningAgent.execute + status |
| `TestKnowledgeIndex` | 8 | build_knowledge_index |
| `TestKnowledgeSearch` | 9 | search_knowledge |
| `TestTradeMemory` | 8 | build_trade_memory |
| `TestLessonsLibrary` | 8 | generate_lessons_library |
| `TestKnowledgeAgent` | 8 | KnowledgeAgent.execute + search |
| `TestLearningSharedServices` | 3 | Learning Agent shared_services |
| `TestKnowledgeSharedServices` | 4 | Knowledge Agent shared_services |
| `TestLearningLayerAggregation` | 11 | Learning Layer aggregation |
| `TestFeatureFlags` | 7 | All 4 feature flags |
| `TestSupervisorIntegration` | 6 | Agent IDs, versions, heartbeat |

---

## 17. Known Limitations

1. **Trade memory is per-request** — stateless design means no cross-session persistence. A Postgres-backed `learning_memory` table would be required for durable history (future phase).

2. **Confidence calibration** uses available `outcome` fields on recommendations. Outcomes are only populated for resolved recommendations — pending recs contribute neutral calibration (0.5).

3. **Pattern confidence grows with occurrences** but is bounded (max ~0.90). Patterns with 1 occurrence may appear if thresholds are met; single-occurrence patterns should be treated as tentative.

4. **Knowledge search is keyword-based** — not semantic/vector search. Queries must contain terms present in the indexed entry text. True NLP search would require an embedding model (future integration).

5. **Operator annotations** are sourced from localStorage on the frontend. The backend currently returns an empty list; a future phase could expose an `/annotations` endpoint to sync them.

6. **Regime performance** uses the current regime from the risk snapshot, not per-trade historical regimes. Historical regime attribution would require the regime to be stored at trade execution time.

---

## 18. Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                  Phase 10D — Learning Layer                     │
│                    READ-ONLY · ADVISORY-ONLY                    │
├────────────────────────┬────────────────────────────────────────┤
│    Learning Agent      │       Knowledge Agent                  │
│    (learning_agent/)   │       (knowledge_agent/)               │
│                        │                                        │
│  Consumes:             │  Consumes:                             │
│  • Decision Snapshot   │  • Research Snapshot                   │
│  • Paper Trades        │  • Timeline Events                     │
│  • Risk Snapshot       │  • Learning Snapshot                   │
│  • Strategy Snapshot   │  • Decision Snapshot                   │
│  • Timeline Events     │  • Paper Trades                        │
│                        │  • Operator Annotations               │
│  Produces:             │                                        │
│  • 9 Learning Metrics  │  Produces:                             │
│  • 8 Insights          │  • Knowledge Index (all types)         │
│  • Pattern Discovery   │  • NL Search                          │
│  • Health Assessment   │  • Trade Memory                        │
│                        │  • Lessons Library                     │
│                        │  • Pattern Discovery                   │
└────────────┬───────────┴──────────────┬─────────────────────────┘
             │                          │
             └──────────┬───────────────┘
                        │
             ┌──────────▼───────────┐
             │   learning_layer/    │
             │   shared_services    │
             │                      │
             │  • get_learning_summary()    → Command Centre
             │  • get_learning_timeline()   → Trading Timeline
             │  • get_learning_performance()→ Performance metrics
             └──────────────────────┘
```

---

## 19. Sequence Diagram

```
Operator requests /command-center
         │
         ▼
  CommandCenter.tsx
  LearningLayerCard
         │
         ▼ GET /api/learning-layer/summary
  learningLayer.ts router
         │
         ▼ runPython("agent_learning_summary")
  main.py dispatch
         │
         ├──▶ learning_agent.shared_services.get_learning_snapshot()
         │         │
         │         ▼ LearningAgent.execute()
         │         ├── portfolio_store.load_portfolio()      → trades
         │         ├── ai_decision_agent.get_recommendations() → recs
         │         ├── risk_agent.get_risk_snapshot()         → risk
         │         ├── strategy_agent.get_strategy_snapshot() → strategy
         │         └── compute_learning_metrics() + insights + patterns
         │
         └──▶ knowledge_agent.shared_services.get_knowledge_snapshot()
                   │
                   ▼ KnowledgeAgent.execute()
                   ├── build_knowledge_index() → 6 entry types
                   ├── build_trade_memory()    → per-trade records
                   ├── generate_lessons_library()
                   └── discover_patterns()
         │
         ▼ JSON response → LearningLayerCard renders
```

---

## 20. Learning Flow Diagram

```
Completed Paper Trade
         │
         ├──▶ LearningAgent
         │         ├── compute_learning_metrics()
         │         │       → win rate, accuracy, calibration,
         │         │         holding time, R:R, sector perf,
         │         │         regime perf, risk accuracy, exec accuracy
         │         ├── compute_learning_insights()
         │         │       → best/worst strategy, top/weak sector,
         │         │         most reliable rec type, rejection reasons,
         │         │         risk warnings, recurring patterns
         │         └── discover_patterns()
         │                 → GAP_BREAKOUT, HIGH_VIX_FALSE_BREAKOUT,
         │                   MORNING_MOMENTUM_FADE, SECTOR_ROTATION,
         │                   REPEATED_RISK_FAILURES (or BASELINE)
         │
         └──▶ KnowledgeAgent
                   ├── build_knowledge_index()
                   │       → TRADE / RECOMMENDATION / RESEARCH /
                   │         TIMELINE_EVENT / DECISION_EXPLANATION /
                   │         ANNOTATION entries
                   ├── build_trade_memory()
                   │       → decision + execution + outcome + lessons
                   ├── search_knowledge(query)
                   │       → NL keyword search over index
                   └── generate_lessons_library()
                           → what_worked / what_failed /
                             what_to_review / what_to_monitor /
                             open_questions
                                     │
                                     ▼
                           Operator Reviews (ALL advisory)
                           No automated model/strategy changes
```

---

## 21. READ-ONLY / ADVISORY Architecture Confirmation

✅ **No model retraining** — `auto_model_updates = False` hardcoded in `LearningAgent.execute()`; verified by test `test_auto_model_updates_always_false`.

✅ **No parameter tuning** — `auto_strategy_tuning = False` hardcoded; verified by test `test_auto_strategy_tuning_always_false`.

✅ **No order placement** — neither agent contains any `portfolio_store.add_trade()` or order execution calls.

✅ **No automatic optimisation** — all outputs are advisory. The spec's constraint is enforced structurally (agents are read-only consumers only).

✅ **Feature flags** — `LEARNING_AGENT_ENABLED`, `KNOWLEDGE_AGENT_ENABLED` (both default true). `AUTO_MODEL_UPDATES` and `AUTO_STRATEGY_TUNING` are named constants in `agent_framework/config.py` but never set to true anywhere in the codebase.

✅ **Operator approval required** — all snapshot responses include `"advisory_only": true` and all UI pages display the ADVISORY badge and safety alert banners.

---

**PHASE 10D COMPLETE** ✅

- **109/109 tests pass**
- **0 TypeScript errors**
- **13 new API endpoints** (all GET, read-only)
- **6 new React pages**
- **2 new AI agents** (Learning + Knowledge)
- **1 aggregation layer** (Learning Layer)
- **Command Centre updated** with LearningLayerCard
- **Agent 9 populated** with all 6 Learning Layer pages
- **Phase-9-compatible timeline** with 5 new event types
- **Fully advisory** — no model changes, no parameter tuning, no order placement
