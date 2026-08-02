---
name: Phase 10E Collaborative Intelligence + Autonomous Operations
description: CollaborationEngine + AutonomousOpsAgent design, pitfalls, and test patterns.
---

## What was built
Phase 10E added two new agent packages and one aggregation layer:
- `collaboration_engine/` — 11-node dependency graph, 10 edges, decision lineage, alerts, comm monitor
- `autonomous_operations/` — 8-component weighted health score, scalability dashboard, supervisor extensions
- `collaboration_layer/` — aggregation layer (summary / timeline / performance) consumed by Command Centre

## Collaboration Graph
- 11 agents, 10 directed edges
- Supervisor → market_data is the first edge (supervisor_snapshot consumed by market_data)
- Then 9 downstream handoffs (market_data→research→…→knowledge)
- Edge count = 10, Node count = 11

## System Health Score
8-component weights that sum to 1.0:
Agent=0.30, Snapshot=0.15, Heartbeat=0.10, Timeline=0.10, Knowledge=0.10, Learning=0.05, Performance=0.10, Collaboration=0.10

## Safety hardcodes
- `CollaborationEngine`: `AUTONOMOUS_EXECUTION = False`, `AUTO_RECOVERY = False`
- `AutonomousOpsAgent`: `AUTONOMOUS_EXECUTION = False`, `AUTO_RECOVERY = False`, `AUTO_STRATEGY_TUNING = False`, `AUTO_AI_RETRAINING = False`, `AUTO_PORTFOLIO_CHANGES = False`
- Never derive these from env vars.

## Critical pitfalls

### Mock patch targets
All agent classes import their collaborators **locally inside function bodies** (e.g., `from .collaboration_alerts import generate_collaboration_alerts`).
- Patching `collaboration_engine.agent.generate_collaboration_alerts` will fail if it's a local import.
- **Fix**: import the function at module level with an alias (e.g., `from .collaboration_alerts import generate_collaboration_alerts as _gen_alerts`) so the mock can patch `collaboration_engine.agent._gen_alerts`.
- Same principle: if `get_comm_monitor()` imports `build_collaboration_graph` locally, patch `collaboration_engine.collaboration_graph.build_collaboration_graph`, not `collaboration_engine.shared_services.build_collaboration_graph`.

### runPython not exported from python-env
`../lib/python-env` only exports `PYTHON_BIN` and `PYTHON_DIR`. Every route file must define its own inline `runPython` using `spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], { cwd: PYTHON_DIR })`. See `learningLayer.ts` for the canonical pattern.

### _HISTORY ring buffer
`operations_engine._HISTORY` is a module-level list — accumulates across tests in the same process. Tests checking its length must use `assertGreaterEqual`, not `assertEqual`.

### test_unavailable_snap_gives_unavailable_status
When `_safe_call` returns None, Step 7 (ai_decision) returns `NO_RECOMMENDATIONS` not `UNAVAILABLE` because it has no recommendations to surface. The test should check that zero steps return `AVAILABLE`, not that all return `UNAVAILABLE`.

## Route files
- `collaborationEngine.ts` — 10 GET routes under `/collab/`
- `autonomousOps.ts` — 5 GET routes under `/autonomous-ops/`

## Tests
110/110 in `test_phase10e.py` (13 test classes).

**Why:** Stateless per-request pattern keeps agents simple but makes health probing expensive (all 11 agents probed per graph build). A persistent SnapshotBus registry would be needed for sub-ms graph builds.
