# Phase 10A — Multi-Agent Framework
## ApexQuant AI NSE Intraday Trading Platform

**Status**: ✅ Complete  
**Tests**: 93 / 93 passed  
**TypeScript**: 0 errors  
**READ-ONLY**: ✓ All agents  
**ADVISORY-ONLY**: ✓ All agents  
**Auto-restart**: ✗ Supervisor NEVER auto-restarts agents

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                  Multi-Agent Framework (Phase 10A)              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐   │
│  │ MarketData   │   │  Research    │   │   (Future)       │   │
│  │   Agent      │   │   Agent      │   │   Agents...      │   │
│  │ (READ-ONLY)  │   │ (READ-ONLY)  │   │  (READ-ONLY)     │   │
│  └──────┬───────┘   └──────┬───────┘   └──────────────────┘   │
│         │                  │                                    │
│         ▼                  ▼                                    │
│  ┌─────────────────────────────────────┐                       │
│  │          SnapshotBus                │                       │
│  │   (topic-based pub/sub · thread-safe│                       │
│  │    no direct agent-to-agent calls)  │                       │
│  └─────────────────────┬───────────────┘                       │
│                         │                                       │
│         ┌───────────────▼──────────────┐                       │
│         │      SupervisorAgent         │                       │
│         │  (reads AgentRegistry + Bus  │                       │
│         │   advisory alerts only       │                       │
│         │   NEVER auto-restarts)       │                       │
│         └───────────────┬──────────────┘                       │
│                         │                                       │
│  ┌──────────────────────▼──────────────────────────────────┐   │
│  │             Infrastructure Layer                         │   │
│  │  AgentRegistry · LifecycleManager · HeartbeatService     │   │
│  │  HealthMonitor · AgentScheduler · FrameworkMetrics       │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Sequence Diagram: Agent Snapshot Publication

```
MarketDataAgent          SnapshotBus           SupervisorAgent
      │                       │                      │
      │ execute_task()        │                      │
      │──────────────────>    │                      │
      │ publish("market_data",│                      │
      │         payload)      │                      │
      │──────────────────>    │                      │
      │                       │ store envelope       │
      │                       │──────────────────>   │
      │                       │                      │ snapshot()
      │                       │ latest("market_data")│
      │                       │<─────────────────────│
      │                       │ return envelope      │
      │                       │──────────────────>   │
      │                       │                      │ aggregate
      │                       │                      │ + advisory alerts
```

## Agent Interaction Diagram

```
AgentRegistry
  register(agent)  →  agent.record stored
  get(agent_id)    →  AgentRecord
  summary()        →  {total, running, idle, ...}

LifecycleManager
  start(rec)   → INITIALIZING → RUNNING
  pause(rec)   → RUNNING → PAUSED
  resume(rec)  → PAUSED → RUNNING
  stop(rec)    → any → STOPPED
  mark_error() → any → ERROR
  mark_busy()  → RUNNING → BUSY
  mark_idle()  → BUSY → IDLE/RUNNING

HeartbeatService
  check(agent_id, last_heartbeat, interval)
  → OK | LATE | MISSED | STALLED | NEVER

HealthMonitor (scoring)
  state        40 pts  (RUNNING=40, IDLE=35, BUSY=30, PAUSED=20, WARNING=15, ERROR=5, STOPPED=0)
  heartbeat    30 pts  (OK=30, LATE=20, MISSED=10, STALLED=0, NEVER=0)
  error_rate   20 pts  (0 errors=20, decreases with error count)
  activity     10 pts  (recent snapshots published)
  ─────────────────────
  total       100 pts  (70+ Healthy · 40–69 Degraded · <40 Critical)
```

## Deliverables

### Python Backend (`artifacts/api-server/src/python/`)

| Module | File | Purpose |
|--------|------|---------|
| agent_framework | `models.py` | AgentState (9 states), AgentRecord, SnapshotEnvelope, HealthStatus |
| agent_framework | `config.py` | Feature flags + disabled_response() |
| agent_framework | `snapshot_bus.py` | Singleton pub/sub bus, thread-safe |
| agent_framework | `heartbeat_service.py` | OK/LATE/MISSED/STALLED/NEVER detection |
| agent_framework | `metrics.py` | AgentMetrics, FrameworkMetrics, ScalabilityEstimator |
| agent_framework | `agent_registry.py` | Singleton registry, CRUD, queries |
| agent_framework | `lifecycle_manager.py` | Valid state machine transitions |
| agent_framework | `scheduler.py` | Periodic + one-shot task scheduler |
| agent_framework | `health_monitor.py` | 0–100 health scoring, advisory alerts |
| agent_framework | `base_agent.py` | Abstract base; lifecycle/heartbeat/publish wired |
| supervisor_agent | `supervisor.py` | Advisory alerts only; NEVER auto-restart |
| supervisor_agent | `shared_services.py` | 5 shared service functions |
| market_data_agent | `agent.py` | Reads scan_state_store + market_intelligence_hub |
| market_data_agent | `shared_services.py` | 3 shared service functions |
| research_agent | `agent.py` | Reads event_intelligence + macro_intelligence + research_lab |
| research_agent | `shared_services.py` | 3 shared service functions |

