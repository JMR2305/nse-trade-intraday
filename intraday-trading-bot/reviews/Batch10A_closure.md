# Batch 10A Closure Report — Market Intelligence Layer

**RC version:** 0.10.0-rc  
**Date:** 2026-07-23  
**Author:** Agent (main)

---

## Summary

Batch 10A delivers the **Market Intelligence Layer** — a fully optional, side-car enrichment tier that attaches multi-timeframe technical context, market-regime classification, instrument ranking, strategy scoring, and corporate announcement intelligence to every `StrategyContext` snapshot.

All 104 tests (89 unit + 15 integration) pass green. No pre-existing test was modified or broken.

---

## Scope

### New packages
| Module | Description |
|---|---|
| `market_intelligence/multi_timeframe_context.py` | Pydantic frozen models: `MarketRegime`, `MarketRegimeSnapshot`, `AnnouncementRecord`, `InstrumentScore`, `WatchlistRankingSnapshot`, `StrategyScore`, `MultiTimeframeContext` |
| `market_intelligence/timeframe.py` | `TimeframeAggregator` — count-based 1m→5m/15m/1h aggregation with session-boundary and gap detection |
| `market_intelligence/indicator_engine.py` | `IndicatorEngine` + pure functions: SMA, EMA, RSI, ATR, ADX/DI, MACD, VWAP, Bollinger |
| `market_intelligence/regime.py` | `MarketRegimeDetector` — ADX/DI-gated regime classification (UNKNOWN / RANGING / UPTREND / DOWNTREND / STRONG_UPTREND / STRONG_DOWNTREND / EXPANDING_RANGE) |
| `market_intelligence/ranking.py` | `WatchlistRanker` — 5-factor composite score + ranked `WatchlistRankingSnapshot` |
| `market_intelligence/strategy_scoring.py` | `StrategyScorer` — per-strategy-type alignment table, regime alignment × instrument suitability |
| `market_intelligence/announcements.py` | `AnnouncementIntelligenceService` — keyword classifier, in-memory TTL cache, dedup, blackout-window guard |
| `market_intelligence/poller.py` | `AnnouncementPoller` — asyncio background polling task |

### Modified files
| File | Change |
|---|---|
| `database/models.py` | Added `sector` column to `InstrumentMaster`; new `Announcement` ORM model |
| `database/repositories/announcements.py` | New `AnnouncementRepository` (upsert by exchange+id, queries by instrument/classification) |
| `core/config.py` | Added `MarketIntelligenceSettings` sub-class; wired into `Settings` as `market_intelligence` field |
| `strategy/context_builder.py` | Backward-compatible: added optional `indicator_engine`, `regime_detector`, `announcement_service`, `watchlist_ranker` kwargs + new sync `build()` method; existing `build_context()` unchanged |
| `migrations/versions/0004_rc10a_announcements_sector.py` | Alembic migration: `sector` column + `announcements` table |

---

## Design Decisions

### 1. Optional injection pattern
Intelligence services are passed as keyword-only `None`-default arguments to `ContextBuilder`. When all are `None` the existing runtime behaviour is byte-for-byte identical to RC-9. This eliminates any risk of breaking the live trading loop.

### 2. Sync `build()` vs async `build_context()`
A new sync `build()` method was added to support the test suite and future synchronous callers. The existing `build_context()` async method is unchanged.

### 3. Keyword-based announcement classifier
A deterministic keyword lookup table (`classify_announcement()`) was chosen over an LLM or regex engine because:
- It is testable and auditable.
- It adds zero latency on the hot path.
- It can be upgraded to a heavier model later without changing the interface.

### 4. Count-based timeframe aggregation
`TimeframeAggregator` emits an aggregated bar after collecting exactly N source bars (5 for 5m, 15 for 15m, 60 for 1h). A **session boundary** (day change) triggers an early emit and resets the buffer; a **gap** (inter-bar time > 2× the target interval) also triggers an early emit.

### 5. `CompletedBar.timestamp` is a datetime, not a string
The existing Pydantic model coerces ISO strings to `datetime` on construction. `_parse_ts()` in `timeframe.py` was written to accept both types to future-proof against callers that pass either.

---

## Test Results

```
tests/unit/market_intelligence/          89 passed
tests/integration/test_context_builder_with_intelligence.py   5 passed
tests/integration/test_context_builder_no_intelligence.py     4 passed
tests/integration/test_timeframe_pipeline.py                  2 passed
tests/integration/test_regime_from_bars.py                    2 passed
tests/integration/test_announcement_persistence.py            2 passed

Total: 104 passed, 0 failed
```

Pre-existing integration test errors (test_auth, test_health, test_orders, test_positions, test_sessions) are unrelated to Batch 10A — they fail due to password/DB-fixture misconfiguration that predates this batch.

---

## Acceptance Criteria

- [x] All 8 core implementation modules written and importable.
- [x] `MarketIntelligenceSettings` added to `Settings`.
- [x] `Announcement` ORM model and migration present.
- [x] `AnnouncementRepository` with upsert/query implemented.
- [x] `ContextBuilder` backward-compatible: existing `build_context()` unchanged.
- [x] New `ContextBuilder.build()` sync method injects intelligence when present.
- [x] All 104 unit + integration tests green.
- [x] Git commit and tag `RC-10A-complete`.
