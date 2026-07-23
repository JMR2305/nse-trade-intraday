# RC-10A — Market Intelligence Layer
## Status & Summary

**Status:** ✅ Complete
**Commit:** `8cdc360`
**Tag:** `RC-10A-complete`
**Date:** 2026-07-23

---

## What Was Built

The RC-10A batch adds an entirely optional intelligence tier that enriches
`StrategyContext` snapshots with multi-timeframe technical data, regime
classification, instrument ranking, and corporate announcement awareness —
without touching any existing runtime path.

| Module | Purpose |
|---|---|
| `TimeframeAggregator` | Aggregates 1m bars into 5m/15m/1h with session-boundary and gap detection |
| `IndicatorEngine` | Per-timeframe bar buffer + pure functions: SMA, EMA, RSI, ATR, ADX/DI, MACD, VWAP, Bollinger |
| `MarketRegimeDetector` | 7-state ADX/DI-gated classifier (UNKNOWN → RANGING → UP/DOWN → STRONG_UP/DOWN → EXPANDING_RANGE) with confidence |
| `WatchlistRanker` | 5-factor composite score → ranked `WatchlistRankingSnapshot` |
| `StrategyScorer` | Per-strategy-type alignment table (trend strategies favoured in uptrends, mean-reversion in ranging) |
| `AnnouncementIntelligenceService` | Keyword classifier, TTL in-memory cache, dedup by `(exchange, announcement_id)`, blackout-window guard |
| `AnnouncementPoller` | asyncio background polling task |
| `AnnouncementRepository` | Postgres persistence — upsert-by-exchange-id, query by instrument/classification |

---

## Schema Changes

- `instrument_master.sector` column added
- New `announcements` table
- Alembic migration: `migrations/versions/0004_rc10a_announcements_sector.py`

---

## Config

`MarketIntelligenceSettings` added as `settings.market_intelligence` (env prefix `MI_`).

Key settings:

| Setting | Default | Description |
|---|---|---|
| `MI_ENABLED` | `true` | Enable/disable the layer globally |
| `MI_ENABLED_TIMEFRAMES` | `["1m","5m","15m","1h"]` | Active aggregation timeframes |
| `MI_MAX_INDICATOR_BUFFER_BARS` | `150` | Max bars kept per timeframe per instrument |
| `MI_ANNOUNCEMENT_POLL_INTERVAL_SECONDS` | `60` | Background poller cadence |
| `MI_ANNOUNCEMENT_TTL_HOURS` | `24` | Cache expiry for announcements |
| `MI_ANNOUNCEMENT_BLACKOUT_WINDOW_MINUTES` | `30` | Entry suppression window around announcements |

---

## Backward Compatibility

`ContextBuilder` is 100% backward-compatible.

- All intelligence services are injected as `None`-default keyword arguments.
- The existing `await builder.build_context(...)` call is **unchanged**.
- A new sync `build()` method is available for tests and future sync callers.
- When no intelligence is injected, `market_snapshots == {}` — identical to RC-9 behaviour.

---

## Files Delivered

### New implementation files
```
src/market_intelligence/__init__.py
src/market_intelligence/multi_timeframe_context.py
src/market_intelligence/timeframe.py
src/market_intelligence/indicator_engine.py
src/market_intelligence/regime.py
src/market_intelligence/ranking.py
src/market_intelligence/strategy_scoring.py
src/market_intelligence/announcements.py
src/market_intelligence/poller.py
src/database/repositories/announcements.py
migrations/versions/0004_rc10a_announcements_sector.py
```

### Modified files
```
src/database/models.py           — sector column + Announcement ORM model
src/core/config.py               — MarketIntelligenceSettings
src/strategy/context_builder.py  — optional intelligence injection + sync build()
```

---

## Test Results

| Suite | Tests | Result |
|---|---|---|
| Unit — `market_intelligence/` | 89 | ✅ All pass |
| Integration — ContextBuilder with intelligence | 5 | ✅ All pass |
| Integration — ContextBuilder without intelligence | 4 | ✅ All pass |
| Integration — Timeframe pipeline | 2 | ✅ All pass |
| Integration — Regime from bars | 2 | ✅ All pass |
| Integration — Announcement persistence | 2 | ✅ All pass |
| **RC-10A Total** | **104** | **✅ 0 failures** |

### Pre-existing suite (no regressions)

| Suite | Tests | Result |
|---|---|---|
| All unit tests | 534 | ✅ 533 pass |
| `test_kill_switch::test_history` | 1 | ⚠️ Pre-existing failure (tracked since RC-8B, unrelated to RC-10A) |

---

## Key Design Decisions

1. **Optional injection pattern** — Intelligence is a side-car, not a replacement.
   Injecting `None` for all services is safe and produces identical output to RC-9.

2. **Count-based timeframe aggregation** — Emits after exactly N bars (5/15/60).
   Session-boundary (day change) and gaps (inter-bar time > 2× interval) trigger
   early emit + buffer reset to avoid cross-session OHLCV pollution.

3. **Keyword classifier** — `classify_announcement()` is a deterministic
   keyword-lookup table. Zero latency, fully testable, no external dependency.
   Upgradeable to an LLM classifier later without interface changes.

4. **Announcement dedup key** — `(exchange, announcement_id)`, not just
   `announcement_id`. The same numeric ID can appear on both NSE and BSE.

5. **`CompletedBar.timestamp` is `datetime`, not `str`** — Pydantic coerces
   ISO strings on construction. `_parse_ts()` in `timeframe.py` accepts both
   types to handle callers that pass either form.
