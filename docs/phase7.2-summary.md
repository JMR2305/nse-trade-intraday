# Phase 7.2 — Event & Corporate Intelligence Hub

**Status:** ✅ Complete  
**Feature Flag:** `EVENT_INTELLIGENCE_ENABLED=true`  
**Classification:** Read-only · Advisory-only · Paper Trading  
**Platform:** ApexQuant AI — NSE Intraday Paper Trading System  
**Completed:** 2026-07-29

---

## Overview

Phase 7.2 introduces the **Event & Corporate Intelligence Hub**, a comprehensive read-only intelligence layer that aggregates corporate actions, regulatory alerts, market news, and event impact analysis into a single operator-facing dashboard. It builds directly on the Phase 7.1 Market Intelligence snapshot and scan signal caches — no new data sources are introduced beyond those already proven in production.

All six API endpoints are advisory-only. The module contains zero write paths to orders, portfolio, strategies, AI models, or risk engine state. This is enforced both architecturally (no relevant imports) and by an automated AST safety test that runs as part of the 68-test suite.

---

## Architecture

```
Python backend (event_intelligence/)
│
├── models.py               EventRecord dataclass, enums, grade/priority helpers
├── corporate_intelligence  Results, dividends, splits, board meetings, bulk deals
├── regulatory_intelligence ASM/GSM detection, F&O ban, NSE/SEBI circulars
├── news_intelligence       Company / sector / market / economic news, dedup
├── impact_engine           Importance/confidence scoring, historical patterns
├── timeline                Today / Past-7d / Past-30d / Upcoming / 7-day calendar
├── brief                   Daily Intelligence Brief (market tone, risk, opportunities)
├── shared_services         Public interface: 6 endpoints + snapshot + CSV/JSON export
└── api                     Command dispatch adapter (main.py integration)

TypeScript layer
├── routes/event-intelligence.ts   8 REST route handlers
└── routes/index.ts                Router registration

React frontend
└── pages/EventIntelligence.tsx    6-tab dashboard (Overview, Daily Brief, Corporate,
                                   News, Regulatory, Timeline)
```

---

## API Endpoints

