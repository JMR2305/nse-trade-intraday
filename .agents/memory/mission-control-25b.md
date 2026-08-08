---
name: Mission Control 25B widgets
description: Intelligence & ops widget conventions for the Mission Control page (Mission Map, AI Health, Learning, Alerts, Replay, Backtest, Timeline, Broker, System Health)
---

# Mission Control 25B widgets

- The unified replay snapshot query (`["mc","replay-latest"]`, `/replay/sessions/latest`, 45s timeout) is fetched ONCE at page level in `MissionControl.tsx` and shared by PipelinePanel, MissionMapWidget and ReplayWidget. Never add a second fetch of stage counts.
- Widget components live in `src/components/mission/IntelWidgets.tsx` (Mission Map, AI Health, AI Learning, Alert Center) and `OpsWidgets.tsx` (Replay, Backtest, Mission Timeline, Broker, System Health); all use the 25A `<Widget>`/`useWidgetQuery` contract (own key, own cadence, error isolation, last-updated pill).
- Slow endpoints need explicit long timeouts or they hang on first paint: `/learning-layer/summary` ~12s+ (200s timeout), `/phase24/overview` (150s), `/replay/sessions/latest` ~25s cold, `/autonomous-ops/snapshot` (90s). First page load shows skeletons for up to ~30s — this is expected, not a bug.
- Alert Center dedupes by `SEVERITY|title` across observability alerts, operations alerts (may be `status: "DISABLED"` — render a note, not an error) and notification deliveries.
- Backtest launcher POSTs `/backtest/run` with IST dates via `toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" })`; polls `/backtest/runs` at 10s; `sharpe_ratio` may be absent from metrics — render "—".
- Mission Timeline positions dots by IST minutes (Intl.DateTimeFormat parts) across 09:00–15:30, filtered to today's IST date from `/pipeline/events`.

**Why:** widgets that fetched replay counts separately or used default 15s timeouts previously blanked panels (see endpoint-timeout-patterns.md).
**How to apply:** any new Mission Control widget must reuse shared queries where data overlaps and set an explicit timeout ≥ the endpoint's cold latency.
