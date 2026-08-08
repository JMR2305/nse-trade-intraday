---
name: Mission Control (Phase 25A)
description: Conventions & pitfalls for the /mission-control dashboard and its data sources.
---

- Every registered dashboard route MUST render `<DataFreshnessBar>` (any variant) or the literal "No live dataset used on this page" marker — `src/lib/freshness-coverage.test.ts` parses App.tsx and fails otherwise. ~61 legacy pages already fail this (pre-existing baseline); don't count them as new regressions.
- Canonical replay build for the newest scan: `GET /api/replay/sessions/latest` (explicit route registered before `:scanId`; replay_engine resolves "latest"). Payload stages carry stocks_in/stocks_out/rejected/pending/cancelled/duration_ms — the ONLY sanctioned pipeline count source. Heavy (~30s Python): poll slowly with explicit 45s timeout; use fast `/pipeline/summary` (5s cache) for live animation.
- `useLiveStream` now exposes `pipelineEvents` (newest-first ring buffer, max 100) so panels can render SSE events immediately and merge/dedupe with the REST `/pipeline/events` feed by id. Use one `useLiveStream()` per page and pass it down — each call opens its own EventSource.
- Reviewer contract: "live" pages should invalidate all affected canonical queries on stream events (pipeline event → feed/summary/ledger/portfolio; scanEvent → scan/replay/summary/portfolio), not only the event feed.
- Widget framework: `src/components/mission/Widget.tsx` — per-widget query key/cadence/timeout, error inline, stale pill at 2× cadence.
- `/portfolio/snapshot` real shape (portfolio_snapshot.py): equity, cash, invested_value, unrealised_pnl, realised_pnl_today, open_positions (avg_entry_price/market_value/unrealised_pnl), sector_exposures, open_position_count — richer than what LiveCommandCenter consumes.
