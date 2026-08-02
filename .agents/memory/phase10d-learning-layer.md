---
name: Phase 10D Learning Layer
description: Architecture decisions and test pitfalls for the Phase 10D Learning Layer (Learning Agent + Knowledge Agent)
---

## Key architecture decisions

- **Stateless per-request** — same pattern as Phase 10B/10C: both agents instantiate fresh per API call, no singleton state.
- **Safety flags hardcoded** — `auto_model_updates = False` and `auto_strategy_tuning = False` are **hardcoded in `LearningAgent.execute()`**, not derived from env vars. Tests verify this explicitly.
- **`discover_patterns` lives in `learning_agent.learning_engine`** — the `KnowledgeAgent` imports it from there (`from learning_agent.learning_engine import discover_patterns`), NOT from `knowledge_agent.knowledge_engine`. Confusion here caused early import errors.
- **`LearningAgent` is imported locally inside functions** in `shared_services.py` (inside each function body with `from .agent import LearningAgent`). Therefore mock patches must target `learning_agent.agent.LearningAgent` not `learning_agent.shared_services.LearningAgent`.
- **`trades_analysed` is inside `metrics` dict** — returned by `compute_learning_metrics()` as a key inside its return dict. The `get_learning_summary()` reads it via `metrics.get("trades_analysed", 0)`. Test stubs must include it inside `metrics`.

## What's built

- `learning_agent/` — agent + learning_engine + shared_services (4 endpoints)
- `knowledge_agent/` — agent + knowledge_engine + shared_services (6 endpoints)  
- `learning_layer/` — aggregation layer (3 endpoints)
- `test_learning_layer.py` — 109/109 tests, 14 classes
- 6 new React pages under Agent 9 — Learning
- `LearningLayerCard` in CommandCenter
- 13 new dispatch cases in main.py
- Routes in `learningLayer.ts`, mounted in `index.ts`

## Dispatch commands added (main.py)
- `agent_learning_snapshot/metrics/insights/status`
- `agent_knowledge_snapshot/search/patterns/lessons/memory/status`
- `agent_learning_summary/timeline/performance`

## Win-rate check location
The "Win rate below 40%" advisory is in `what_to_review` (not `what_to_fail`) in `generate_lessons_library()`.

**Why:** Win rate below 40% is a signal to review entry criteria, not a confirmed failure of a specific trade — so it fits the review category.
