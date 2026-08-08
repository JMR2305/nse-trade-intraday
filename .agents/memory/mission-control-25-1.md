---
name: Mission Control 25.1 live-ops widgets
description: Conventions for the Phase 25.1 widget layer — shared-data props, ledger hook, layout manager, display-only alert state, investigation deep links.
---

- New widgets live in `SessionWidgets.tsx` (session/throughput/performance/breadth) and `DeepWidgets.tsx` (agents/stock-watch/explainability/system-health-2); all lazy chunks.
- Shared canonical data flows DOWN as props: replay snapshot, portfolio snapshot, scan status, SSE market object; `useLedgerToday()` is called once page-level and shared. Never add a second fetch of these in a widget.
- **Why:** duplicate fetches of the replay snapshot / ledger were the primary perf bug class in 25A/B.
- Alert ack/dismiss is display-level only (localStorage `mc-alert-state-v1`) — there is NO backend alert mutation; don't invent one.
- Layout customization: `LayoutManager.tsx`, localStorage `mc-layout-v1`, stable section ids (market-session … event-feed). New sections must be added to `MC_SECTIONS` or they won't reconcile.
- InvestigationCenter accepts deep-link params `?run=&symbol=&trade=&ts=` (applied progressively as runs/symbols/bundle load, then consumed). Event feed + Mission Timeline emit these links.
- SystemHealth2 engine probes must stay CHEAP status/list endpoints; Redis row intentionally omitted (no Redis in stack). Widget chrome is driven by the observability query, so its failure hides all cells — degrade tests should fail an engine probe instead.
- Dashboard vitest runs need `PORT=9999 BASE_PATH=/trading-dashboard/` env (vite.config throws otherwise); package `test` script sets them.
