---
name: Mission Control 25C
description: Command bar, global search, responsive/perf and test lessons for Mission Control completion.
---

## Command bar
- All actions map to existing control endpoints: scan run/abort, risk kill-switch trigger/resume (resume needs `{acknowledge:true}`), phase17 reports. Emergency Stop = scan abort + kill-switch trigger via `Promise.allSettled` with partial-failure messaging.
- **Why:** no new backend logic allowed; kill switch is the single AI pause mechanism.

## Configurable home
- `lib/homeRoute.ts`: pref `auto|mission-control|command-center` in localStorage; auto = Mission Control Mon–Fri 09:00–15:30 IST via `Intl.DateTimeFormat` parts (never local timezone math). AppLayout pinned Home + AUTO/MC/CC toggle.

## Vitest 4 + React Query gotcha
- Touching a `vi.fn()` API mock inside `beforeEach` (`mockReset()` **or** `mockClear()`) makes React Query's handled queryFn rejections surface as unhandled errors and fails the test (~50ms in). Fix: no mock-touching hooks; each test installs its own implementation. Also assert the error UI **before** the happy-path text, and give `useWidgetQuery` a `retry` override (`retry:false` in tests) to dodge retry backoff.

## Perf pattern
- Widget rows below the fold are `React.lazy(() => import(...).then(m => ({default: m.Named})))` behind Suspense skeletons; event feed uses hand-rolled windowing (fixed 22px rows, absolute-positioned slice) — no dependency needed.

## Search extension
- QuickSwitcher warm cache fetches all sources with `Promise.allSettled` and tolerant shape-parsing (`Array.isArray(v) ? v : v?.sessions ?? v?.data ?? []`) because ledger/replay/events/recommendations responses differ in envelope shape.

**How to apply:** any new Mission Control action must reuse existing endpoints + confirm dialogs for impactful ops; any new widget row goes in a lazy chunk.
