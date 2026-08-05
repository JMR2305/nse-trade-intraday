# ApexQuant AI — Session Task Ledger · 2026-08-05

> **Scope:** All tasks discussed, completed, proposed, or pending as of this session.
> Sections: [Completed](#completed-this-session) · [Fix Applied](#fix-applied-this-session) · [Pending / Proposed](#pending--proposed-tasks) · [Backlog sample](#backlog-sample-proposed-not-yet-started)

---

## Completed This Session

### Task #317 — 10-second Node.js cache for `/api/ops-centre/platform`
| | |
|---|---|
| **Category** | Performance |
| **Status** | ✅ Done |
| **File** | `artifacts/api-server/src/routes/trading.ts` |

**What was built**
- `PLATFORM_CACHE_MS = 10_000` in-process cache with a coalescing in-flight guard so concurrent requests share one Python process.
- `clearPlatformCache()` export wired to `eventBus.on("event")` — cache invalidates on `scan.completed`.
- `/ops-centre/snapshot` success path also clears the cache so a fresh full snapshot immediately supersedes the cached fast value.
- Benchmark: cold 341 ms → cached 9 ms (38× faster).

---

### Task #318 — Cache-staleness badge on the Platform Status bar
| | |
|---|---|
| **Category** | UX / Observability |
| **Status** | ✅ Done |
| **File** | `artifacts/trading-dashboard/src/pages/AIOperationsCentrePage.tsx` |

**What was built**
- `PlatformStatusBar` accepts `fast`, `generatedAt`, `cacheTs` props.
- Live 1-second age ticker: amber **"Cached snapshot · Ns ago"** when `fast=true`, emerald **"Live · Ns ago"** when `fast=false`.
- Age counts from `cache_ts` (real KV write time); falls back to `generated_at` for the provisional path.
- Mobile `PlatformHealthCard` in `artifacts/trading-mobile/app/(tabs)/ai-ops.tsx` derives Cached/Live from `generated_at` age (≥ 120 s = amber).

---

### Task #324 — Snapshot in-flight coalescing
| | |
|---|---|
| **Category** | Performance / Reliability |
| **Status** | ✅ Done |
| **File** | `artifacts/api-server/src/routes/trading.ts` |

**What was built**
- `snapshotInFlight` variable: concurrent `/ops-centre/snapshot` callers share one Python process instead of spawning duplicates.
- Tests: concurrent coalescing (#6), sequential requests each spawn independently (#7).

---

### Task #325 — Integration tests for platform cache invalidation
| | |
|---|---|
| **Category** | Test coverage |
| **Status** | ✅ Done |
| **File** | `artifacts/api-server/src/routes/platform-cache.test.ts` (new) |

**What was built**
Six tests covering: cache hit, `clearPlatformCache()` miss, `scan.completed` event clear, snapshot-success clear, concurrent coalescing, snapshot-failure does NOT clear cache.
49 → 51 passing.

---

## Fix Applied This Session

### AI Operations Centre — all sections blank / loading forever
| | |
|---|---|
| **Category** | Critical bug fix |
| **Status** | ✅ Fixed |
| **File** | `artifacts/trading-dashboard/src/pages/AIOperationsCentrePage.tsx` |

**Root cause**
`apiJson` carries a **15-second hard abort** (`DEFAULT_TIMEOUT_MS = 15_000`).
The `/ops-centre/snapshot` endpoint collects 12 agent snapshots in parallel and consistently returns in **22–30 seconds**.
Every browser request was silently killed at 15 s. React Query retried once (also killed), then gave up — `snapshotData` stayed `undefined` indefinitely.
All sections that read from `snapshotData` — Agent Health Summary, DependencyChain, Smart Insights, Confidence Distribution, Missed Opportunities, Pipeline Heatmap, Agent Load Monitor — showed loading skeletons or zeros forever.

**Changes made**

| Change | Before | After |
|---|---|---|
| Snapshot `apiJson` timeout | 15 000 ms (default) | **60 000 ms** explicit |
| React Query `retry` | 1 | **2** |
| Loading state banner | None | Teal spinner: "Fetching agent snapshot — takes ~25 seconds" |
| Error state banner | None | Rose card with **Retry** button |
| Agent Details badge | "Loading agent details…" | **"Fetching (~25s)…"** / "Snapshot failed" |
| Debug panel | None | Visible at `?debug` URL param — shows field counts, timestamps, React Query state |

**Verified data once snapshot lands**

| Section | Field | Value |
|---|---|---|
| Agent Health Summary | `healthy_count` | 12 (was 0) |
| Agent Health Summary | `slowest_agent` | Research Agent |
| DependencyChain | all statuses | 12 × ACTIVE (was UNKNOWN) |
| Smart Insights | count | 7 items populate |
| Confidence Distribution | `90_100` bucket | 9 stocks |
| Missed Opportunities | count | 10 stocks |
| Pipeline Heatmap | stages | 12 |
| Agent Load Monitor | agents | 12 |
| Recommendation Leaderboard | top_buy | 0 — correct (no BUY signals this cycle) |
| Pipeline Efficiency | pct | 0% — correct (0 stocks cleared risk gate) |

---

## Pending / Proposed Tasks

### Task #322 — Confirm the Cached-snapshot badge disappears the moment a fresh full scan lands
| | |
|---|---|
| **Category** | Test / Validation |
| **Status** | 🟡 PENDING |
| **Blocked by** | Concurrency limit |

**What to verify**
When a scheduled market scan completes and `/ops-centre/snapshot` returns `fast=false`, the amber "Cached snapshot" badge on the Platform Status bar must switch to the emerald "Live" badge **without** requiring a page reload.

**Acceptance criteria**
- Trigger a scan completion event (or mock `eventBus.emit("event", { type: "scan.completed" })`) while the page is open.
- Within the next React Query poll (≤ 10 s), the badge changes from amber → emerald.
- No manual refresh required.

**Relevant files**
- `artifacts/trading-dashboard/src/pages/AIOperationsCentrePage.tsx` — `PlatformStatusBar`, `effectivePlatform` merge logic, `fast` prop
- `artifacts/api-server/src/routes/trading.ts` — `clearPlatformCache()`, `scan.completed` listener
- `artifacts/api-server/src/routes/platform-cache.test.ts` — existing cache tests

---

### Task #323 — Show the same Cached/Live badge on the Command Centre platform header
| | |
|---|---|
| **Category** | UX / Consistency |
| **Status** | 🟡 PENDING |
| **Blocked by** | Concurrency limit |

**What to build**
The AI Operations Centre platform bar has an amber/emerald staleness badge. The **Command Centre** page (`/command-centre` or similar) has its own platform health header but no equivalent badge. Operators switching between pages get inconsistent staleness signals.

**Done looks like**
- Command Centre platform header shows the same amber "Cached snapshot · Ns ago" / emerald "Live · Ns ago" pill.
- Uses the same `/ops-centre/platform` fast endpoint (already polled every 10 s on that page).
- Live 1-second age ticker, same as the Ops Centre.

**Relevant files**
- `artifacts/trading-dashboard/src/pages/AIOperationsCentrePage.tsx` — `PlatformStatusBar` component (source of truth)
- Command Centre page (grep for `command-centre` in `src/pages/`)

---

### Task #327 — Stop concurrent Opportunity Scan requests from each spawning a separate Python process
| | |
|---|---|
| **Category** | Performance / Reliability |
| **Status** | 🟡 PENDING |

**What to build**
`/ops-centre/snapshot` already has in-flight coalescing (Task #324). The **Opportunity Scan** route (`/opportunity-scan` or similar) does not. If two operators click "Refresh Opportunity Scan" simultaneously, two Python processes spawn, doubling CPU/memory load.

**Done looks like**
- An `opportunityScanInFlight` variable mirrors the `snapshotInFlight` pattern in `trading.ts`.
- Concurrent callers join the single in-flight promise; only one Python process runs per scan.
- A test confirms that N concurrent requests produce exactly 1 Python spawn.

**Relevant files**
- `artifacts/api-server/src/routes/trading.ts` — `snapshotInFlight` (pattern to replicate)
- Grep for `opportunity-scan` in `artifacts/api-server/src/` to find the route

---

### Task #328 — Fix agent framework cross-page consistency
| | |
|---|---|
| **Category** | Bug fix / Data integrity |
| **Status** | 🔵 IN PROGRESS (task agent) |

**What to fix**
Agent framework pages (Research, Market Intelligence, Strategy, etc.) each call their own `/agent-framework/<agent>/snapshot` endpoint. Some derived fields (regime, confidence, rejection reasons) are re-computed per page rather than derived from the canonical phase-7 scan snapshot. This causes values to drift between pages.

**Done looks like**
- All cross-page values derive from the same canonical scan snapshot.
- Parity checker flags any missing required fields rather than silently skipping them.

**Relevant files**
- `artifacts/api-server/src/python/` — agent snapshot functions
- `artifacts/trading-dashboard/src/pages/` — individual agent pages
- `.agents/memory/cross-page-consistency.md` — governing rules

---

### Task #329 — Confirm `load_all` stays fault-tolerant if any section loader raises at startup
| | |
|---|---|
| **Category** | Reliability / Test |
| **Status** | 🟡 PROPOSED |

**What to verify**
The `load_all` / `load_section` aggregator in `shared_services.py` is meant to catch exceptions from individual section loaders and return neutral defaults rather than crashing the whole snapshot. Verify this holds end-to-end: if one loader (e.g. Paper Analytics) raises an `ImportError` or any other exception at startup, the Executive Score still returns a valid neutral score rather than a 500 error or a 0.

**Acceptance criteria**
- Mock one section loader to raise `ImportError`.
- `GET /executive-dashboard/snapshot` still returns HTTP 200 with the other sections populated.
- The affected section shows a neutral/empty value; all other sections are unaffected.
- Test is deterministic and does not rely on a real import failure.

**Relevant files**
- `artifacts/api-server/src/python/shared_services.py` — `load_all` / `load_section`
- `artifacts/api-server/src/python/executive_dashboard.py` — Executive Score aggregation
- `artifacts/api-server/src/python/paper_analytics/` — the module most likely to raise on import

---

### Task #330 — Confirm the Executive Score neutral fallback survives a hot-reload without resetting to zero mid-session
| | |
|---|---|
| **Category** | Reliability / Test |
| **Status** | 🟡 PROPOSED |

**What to verify**
When the API server hot-reloads (e.g. after a code change mid-session), the Executive Score should re-read its last known state from the database/cache rather than falling back to a transient 0. A 0 during a reload looks like a real score collapse to operators.

**Acceptance criteria**
- Simulate a hot-reload (restart the API server workflow) while a session is in progress.
- Within the next poll cycle, the Executive Score shows the last persisted value (not 0).
- If no persisted value exists, shows "—" or a clearly marked placeholder, not 0.

**Relevant files**
- `artifacts/api-server/src/python/executive_dashboard.py`
- `artifacts/api-server/src/python/shared_services.py`
- Postgres `scan_state_store` table (durable state source)

---

## Backlog Sample — Proposed, Not Yet Started

> Full list has 90+ tasks. Below are the highest-signal ones surfaced during this session.

| Ref | Title | Category |
|---|---|---|
| #171 | Warn operators on the Trade Decisions page when AI accuracy has been declining for 30 days | UX |
| #180 | Prevent the 09:20 reconciliation from running when all actual prices are null | Reliability |
| #182 | Confirm readiness score updates when auto-paper entries open, not only on position close | Validation |
| #208 | Confirm Performance Snapshot shows accurate stats after paper trades (not zeros) | Validation |
| #214 | Confirm Strategy Optimisation gives sensible results after 30+ real paper trades | Validation |
| #229 | Mark each trade entry and exit on the equity curve | UX |
| #230 | Confirm the equity chart renders correctly with exactly 1 or 2 data points | Validation |
| #234 | Show which strategies are viable for the current regime on Trade Decisions | UX |
| #235 | Prevent stale regime data from masking a transition that happened mid-session | Reliability |
| #236 | Apply `_as_str` coercion to string KPI fields in shared_services snapshot functions | Bug fix |
| #247 | Confirm neutral fallback protects Executive Score when Paper Analytics raises at startup | Reliability |
| #258 | Show per-domain quality trends on History tab so operators see which domain is degrading | UX |
| #259 | Include Data Quality in the Executive Score so a data outage visibly lowers the score | Feature |
| #260 | Show whether data quality is improving or declining on the Executive Dashboard | UX |
| #261 | Confirm the Data Quality widget stays accurate when the API server restarts mid-session | Reliability |
| #295 | Make the mobile Scan button use the same full-quality scan as the web dashboard | Bug fix |
| #303 | Confirm sparklines show the right shape when a position has been open through multiple scans | Validation |
| #304 | Persist intraday price snapshots per symbol so sparklines have richer history | Feature |
| #305 | Fix tsconfig references path so all three Playwright specs can run together | Dev tooling |
| #313 | Confirm the Risk Agent card stays ACTIVE after a full restart with no prior scan data | Validation |
| #314 | Show accurate rejection breakdown per gate on the Risk Agent card | UX |
| #315 | Show last known pipeline state when the mobile app opens offline | UX / Resilience |
| #316 | Alert operators on their phone when platform health drops below 70% mid-session | Feature |

---

## Key Engineering Rules Captured This Session

### apiJson timeout rule
Any API route whose Python work takes > 10 s **must** pass an explicit `timeoutMs` as the third argument to `apiJson`. Never rely on the 15 s default for slow aggregation endpoints.

```typescript
// ✅ Correct — snapshot takes 22-30 s
queryFn: () => apiJson("/ops-centre/snapshot", undefined, 60_000),

// ❌ Wrong — silent 15 s abort kills the request every time
queryFn: () => apiJson("/ops-centre/snapshot"),
```

### In-flight coalescing pattern (trading.ts)
```typescript
let snapshotInFlight: Promise<unknown> | null = null;

router.get("/snapshot", async (req, reply) => {
  if (!snapshotInFlight) {
    snapshotInFlight = runPython(...)
      .finally(() => { snapshotInFlight = null; });
  }
  const data = await snapshotInFlight;
  reply.send(data);
});
```
Apply the same pattern to any route with a slow Python process (opportunity-scan, etc.).

### Debug panel convention
Add `?debug` to any dashboard URL to reveal a violet debug panel showing field counts, timestamps, and React Query state. Gate with:
```typescript
const debugMode = useMemo(
  () => typeof window !== "undefined" && new URLSearchParams(window.location.search).has("debug"),
  [],
);
```
