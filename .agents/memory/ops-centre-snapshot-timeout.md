---
name: AI Ops Centre snapshot timeout
description: Why the snapshot query returned undefined and all sections stayed blank/loading
---

## The rule
The ops-centre snapshot query MUST pass an explicit timeout ≥ 60 000 ms to `apiJson`.

```typescript
queryFn: () => apiJson("/ops-centre/snapshot", undefined, 60_000),
```

**Why:** `apiJson` has a 15-second hard abort (`DEFAULT_TIMEOUT_MS = 15_000`). The Python snapshot
gathers 12 agent snapshots in parallel and consistently takes 22–30 s to return. Every request was
silently aborted, React Query retried once (also aborted), then `snapshotData` stayed `undefined`
forever — all sections rendered their loading/empty/zero states indefinitely.

**How to apply:** Any route whose Python work takes > 10 s must pass a matching `timeoutMs` argument
as the third parameter to `apiJson`. Never rely on the 15 s default for slow aggregation endpoints.

## Secondary findings (once timeout was fixed)
- **DependencyChain UNKNOWN** — was a downstream symptom, not a real bug. With data present all
  12 agents show ACTIVE.
- **RecommendationLeaderboard empty** — correct data; 0 BUY signals this cycle. Already has an
  empty-state message.
- **Pipeline Efficiency 0%** — correct data; 0 stocks cleared the full risk gate.
- **Confidence Distribution** — data was there (9 stocks in 90–100% bucket); just never delivered.
- **Smart Insights** — 7 items were there; just never delivered.

## Improvements added alongside the fix
- Loading banner: "Fetching agent snapshot — takes ~25 seconds" (teal, with spinner)
- Error banner: shown if snapshot fails after retries, with a Retry button
- Agent Details badge: shows "Fetching (~25s)…" while loading, "Snapshot failed" on error
- Debug panel: visible at `?debug` URL param; shows field counts, timestamps, React Query state
- `retry` bumped from 1 → 2 so transient failures get an extra chance
