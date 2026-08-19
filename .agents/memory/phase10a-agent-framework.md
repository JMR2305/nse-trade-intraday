---
name: Phase 10A Multi-Agent Framework
description: Agent Framework infrastructure — registry, lifecycle, heartbeat, snapshot bus, supervisor, market data agent, research agent. All READ-ONLY and ADVISORY-ONLY.
---

## Core rule
Supervisor NEVER auto-restarts agents. Every alert must have `auto_action: null`. This is enforced in both the HealthMonitor and the SupervisorAgent.

**Why:** Operator must remain in control of all agent lifecycle changes. Auto-restart would bypass this.

**How to apply:** Any new alert-generating code must set `auto_action: null`.

## Singleton pattern
`AgentRegistry` and `SnapshotBus` are process-level singletons accessed via `.instance()`. Tests must call `.reset()` in `autouse` fixtures. Never call `.reset()` in production code.

## Agent lazy initialization
Agents do NOT start at import time. They initialize on first `shared_services.*()` call via the `_get_agent()` pattern. The `/agent-operations` page will show "No agents registered" until the first API call triggers initialization.

## Cross-process Agent Operations details
Agent Operations list and per-agent detail must both derive from the canonical ops snapshot, never the in-process `AgentRegistry`.

**Why:** API routes spawn a fresh Python process for each request, so its registry is empty even when canonical collectors can report a live agent. Retrying a registry-backed detail request would remain unavailable forever.

**How to apply:** Keep detail response fields compatible with the Agent Operations panel, mark only true collection failures as recoverable, and cover this with an unmocked fresh-process command test.

## DS component prop names (Phase 10A-verified)
- `StatusBadge`: uses `variant` (not `status`)
- `HealthCard`: uses `label` (not `title`); `details` is a string (not `items` array)
- `EmptyState`: requires `description`; `why` is optional
- `AlertCard`: no `footer` prop; fold recommendation into `body`
- `StatCard`: no `changeColor`; use `changeLabel` instead
- `SectionHeader`: `badge` is `ReactNode` (not a string with color)
- `PageHeader`: `advisory` (not `advisoryOnly`)
- `DataTable`: uses `TableColumn<T>` (not `ColumnDef`); `label` (not `header`); `T` must extend `Record<string, unknown>`

## Pre-existing typecheck failures (unrelated to Phase 10A)
`lib/__tests__/cacheSchema.test.ts` and `lib/__tests__/phase1-connectivity.test.ts` fail the project-wide typecheck with "cannot find module 'vitest'". These are pre-existing. The trading-dashboard scoped `pnpm --filter trading-dashboard exec tsc --noEmit` passes clean.

## Test count
93/93 passed. Run from `artifacts/api-server/src/python/` via `python3 -m pytest test_agent_framework.py -v`.
