# Phase 5D.3 — Strategy Intelligence

**Status:** COMPLETE  
**Feature flag:** `STRATEGY_INTELLIGENCE_ENABLED=true`  
**Module:** `artifacts/api-server/src/python/strategy_intelligence/`  
**Dashboard:** `artifacts/trading-dashboard/src/pages/StrategyIntelligence.tsx` → `/strategy-intelligence`

---

## What was built

A read-only analytics service that compares every strategy by win rate, profit factor, net P&L, max drawdown, execution quality, market regime fit, sector fit, and time-of-day performance — then ranks and recommends each one with advisory text only. Nothing modifies the trading engine, portfolio, orders, or strategy execution.

---

## Files created

| File | Purpose |
|---|---|
| `strategy_intelligence/__init__.py` | Package docstring — advisory-only contract |
| `strategy_intelligence/strategy_models.py` | `ClosedTrade`, `StrategyProfile` dataclasses; `is_enabled()`, `disabled_response()`, `TIME_SLOTS`, `REGIMES` |
| `strategy_intelligence/strategy_engine.py` | FIFO BUY→SELL matching; IST time-slot bucketing; execution quality lookup; `load_all_data()` |
| `strategy_intelligence/strategy_statistics.py` | Per-strategy aggregation → `StrategyProfile`; running drawdown; regime/sector/time breakdowns |
| `strategy_intelligence/strategy_rankings.py` | 7-factor weighted rank score (0–100); leaderboard; per-criterion rankings |
| `strategy_intelligence/market_regime_analysis.py` | Regime-level win rate / P&L matrix; best strategy per regime |
| `strategy_intelligence/sector_analysis.py` | Sector-level matrix; best/worst sector highlights |
| `strategy_intelligence/time_analysis.py` | IST time-slot + day-of-week + hour matrices; best/worst highlights |
| `strategy_intelligence/recommendations.py` | Rule-based advisory labels with severity and one-sentence rationale |
| `strategy_intelligence/shared_services.py` | **Stable shared interface for 5D.4 / 5D.5** — see below |
| `strategy_intelligence/api.py` | 6 HTTP-facing façade functions called by Express |
| `strategy_intelligence/test_strategy_intelligence.py` | 31 unit tests — all passing |

**Files modified:**

| File | Change |
|---|---|
| `artifacts/api-server/src/python/main.py` | +6 strategy commands |
| `artifacts/api-server/src/routes/index.ts` | Added `strategyRouter` |
| `artifacts/api-server/src/routes/strategy.ts` | 6 Express GET endpoints |
| `artifacts/trading-dashboard/src/App.tsx` | Added route |
| `artifacts/trading-dashboard/src/components/layout/AppLayout.tsx` | Added sidebar entry (Zap icon) |

---

## API endpoints

| Endpoint | Returns |
|---|---|
| `GET /api/strategy/summary` | Top-level KPIs, criterion winners, top-10 leaderboard |
| `GET /api/strategy/rankings` | Full leaderboard + per-profile stats + criterion rankings |
| `GET /api/strategy/regimes` | Regime matrix + best strategy per regime |
| `GET /api/strategy/sectors` | Sector matrix + best/worst sector |
| `GET /api/strategy/timing` | Time-slot, day-of-week, hour matrices + highlights |
| `GET /api/strategy/recommendations` | Advisory recommendation cards per strategy |

---

## Ranking algorithm

7 factors, min-max normalised per factor, then weighted:

| Factor | Weight | Direction |
|---|---|---|
| Net P&L | 20% | higher better |
| Win rate | 20% | higher better |
| Profit factor | 20% | higher better |
| Risk-adjusted return (P&L / MaxDD) | 15% | higher better |
| Max drawdown % | 15% | **lower better** |
| Avg execution quality score | 10% | higher better |
| Consistency (avg win / avg loss ratio) | 10% | higher better |

Strategies with zero closed trades score 0 and rank last.

---

## How 5D.4 and 5D.5 reuse this module

### Deliverable #10 — Reuse contract

Phase 5D.4 (AI Performance Intelligence) and Phase 5D.5 (Executive Dashboard) **must not recalculate strategy metrics**. They import from `shared_services` directly:

```python
# In 5D.4 or 5D.5 — one import, no recalculation
from strategy_intelligence.shared_services import (
    get_all_strategy_profiles,   # List[StrategyProfile] — ranked + recommended
    get_strategy_stats,          # single strategy by name
    get_regime_matrix,           # full regime dict
    get_sector_matrix,           # full sector dict
    get_time_matrix,             # slot + day + hour dicts
    get_strategy_rankings,       # leaderboard rows
    get_recommendations,         # advisory recommendation rows
    get_criterion_rankings,      # best by each criterion
    get_summary_snapshot,        # single top-level KPI dict for embedding
)
```

`get_summary_snapshot()` is specifically designed for the Phase 5D.5 Executive Dashboard — it returns a single flat dict with all cross-domain KPIs (`best_strategy`, `best_regime`, `best_sector`, `best_time_slot`, `criterion_rankings`) so the executive view makes one call instead of fan-out.