All endpoints live under `/api/event-intelligence/`.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/summary` | Aggregated score, grade, event counts, key highlights |
| `GET` | `/corporate` | Corporate events — dividends, splits, results, board meetings, bulk deals |
| `GET` | `/regulatory` | ASM/GSM watchlists, F&O ban list, NSE/SEBI/margin circulars |
| `GET` | `/news` | Company, sector, market, and economic news with freshness scores |
| `GET` | `/timeline` | Events bucketed into Today / Past-7d / Past-30d / Upcoming + 7-day calendar |
| `GET` | `/brief` | Daily Intelligence Brief with market tone, high-risk stocks, opportunities, alerts |
| `GET` | `/export/csv` | All events as a downloadable CSV |
| `GET` | `/export/json` | Full snapshot as a downloadable JSON file |

### Sample Summary Response

```json
{
  "status": "ENABLED",
  "advisory_only": true,
  "intelligence_score": 72.5,
  "grade": "B",
  "total_events": 37,
  "corporate_count": 30,
  "regulatory_count": 4,
  "news_count": 3
}
```

---

## Intelligence Modules

### 1. Corporate Intelligence
Sources corporate events from yfinance (dividends, splits) and infers results, board meetings, and bulk deal activity from existing scan signals.

**Event sub-types:** `DIVIDEND`, `SPLIT`, `RESULTS`, `BOARD_MEETING`, `BULK_DEAL`

**Priority scoring:**
- Results + high confidence scan signal → score 80–95 (HIGH / CRITICAL)
- Dividend with yield > 2 % → score 70–85 (MEDIUM / HIGH)
- Board meeting in next 7 days → score 55–70 (MEDIUM)

### 2. Regulatory Intelligence
Infers regulatory status from RSI, volume, and OI metrics present in the existing scan snapshot.

| Trigger | Rule | Event |
|---------|------|-------|
| RSI > 80 or < 20 and volume_ratio > 2.5 | Extreme volatility proxy | ASM Watch |
| RSI > 90 or volume_ratio > 4.0 | Sustained extreme levels | GSM Watch |
| oi_ratio > 0.90 | OI concentration above 90 % | F&O Ban |
| Static list | Known NSE/SEBI/margin updates | Circular |

### 3. News Intelligence
Synthesises news events from scan-level signals and the Phase 7.1 market regime snapshot. Articles are deduplicated by event ID and by first-40-character title similarity (fuzzy match), preventing the same story from appearing in multiple categories.

**Categories:** Company News, Sector News, Market Update, Economic Update  
**Freshness scoring:** Decays over 24 hours; stale items are flagged but retained for context.

### 4. Impact Engine
Every event is scored on four dimensions:

| Dimension | Range | Meaning |
|-----------|-------|---------|
| importance | 0–100 | Market-moving potential |
| confidence | 0–100 | Data quality / signal strength |
| direction | BULLISH / BEARISH / NEUTRAL | Expected price direction |
| volatility_impact | LOW / MEDIUM / HIGH / EXTREME | Expected vol change |

Historical comparisons are matched by event sub-type (e.g., previous results events for the same symbol). Sector heat is aggregated by summing importance scores within each sector group.

### 5. Event Timeline
Events are bucketed into five views:

```
today       → event_date == today
past_7_days → today-7d < event_date < today
past_30_days→ today-30d < event_date <= today-7d
upcoming    → event_date > today
calendar    → 7-day forward grid (date → [event_ids])
```

### 6. Daily Intelligence Brief
A structured narrative summary generated fresh on each API call:

- **Market tone** — derived from regime + breadth (e.g., "Broadly Bullish")
- **High-risk stocks** — symbols with regulatory flags or extreme volatility signals
- **Opportunities** — corporate events coinciding with bullish scan confidence
- **Sector highlights** — top/bottom performing sectors by heat score
- **Volatility alerts** — upcoming events with HIGH or EXTREME impact
- **Brief score** — 0–100 aggregate readiness metric for the trading day

---

## Frontend Dashboard

The React page (`/event-intelligence`) provides a 6-tab interface:

| Tab | Content |
|-----|---------|
| **Overview** | Score ring, key stats, top corporate / regulatory / news events |
| **Daily Brief** | Market tone card, high-risk list, opportunity list, volatility alerts |
| **Corporate** | Full corporate event list with importance badges and direction indicators |
| **News** | Company and market news with freshness scores and impact labels |
| **Regulatory** | ASM/GSM watchlist, F&O ban entries, circular notices |
| **Timeline** | Bucketed event timeline with 7-day forward calendar |

**Header controls:** Export CSV · Export JSON · Refresh  
**Identity strip:** `Event Intelligence · Read-only · Advisory Only · Paper Trading · ApexQuant AI`

The `ADVISORY ONLY` badge is permanently visible in the page header to reinforce the read-only nature of all displayed intelligence.

---

## Test Coverage

**68 / 68 tests pass** across 13 test classes.

| Class | Tests | Covers |
|-------|-------|--------|
| `TestFeatureFlag` | 3 | Enable / disable / default state |
| `TestModels` | 5 | EventRecord fields, grade helpers, priority mapping |
| `TestCorporateIntelligence` | 7 | Dividends, splits, results, board, bulk deals |
| `TestRegulatoryIntelligence` | 5 | ASM, GSM, F&O ban, circular structure |
| `TestNewsIntelligence` | 5 | All 4 categories, freshness decay, dedup |
| `TestImpactEngine` | 5 | Importance sort, sector heat, historical context |
| `TestTimeline` | 6 | All 5 buckets + calendar |
| `TestBrief` | 5 | Structure, tone, risk list, opportunities, volatility |
| `TestSharedServices` | 8 | All 6 endpoints, snapshot, advisory flags |
| `TestDuplicateDetection` | 3 | Same ID, different IDs, similar title (first-40-char) |
| `TestExport` | 3 | CSV disabled, CSV non-empty, JSON parseable |
| `TestAPIDispatch` | 8 | All 8 `cmd_*` dispatch functions |
| `TestAdvisoryOnlySafety` | 3 | AST scan — zero write imports across all modules |

---

## Data Flow

```
Phase 7 live scan snapshot
        │
        ▼
