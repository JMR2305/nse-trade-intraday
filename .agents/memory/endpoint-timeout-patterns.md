---
name: Endpoint timeout patterns
description: Several endpoints exceed apiJson's 15 s default timeout; pattern for fixing and caching slow Python aggregate endpoints.
---

## The Problem

`apiJson()` has a 15 s default timeout. Several aggregate Python endpoints take longer than that on cold start, causing the frontend to show a permanent loading skeleton or stale error state even though the backend eventually succeeds.

## Known slow endpoints and their warm-start times

| Endpoint | Cold-start | Warm (cached) | Fix |
|---|---|---|---|
| `/api/ops-centre/snapshot` | 22–30 s | ~30 s cache | Pass `60_000` as 3rd arg to `apiJson` |
| `/api/command-center/summary` | 14.8 s | 30 s Node.js cache | 30 s Node.js cache + `apiJson(…, undefined, 30_000)` in `q()` |
| `/api/command-center/briefing` | 21.7 s | 30 s Node.js cache | 30 s Node.js cache + coalescing in command-center.ts |
| `/api/analysis-agents/summary` | 8–10 s | 30 s Node.js cache | 30 s Node.js cache + coalescing in analysisAgents.ts |
| `/api/agent-framework/agents` | 25 s | 30 s Node.js cache | 30 s Node.js cache + coalescing in agentFramework.ts; 45 s timeout in AgentOperations.tsx |

## Fix pattern

**Backend (TypeScript route)**
```typescript
const TTL = 30_000;
let cache: { data: unknown; ts: number } | null = null;
let inFlight: Promise<unknown> | null = null;

router.get("/slow-endpoint", async (_req, res) => {
  try {
    if (cache && Date.now() - cache.ts < TTL) { res.json(cache.data); return; }
    if (!inFlight) {
      inFlight = runPython(["command"], 90_000)
        .then(d => { cache = { data: d, ts: Date.now() }; return d; })
        .finally(() => { inFlight = null; });
    }
    res.json(await inFlight);
  } catch (e: any) { res.status(500).json({ error: e.message }); }
});
```

**Frontend (React Query)**
```typescript
// Always specify an explicit timeout when the endpoint might exceed 15 s
queryFn: () => apiJson("slow-endpoint", undefined, 45_000),
retry: 2,
retryDelay: (n) => Math.min(2000 * 2 ** n, 10_000),
```

**Why:**
- `apiJson` defaults to 15 s. If the cold-start exceeds that, the query fails and shows a permanent loading skeleton.
- Node.js in-process cache + coalescing ensures the backend only ever runs one Python subprocess per cache TTL regardless of how many concurrent requests arrive.
- Cache should be invalidated on `scan.completed` events for endpoints whose data changes after a scan.

## Cache invalidation

`clearAgentsCache`, `clearPlatformCache`, `clearCommandCenterCache` are all called from the `scan.completed` event in `artifacts/api-server/src/routes/trading.ts`.