The stable function signatures in `shared_services.py` must **not be renamed** without a version bump. The key contract is: all functions check `is_enabled()` first and return empty lists / `disabled_response()` when the flag is off — 5D.4 and 5D.5 do not need to repeat that check for strategy data.

---

## Test summary

31/31 passing (0.49s):
- Feature flag disabled → all endpoints return `{"status": "DISABLED"}`
- Zero trades → all endpoints return empty data gracefully
- Single strategy (winning / losing)
- Multiple strategies → correct ranking order
- Mixed performance → correct P&L, profit factor, win rate
- Market regime matrix populated and sorted
- Sector matrix: correct best/worst detection, summary sorted by P&L desc
- Time analysis: correct day + slot assignment in IST
- Recommendations: all 5 classification paths verified
- Shared service API consistent with HTTP endpoints
- Restart persistence: two sequential calls return identical results

---

## Dashboard tabs

1. **Overview** — 4 bar charts: Net P&L, Win Rate, Profit Factor, Drawdown by strategy
2. **Rankings** — Sortable leaderboard + per-strategy stat cards
3. **Regimes** — Regime P&L + Win Rate charts + matrix table
4. **Sectors** — Sector P&L + Win Rate charts + matrix table  
5. **Timing** — Time-slot + day-of-week charts + time-slot matrix
6. **Recommendations** — Advisory cards with severity, rationale, key metrics

All charts use paper-trading colour coding: green = positive/good, red = negative/bad, amber = borderline.

---

## Issues & known gaps

| # | Area | Description | Severity | Resolution path |
|---|---|---|---|---|
| 1 | Feature flag off by default | `STRATEGY_INTELLIGENCE_ENABLED` is not set in the environment, so the page shows the disabled banner until an operator explicitly enables it. | Low — intentional design | Set `STRATEGY_INTELLIGENCE_ENABLED=true` in environment secrets (same pattern as Portfolio Performance). |
| 2 | Execution quality score availability | `quality_score` on a `ClosedTrade` is only populated when the Phase 5D.1 execution quality module has already computed records for the same trade IDs. Trades entered before 5D.1 was deployed will show `quality_score=0` and `quality_grade=""`. | Low | Acceptable for paper trading; will self-resolve as new trades are recorded. |
| 3 | Sector detection is best-effort | `_sector_of(symbol)` calls `market_scanner._sector_of()` which returns `"Unknown"` for any symbol not in the NSE sector map. Symbols added to the watchlist after the map was last updated will show under `Unknown`. | Low | Extend the sector map in `market_scanner.py` as new symbols are added. |
| 4 | FIFO matching covers one open position per symbol | The FIFO BUY→SELL engine closes the first open BUY when it sees any SELL for the same symbol. If the system ever places two open BUYs for the same symbol (currently prevented by paper trading's partial-unique-index), only the first round-trip will be matched. | Low | The paper trading engine's claim-before-buy constraint prevents this in practice. |
| 5 | Ranking weights are fixed constants | The 7 ranking weights are hardcoded (`20/20/20/15/15/10/10`). Different operators or market conditions may warrant different weightings. | Medium | Expose weights as configurable environment variables in a future iteration. |
| 6 | No caching between API calls | Every HTTP request triggers a full reload from `portfolio_store` and recomputes all profiles. With hundreds of trades this adds ~50–100 ms per request (within spec), but will grow linearly. | Medium | Add an in-process TTL cache (e.g. 60 s) in `shared_services._load_all()` once trade volume justifies it. |
| 7 | `worst_day` / `worst_slot` shows `None` when all trades fall in one slot | If all trades happen in a single time slot, `worst` and `best` resolve to the same slot. The UI displays the value correctly but the label is slightly misleading. | Cosmetic | Add a `"—"` fallback when `best == worst` in `time_analysis.py`. |
| 8 | TypeScript strict-null on `timing?.day_matrix?.[d]?.trades` | Required a `.filter` fix (`?? 0`) during build. No runtime impact, but signals that optional chaining on deeply nested query data should be wrapped consistently throughout the dashboard. | Cosmetic — fixed | Already resolved before ship. Noted so the same pattern is applied in 5D.4/5D.5. |

---

## What to enable before using in a live session

1. `STRATEGY_INTELLIGENCE_ENABLED=true` — in environment secrets.
2. Ensure `PORTFOLIO_PERFORMANCE_ENABLED=true` is also set — strategy intelligence reads the same `paper_trades` table that portfolio performance uses.
3. Confirm at least ~10 closed round-trip trades exist for meaningful rankings (rankings with fewer than 5 trades per strategy display "Promising — More Data Needed").

---

## Dependencies for downstream phases

| Phase | What it needs from 5D.3 |
|---|---|
| **5D.4 AI Performance Intelligence** | `get_all_strategy_profiles()`, `get_regime_matrix()`, `get_sector_matrix()` from `shared_services` |
| **5D.5 Executive Dashboard** | `get_summary_snapshot()` — single-call KPI dict; covers best strategy, regime, sector, time slot, and criterion rankings |