signals_cache.get_latest_signals()
        │
        ├──► corporate_intelligence  ──┐
        ├──► regulatory_intelligence ──┤
        ├──► news_intelligence       ──┤
        └──► Phase 7.1 market hub    ──┤
                                       ▼
                               impact_engine (scores all events)
                                       │
                               ┌───────┴───────┐
                               ▼               ▼
                           timeline         brief
                               │               │
                               └───────┬───────┘
                                       ▼
                               shared_services
                                (public API layer)
                                       │
                               ┌───────┴──────────┐
                               ▼                  ▼
                         REST routes         EventIntelligence.tsx
                     (event-intelligence.ts)  (React dashboard)
```

---

## Integration Points

### Executive Dashboard (Phase 5D.5)
`get_event_intelligence_snapshot()` in `shared_services.py` returns a flat KPI dict that can be imported by the Executive Dashboard's `load_all()` without any structural changes — following the identical pattern established by Phase 5D.1–5D.4 analytics modules.

### Future Phases
The shared_services interface is stable and backward-compatible for:

| Phase | Integration |
|-------|-------------|
| Phase 7.3 — Economic Intelligence | Can consume `get_news_events()` for macro context |
| Phase 7.4 — Explainable AI | Can annotate Trade Decisions with upcoming event risks |
| Phase 7.5 — Research Lab | Can query `get_timeline()` to filter backtests around events |

---

## Known Limitations

| Limitation | Impact | Future Resolution |
|------------|--------|-------------------|
| News synthesised from scan signals, no live news feed | Articles are inferred, not verbatim | Phase 7.3: economic news connector |
| yfinance capped at ~3 symbols per call | Corporate data limited to watchlist top picks | Async batch fetching in Phase 7.3 |
| ASM/GSM inferred from RSI/volume, not exchange datafeed | Possible false positives | Direct NSE surveillance API in Phase 8+ |
| Regulatory circulars are static | Cannot auto-detect new circulars | Circular scraper in Phase 7.3 |

---

## Files Changed

```
artifacts/api-server/src/python/
├── event_intelligence/
│   ├── __init__.py
│   ├── models.py
│   ├── corporate_intelligence.py
│   ├── regulatory_intelligence.py
│   ├── news_intelligence.py
│   ├── impact_engine.py
│   ├── timeline.py
│   ├── brief.py
│   ├── shared_services.py
│   └── api.py
├── main.py                         (8 new command handlers)
└── test_event_intelligence.py      (68 tests)

artifacts/api-server/src/routes/
├── event-intelligence.ts           (new — 8 REST routes)
└── index.ts                        (router registered)

artifacts/trading-dashboard/src/
├── pages/EventIntelligence.tsx     (new — 6-tab dashboard)
├── App.tsx                         (route added)
└── components/layout/AppLayout.tsx (nav entry added)

Environment
└── EVENT_INTELLIGENCE_ENABLED=true
```

---

## Spec Compliance Checklist

| Requirement | Status |
|-------------|--------|
| Corporate Intelligence (results, dividends, splits, bulk deals, board) | ✅ |
| Regulatory Intelligence (ASM/GSM/F&O ban, NSE/SEBI circulars) | ✅ |
| News Intelligence (company/sector/market/economic, dedup, freshness) | ✅ |
| Event Impact Analysis (importance, direction, volatility, historical) | ✅ |
| Event Timeline (today/past7/past30/upcoming/calendar) | ✅ |
| Daily Intelligence Brief | ✅ |
| Feature flag `EVENT_INTELLIGENCE_ENABLED` | ✅ |
| 6 API endpoints under `/api/event-intelligence/` | ✅ (8 delivered — includes 2 export routes) |
| Advisory-only enforcement (no write paths) | ✅ AST-verified |
| Test suite | ✅ 68/68 pass |
| Frontend dashboard with tabs | ✅ |
| Export (CSV + JSON) | ✅ |
