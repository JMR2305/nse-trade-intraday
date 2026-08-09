---
name: Pipeline stage visibility pattern
description: Durable rules for exposing a new gate/stage in the trading pipeline events, replay, and dashboards
---
- Emit gate events at the true decision point, copying the engine's exact reason list; the emitter must be fail-safe and must never recompute or alter the decision. Replay reconstructs decisions from stored events only.
- **Why:** the Portfolio Engine (or any gate engine) must remain the single source of validation logic, and all dashboards must show identical event-derived counts.
- **How to apply:** when adding a pipeline stage, update every hardcoded stage list in lockstep — backend stage vocabulary, replay stage builder AND its module-level STAGES constant, ops trace order, and all frontend stage arrays (several funnels are index-mapped label/count pairs that silently shift otherwise, and rejection-view event-type filters won't show the new REJECTED type unless added).
- Count honesty: a gate that only evaluates a subset (e.g. actual BUY attempts) must expose approved/evaluated/not_evaluated separately; never label pass-through flow as "approved". Per-symbol journeys must mark downstream stages SKIPPED when an upstream gate blocked the symbol.
- Scan attribution: every production path that reaches the gate must carry the canonical scan id (fail-safe to None), or the scan-scoped replay will silently drop real decisions.
- Frontend vitest needs `PORT=9999 BASE_PATH=/trading-dashboard/`; freshness-coverage.test.ts has ~65 pre-existing failures unrelated to pipeline work.
