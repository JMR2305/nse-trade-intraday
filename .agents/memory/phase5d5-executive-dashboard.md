---
name: Phase 5D.5 Executive Dashboard
description: Aggregates 5D.1–5D.4 + preopen + risk into one read-only command centre; zero recalculation; stable shared_services for future phases.
---

## Key design decisions

**NEVER recalculate.** dashboard_engine._load_*() functions call existing module functions directly — no arithmetic over raw trade data.

**Load order is sequential** — 8 loaders run in order; each is independently guarded (try/except). A single broken module shows "No data" in that section, not a page crash.

**Why patch shared_services.load_all not dashboard_engine.load_all in tests:**
shared_services.py imports via `from .dashboard_engine import load_all` — this creates a local name binding. Patching `executive_dashboard.dashboard_engine.load_all` doesn't reach the already-bound name. Always patch `executive_dashboard.shared_services.load_all`.

## Stable future interface
`get_executive_snapshot()` — flat dict for super-dashboards/future phases:
`executive_score`, `executive_label`, `portfolio_value`, `net_pnl`, `win_rate`,
`ai_health_score`, `ai_trend`, `execution_score`, `open_positions`.

## Feature flags required for full data
EXECUTIVE_DASHBOARD_ENABLED + STRATEGY_INTELLIGENCE_ENABLED + AI_PERFORMANCE_ENABLED +
EXECUTION_QUALITY_ENABLED + PORTFOLIO_PERFORMANCE_ENABLED.

## Known gap
meta_health.get_meta_health() shape undocumented — system_health and market_snapshot sections
may show UNKNOWN; future fix: wire to live_data_provider.get_market_overview().

## Tests: 29/29 at 1.74s