### main.py Commands (9 new)

| Command | Description |
|---------|-------------|
| `agent_supervisor_snapshot` | Full supervisor snapshot |
| `agent_list` | All registered agents |
| `agent_detail <id>` | Single agent detail |
| `agent_supervisor_alerts` | Advisory alerts |
| `agent_market_data_snapshot` | Market data agent output |
| `agent_market_data_metrics` | Market data agent metrics |
| `agent_research_snapshot` | Research agent output |
| `agent_research_metrics` | Research agent metrics |
| `agent_scalability` | Scalability estimator |

### Node.js Routes (`artifacts/api-server/src/routes/agentFramework.ts`)

| Route | Description |
|-------|-------------|
| GET /agent-framework/supervisor/snapshot | Full supervisor snapshot |
| GET /agent-framework/supervisor/alerts | Advisory alerts |
| GET /agent-framework/scalability | Scalability estimate |
| GET /agent-framework/agents | Agent registry list |
| GET /agent-framework/agents/:agentId | Single agent detail |
| GET /agent-framework/market-data/snapshot | Market data snapshot |
| GET /agent-framework/market-data/metrics | Market data metrics |
| GET /agent-framework/research/snapshot | Research snapshot |
| GET /agent-framework/research/metrics | Research metrics |

### Frontend (`artifacts/trading-dashboard/src/pages/AgentOperations.tsx`)

9-section page:
1. PageHeader (advisory, readOnly, faqs, relatedPages)
2. Overall Health + Supervisor Summary strip (8 KPI tiles)
3. Agent Registry Table (DataTable, sortable, exportable)
4. Supervisor Alerts (AlertCard, advisory-only note)
5. Market Data Snapshot card
6. Research Snapshot card
7. Scalability Estimator (8 StatCards)
8. Snapshot Bus stats (topic count, sequence numbers)
9. Advisory footer

### Navigation
- `/agent-operations` added to Operations Agent in `AgentConfig.ts`
- Route added in `App.tsx`

## Performance Benchmarks

| Metric | Value |
|--------|-------|
| test_agent_framework.py | 93 / 93 passed (46.2s) |
| TypeScript errors | 0 |
| Routes | 9 GET |
| Python modules | 15 files across 4 packages |
| Health scoring | 0–100, 4-component weighted |
| State machine | 9 states, strict transition table |

## Scalability Estimates (Advisory)

| Scenario | Symbols | Agents | Interval |
|----------|---------|--------|----------|
| Current | 50 | 2 | 900s |
| Safe | 100 | 10 | 900s |
| Max estimated | 200 | 50 | 1800s |

_All advisory-only. Actual limits depend on yfinance rate limits, Postgres load, and network._

## Safety Guarantees

1. **No auto-restart**: `auto_action: null` on every Supervisor alert
2. **No analysis in agents**: MarketDataAgent + ResearchAgent return raw normalised data only
3. **No forbidden fields**: Tests verify absence of buy/sell/order/strategy recommendation fields
4. **Circuit isolation**: SnapshotBus subscriber errors never propagate to the publisher
5. **Scheduler safety**: Task errors are recorded on the task record, never propagated
6. **Feature flags**: All 3 flags default to `true`; `disabled_response()` with standard shape when off
7. **Singleton safety**: `AgentRegistry.reset()` and `SnapshotBus.reset()` available for tests only

## Known Limitations

- MarketDataAgent and ResearchAgent use best-effort reads from existing caches; graceful on empty data
- Scalability estimates are heuristic; not measured against live load
- Heartbeat detection relies on wall-clock timestamps; clock skew between processes not handled
- Supervisor health score is an advisory estimate; not a substitute for infrastructure monitoring

## READ-ONLY / ADVISORY-ONLY Confirmation

✅ No trading engine calls  
✅ No risk engine calls  
✅ No portfolio engine calls  
✅ No strategy logic calls  
✅ No AI model inference  
✅ No order execution  
✅ Supervisor never auto-restarts agents  
✅ All endpoints are GET (read-only)  
✅ All agent methods are read-only observers  
