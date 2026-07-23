# Changelog

All notable changes to the intraday trading bot are recorded here.
Entries are listed newest first. Each batch is tagged in git.

---

## RC-10A — Market Intelligence Layer
**Tag:** `RC-10A-FINAL`  
**Status:** ✅ ACCEPTED & FROZEN (2026-07-23)  
**Baseline for:** RC-10B and all subsequent development

### Added
- `src/market_intelligence/` package (8 new modules):
  - `multi_timeframe_context.py` — frozen Pydantic domain models: `MarketRegime`, `MarketRegimeSnapshot`, `AnnouncementRecord`, `InstrumentScore`, `WatchlistRankingSnapshot`, `StrategyScore`, `MultiTimeframeContext`
  - `timeframe.py` — `TimeframeAggregator`; count-based bar aggregation for 5m / 15m / 1h / daily; session-boundary and gap detection
  - `indicator_engine.py` — `IndicatorEngine` with bounded 150-bar deque buffers; 11 indicators: SMA(10/20/50), EMA(9/21), RSI(14), ATR(14), ADX(14), MACD(12,26,9), VWAP, Bollinger(20,2)
  - `regime.py` — `MarketRegimeDetector`; 7-state ADX/DI/ATR classification with confidence in [0,1]
  - `ranking.py` — `WatchlistRanker`; 5-factor composite instrument scoring and ranking
  - `strategy_scoring.py` — `StrategyScorer`; per-strategy-type regime alignment scores
  - `announcements.py` — `AnnouncementIntelligenceService`; keyword-based 8-category classifier, in-memory cache with TTL and dedup; `poll_and_classify()` stubbed (HTTP deferred to 10E)
  - `poller.py` — `AnnouncementPoller`; asyncio background task with clean cancellation
- `src/core/config.py` — `MarketIntelligenceSettings` (env prefix `MI_`) wired into `Settings`
- `src/database/models.py` — `Announcement` ORM model; `sector` column on `InstrumentMaster`
- `src/database/repositories/announcements.py` — `AnnouncementRepository` with upsert-by-`(exchange, announcement_id)` and TTL queries
- `migrations/versions/0004_rc10a_announcements_sector.py` — Alembic migration with working upgrade/downgrade
- 104 tests: 89 unit + 15 integration, all passing

### Modified
- `src/strategy/context_builder.py`:
  - Optional intelligence injection via keyword-only constructor args (`indicator_engine`, `regime_detector`, `announcement_service`, `watchlist_ranker`)
  - New sync `build()` method for market intelligence tests
  - `build_context()` signature unchanged (RC-9 contract frozen)
  - **Final Patch:** `market_snapshots[token]` now typed `MultiTimeframeContext` instances (not raw dicts)
  - **Final Patch:** Shared injection logic extracted to `_inject_market_intelligence()` private helper

### Audit Bugs Fixed (Batch10A_Replit_Audit.md)
- `Announcement.effective_date` type annotation corrected: `Mapped[Optional[datetime]]` → `Mapped[Optional[date]]`; `date` added to `models.py` imports
- `AnnouncementRecord.model_version` Pydantic protected-namespace warning suppressed via `protected_namespaces=()`
- Unused imports `StrategyLifecycleState`, `StrategyError` removed from `context_builder.py`

### Final Patch (Batch10A_Final_Patch.md — O-1, O-2)
- `market_snapshots[token]` now holds typed `MultiTimeframeContext` objects (not raw dicts)
- Duplicate injection logic eliminated; lives solely in `_inject_market_intelligence()`

### Known Deferred Items (not bugs — intentional scope boundaries)
| Item | Deferred to |
|------|-------------|
| HTTP polling to BSE/NSE feeds (`poll_and_classify()` is a stub) | RC-10E |
| `AnnouncementRepository.upsert()` not called — in-memory cache only | RC-10D/10E |
| Clock-aligned bar aggregation (9:15, 9:20 …) — count-based only | RC-10B or 10C |
| `WatchlistRanker` volume ratio and spread/liquidity hardcoded to 1.0 | RC-10C/10D (needs Quote data) |
| `WatchlistRanker.score()` signature vs spec (`dict+regime` vs `MultiTimeframeContext`) | RC-10B normalisation |
| `get_active_announcements()` sync naming vs spec async | RC-10B normalisation |
| Input sanitisation + JSONB size cap on announcement text | Before HTTP polling |
| `datetime.utcnow()` deprecation warnings | Separate housekeeping batch |

---

## RC-9 — Strategy Engine
**Tag:** `RC-9-complete`  
**Status:** ✅ FROZEN

Coordinator deregister deadlock fix, async `FillEventBus` API, `_on_signal` schedules task,
error propagation via lifecycle, `ExecutionService` wiring. See `reviews/` for audit trail.

---

## RC-8 — Broker Safety Layer
**Tag:** `RC-8`  
**Status:** ✅ FROZEN

Credential masking, no-auto-execution guarantee, two-step confirm tokens,
`MockBrokerClient` fallback. See `reviews/` for audit trail.

---

_Earlier batches (RC-1 through RC-7) predate this changelog. See git history and `reviews/` for full record._
