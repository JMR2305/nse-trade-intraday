# RC-10 Master Implementation Plan
## Production Engineering Blueprint

**Version:** 1.0  
**Date:** 2026-07-23  
**Baseline:** RC-9 Complete (`RC-9-complete` tag, 445/446 unit tests passing)  
**Reference:** `docs/RC10_Reference.md`  
**Audience:** Kimi — implementing agent

> This document is the single source of truth for how RC-10 will be built. Read `RC10_Reference.md` first for background. This document governs what is built, in what order, to what standard, and how it is validated.

---

# EXECUTIVE SUMMARY

RC-10 extends the intraday trading bot with five orthogonal capability layers, all building on top of the frozen RC-9 strategy engine. Implementation proceeds in dependency order: market intelligence first (10A), then AI forecasting (10B) and broker wiring (10D) in parallel, then portfolio management (10C), and finally operations (10E).

**Totals across all phases:**

| Metric | Count |
|--------|-------|
| New source files | ~65 |
| Modified existing files | ~12 |
| New database tables | 4 |
| New Alembic migrations | 4 |
| New API endpoints | 17 |
| New unit tests (minimum) | 220 |
| New integration tests (minimum) | 25 |
| Estimated total test count at RC-10 completion | ~700+ |

---

# TABLE OF CONTENTS

1. [Recommended Implementation Order](#recommended-implementation-order)
2. [Complexity & Scope Summary](#complexity--scope-summary)
3. [Batch 10A — Market Intelligence Layer](#batch-10a--market-intelligence-layer)
4. [Batch 10B — AI Forecast Layer](#batch-10b--ai-forecast-layer)
5. [Batch 10C — Portfolio Management](#batch-10c--portfolio-management)
6. [Batch 10D — Broker Layer](#batch-10d--broker-layer)
7. [Batch 10E — Operations](#batch-10e--operations)
8. [Cross-Cutting Concerns](#cross-cutting-concerns)
9. [Kimi Implementation Splits](#kimi-implementation-splits)
10. [Replit Validation Checklist](#replit-validation-checklist)
11. [Merge Strategy](#merge-strategy)

---

# RECOMMENDED IMPLEMENTATION ORDER

```
WEEK 1-2
  └── Batch 10A: Market Intelligence Layer
        (multi-timeframe, indicators, regime, ranking, announcements)

WEEK 3-4 [parallel tracks]
  ├── Batch 10B: AI Forecast Layer
  │     (Kronos adapter, confidence gate, volatility, features, benchmark)
  └── Batch 10D: Broker Layer
        (Zerodha Kite full write, order sync, position reconcile, account API)

WEEK 5
  └── Batch 10C: Portfolio Management
        (sizing, allocation, sector, correlation, capital engine)
        [requires 10A ranking + 10B volatility + 10D account margin data]

WEEK 6-7
  └── Batch 10E: Operations
        (strategy API, analytics, alerts, reports, soak test)
        [requires all prior batches complete]
```

**Rationale:**
- 10A must come first because `MultiTimeframeContext` and `MarketRegimeSnapshot` are consumed by 10B, 10C, and 10E.
- 10B and 10D have no interdependency — they can be developed simultaneously on separate branches.
- 10C depends on `VolatilityForecast` from 10B and margin data from 10D.
- 10E wires all prior layers together; it is the integration and operations batch.

---

# COMPLEXITY & SCOPE SUMMARY

| Batch | Complexity | New Files | Modified Files | New Tests | New Migrations |
|-------|-----------|-----------|----------------|-----------|----------------|
| 10A | Medium | ~18 | 3 | ~55 | 1 |
| 10B | High | ~14 | 2 | ~50 | 1 |
| 10C | Medium | ~10 | 3 | ~45 | 0 |
| 10D | High | ~14 | 4 | ~45 | 1 |
| 10E | Medium | ~12 | 5 | ~40 | 1 |
| **Total** | — | **~68** | **~17** | **~235** | **4** |

**Complexity definition:**
- Low: Straightforward additions, well-defined interfaces, no external dependencies
- Medium: Multiple interacting modules, some external I/O, moderate test coverage
- High: External API integration, concurrency concerns, safety-critical paths, large test surface

---

# BATCH 10A — MARKET INTELLIGENCE LAYER

## 1. Objective

Provide every strategy runtime with rich, pre-computed market intelligence at each bar cycle: multi-timeframe OHLCV indicators, market regime classification, watchlist ranking scores, and corporate announcement context. All intelligence is injected into the existing `StrategyContext.market_snapshots` extension point without modifying any frozen RC-9 contracts.

## 2. Scope

**In scope:**
- `TimeframeAggregator`: aggregates 1m bars into 5m, 15m, 1h, daily bars
- `IndicatorEngine`: rolling computation of SMA, EMA, RSI, VWAP, MACD, Bollinger Bands, ATR, ADX for each timeframe
- `MultiTimeframeContext`: frozen Pydantic snapshot of all indicator values per instrument
- `MarketRegimeDetector`: classifies regime from ADX/ATR/price-MA relationships
- `WatchlistRanker`: scores and ranks instruments by opportunity quality
- `StrategyScorer`: scores strategy alignment with current market regime
- `AnnouncementIntelligenceService`: polls BSE/NSE feeds, classifies, deduplicates, stores
- `AnnouncementPoller`: background asyncio task driving the service
- `ContextBuilder` extension to populate `market_snapshots`
- Alembic migration 0004 (`announcements` table, `sector` column on `instrument_master`)

**Out of scope:**
- AI/ML-based indicator signals (that is 10B)
- Position sizing using intelligence data (that is 10C)
- Real-time WebSocket streaming of intelligence data (that is 10E)
- Historical backtesting of indicators

## 3. Functional Requirements

| ID | Requirement |
|----|------------|
| 10A-F01 | `TimeframeAggregator` must emit a 5m bar after every 5 consecutive 1m bars for the same instrument, aligned to the clock (9:15, 9:20, …) |
| 10A-F02 | `TimeframeAggregator` must support 5m, 15m, 1h, and daily aggregation |
| 10A-F03 | `IndicatorEngine` must compute SMA(10), SMA(20), SMA(50), EMA(9), EMA(21), RSI(14), ATR(14), ADX(14), MACD(12,26,9), VWAP, Bollinger Bands(20,2) for each subscribed instrument and timeframe |
| 10A-F04 | All indicator computations must be deterministic: same input bars → same indicator values |
| 10A-F05 | `MarketRegimeDetector` must classify one of: UNKNOWN, RANGING, UPTREND, DOWNTREND, STRONG_UPTREND, STRONG_DOWNTREND, EXPANDING_RANGE — using the ADX/ATR algorithm defined in RC10_Reference.md §3.3 |
| 10A-F06 | `MarketRegimeSnapshot` must include `confidence: Decimal` in [0, 1] reflecting certainty of classification |
| 10A-F07 | `WatchlistRanker` must rank all instruments by a composite score of regime quality, relative volume, RSI momentum, ATR/price ratio, and spread |
| 10A-F08 | `StrategyScorer` must produce a score per strategy reflecting regime alignment and instrument suitability |
| 10A-F09 | `AnnouncementPoller` must poll BSE and NSE announcement endpoints on a configurable interval (default 60s) |
| 10A-F10 | Announcements must be classified into: EARNINGS_RESULT, DIVIDEND, BONUS, STOCK_SPLIT, MERGER_ACQUISITION, BOARD_MEETING, REGULATORY, OTHER |
| 10A-F11 | Announcements must be deduplicated by `(exchange, announcement_id)` within a 24-hour TTL |
| 10A-F12 | `ContextBuilder.build()` must attach a `MultiTimeframeContext` to `StrategyContext.market_snapshots[instrument_token]` for every instrument in `StrategyConfig.instrument_tokens` |
| 10A-F13 | `AnnouncementIntelligenceService.get_active_announcements()` must return empty list (not raise) when DB or poll is unavailable |
| 10A-F14 | All new modules must emit structured log entries at appropriate levels |

## 4. Non-Functional Requirements

| ID | Requirement |
|----|------------|
| 10A-NF01 | `IndicatorEngine.get_indicators()` must complete in < 5ms for any instrument/timeframe combination after the warm-up period |
| 10A-NF02 | `MultiTimeframeContext` assembly must add < 10ms to `ContextBuilder.build()` latency |
| 10A-NF03 | `MarketRegimeDetector.detect()` must complete in < 2ms |
| 10A-NF04 | `WatchlistRanker.rank()` must handle 100 instruments in < 50ms |
| 10A-NF05 | `AnnouncementPoller` must not block the asyncio event loop; all I/O must be awaited |
| 10A-NF06 | `IndicatorEngine` rolling buffers must be bounded: keep at most `max_period * 3` bars per instrument per timeframe (configurable, default 150) |
| 10A-NF07 | All new modules must be importable without starting the FastAPI application |
| 10A-NF08 | No global mutable state except the singleton `IndicatorEngine` instance (injected via coordinator) |

## 5. Detailed Module Breakdown

### 5.1 `TimeframeAggregator`
**Purpose:** Aggregates 1m `CompletedBar` events into higher timeframe bars.  
**Responsibilities:**
- Maintain a buffer of 1m bars per instrument
- Detect when a higher timeframe bar is complete (e.g., 5th 1m bar for 5m)
- Emit a synthesised `CompletedBar` with OHLCV computed from buffer: O=first.open, H=max(high), L=min(low), C=last.close, V=sum(volume)
- Respect market open alignment: the first bar of a session starts at 09:15 IST

**Key method:** `on_bar(bar: CompletedBar) -> Optional[CompletedBar]`  
Returns an aggregated bar when complete, else None.

### 5.2 `IndicatorEngine`
**Purpose:** Computes and caches technical indicators from rolling bar buffers.  
**Responsibilities:**
- Accept bars from multiple timeframe aggregators
- Maintain per-`(instrument_token, timeframe)` rolling deque of `CompletedBar`
- Compute indicator values on each update; cache results
- Expose synchronous `get_indicators()` returning a frozen dict snapshot

**Pure indicator functions** (all in `indicator_engine.py`):
- `compute_sma(bars, period) -> Decimal`
- `compute_ema(bars, period) -> Decimal`
- `compute_rsi(bars, period) -> Decimal`  (RSI in [0, 100])
- `compute_atr(bars, period) -> Decimal`  (Average True Range)
- `compute_adx(bars, period) -> Tuple[Decimal, Decimal, Decimal]`  (ADX, +DI, -DI)
- `compute_macd(bars, fast, slow, signal) -> Tuple[Decimal, Decimal, Decimal]`  (MACD line, signal, histogram)
- `compute_vwap(bars) -> Decimal`  (session VWAP from open)
- `compute_bollinger(bars, period, num_std) -> Tuple[Decimal, Decimal, Decimal]`  (upper, middle, lower)

### 5.3 `MultiTimeframeContext`
**Purpose:** Frozen Pydantic snapshot of all timeframe/indicator data for one instrument at one point in time.  
**Fields:**
- `instrument_token: str`
- `snapshot_timestamp: datetime`
- `timeframes: Dict[str, Dict[str, Decimal]]`  — e.g., `{"1m": {"sma_20": ..., "rsi_14": ...}, "5m": {...}}`
- `regime: MarketRegimeSnapshot`
- `active_announcements: List[AnnouncementRecord]`
- `watchlist_rank: Optional[int]`
- `composite_score: Optional[Decimal]`

### 5.4 `MarketRegimeDetector`
**Purpose:** Classifies market regime for an instrument using ADX/ATR/price-MA relationships.  
**Algorithm** (from RC10_Reference.md §3.3):
1. ADX > 40 and +DI > -DI → STRONG_UPTREND
2. ADX > 25 and +DI > -DI → UPTREND
3. ADX > 40 and -DI > +DI → STRONG_DOWNTREND
4. ADX > 25 and -DI > +DI → DOWNTREND
5. ATR/price > 0.02 → EXPANDING_RANGE
6. ADX < 20 and ATR/price < 0.005 → RANGING
7. Otherwise → UNKNOWN

Confidence = `ADX / 50` clamped to [0, 1] (higher ADX = more confident trend classification).

### 5.5 `WatchlistRanker`
**Purpose:** Scores and ranks instruments by trading opportunity quality.  
**Scoring factors and weights:**
- Regime quality weight 0.35: STRONG_UPTREND=1.0, UPTREND=0.7, RANGING=0.4, EXPANDING_RANGE=0.5, bearish regimes=0.1
- Relative volume weight 0.20: current volume / 20-bar average (capped at 3.0)
- RSI momentum weight 0.20: RSI normalised to [0, 1]; midpoint 50 = 0.5
- Volatility opportunity weight 0.15: ATR as percentage of close price
- Spread/liquidity weight 0.10: inverse of (ask-bid)/mid spread (from Quote if available, else 1.0)

### 5.6 `StrategyScorer`
**Purpose:** Scores each strategy's alignment with current market conditions.  
**Inputs:** `StrategyConfig`, `WatchlistRankingSnapshot`, `Dict[str, MarketRegimeSnapshot]`  
**Output:** `StrategyScore` with `score`, `regime_alignment`, `instrument_suitability`

### 5.7 `AnnouncementIntelligenceService`
**Purpose:** Maintains a live index of corporate announcements per instrument.  
**Responsibilities:**
- `get_active_announcements(instrument_token) -> List[AnnouncementRecord]` (sync, cache-first)
- `poll_and_classify() -> int` (async, hits BSE/NSE announcement APIs)
- Stores results in `announcements` table via `AnnouncementRepository`
- Deduplicates by `(exchange, announcement_id)` with 24h TTL

### 5.8 `AnnouncementPoller`
**Purpose:** Background asyncio task that calls `poll_and_classify()` on a timer.  
**Lifecycle:** `start(interval_seconds=60)` / `stop()`  
**Error handling:** If poll fails, log WARNING and wait for next interval. Never raise.

## 6. Folder Structure

```
src/
└── market_intelligence/
    ├── __init__.py
    ├── timeframe.py
    ├── indicator_engine.py
    ├── multi_timeframe_context.py
    ├── regime.py
    ├── ranking.py
    ├── strategy_scoring.py
    ├── announcements.py
    └── poller.py

src/database/repositories/
└── announcements.py          (new)

migrations/versions/
└── 0004_rc10a_announcements_sector.py

tests/unit/
└── market_intelligence/
    ├── __init__.py
    ├── test_timeframe.py
    ├── test_indicator_engine.py
    ├── test_regime.py
    ├── test_ranking.py
    ├── test_strategy_scoring.py
    └── test_announcements.py
```

## 7. Files to Create

| File | Purpose |
|------|---------|
| `src/market_intelligence/__init__.py` | Package exports |
| `src/market_intelligence/timeframe.py` | `TimeframeAggregator` |
| `src/market_intelligence/indicator_engine.py` | `IndicatorEngine` + all pure indicator functions |
| `src/market_intelligence/multi_timeframe_context.py` | `MultiTimeframeContext`, `MarketRegimeSnapshot`, `AnnouncementRecord`, `InstrumentScore`, `WatchlistRankingSnapshot`, `StrategyScore` (all frozen Pydantic) |
| `src/market_intelligence/regime.py` | `MarketRegimeDetector` |
| `src/market_intelligence/ranking.py` | `WatchlistRanker` |
| `src/market_intelligence/strategy_scoring.py` | `StrategyScorer` |
| `src/market_intelligence/announcements.py` | `AnnouncementIntelligenceService` |
| `src/market_intelligence/poller.py` | `AnnouncementPoller` |
| `src/database/repositories/announcements.py` | `AnnouncementRepository` |
| `migrations/versions/0004_rc10a_announcements_sector.py` | Schema migration |
| `tests/unit/market_intelligence/test_timeframe.py` | Aggregation tests |
| `tests/unit/market_intelligence/test_indicator_engine.py` | Indicator correctness tests |
| `tests/unit/market_intelligence/test_regime.py` | Regime detection tests |
| `tests/unit/market_intelligence/test_ranking.py` | Ranking tests |
| `tests/unit/market_intelligence/test_strategy_scoring.py` | Strategy scoring tests |
| `tests/unit/market_intelligence/test_announcements.py` | Announcement service tests |

## 8. Existing Files That May Be Modified

| File | Change |
|------|--------|
| `src/strategy/context_builder.py` | Extend `build()` to populate `market_snapshots` with `MultiTimeframeContext` (optional injection — existing behaviour unchanged when `market_intelligence` not wired) |
| `src/database/models.py` | Add `sector: Optional[str]` column to `InstrumentMaster`; add `Announcement` model |
| `src/core/config.py` | Add `MarketIntelligenceSettings` sub-class with `announcement_poll_interval_seconds`, `max_indicator_buffer_bars`, `enabled_timeframes` |

## 9. Public Interfaces

```
TimeframeAggregator(instrument_token: str, target_interval: str)
  .on_bar(bar: CompletedBar) -> Optional[CompletedBar]
  .reset() -> None

IndicatorEngine()
  .subscribe(instrument_token: str, timeframe: str) -> None
  .update(bar: CompletedBar, timeframe: str) -> None
  .get_indicators(instrument_token: str, timeframe: str) -> Dict[str, Decimal]
  .get_all_timeframes(instrument_token: str) -> Dict[str, Dict[str, Decimal]]

MarketRegimeDetector()
  .detect(instrument_token: str, indicators: Dict[str, Decimal]) -> MarketRegimeSnapshot

WatchlistRanker()
  .score(instrument_token: str, mtf_context: MultiTimeframeContext) -> InstrumentScore
  .rank(scores: List[InstrumentScore]) -> WatchlistRankingSnapshot

StrategyScorer()
  .score(config: StrategyConfig, ranking: WatchlistRankingSnapshot,
         regimes: Dict[str, MarketRegimeSnapshot]) -> StrategyScore

AnnouncementIntelligenceService(repository: AnnouncementRepository)
  async .get_active_announcements(instrument_token: str) -> List[AnnouncementRecord]
  async .poll_and_classify(session: AsyncSession) -> int
  .is_blackout_period(instrument_token: str, window_minutes: int) -> bool

AnnouncementPoller(service: AnnouncementIntelligenceService, engine: AsyncEngine)
  async .start(interval_seconds: int = 60) -> None
  async .stop() -> None
```

## 10. Data Flow

```
MarketDataService.publish_bar(CompletedBar[1m])
  │
  ├──→ TimeframeAggregator[5m].on_bar()  → CompletedBar[5m]?
  │       └──→ IndicatorEngine.update(bar, "5m")
  ├──→ TimeframeAggregator[15m].on_bar() → CompletedBar[15m]?
  │       └──→ IndicatorEngine.update(bar, "15m")
  ├──→ IndicatorEngine.update(bar, "1m")
  │
  └──→ StrategyRuntime._process_bar()
          └──→ ContextBuilder.build(config, state)
                  └──→ IndicatorEngine.get_all_timeframes(token)
                        MarketRegimeDetector.detect(token, indicators["15m"])
                        AnnouncementIntelligenceService.get_active_announcements(token)
                        WatchlistRanker.get_score(token)
                        → MultiTimeframeContext assembled
                        → StrategyContext.market_snapshots[token] = MultiTimeframeContext
```

```
Background (every 60s):
  AnnouncementPoller
    └──→ AnnouncementIntelligenceService.poll_and_classify(session)
            └──→ HTTP GET BSE/NSE announcement API
            → classify each announcement
            → deduplicate by (exchange, announcement_id)
            → AnnouncementRepository.upsert(session, record)
```

## 11. Sequence Diagrams

### Bar Processing with Market Intelligence

```
StrategyRuntime          ContextBuilder        IndicatorEngine       MarketRegimeDetector
      │                        │                     │                       │
      │  _process_bar(bar)     │                     │                       │
      │──────────────────────→ │                     │                       │
      │                        │  get_all_timeframes │                       │
      │                        │────────────────────→│                       │
      │                        │  {1m:{...}, 5m:{...}}                       │
      │                        │←────────────────────│                       │
      │                        │                     │  detect(token, ind)   │
      │                        │─────────────────────────────────────────────→
      │                        │  MarketRegimeSnapshot                        │
      │                        │←─────────────────────────────────────────────
      │                        │                     │                       │
      │                        │  get_active_announcements(token)            │
      │                        │──→ AnnouncementIntelligenceService          │
      │                        │  List[AnnouncementRecord]                   │
      │                        │←──────────────────────────────────────────  │
      │                        │                                             │
      │                        │  MultiTimeframeContext assembled            │
      │                        │  StrategyContext returned                   │
      │  StrategyContext        │                                             │
      │←───────────────────────│                                             │
      │  strategy.on_bar(bar, ctx)                                           │
```

## 12. Database Changes

### Migration 0004: `rc10a_announcements_sector`

**New table: `announcements`**

| Column | Type | Constraints |
|--------|------|------------|
| `id` | `SERIAL PRIMARY KEY` | |
| `announcement_id` | `VARCHAR(100)` | NOT NULL |
| `exchange` | `VARCHAR(10)` | NOT NULL |
| `instrument_token` | `VARCHAR(50)` | NOT NULL |
| `tradingsymbol` | `VARCHAR(50)` | NOT NULL |
| `classification` | `VARCHAR(30)` | NOT NULL |
| `headline` | `TEXT` | NOT NULL |
| `body_text` | `TEXT` | |
| `ai_summary` | `TEXT` | NULLABLE |
| `model_version` | `VARCHAR(20)` | NULLABLE |
| `published_at` | `TIMESTAMPTZ` | NOT NULL |
| `effective_date` | `DATE` | NULLABLE |
| `raw_metadata` | `JSONB` | DEFAULT `{}` |
| `created_at` | `TIMESTAMPTZ` | server_default=now() |

**Indexes:** `(exchange, announcement_id)` UNIQUE, `(instrument_token, published_at)`, `(classification, published_at)`

**Modified table: `instrument_master`** — add column:
- `sector: VARCHAR(50) NULLABLE`

**Index:** `(sector)` on `instrument_master`

## 13. API Changes

No new API endpoints in 10A.  
The `GET /health` response may optionally be extended to include `market_intelligence_status: {indicator_engine: "active", announcement_poller: "active", last_poll_at: "..."}` — but this is deferred to 10E.

## 14. Configuration Changes

Add to `src/core/config.py`:

```
class MarketIntelligenceSettings(BaseSettings):
    enabled: bool = True
    enabled_timeframes: List[str] = ["1m", "5m", "15m", "1h"]
    max_indicator_buffer_bars: int = 150
    announcement_poll_interval_seconds: int = 60
    announcement_ttl_hours: int = 24
    announcement_blackout_window_minutes: int = 30
    bse_announcement_base_url: str = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
    nse_announcement_base_url: str = "https://www.nseindia.com/api/corporate-announcements"

Settings:
    market_intelligence: MarketIntelligenceSettings = Field(default_factory=MarketIntelligenceSettings)
```

## 15. Integration Points with RC-7, RC-8, RC-9

| RC Layer | Integration Point | How 10A uses it |
|----------|------------------|----------------|
| RC-6 (market_data) | `CompletedBar`, `Tick` — frozen | `TimeframeAggregator.on_bar()` accepts `CompletedBar`; never modifies the contract |
| RC-6 (market_data) | `MarketDataService` — frozen | `AnnouncementPoller` runs independently; does not use `MarketDataService` |
| RC-9 (strategy) | `StrategyContext.market_snapshots` — extension point | `ContextBuilder` populates this dict; existing strategies ignoring it are unaffected |
| RC-9 (strategy) | `StrategyConfig.instrument_tokens` | `IndicatorEngine` subscribes only to instruments listed in active strategies |
| RC-9 (strategy) | `SessionContext` — sole commit site | `AnnouncementPoller` wraps all DB writes in `SessionContext(engine)` |
| RC-9 (strategy) | `StrategyCoordinator` | `AnnouncementPoller` is started/stopped by coordinator lifecycle (optional injection) |

**Zero dependencies on RC-7 (Execution) or RC-8 (Risk)** — 10A is entirely above those layers.

## 16. Dependency Order

```
Within 10A:
  multi_timeframe_context.py    (domain types — no deps)
         ↓
  indicator_engine.py           (depends on multi_timeframe_context)
         ↓
  timeframe.py                  (depends on indicator_engine)
         ↓
  regime.py                     (depends on indicator_engine)
         ↓
  ranking.py                    (depends on regime, indicator_engine)
         ↓
  strategy_scoring.py           (depends on ranking, regime)
         ↓
  announcements.py              (depends on DB repository, multi_timeframe_context)
         ↓
  poller.py                     (depends on announcements, SessionContext)
         ↓
  context_builder.py (modify)   (depends on indicator_engine, regime, announcements)
```

## 17. Unit Testing Requirements

**Minimum 55 unit tests across 6 test files.**

| File | Test Cases (minimum) |
|------|---------------------|
| `test_timeframe.py` | Correct 5m/15m/1h aggregation; OHLCV computed correctly; session-boundary alignment; handles gaps gracefully |
| `test_indicator_engine.py` | SMA known-value test (simple case); EMA convergence; RSI boundaries (0/100); ATR positive; ADX direction agreement with trend; VWAP intraday reset; Bollinger band width positive |
| `test_regime.py` | STRONG_UPTREND when ADX>40 and +DI>-DI; RANGING when ADX<20 and ATR low; EXPANDING when ATR high; confidence in [0,1]; UNKNOWN for insufficient data |
| `test_ranking.py` | Higher volume → higher score (ceteris paribus); correct rank ordering for 5 instruments; score in [0, 1]; handles single instrument |
| `test_strategy_scoring.py` | High regime alignment score for strategy matching strong trend; low score for counter-trend; handles empty instrument list |
| `test_announcements.py` | Deduplication: same announcement_id twice → one record; TTL expiry returns empty; `get_active_announcements` returns empty on DB error (not raise); classification correctness for known headlines |

**Additional requirements:**
- All indicator functions must have known-value tests using manually computed reference values
- `TimeframeAggregator` must pass a determinism test: identical input sequences → identical output
- All tests must pass without any database or network connection

## 18. Integration Testing Requirements

**Minimum 5 integration tests.**

| Test | Description |
|------|------------|
| `test_context_builder_with_intelligence.py` | Wire `ContextBuilder` with `IndicatorEngine` and assert `market_snapshots` populated for each instrument |
| `test_announcement_persistence.py` | Full round-trip: poll mock → classify → store → retrieve |
| `test_timeframe_pipeline.py` | 75 consecutive 1m bars → verify 15 five-minute bars emitted |
| `test_regime_detection_from_db_bars.py` | Load bar sequence from test DB → correct regime detected |
| `test_context_builder_no_intelligence.py` | `ContextBuilder` without `IndicatorEngine` injected produces same result as pre-10A (regression guard) |

## 19. Performance Requirements

- `IndicatorEngine.update()` + `get_indicators()`: combined < 5ms per instrument per bar
- `ContextBuilder.build()` total latency increase from pre-10A: < 10ms
- `AnnouncementPoller.poll_and_classify()`: max 5s per poll cycle (timeout enforced)
- `TimeframeAggregator.on_bar()`: < 0.5ms per call
- Memory per instrument: rolling buffer of 150 bars × 4 timeframes × ~200 bytes/bar ≈ 120KB per instrument. 50 instruments ≈ 6MB total — acceptable

## 20. Security Considerations

- BSE/NSE announcement API calls are outbound HTTP GET. No authentication tokens are required for public feeds; if tokens are added later, they must be stored in `Settings`, not hardcoded
- `AnnouncementRecord.raw_metadata` is JSONB — validate that payload size is bounded before persistence (max 64KB per record)
- Announcement headline and body_text fields must be sanitised before storage (strip null bytes, limit length)
- No announcement data should be logged at DEBUG level in full — log only `announcement_id` and `classification`

## 21. Failure and Recovery Behaviour

| Failure | Behaviour |
|---------|-----------|
| `AnnouncementPoller` HTTP timeout | Log WARNING; skip cycle; retry on next interval |
| `AnnouncementPoller` DB write failure | Log WARNING; continue; data will be fetched again next cycle |
| `IndicatorEngine` insufficient data (< period bars) | Return `None` or `Decimal("0")` for that indicator; do not raise |
| `ContextBuilder` `IndicatorEngine` returns None for an instrument | Skip `MultiTimeframeContext` for that instrument; `market_snapshots` entry absent; strategy receives context without intelligence data |
| `MarketRegimeDetector` receives all-zero indicators | Returns UNKNOWN with confidence=0 |
| BSE/NSE API unavailable for > 1 hour | `AnnouncementIntelligenceService` serves stale data from DB; no errors surfaced to strategies |

## 22. Acceptance Criteria

- [ ] All 445 pre-10A unit tests still pass
- [ ] 55+ new unit tests pass in `tests/unit/market_intelligence/`
- [ ] 5+ integration tests pass
- [ ] `StrategyContext.market_snapshots[token]` contains `MultiTimeframeContext` for all instrument tokens
- [ ] `MarketRegimeSnapshot.confidence` is in [0, 1] for all instruments
- [ ] `WatchlistRankingSnapshot` produced within 50ms for 50 instruments
- [ ] `AnnouncementPoller` runs in background without blocking event loop
- [ ] Alembic migration 0004 applies cleanly and rolls back cleanly
- [ ] `AnnouncementRepository` upsert is idempotent (calling twice with same announcement_id → one DB row)
- [ ] All indicator computations pass known-value tests

## 23. Deliverables

- 9 new source files in `src/market_intelligence/`
- 1 new repository file `src/database/repositories/announcements.py`
- 1 Alembic migration
- 7 test files with 55+ tests
- Modifications to `src/strategy/context_builder.py`, `src/database/models.py`, `src/core/config.py`
- `reviews/Batch10A_closure.md` — closure report

## 24. Out-of-Scope Items

- Real-time WebSocket streaming of indicator data
- Historical backtesting or replaying indicators on past data
- Machine-learning-based regime classification (that is 10B)
- Any modification to `SignalRouter` or `RiskIntegrationLayer`
- AI summarisation of announcements (deferred, optional)

## 25. Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|-----------|
| BSE/NSE public API changes structure | Medium | Medium | Store raw response in `raw_metadata`; classifier is independent of feed structure |
| Indicator warm-up period causes initial UNKNOWN regimes | High | Low | Expected behaviour; strategies must handle UNKNOWN regime gracefully |
| `ContextBuilder` modification breaks existing tests | Low | High | All `ContextBuilder` intelligence injection is optional (guarded by `if indicator_engine is not None`) |
| `IndicatorEngine` memory growth for many instruments | Medium | Medium | Configurable buffer cap (`max_indicator_buffer_bars = 150`); enforce at update time |

## 26. Rollback Strategy

- `ContextBuilder` modifications are additive (optional injection) — removing `market_intelligence` from the constructor restores pre-10A behaviour
- Alembic migration 0004 has a `downgrade()` function that drops the `announcements` table and `sector` column
- `AnnouncementPoller` is never started by default — requires explicit wiring in `main.py`
- Git tag `RC-10A-complete` after acceptance; revert to `RC-9-complete` if rollback required

---

# BATCH 10B — AI FORECAST LAYER

## 1. Objective

Integrate an AI forecasting service (Kronos pattern) as an optional, non-blocking signal enrichment layer. Strategies that opt in receive a `ForecastResult` in signal metadata. The gate is fail-open — when Kronos is unavailable, all signals route normally. Track forecast accuracy over time via a benchmark framework.

## 2. Scope

**In scope:**
- `KronosAdapter`: async HTTP (or local model) inference client
- `FeatureGenerator`: converts `MultiTimeframeContext` → `FeatureVector`
- `ForecastConfidenceGate`: optional pre-routing signal filter
- `VolatilityForecaster`: ATR-based intraday volatility prediction
- `ForecastBenchmark`: records forecast + actual outcome, computes accuracy
- Alembic migration 0005 (`forecast_benchmark` table)
- `SignalRouter` modification to call `ForecastConfidenceGate` (optional)

**Out of scope:**
- Training or fine-tuning ML models
- Model deployment infrastructure
- Position sizing using volatility (that is 10C)
- Kronos WebSocket streaming

## 3. Functional Requirements

| ID | Requirement |
|----|------------|
| 10B-F01 | `KronosAdapter.forecast()` must return `None` (not raise) when the inference endpoint is unavailable |
| 10B-F02 | `ForecastConfidenceGate.should_route()` must return `(True, None)` when `KronosAdapter` returns None |
| 10B-F03 | When a strategy sets `StrategyConfig.parameters["min_forecast_confidence"]`, signals with confidence below that threshold must be suppressed |
| 10B-F04 | `ForecastResult` must be attached to `Signal.metadata["forecast"]` before the routing callback fires |
| 10B-F05 | `FeatureGenerator.generate()` must produce the same `FeatureVector` for identical `MultiTimeframeContext` inputs |
| 10B-F06 | `VolatilityForecaster.forecast()` must produce positive `predicted_atr` and `predicted_range_pct` |
| 10B-F07 | `ForecastBenchmark.record_forecast()` must be idempotent by `(instrument_token, forecast_horizon, computed_at)` |
| 10B-F08 | `ForecastBenchmark.get_accuracy_report()` must return directional accuracy, calibration error, and sample count |
| 10B-F09 | `KronosAdapter` must log `model_version` from the response in every structured log entry |
| 10B-F10 | All Kronos HTTP calls must respect a configurable timeout (default 2000ms) |

## 4. Non-Functional Requirements

| ID | Requirement |
|----|------------|
| 10B-NF01 | `KronosAdapter.forecast()` P95 latency must be < 500ms (network call included) |
| 10B-NF02 | If Kronos prefetch is used, it must not delay the bar processing critical path |
| 10B-NF03 | `FeatureGenerator.generate()` must complete in < 1ms (pure computation) |
| 10B-NF04 | `VolatilityForecaster.forecast()` must complete in < 5ms |
| 10B-NF05 | `ForecastBenchmark` DB writes must be non-blocking (async) |
| 10B-NF06 | `KronosAdapter` must be fully replaceable by a mock in all tests — no live API calls in test suite |

## 5. Detailed Module Breakdown

### 5.1 `KronosAdapter`
**Purpose:** Async HTTP client for Kronos inference API.  
**Key behaviours:**
- Configurable base URL from `settings.ai_forecast.kronos_base_url`
- Timeout enforced at HTTP client level
- Returns `Optional[ForecastResult]` — None on any error
- Records latency per call to `MetricsCollector` (if injected)
- Prefetch pattern: starts inference as `asyncio.create_task()` when bar arrives; result awaited when signal is ready

### 5.2 `FeatureGenerator`
**Purpose:** Converts `MultiTimeframeContext` into a `FeatureVector` suitable for Kronos.  
**Feature set (fixed schema — any change requires model retraining):**
- 1m returns (last 5 bars), 5m returns (last 3 bars)
- RSI(14) normalised to [0, 1] for 1m and 5m
- MACD histogram sign and magnitude (1m, 5m)
- Bollinger band position: (close - lower) / (upper - lower) for 1m
- ATR/close ratio for 1m and 5m
- Regime one-hot encoding (7 values)
- Volume ratio (relative to 20-bar average, 1m)

**Total: ~25 features.** Fixed-length. Schema version stored as a constant `FEATURE_SCHEMA_VERSION`.

### 5.3 `ForecastConfidenceGate`
**Purpose:** Filters signals by Kronos forecast confidence.  
**Logic:**
1. If strategy has no `min_forecast_confidence` in parameters → pass (no filtering)
2. Request forecast from `KronosAdapter`
3. If adapter returns None → pass (fail-open)
4. If `forecast.confidence >= min_confidence` → pass, attach forecast to signal metadata
5. If `forecast.confidence < min_confidence` → suppress; log with reason

### 5.4 `VolatilityForecaster`
**Purpose:** Pure computation of intraday volatility estimates.  
**Algorithms:**
- ATR-based: `predicted_atr = EMA(true_range, 14)` — standard calculation
- Range forecast: `predicted_range_pct = predicted_atr / last_close * 100`
- Confidence: based on ATR stability (low confidence if ATR variance is high)
- Horizon: current session remaining bars (estimated)

### 5.5 `ForecastBenchmark`
**Purpose:** Tracks forecast accuracy for model monitoring.  
**Workflow:**
1. `record_forecast(session, forecast)` — stores forecast record at time T
2. On bar T+horizon: `record_outcome(session, instrument_token, horizon, actual_return)` — updates the record with actual direction
3. `get_accuracy_report(session, instrument_token?, last_n=100)` — computes: directional_accuracy (%), calibration_error (MAE between predicted confidence and binary outcome), sample_count

## 6. Folder Structure

```
src/
└── ai_forecast/
    ├── __init__.py
    ├── kronos_adapter.py
    ├── features.py
    ├── confidence_gate.py
    ├── volatility.py
    └── benchmark.py

migrations/versions/
└── 0005_rc10b_forecast_benchmark.py

tests/unit/
└── ai_forecast/
    ├── __init__.py
    ├── test_kronos_adapter.py
    ├── test_features.py
    ├── test_confidence_gate.py
    ├── test_volatility.py
    └── test_benchmark.py
```

## 7. Files to Create

| File | Purpose |
|------|---------|
| `src/ai_forecast/__init__.py` | Package exports |
| `src/ai_forecast/kronos_adapter.py` | `KronosAdapter`, `ForecastResult` (frozen Pydantic) |
| `src/ai_forecast/features.py` | `FeatureGenerator`, `FeatureVector` (frozen Pydantic) |
| `src/ai_forecast/confidence_gate.py` | `ForecastConfidenceGate` |
| `src/ai_forecast/volatility.py` | `VolatilityForecaster`, `VolatilityForecast` (frozen Pydantic) |
| `src/ai_forecast/benchmark.py` | `ForecastBenchmark`, `BenchmarkReport` (frozen Pydantic) |
| `migrations/versions/0005_rc10b_forecast_benchmark.py` | `forecast_benchmark` table |
| `tests/unit/ai_forecast/test_kronos_adapter.py` | Mock-based adapter tests |
| `tests/unit/ai_forecast/test_features.py` | Feature vector determinism + bounds |
| `tests/unit/ai_forecast/test_confidence_gate.py` | Gate open/closed/fail-open |
| `tests/unit/ai_forecast/test_volatility.py` | ATR/range correctness |
| `tests/unit/ai_forecast/test_benchmark.py` | Record + outcome + accuracy |

## 8. Existing Files That May Be Modified

| File | Change |
|------|--------|
| `src/strategy/signal_router.py` | Add optional `ForecastConfidenceGate` injection; call gate before routing if configured |
| `src/core/config.py` | Add `AiForecastSettings` sub-class with Kronos URL, timeout, feature schema version |

## 9. Public Interfaces

```
ForecastResult (frozen Pydantic):
  instrument_token: str
  forecast_horizon: str        # "15m", "1h"
  direction: str               # "UP" | "DOWN" | "NEUTRAL"
  confidence: Decimal          # [0, 1]
  price_target: Optional[Decimal]
  forecast_error: Optional[str]
  model_version: str
  computed_at: datetime

FeatureVector (frozen Pydantic):
  instrument_token: str
  schema_version: str
  features: List[Decimal]      # fixed-length, schema_version defines semantics
  generated_at: datetime

VolatilityForecast (frozen Pydantic):
  instrument_token: str
  predicted_atr: Decimal
  predicted_range_pct: Decimal
  confidence: Decimal
  forecast_horizon: str
  computed_at: datetime

KronosAdapter(base_url: str, timeout_ms: int = 2000)
  async .forecast(instrument_token: str, features: FeatureVector,
                  horizon: str = "15m") -> Optional[ForecastResult]

FeatureGenerator(feature_schema_version: str)
  .generate(context: MultiTimeframeContext) -> FeatureVector

ForecastConfidenceGate(adapter: KronosAdapter, generator: FeatureGenerator)
  async .should_route(signal: Signal, context: MultiTimeframeContext,
                      min_confidence: Decimal) -> Tuple[bool, Optional[ForecastResult]]

VolatilityForecaster()
  .forecast(instrument_token: str, bars: List[CompletedBar]) -> VolatilityForecast

ForecastBenchmark()
  async .record_forecast(session: AsyncSession, forecast: ForecastResult) -> None
  async .record_outcome(session: AsyncSession, instrument_token: str,
                        horizon: str, actual_return: Decimal,
                        reference_timestamp: datetime) -> None
  async .get_accuracy_report(session: AsyncSession,
                              instrument_token: Optional[str] = None,
                              last_n: int = 100) -> BenchmarkReport
```

## 10. Data Flow

```
StrategyRuntime._process_bar(bar)
  │
  └──→ ContextBuilder.build() → StrategyContext (with MultiTimeframeContext)
  │
  └──→ KronosAdapter.forecast() [asyncio.create_task — prefetch starts now]
  │
  └──→ strategy.on_bar(bar, ctx) → Optional[Signal]
  │
  └──→ if Signal:
          ForecastConfidenceGate.should_route(signal, context, min_confidence)
            └──→ await prefetch task → ForecastResult or None
            └──→ if confidence < threshold → suppress signal
            └──→ if confidence ≥ threshold (or adapter unavailable):
                  Signal.metadata["forecast"] = ForecastResult
                  SignalRouter.route(signal)
                  ForecastBenchmark.record_forecast(session, forecast)  [fire-and-forget]
```

## 11. Sequence Diagrams

### Signal Enrichment with Forecast Gate

```
StrategyRuntime    ForecastConfidenceGate    KronosAdapter    SignalRouter
      │                     │                     │                │
      │ on_bar fires         │                     │                │
      │ create_task(forecast)│                     │                │
      │──────────────────────────────────────────→ │                │
      │                      │                     │ HTTP POST      │
      │ strategy.on_bar()    │                     │────────────→  │
      │──→ Signal emitted    │                     │               │
      │                      │                     │ ForecastResult │
      │ should_route(signal) │                     │←───────────── │
      │─────────────────────→│                     │                │
      │                      │ await prefetch       │                │
      │                      │────────────────────→│                │
      │                      │ ForecastResult       │                │
      │                      │←────────────────────│                │
      │                      │ confidence ≥ min     │                │
      │                      │ → (True, forecast)  │                │
      │ (True, ForecastResult)│                    │                │
      │←─────────────────────│                     │                │
      │ signal.metadata["forecast"] = forecast      │                │
      │ SignalRouter.route(signal)                  │               │
      │────────────────────────────────────────────────────────────→│
```

## 12. Database Changes

### Migration 0005: `rc10b_forecast_benchmark`

**New table: `forecast_benchmark`**

| Column | Type | Constraints |
|--------|------|------------|
| `id` | `SERIAL PRIMARY KEY` | |
| `instrument_token` | `VARCHAR(50)` | NOT NULL |
| `forecast_horizon` | `VARCHAR(10)` | NOT NULL |
| `direction` | `VARCHAR(10)` | NOT NULL |
| `confidence` | `NUMERIC(6,4)` | NOT NULL |
| `model_version` | `VARCHAR(20)` | NOT NULL |
| `computed_at` | `TIMESTAMPTZ` | NOT NULL |
| `actual_direction` | `VARCHAR(10)` | NULLABLE (filled in on outcome) |
| `actual_return` | `NUMERIC(12,6)` | NULLABLE |
| `outcome_recorded_at` | `TIMESTAMPTZ` | NULLABLE |
| `created_at` | `TIMESTAMPTZ` | server_default=now() |

**Indexes:** `(instrument_token, forecast_horizon, computed_at)` UNIQUE, `(model_version, computed_at)`, `(outcome_recorded_at)` partial where outcome_recorded_at IS NOT NULL

## 13. API Changes

No new endpoints in 10B. `GET /strategies/{strategy_id}/metrics` (added in 10E) will include `forecast_accuracy` from `BenchmarkReport`.

## 14. Configuration Changes

```
class AiForecastSettings(BaseSettings):
    enabled: bool = True
    kronos_base_url: str = "http://localhost:8090"
    kronos_timeout_ms: int = 2000
    kronos_max_retries: int = 1
    feature_schema_version: str = "1.0"
    default_forecast_horizon: str = "15m"
    benchmark_accuracy_alert_threshold: float = 0.52   # alert if below 52%

Settings:
    ai_forecast: AiForecastSettings = Field(default_factory=AiForecastSettings)
```

## 15. Integration Points with RC-7, RC-8, RC-9

| RC Layer | Integration Point |
|----------|------------------|
| RC-9 Signal | `ForecastResult` stored in `Signal.metadata["forecast"]` — no contract change |
| RC-9 SignalRouter | Optional `ForecastConfidenceGate` injected as keyword arg; default None |
| RC-9 StrategyConfig | `parameters["min_forecast_confidence"]` read by gate; absent = no filtering |
| 10A MultiTimeframeContext | `FeatureGenerator` consumes this as input |

**Kronos must not call `RiskIntegrationLayer`, `SignalRouter.route()`, or any execution method.**

## 16. Dependency Order

```
features.py              (depends on 10A MultiTimeframeContext)
    ↓
volatility.py            (depends on market_data.contracts only)
    ↓
kronos_adapter.py        (depends on features.py, ForecastResult)
    ↓
confidence_gate.py       (depends on kronos_adapter, features)
    ↓
benchmark.py             (depends on DB session, ForecastResult)
    ↓
signal_router.py (mod)   (depends on confidence_gate — optional injection)
```

## 17. Unit Testing Requirements

**Minimum 50 tests.**

| File | Key Tests |
|------|-----------|
| `test_kronos_adapter.py` | Returns None on HTTP 503; returns None on timeout; returns ForecastResult on success; logs model_version; retries once on failure |
| `test_features.py` | Determinism test (same context → same vector); feature count = 25; all values finite Decimal; correct regime one-hot encoding |
| `test_confidence_gate.py` | Gate open when adapter returns None (fail-open); gate open when no min_confidence in params; gate closed when confidence < threshold; gate open when confidence ≥ threshold; forecast attached to signal metadata |
| `test_volatility.py` | `predicted_atr` > 0 for valid bars; `confidence` in [0, 1]; handles < 14 bars (returns low confidence) |
| `test_benchmark.py` | `record_forecast` idempotent; `record_outcome` updates correct row; `get_accuracy_report` computes directional_accuracy correctly for known cases; empty result for no records |

## 18. Integration Testing Requirements

**Minimum 5 integration tests.**

| Test | Description |
|------|------------|
| `test_signal_router_with_gate.py` | Signal with high confidence routes; signal with low confidence suppressed |
| `test_forecast_benchmark_persistence.py` | Record forecast + outcome → accuracy report reflects both |
| `test_kronos_adapter_unavailable.py` | Adapter unavailable → signals still route (fail-open verified end-to-end) |
| `test_feature_vector_from_live_context.py` | Full pipeline: 30 bars → `MultiTimeframeContext` → `FeatureVector` |
| `test_volatility_from_real_bars.py` | 20 real bars from test fixture → positive ATR forecast |

## 19. Performance Requirements

- `ForecastConfidenceGate.should_route()` (including Kronos HTTP call): < 500ms P95
- `FeatureGenerator.generate()`: < 1ms
- `VolatilityForecaster.forecast()`: < 5ms for 150 bars
- Kronos prefetch task must not delay bar processing beyond `settings.ai_forecast.kronos_timeout_ms`

## 20. Security Considerations

- Kronos base URL must be from `Settings`, never hardcoded
- Kronos responses must be validated as `ForecastResult` before use — malformed responses return `None`
- `ForecastResult.confidence` must be validated in [0, 1]; values outside range are rejected
- No signal data is sent to Kronos — only the `FeatureVector` (computed from market data, no account/portfolio data)

## 21. Failure and Recovery Behaviour

| Failure | Behaviour |
|---------|-----------|
| Kronos HTTP 503 | Return None; gate passes signal; log WARNING |
| Kronos response malformed | Return None; gate passes signal; log ERROR |
| Kronos timeout | Return None (after timeout_ms); gate passes signal; log WARNING |
| `record_forecast` DB error | Log WARNING; do not retry; routing continues unaffected |
| `record_outcome` row not found | Log DEBUG (forecast may have been pruned); no error |
| `get_accuracy_report` DB error | Return `BenchmarkReport` with `sample_count=0` and accuracy=0.0; not raise |

## 22. Acceptance Criteria

- [ ] All pre-10B tests still pass
- [ ] 50+ new unit tests pass
- [ ] `KronosAdapter` returns None on all error conditions (verified by mock tests)
- [ ] `ForecastConfidenceGate` is fail-open (verified by integration test)
- [ ] `Signal.metadata["forecast"]` contains `ForecastResult` when Kronos succeeds
- [ ] Strategy without `min_forecast_confidence` in parameters routes all signals unchanged
- [ ] `ForecastBenchmark` table populated after one bar cycle with mocked Kronos
- [ ] Alembic migration 0005 applies and rolls back cleanly
- [ ] Zero live Kronos API calls in any test

## 23. Deliverables

- 6 new source files in `src/ai_forecast/`
- 1 Alembic migration
- 6 test files with 50+ tests
- Modifications to `src/strategy/signal_router.py`, `src/core/config.py`
- `reviews/Batch10B_closure.md`

## 24. Out-of-Scope Items

- Model training or retraining pipeline
- Model deployment (Kronos is treated as an external service)
- Alternative AI providers
- Real-time streaming forecast updates

## 25. Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|-----------|
| Kronos latency exceeds bar cycle time | Medium | High | Prefetch pattern starts inference concurrently with bar processing; timeout enforced |
| Feature schema drift breaks model | Low | High | `feature_schema_version` constant; model API must reject mismatched versions |
| Benchmark accuracy drops silently | Medium | Medium | `ForecastBenchmark` report surfaced in 10E dashboard; alert if accuracy < 52% |
| `min_forecast_confidence` misconfigured too high → no signals | Medium | Medium | Alert when a strategy suppresses >80% of signals in a session |

## 26. Rollback Strategy

- `SignalRouter` modification is guarded by `if self._forecast_gate is not None` — removing the injection restores pre-10B behaviour
- `ForecastBenchmark` table can remain (additive); migration 0005 `downgrade()` drops it
- Git tag `RC-10B-complete`

---

# BATCH 10C — PORTFOLIO MANAGEMENT

## 1. Objective

Add a portfolio management layer that computes optimal trade quantities (dynamic position sizing), enforces per-strategy capital allocation, limits sector concentration, monitors instrument correlation, and allocates total capital across strategies based on their scores.

## 2. Scope

**In scope:**
- `PositionSizer`: computes trade quantity from risk parameters and volatility
- `PortfolioAllocator`: enforces per-strategy capital limits in real time
- `SectorExposureTracker`: computes and limits sector concentration
- `CorrelationMonitor`: maintains rolling correlation matrix; filters correlated entries
- `CapitalAllocationEngine`: divides equity across strategies by score
- New risk rule `SECTOR_EXPOSURE` wired into `RiskIntegrationLayer`
- Modifications to `SignalRouter` to apply sizing before order submission

**Out of scope:**
- Multi-leg order strategies (pairs trading, spreads)
- Portfolio optimisation beyond the defined constraints
- Historical portfolio backtesting

## 3. Functional Requirements

| ID | Requirement |
|----|------------|
| 10C-F01 | `PositionSizer.compute_quantity()` must return a quantity ≤ `StrategyConfig.max_position_quantity` always |
| 10C-F02 | If computed quantity rounds to zero, `SizingResult.recommended_quantity == Decimal("0")` — signal must be dropped by `SignalRouter` |
| 10C-F03 | `PositionSizer` must support three sizing methods: fixed-risk (1% per trade), Kelly Criterion (fractional, capped at 25% Kelly), volatility-adjusted (ATR-stop based) |
| 10C-F04 | `PortfolioAllocator.can_allocate()` must return False when `reserved + proposed > strategy_capital_limit` |
| 10C-F05 | `PortfolioAllocator.reserve()` and `.release()` must be coroutine-safe (asyncio.Lock protected) |
| 10C-F06 | `SectorExposureTracker.check_limit()` must return False when adding the proposed notional would push sector exposure above `settings.risk.sector_exposure_pct` |
| 10C-F07 | `CorrelationMonitor.check_correlation()` must return False when the new instrument has correlation ≥ `settings.risk.correlation_threshold` with any currently held instrument |
| 10C-F08 | `CapitalAllocationEngine.allocate()` must allocate the full `total_equity * max_allocation_pct` across strategies proportional to their scores |
| 10C-F09 | All sizing decisions must be logged with `rationale` explaining the sizing method and key inputs |
| 10C-F10 | `SectorExposureTracker` must return PASS (not block) when `sector` is NULL for an instrument |

## 4. Non-Functional Requirements

| ID | Requirement |
|----|------------|
| 10C-NF01 | `PositionSizer.compute_quantity()` must complete in < 2ms |
| 10C-NF02 | `PortfolioAllocator` operations must complete in < 1ms under asyncio.Lock |
| 10C-NF03 | `CorrelationMonitor.update()` must complete in < 5ms for a matrix of 50 instruments |
| 10C-NF04 | `CapitalAllocationEngine.allocate()` must complete in < 10ms for 20 strategies |
| 10C-NF05 | All portfolio state is in-process only; no DB writes required for hot-path operations |

## 5. Detailed Module Breakdown

### 5.1 `PositionSizer`
**Methods:**
- `compute_quantity(signal, portfolio, volatility_forecast, config, risk_config) -> SizingResult`
- `_fixed_risk_quantity(equity, risk_pct, stop_distance, price) -> Decimal`
- `_kelly_quantity(equity, win_rate, win_loss_ratio, max_fraction) -> Decimal`
- `_volatility_adjusted_quantity(equity, risk_pct, atr, atr_multiplier, price) -> Decimal`

**SizingResult (frozen dataclass):** `recommended_quantity: Decimal`, `sizing_method: str`, `rationale: str`, `risk_fraction_used: Decimal`, `hard_cap_applied: bool`

### 5.2 `PortfolioAllocator`
**State:** `_allocations: Dict[strategy_id, Decimal]` (currently reserved notional), `_limits: Dict[strategy_id, Decimal]` (per-strategy capital limit), `asyncio.Lock`  
**Methods:** `configure_limit(strategy_id, capital_limit)`, `can_allocate(strategy_id, notional) -> bool`, `async reserve(strategy_id, notional)`, `async release(strategy_id, notional)`, `get_allocation(strategy_id) -> Decimal`, `get_all_allocations() -> Dict[str, Decimal]`

### 5.3 `SectorExposureTracker`
**State:** No internal state — computes from `PortfolioSnapshot` + instrument sector data on each call  
**Methods:** `get_exposures(portfolio, instrument_sectors) -> Dict[str, Decimal]`, `check_limit(sector, proposed_notional, total_equity, max_pct) -> bool`

### 5.4 `CorrelationMonitor`
**State:** Per-`(instrument_token)` rolling return series (last N bars)  
**Methods:** `update(bar: CompletedBar)`, `check_correlation(new_token, current_tokens, threshold) -> bool`, `get_correlation_matrix() -> Dict[str, Dict[str, Decimal]]`  
**Algorithm:** Pearson correlation on log returns of last 20 bars (configurable)

### 5.5 `CapitalAllocationEngine`
**Methods:** `allocate(scores: List[StrategyScore], total_equity: Decimal) -> Dict[str, Decimal]`  
**Allocation modes:** `equal` (1/N), `score_proportional` (share = score_i / sum(scores)), `risk_adjusted` (score × (1 - drawdown_pct))

## 6. Folder Structure

```
src/
└── portfolio/
    ├── __init__.py
    ├── sizing.py
    ├── allocation.py
    ├── sector.py
    ├── correlation.py
    └── capital.py

tests/unit/
└── portfolio/
    ├── __init__.py
    ├── test_sizing.py
    ├── test_allocation.py
    ├── test_sector.py
    ├── test_correlation.py
    └── test_capital.py
```

## 7. Files to Create

| File | Purpose |
|------|---------|
| `src/portfolio/__init__.py` | Package exports |
| `src/portfolio/sizing.py` | `PositionSizer`, `SizingResult` |
| `src/portfolio/allocation.py` | `PortfolioAllocator` |
| `src/portfolio/sector.py` | `SectorExposureTracker` |
| `src/portfolio/correlation.py` | `CorrelationMonitor` |
| `src/portfolio/capital.py` | `CapitalAllocationEngine` |
| `tests/unit/portfolio/test_sizing.py` | Sizing tests |
| `tests/unit/portfolio/test_allocation.py` | Allocation tests |
| `tests/unit/portfolio/test_sector.py` | Sector exposure tests |
| `tests/unit/portfolio/test_correlation.py` | Correlation matrix tests |
| `tests/unit/portfolio/test_capital.py` | Capital allocation tests |

## 8. Existing Files That May Be Modified

| File | Change |
|------|--------|
| `src/strategy/signal_router.py` | Add optional `PositionSizer` and `PortfolioAllocator` injection; adjust signal quantity before routing; drop signal if sizing returns 0 |
| `src/risk/contracts.py` | Add `SECTOR_EXPOSURE` to `RiskCheckType` enum (additive — no existing values change) |
| `src/risk/rules.py` | Implement `SectorExposureRule` using `SectorExposureTracker` |

## 9. Public Interfaces

```
SizingResult (frozen dataclass):
  recommended_quantity: Decimal
  sizing_method: str
  rationale: str
  risk_fraction_used: Decimal
  hard_cap_applied: bool

PositionSizer(default_method: str = "volatility_adjusted")
  .compute_quantity(signal, portfolio, volatility_forecast,
                    config, risk_config) -> SizingResult

PortfolioAllocator()
  .configure_limit(strategy_id: str, capital_limit: Decimal) -> None
  async .can_allocate(strategy_id: str, notional: Decimal) -> bool
  async .reserve(strategy_id: str, notional: Decimal) -> None
  async .release(strategy_id: str, notional: Decimal) -> None
  .get_allocation(strategy_id: str) -> Decimal

SectorExposureTracker()
  .get_exposures(portfolio: PortfolioSnapshot,
                 instrument_sectors: Dict[str, str]) -> Dict[str, Decimal]
  .check_limit(sector: str, proposed_notional: Decimal,
               total_equity: Decimal, max_pct: Decimal) -> bool

CorrelationMonitor(window: int = 20)
  .update(bar: CompletedBar) -> None
  .check_correlation(new_token: str, current_tokens: List[str],
                     threshold: Decimal) -> bool

CapitalAllocationEngine(method: str = "score_proportional",
                         max_allocation_pct: Decimal = Decimal("0.8"))
  .allocate(scores: List[StrategyScore],
            total_equity: Decimal) -> Dict[str, Decimal]
```

## 10. Data Flow

```
StrategyRuntime._process_bar() → strategy.on_bar() → Signal
  │
  └──→ SignalRouter.route(signal)
          │
          ├──→ PortfolioAllocator.can_allocate(strategy_id, signal.quantity * price)?
          │       → NO: suppress signal, log reason
          │
          ├──→ PositionSizer.compute_quantity(signal, portfolio, volatility, config)
          │       → SizingResult.recommended_quantity = 0? → drop signal
          │       → adjust signal.quantity (create new frozen Signal with adjusted qty)
          │
          ├──→ SectorExposureTracker (via SECTOR_EXPOSURE risk rule in RiskEngine)
          │       → evaluated inside RiskIntegrationLayer.submit_order()
          │
          └──→ RiskIntegrationLayer.submit_order(account_id, adjusted_order)
                  → if approved: PortfolioAllocator.reserve(strategy_id, notional)
                  → on fill: PortfolioAllocator.release(strategy_id, notional)
                             (triggered via FillEventBus handler)
```

## 11. Sequence Diagrams

### Sized Signal Routing

```
SignalRouter         PositionSizer      PortfolioAllocator    RiskIntegrationLayer
    │                     │                    │                      │
    │ route(signal)        │                    │                      │
    │──────────────────→   │                    │                      │
    │                      │                    │                      │
    │ compute_quantity()   │                    │                      │
    │──────────────────────→                    │                      │
    │ SizingResult(qty=150)│                    │                      │
    │←──────────────────────                    │                      │
    │                      │                    │                      │
    │ qty == 0? → drop       │                    │                      │
    │                      │                    │                      │
    │ can_allocate(sid, 150*price)?              │                      │
    │──────────────────────────────────────────→│                      │
    │ True                 │                    │                      │
    │←──────────────────────────────────────────│                      │
    │                      │                    │                      │
    │ submit_order(adjusted_order)              │                      │
    │──────────────────────────────────────────────────────────────────→
    │ RiskIntegrationResult(approved=True)       │                     │
    │←──────────────────────────────────────────────────────────────────
    │                      │                    │                      │
    │ reserve(sid, notional)                     │                      │
    │──────────────────────────────────────────→│                      │
```

## 12. Database Changes

No new tables in 10C. Sector data leverages the `sector` column added to `instrument_master` in migration 0004.

## 13. API Changes

No new endpoints in 10C. `GET /strategies/{strategy_id}` (added in 10E) will include `portfolio_allocation_reserved` from `PortfolioAllocator`.

## 14. Configuration Changes

`RiskSettings` already contains `sector_exposure_pct` and `correlation_threshold`. No new top-level settings needed. `PositionSizer` default method can be added to `ExecutionSettings`.

## 15. Integration Points with RC-7, RC-8, RC-9

| Layer | Integration |
|-------|------------|
| RC-8 RiskEngine | New `SECTOR_EXPOSURE` rule added via `add_limit()` API |
| RC-8 FillEventBus | `PortfolioAllocator.release()` called on fill via bus subscription |
| RC-9 SignalRouter | `PositionSizer` and `PortfolioAllocator` injected as optional kwargs |
| 10A `VolatilityForecast` | Used by `PositionSizer._volatility_adjusted_quantity()` |
| 10A `WatchlistRankingSnapshot` | Used by `CapitalAllocationEngine.allocate()` |

## 16. Dependency Order

```
sizing.py            (depends on 10B VolatilityForecast, execution.portfolio)
    ↓
allocation.py        (no external deps beyond asyncio)
    ↓
sector.py            (depends on execution.portfolio, instrument_master data)
    ↓
correlation.py       (depends on market_data.contracts)
    ↓
capital.py           (depends on 10A StrategyScore)
    ↓
signal_router.py     (modified to inject sizing + allocation)
risk/rules.py        (modified to add sector rule)
```

## 17. Unit Testing Requirements

**Minimum 45 tests.**

| File | Key Tests |
|------|-----------|
| `test_sizing.py` | Hard cap enforced; qty=0 when risk budget insufficient; three methods produce valid results; risk_fraction_used ≤ 1.0 |
| `test_allocation.py` | `can_allocate` False when limit exceeded; reserve + can_allocate + release cycle; concurrent reserve calls serialised by lock |
| `test_sector.py` | Exposure calculation correct for 2-sector portfolio; `check_limit` False when over max_pct; PASS when sector=None |
| `test_correlation.py` | Positively correlated instruments detected; uncorrelated instruments not blocked; correlation in [-1, 1] |
| `test_capital.py` | Equal weight: all equal; score-proportional: higher score → more capital; total allocation = max_allocation_pct × equity |

## 18. Integration Testing Requirements

**Minimum 4 integration tests.**

| Test | Description |
|------|------------|
| `test_signal_router_sizing.py` | Signal quantity adjusted by sizer before risk check |
| `test_signal_router_qty_zero.py` | Signal dropped when sizer returns 0 |
| `test_portfolio_allocator_fill_release.py` | Reserve on route, release on fill via FillEventBus |
| `test_sector_risk_rule.py` | SECTOR_EXPOSURE rule blocks order when sector limit exceeded |

## 19. Performance Requirements

- `PositionSizer.compute_quantity()`: < 2ms
- `PortfolioAllocator` operations: < 1ms each
- `CorrelationMonitor.update()` for 50 instruments: < 5ms

## 20. Security Considerations

- `PortfolioAllocator` state reset on crash is intentional — no persistence risk
- Sector data from `instrument_master` is read-only from the portfolio layer — no writes
- Position sizing can never increase signal quantity beyond `max_position_quantity` — this is a safety cap

## 21. Failure and Recovery Behaviour

| Failure | Behaviour |
|---------|-----------|
| `PositionSizer` encounters None volatility forecast | Falls back to fixed-risk method; logs WARNING |
| `PortfolioAllocator.reserve()` error | Log ERROR; routing continues (fail-open for allocation failures) |
| `CorrelationMonitor` insufficient data | Returns True (allow) — correlation cannot be asserted without data |
| `CapitalAllocationEngine` all scores zero | Falls back to equal weight |

## 22. Acceptance Criteria

- [ ] All pre-10C tests still pass
- [ ] 45+ new unit tests pass
- [ ] Signal quantity never exceeds `StrategyConfig.max_position_quantity`
- [ ] Signal with sizing result = 0 is dropped (not sent with qty=0)
- [ ] `SECTOR_EXPOSURE` rule correctly blocks when sector limit breached
- [ ] `PortfolioAllocator.release()` called on every fill (verified via FillEventBus test)
- [ ] `CapitalAllocationEngine` allocations sum ≤ `total_equity * max_allocation_pct`

## 23. Deliverables

- 6 new source files in `src/portfolio/`
- 5 test files with 45+ tests
- Modifications to `src/strategy/signal_router.py`, `src/risk/contracts.py`, `src/risk/rules.py`
- `reviews/Batch10C_closure.md`

## 24. Out-of-Scope Items

- Multi-leg orders or spread strategies
- Historical portfolio optimisation
- External portfolio analytics services

## 25. Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|-----------|
| `PortfolioAllocator` state lost on crash | High (by design) | Low | Expected — allocations reset on restart; recovery system restores strategy state |
| Sector data missing from `instrument_master` | High | Low | `check_limit` returns True when sector=None |
| Sizing produces non-integer quantity for NSE equities | High | Medium | Round down to integer lots after sizing; never round up |
| Correlation matrix computation slow for 100 instruments | Low | Low | Pearson on 20 returns = trivial; use numpy if available |

## 26. Rollback Strategy

- All `SignalRouter` changes are optional injections — remove kwargs to restore pre-10C
- `SECTOR_EXPOSURE` rule is additive to `risk/rules.py` — remove the rule class and registry entry
- No DB changes — no migration rollback needed
- Git tag `RC-10C-complete`

---

# BATCH 10D — BROKER LAYER

## 1. Objective

Enable full Zerodha Kite Connect write integration, replacing the paper broker simulation for LIVE mode. Add order synchronisation to detect fills from the exchange, position reconciliation to ensure internal state matches Kite's book, and account-level API endpoints.

## 2. Scope

**In scope:**
- `ZerodhaKiteClient`: full `BrokerInterface` implementation using `kiteconnect`
- `ZerodhaExecutionAdapter`: `ExecutionEnginePort` wrapping the Kite client
- `OrderSyncService`: background task polling Kite order book
- `PositionReconciler`: on-demand position verification
- `zerodha_sessions` table for persisting Kite access tokens
- Account API router (`/account/margins`, `/account/holdings`, `/account/profile`)
- LIVE mode enablement (conditional — gated by double env var confirmation)

**Out of scope:**
- Options/futures order types
- Basket orders or multi-leg orders
- WebSocket tick stream from Kite (data feeds — defer to separate RC)

## 3. Functional Requirements

| ID | Requirement |
|----|------------|
| 10D-F01 | `ZerodhaKiteClient.place_order()` must route through `RiskIntegrationLayer.submit_order()` — no direct broker call without risk approval |
| 10D-F02 | LIVE mode must require both `ENABLE_LIVE_TRADING=true` AND `LIVE_TRADING_CONFIRMED=true` environment variables; absence of either keeps PAPER mode active |
| 10D-F03 | Kite access token must be persisted in `zerodha_sessions` table and reused across restarts |
| 10D-F04 | `OrderSyncService.sync_once()` must detect COMPLETE fills in Kite not yet recorded in the internal DB and publish `FillEvent` via `FillEventBus` |
| 10D-F05 | `PositionReconciler.reconcile()` must stop all active strategies and set a reconciliation flag when position mismatch is detected |
| 10D-F06 | `ZerodhaKiteClient` must implement a token-bucket rate limiter at ≤ 3 requests/second |
| 10D-F07 | Access token expiry (HTTP 403) must trigger a re-login flow or surfaced alert — never silently swallow |
| 10D-F08 | `GET /account/margins` must return paper margins when Kite is not connected |
| 10D-F09 | `ZerodhaKiteClient` must log every API call at DEBUG level with method, status, and latency |
| 10D-F10 | All order modifications and cancellations must also pass through `RiskIntegrationLayer` |

## 4. Non-Functional Requirements

| ID | Requirement |
|----|------------|
| 10D-NF01 | `ZerodhaKiteClient.place_order()` round-trip: < 2s P95 (network dependent) |
| 10D-NF02 | `OrderSyncService` poll cycle: < 5s per cycle (including all order fetches) |
| 10D-NF03 | Kite client must implement exponential backoff: 0.5s, 1s, 2s for retries |
| 10D-NF04 | `PositionReconciler.reconcile()` must complete in < 10s for 50 positions |
| 10D-NF05 | Rate limiter must be coroutine-safe (asyncio.Lock or token bucket) |
| 10D-NF06 | Access token storage must be encrypted at rest (use `pgcrypto` or application-level AES) — DEFER to hardening batch; for RC-10D store hashed or plaintext with restricted DB access |

## 5. Detailed Module Breakdown

### 5.1 `ZerodhaKiteClient`
**Implements:** `BrokerInterface`  
**Key additions beyond interface:**
- `login(request_token: str) -> str` — exchanges request token for access token
- `get_token(session: AsyncSession) -> Optional[str]` — loads from `zerodha_sessions` table
- `save_token(session: AsyncSession, access_token: str)` — persists token
- Internal `_rate_limiter: asyncio.Semaphore` with 3/second token bucket

### 5.2 `ZerodhaExecutionAdapter`
**Implements:** `ExecutionEnginePort`  
**Maps BrokerInterface to ExecutionEnginePort:**
- `get_portfolio_snapshot(account_id)` → calls `get_margins()`, converts to `PortfolioSnapshot` dict format
- `get_position_snapshots(account_id)` → calls `get_positions()`, converts to position dict format
- `get_open_orders(account_id)` → calls `get_orders()`, filters to OPEN/PENDING
- `get_market_price(instrument_token)` → calls `get_quote([symbol])`
- `submit_order(account_id, order)` → calls `place_order(OrderRequest)`, returns result dict

### 5.3 `OrderSyncService`
**Responsibilities:**
- Poll `ZerodhaKiteClient.get_orders()` every N seconds
- Compare with `OrderRepository.get_open_orders(session, account_id)`
- On status change (OPEN → COMPLETE): update DB, publish `FillEvent` via `FillEventBus`
- On new Kite order unknown to DB: log WARNING as `EXTERNAL_ORDER`
- Lifecycle: `start(interval_seconds=10)` / `stop()`

### 5.4 `PositionReconciler`
**Responsibilities:**
- Fetch Kite positions via `ZerodhaKiteClient.get_positions()`
- Fetch internal positions from `PositionRepository`
- Compare by `(tradingsymbol, quantity)`
- On mismatch: log CRITICAL, call `coordinator.pause(strategy_id)` for all strategies holding that instrument, persist `ReconciliationResult` to `incidents` table
- Return `ReconciliationResult` with `is_clean: bool`, `mismatches: List[PositionMismatch]`

## 6. Folder Structure

```
src/brokers/
├── (interface.py — unchanged)
├── (paper_broker.py — unchanged)
├── (zerodha_readonly.py — unchanged)
├── zerodha_kite.py
├── zerodha_adapter.py
├── order_sync.py
└── position_reconciler.py

src/api/routers/
└── account.py

src/database/repositories/
└── zerodha_sessions.py

migrations/versions/
└── 0006_rc10d_zerodha_sessions.py

tests/unit/brokers/
├── __init__.py
├── test_zerodha_kite.py
├── test_zerodha_adapter.py
├── test_order_sync.py
└── test_position_reconciler.py

tests/integration/
└── test_account_api.py
```

## 7. Files to Create

| File | Purpose |
|------|---------|
| `src/brokers/zerodha_kite.py` | `ZerodhaKiteClient` (full BrokerInterface impl) |
| `src/brokers/zerodha_adapter.py` | `ZerodhaExecutionAdapter` (ExecutionEnginePort impl) |
| `src/brokers/order_sync.py` | `OrderSyncService` |
| `src/brokers/position_reconciler.py` | `PositionReconciler`, `PositionMismatch`, `ReconciliationResult` |
| `src/api/routers/account.py` | Account API router |
| `src/database/repositories/zerodha_sessions.py` | `ZerodhaSessionRepository` |
| `migrations/versions/0006_rc10d_zerodha_sessions.py` | `zerodha_sessions` table |
| `tests/unit/brokers/test_zerodha_kite.py` | Client unit tests (mocked kiteconnect) |
| `tests/unit/brokers/test_zerodha_adapter.py` | Adapter unit tests |
| `tests/unit/brokers/test_order_sync.py` | Sync service tests |
| `tests/unit/brokers/test_position_reconciler.py` | Reconciler tests |
| `tests/integration/test_account_api.py` | Account endpoint tests |

## 8. Existing Files That May Be Modified

| File | Change |
|------|--------|
| `src/core/config.py` | Relax `enforce_paper_mode` validator: allow LIVE when `ENABLE_LIVE_TRADING=true` AND `LIVE_TRADING_CONFIRMED=true` |
| `src/main.py` | Wire `OrderSyncService` as background task; add account router |
| `src/brokers/paper_broker.py` | Add `get_margins()` stub returning paper capital data |
| `src/core/config.py` | Add `ZerodhaSettings` for API base URL, session expiry hours |

## 9. Public Interfaces

```
ZerodhaKiteClient(api_key: str, api_secret: str, session_token: Optional[str] = None)
  # Implements all BrokerInterface methods
  async .login(request_token: str) -> str
  async .get_token(session: AsyncSession) -> Optional[str]
  async .save_token(session: AsyncSession, access_token: str) -> None

ZerodhaExecutionAdapter(kite: ZerodhaKiteClient)
  # Implements all ExecutionEnginePort methods

OrderSyncService(kite: ZerodhaKiteClient, order_repo: OrderRepository,
                 fill_bus: FillEventBus, engine: AsyncEngine)
  async .start(interval_seconds: int = 10) -> None
  async .stop() -> None
  async .sync_once() -> int   # returns count of synced orders

ReconciliationResult (frozen dataclass):
  is_clean: bool
  mismatches: List[PositionMismatch]
  reconciled_at: datetime

PositionReconciler(kite: ZerodhaKiteClient, position_repo: PositionRepository,
                   coordinator: StrategyCoordinator, engine: AsyncEngine)
  async .reconcile() -> ReconciliationResult
```

## 10. Data Flow

### Order Placement (LIVE mode)

```
StrategyRuntime → Signal → SignalRouter
  → RiskIntegrationLayer.submit_order(account_id, order)
      └──→ ZerodhaExecutionAdapter.submit_order(account_id, order)
              └──→ ZerodhaKiteClient.place_order(OrderRequest)
                      [rate limiter token acquired]
                      [HTTP POST to api.kite.trade]
                      → OrderResponse
      ← RiskIntegrationResult(approved=True, execution_result={...})
  → FillEventBus.publish_nowait(FillEvent) [if status=COMPLETE]
```

### Order Synchronisation (background)

```
OrderSyncService (every 10s)
  └──→ ZerodhaKiteClient.get_orders() → List[KiteOrder]
  └──→ OrderRepository.get_open_orders(session) → List[Order]
  └──→ diff(kite_orders, internal_orders)
       → for each completed Kite order not in DB:
           OrderRepository.update_status(session, COMPLETE)
           FillEventBus.publish_nowait(FillEvent)
```

## 11. Sequence Diagrams

### Access Token Lifecycle

```
main.py            ZerodhaKiteClient    ZerodhaSessionRepository    Kite API
   │                      │                        │                    │
   │ startup               │                        │                    │
   │ get_token(session)    │                        │                    │
   │──────────────────────→│                        │                    │
   │                       │ find_active_token()    │                    │
   │                       │───────────────────────→│                    │
   │                       │ access_token or None   │                    │
   │                       │←───────────────────────│                    │
   │                       │                        │                    │
   │                       │ None → need login      │                    │
   │                       │                        │                    │
   │ operator GET /auth/kite/callback?request_token=... (new endpoint)    │
   │──────────────────────→│                        │                    │
   │                       │ POST /session/token    │                    │
   │                       │───────────────────────────────────────────→ │
   │                       │ {access_token: "..."}  │                    │
   │                       │←───────────────────────────────────────────  │
   │                       │ save_token(session, token)                   │
   │                       │───────────────────────→│                    │
   │ 200 OK               │                        │                    │
   │←──────────────────────│                        │                    │
```

## 12. Database Changes

### Migration 0006: `rc10d_zerodha_sessions`

**New table: `zerodha_sessions`**

| Column | Type | Constraints |
|--------|------|------------|
| `id` | `SERIAL PRIMARY KEY` | |
| `account_id` | `VARCHAR(50)` | NOT NULL |
| `access_token` | `TEXT` | NOT NULL |
| `request_token` | `TEXT` | NULLABLE |
| `login_time` | `TIMESTAMPTZ` | NOT NULL |
| `expiry_time` | `TIMESTAMPTZ` | NOT NULL |
| `is_active` | `BOOLEAN` | NOT NULL DEFAULT TRUE |
| `created_at` | `TIMESTAMPTZ` | server_default=now() |
| `updated_at` | `TIMESTAMPTZ` | server_default=now() |

**Indexes:** `(account_id, is_active)`, `(expiry_time)` partial where is_active=TRUE

## 13. API Changes

**New router: `src/api/routers/account.py`**

| Method | Path | Description |
|--------|------|------------|
| `GET` | `/account/margins` | Current margins (Kite if connected, paper otherwise) |
| `GET` | `/account/holdings` | Long-term equity holdings from Kite |
| `GET` | `/account/profile` | Account metadata (name, segments, user_id) |
| `GET` | `/account/kite/status` | Kite connection status (connected/disconnected/token_expired) |
| `POST` | `/account/kite/callback` | OAuth2 callback receiver — exchanges request_token for access_token |

**All new endpoints require Bearer JWT auth.**

## 14. Configuration Changes

```
class ZerodhaSettings(BaseSettings):
    api_key: Optional[str] = None              # from ZERODHA_API_KEY env var (already in Settings)
    api_secret: Optional[str] = None           # from ZERODHA_API_SECRET env var
    base_url: str = "https://api.kite.trade"
    login_url: str = "https://kite.zerodha.com/connect/login"
    session_expiry_hours: int = 24
    rate_limit_rps: int = 3
    order_sync_interval_seconds: int = 10
    reconcile_on_startup: bool = True

TradingSettings — change enforce_paper_mode:
    Removed unconditional LIVE block.
    New logic: if mode == "LIVE" and not (ENABLE_LIVE_TRADING == "true"
               and LIVE_TRADING_CONFIRMED == "true") → raise ValueError
```

## 15. Integration Points with RC-7, RC-8, RC-9

| Layer | Integration |
|-------|------------|
| RC-7 `ExecutionEnginePort` | `ZerodhaExecutionAdapter` implements this port — all risk evaluation uses existing `RiskIntegrationLayer` |
| RC-8 `FillEventBus` | `OrderSyncService` publishes `FillEvent` on detected fills |
| RC-8 `RiskIntegrationLayer` | ALL Zerodha orders submit through this layer — no bypass ever |
| RC-9 `StrategyCoordinator` | `PositionReconciler` calls `coordinator.pause()` on mismatch |
| RC-9 `SessionContext` | `OrderSyncService` and `ZerodhaSessionRepository` use `SessionContext` for all DB writes |

## 16. Dependency Order

```
zerodha_sessions repository    (DB layer — no broker deps)
    ↓
zerodha_kite.py               (depends on BrokerInterface, sessions repo)
    ↓
zerodha_adapter.py            (depends on zerodha_kite, ExecutionEnginePort)
    ↓
order_sync.py                 (depends on zerodha_kite, FillEventBus, OrderRepository)
    ↓
position_reconciler.py        (depends on zerodha_kite, PositionRepository, Coordinator)
    ↓
account.py (router)           (depends on zerodha_kite)
```

## 17. Unit Testing Requirements

**Minimum 45 tests. All Kite API calls mocked — zero live HTTP calls.**

| File | Key Tests |
|------|-----------|
| `test_zerodha_kite.py` | `place_order` returns OrderResponse; rate limiter fires on 4th concurrent call; HTTP 403 raises token-expiry error; retry on 503; `get_orders` maps to internal format |
| `test_zerodha_adapter.py` | `get_portfolio_snapshot` returns dict with equity/cash; `submit_order` calls kite and returns result dict; `get_market_price` returns None when quote unavailable |
| `test_order_sync.py` | `sync_once` detects COMPLETE fill and publishes FillEvent; `sync_once` ignores orders already COMPLETE in DB; `sync_once` handles empty Kite response |
| `test_position_reconciler.py` | `reconcile` returns is_clean=True when positions match; detects mismatch and pauses strategies; `reconcile` handles Kite API unavailability (returns degraded result, not raises) |

## 18. Integration Testing Requirements

**Minimum 5 integration tests.**

| Test | Description |
|------|------------|
| `test_account_api.py` | `GET /account/margins` returns paper margins when Kite not connected |
| `test_kite_oauth_flow.py` | `POST /account/kite/callback` saves token to DB, returns 200 |
| `test_order_sync_integration.py` | Mocked Kite returns COMPLETE order → FillEvent published |
| `test_reconciler_clean.py` | Matching positions → `is_clean=True` |
| `test_reconciler_mismatch.py` | Position mismatch → strategies paused, incident recorded |

## 19. Performance Requirements

- `ZerodhaKiteClient.place_order()`: < 2s P95 (Kite API SLA dependent)
- `OrderSyncService.sync_once()`: < 5s total for 100 orders
- Rate limiter: ≤ 3 req/s enforced under all conditions
- `PositionReconciler.reconcile()`: < 10s for 50 positions

## 20. Security Considerations

- `ZERODHA_API_KEY` and `ZERODHA_API_SECRET` must come from Replit Secrets (already configured) — never hardcoded
- Access tokens stored in `zerodha_sessions` table — restrict DB user permissions to this table
- `POST /account/kite/callback` must validate the request token came from Zerodha's OAuth flow — validate `state` parameter
- LIVE mode double-confirmation prevents accidental live trading (`ENABLE_LIVE_TRADING` + `LIVE_TRADING_CONFIRMED` both required)
- Access token must have expiry enforced both at DB level (TTL column) and at application level

## 21. Failure and Recovery Behaviour

| Failure | Behaviour |
|---------|-----------|
| Kite HTTP 403 (token expired) | Log CRITICAL; raise `KiteTokenExpiredError`; `OrderSyncService` stops and alerts; operator must trigger `/account/kite/callback` flow |
| Kite HTTP 429 (rate limit) | Wait for rate limiter window; retry after 1s; max 3 retries |
| `OrderSyncService` poll failure | Log WARNING; skip cycle; continue next interval |
| `PositionReconciler` Kite unreachable | Return `ReconciliationResult(is_clean=False, mismatches=[])` with reason "Kite unreachable" |
| Position mismatch detected | CRITICAL log; all strategies paused; incident recorded; operator notified; automatic restart blocked until operator clears |
| Session token not in DB on startup | Start in PAPER mode; log INFO advising operator to complete OAuth flow |

## 22. Acceptance Criteria

- [ ] All pre-10D tests still pass
- [ ] 45+ new unit tests pass with zero live Kite API calls
- [ ] `ZerodhaKiteClient.place_order()` routes through `RiskIntegrationLayer` in all paths
- [ ] Rate limiter enforces ≤ 3 req/s (verified by concurrency test)
- [ ] `OrderSyncService` detects mock-COMPLETE fill and publishes `FillEvent`
- [ ] `PositionReconciler` pauses strategies on mismatch (verified by integration test)
- [ ] `GET /account/margins` returns 200 in PAPER mode
- [ ] `POST /account/kite/callback` saves token to `zerodha_sessions` table
- [ ] Alembic migration 0006 applies and rolls back cleanly
- [ ] LIVE mode blocked without both env vars set

## 23. Deliverables

- 4 new broker source files
- 1 new account API router
- 1 new DB repository
- 1 Alembic migration
- 4 unit test files + 1 integration test file
- Modifications to `src/core/config.py`, `src/main.py`, `src/brokers/paper_broker.py`
- `reviews/Batch10D_closure.md`

## 24. Out-of-Scope Items

- Options or futures order types
- Zerodha GTT (Good Till Triggered) orders
- WebSocket tick streaming from Kite
- Multi-account support

## 25. Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|-----------|
| Kite API breaking changes | Low | High | Pin `kiteconnect` library version; integration tests mock the HTTP layer |
| Token expiry during trading hours | Medium | Critical | `OrderSyncService` proactively refreshes token 30min before expiry |
| Accidental LIVE mode activation | Low | Critical | Double env var confirmation; validator logs at CRITICAL when LIVE mode activated |
| Position mismatch on startup due to overnight holds | High | Medium | `reconcile_on_startup=True` in config; `EXTERNAL_POSITION` flag for manual trades |

## 26. Rollback Strategy

- `ZerodhaExecutionAdapter` is injected into `RiskIntegrationLayer` only when Kite is connected; paper adapter used otherwise
- `enforce_paper_mode` can be restored by removing both LIVE env vars
- Migration 0006 `downgrade()` drops `zerodha_sessions` table
- Git tag `RC-10D-complete`

---

# BATCH 10E — OPERATIONS

## 1. Objective

Provide a complete operational capability layer: REST API for strategy lifecycle management, analytics for P&L and performance tracking, an alert dispatcher for real-time operator notification, automated session reporting, and a long-duration soak test suite to validate production stability.

## 2. Scope

**In scope:**
- `GET/POST /strategies/*` strategy management API endpoints
- `GET /health` extension with strategy and intelligence status
- `PerformanceAnalytics`: per-strategy and per-session P&L, win rate, drawdown
- `ReportGenerator`: end-of-session summary reports
- `AlertDispatcher`: subscribes to FillEventBus, health monitor, kill switch events
- WebSocket endpoint `/alerts/subscribe` for real-time operator feed
- `session_reports` table (migration 0007)
- `tests/soak/test_24h_paper_simulation.py`

**Out of scope:**
- Mobile push notifications (separate system)
- External analytics dashboards (Grafana, etc.)
- Automated trading decisions based on alerts

## 3. Functional Requirements

| ID | Requirement |
|----|------------|
| 10E-F01 | `POST /strategies` must register a strategy and return 201 with `StrategyRegistrationResult` |
| 10E-F02 | `GET /strategies` must return all strategies with current `HealthReport` and `StrategyMetrics` |
| 10E-F03 | `POST /strategies/{id}/start`, `/pause`, `/resume`, `/stop` must map to coordinator lifecycle methods |
| 10E-F04 | `GET /strategies/{id}/signals` must return the last 50 signals from `strategy_signals` table |
| 10E-F05 | `PerformanceAnalytics.compute_strategy_performance()` must use FIFO lot matching for P&L |
| 10E-F06 | `ReportGenerator` must generate a session report automatically when a trading session closes |
| 10E-F07 | `AlertDispatcher` must fire a CRITICAL alert within 1 second of kill switch activation |
| 10E-F08 | `GET /health` must include `strategy_count`, `healthy_strategies`, and `degraded_strategies` |
| 10E-F09 | WebSocket `/alerts/subscribe` must push alerts in real time with < 500ms delay |
| 10E-F10 | Soak test must run for `SOAK_DURATION_HOURS` (default 1, configurable) without OOM, deadlock, or P&L inconsistency |
| 10E-F11 | All strategy API endpoints must require Bearer JWT auth |
| 10E-F12 | `GET /analytics/performance` must aggregate across all strategies in the current session |

## 4. Non-Functional Requirements

| ID | Requirement |
|----|------------|
| 10E-NF01 | `GET /strategies` must respond in < 200ms for up to 50 strategies |
| 10E-NF02 | `PerformanceAnalytics.compute_strategy_performance()`: < 500ms for 1000 fills |
| 10E-NF03 | `ReportGenerator.generate_session_report()`: async, non-blocking |
| 10E-NF04 | `AlertDispatcher` must support up to 10 simultaneous WebSocket subscribers |
| 10E-NF05 | Soak test memory growth: < 50MB over 1 hour of continuous bar processing |
| 10E-NF06 | DB connection pool must not be exhausted during soak test |

## 5. Detailed Module Breakdown

### 5.1 `src/api/routers/strategies.py`
**REST API for strategy management.**  
Maps HTTP verbs to `StrategyCoordinator` methods. Requires injected coordinator from FastAPI dependency system.

### 5.2 `src/analytics/performance.py`
**`PerformanceAnalytics`**  
- `compute_strategy_performance(session, strategy_id) -> StrategyPerformanceSnapshot`
- `compute_session_performance(session, session_id) -> SessionPerformanceReport`
- FIFO lot matching: for each SELL fill, match against earliest unsold BUY lots to compute realised P&L
- Drawdown: track equity curve from fills; compute max drawdown from peak

### 5.3 `src/analytics/reports.py`
**`ReportGenerator`**  
- `generate_session_report(session, trading_session_id) -> SessionReport`
- Triggered by session close event (hook in `sessions.py` router or coordinator shutdown)
- Persisted to `session_reports` table

### 5.4 `src/alerts/dispatcher.py`
**`AlertDispatcher`**  
- `subscribe_fill_bus(fill_bus)` — fires INFO alert on each fill
- `subscribe_health_changes(monitor, strategy_ids)` — polls health; fires CRITICAL on UNHEALTHY
- `subscribe_kill_switch()` — fires CRITICAL on kill switch activation
- `async dispatch(alert: AlertRecord)` — fans out to: structured log, WebSocket subscribers, `incidents` table
- `register_websocket(websocket: WebSocket)` / `unregister_websocket(ws)`

### 5.5 `src/alerts/websocket.py`
**WebSocket endpoint handler.**  
Registers new WebSocket connections with `AlertDispatcher`. Sends alerts as JSON. Handles disconnection gracefully.

### 5.6 Soak Test Framework (`tests/soak/`)
**`test_24h_paper_simulation.py`**  
- Synthetic bar generator: produces realistic OHLCV sequences for N instruments over M hours
- Runs full strategy engine stack with SMA crossover strategy
- Assertions: memory growth < 50MB, P&L non-negative (paper mode, no fees), no asyncio task accumulation, DB pool healthy, no deadlocks

## 6. Folder Structure

```
src/
├── api/routers/
│   └── strategies.py
├── analytics/
│   ├── __init__.py
│   ├── performance.py
│   └── reports.py
└── alerts/
    ├── __init__.py
    ├── dispatcher.py
    └── websocket.py

migrations/versions/
└── 0007_rc10e_session_reports.py

tests/
├── unit/
│   ├── analytics/
│   │   ├── test_performance.py
│   │   └── test_reports.py
│   └── alerts/
│       └── test_dispatcher.py
├── integration/
│   ├── test_strategy_api.py
│   └── test_alerts_websocket.py
└── soak/
    ├── __init__.py
    └── test_24h_paper_simulation.py
```

## 7. Files to Create

| File | Purpose |
|------|---------|
| `src/api/routers/strategies.py` | Strategy management REST API |
| `src/analytics/__init__.py` | Package exports |
| `src/analytics/performance.py` | `PerformanceAnalytics`, `SessionPerformanceReport` (frozen Pydantic) |
| `src/analytics/reports.py` | `ReportGenerator`, `SessionReport` (frozen Pydantic) |
| `src/alerts/__init__.py` | Package exports |
| `src/alerts/dispatcher.py` | `AlertDispatcher`, `AlertRecord` (frozen Pydantic) |
| `src/alerts/websocket.py` | WebSocket endpoint handler |
| `migrations/versions/0007_rc10e_session_reports.py` | `session_reports` table |
| `tests/unit/analytics/test_performance.py` | P&L and drawdown tests |
| `tests/unit/analytics/test_reports.py` | Report generation tests |
| `tests/unit/alerts/test_dispatcher.py` | Alert dispatch tests |
| `tests/integration/test_strategy_api.py` | Strategy API integration tests |
| `tests/integration/test_alerts_websocket.py` | WebSocket alert tests |
| `tests/soak/test_24h_paper_simulation.py` | Long-duration soak test |

## 8. Existing Files That May Be Modified

| File | Change |
|------|--------|
| `src/main.py` | Include strategies router; include account router; start `AlertDispatcher`; trigger `ReportGenerator` on session close |
| `src/api/routers/health.py` | Extend response to include strategy health summary |
| `src/api/routers/sessions.py` | Hook session close event to trigger `ReportGenerator` |
| `src/database/models.py` | Add `SessionReport` ORM model |
| `src/api/dependencies.py` | Add `get_coordinator()` FastAPI dependency |

## 9. Public Interfaces

```
# Strategy API — all require auth headers
POST   /strategies                  body: {config: StrategyConfig, strategy_type: str}
GET    /strategies                  → List[StrategyStatusResponse]
GET    /strategies/{id}             → StrategyStatusResponse
POST   /strategies/{id}/start       → {success: bool, message: str}
POST   /strategies/{id}/pause       → {success: bool, message: str}
POST   /strategies/{id}/resume      → {success: bool, message: str}
POST   /strategies/{id}/stop        → {success: bool, message: str}
GET    /strategies/{id}/signals     → List[StrategySignalRecord]
GET    /strategies/{id}/health      → HealthReport
GET    /strategies/{id}/metrics     → StrategyMetrics

# Analytics
GET    /analytics/performance       → SessionPerformanceReport
GET    /analytics/strategies/{id}/performance → StrategyPerformanceSnapshot

# Reports
GET    /reports/{session_id}        → SessionReport

# Alerts
WS     /alerts/subscribe            → stream of AlertRecord (JSON)

# Health (modified)
GET    /health                      → {status, version, strategies: {count, healthy, degraded, unhealthy}}

StrategyStatusResponse (frozen Pydantic):
  strategy_id: str
  lifecycle_state: StrategyLifecycleState
  health: HealthReport
  metrics: StrategyMetrics
  config: StrategyConfig

AlertRecord (frozen Pydantic):
  alert_id: str
  severity: str      # INFO | WARNING | CRITICAL
  category: str      # FILL | HEALTH | KILL_SWITCH | RECONCILIATION | FORECAST | SYSTEM
  message: str
  strategy_id: Optional[str]
  instrument_token: Optional[str]
  triggered_at: datetime
  metadata: Dict[str, Any]
```

## 10. Data Flow

### Alert Dispatch

```
FillEventBus.publish_nowait(FillEvent)
  → AlertDispatcher._on_fill(fill_event)
      → AlertRecord(severity=INFO, category=FILL, ...)
      → dispatch(alert)
          ├──→ logger.info(structured)
          ├──→ for ws in websocket_subscribers: ws.send_json(alert)
          └──→ IncidentRepository.save(session, alert)  [if severity ≥ WARNING]

KillSwitchActive event
  → AlertDispatcher._on_kill_switch()
      → AlertRecord(severity=CRITICAL, category=KILL_SWITCH, ...)
      → dispatch(alert)  [same fan-out]

StrategyHealthMonitor polling (every 30s)
  → AlertDispatcher._check_health()
      → for strategy_id in active_strategies:
          health = monitor.compute_health(strategy_id)
          if health.status == UNHEALTHY and not already_alerted:
              → dispatch(AlertRecord(severity=CRITICAL, category=HEALTH, ...))
```

### Session Report Generation

```
POST /sessions/{id}/close  (or coordinator.shutdown())
  → ReportGenerator.generate_session_report(session, trading_session_id)
      → PerformanceAnalytics.compute_session_performance(session, session_id)
      → SessionReport assembled
      → SessionReportRepository.save(session, report)
  → GET /reports/{session_id} now returns the report
```

## 11. Sequence Diagrams

### Strategy Registration via API

```
Client          StrategiesRouter      StrategyCoordinator     DB
  │                    │                      │                │
  │ POST /strategies   │                      │                │
  │───────────────────→│                      │                │
  │                    │ validate auth         │                │
  │                    │ parse StrategyConfig  │                │
  │                    │ build strategy instance               │
  │                    │ coordinator.register(config, inst)   │
  │                    │─────────────────────→│                │
  │                    │                      │ persist REGISTERED
  │                    │                      │──────────────→ │
  │                    │                      │ ack            │
  │                    │                      │←──────────────  │
  │                    │ StrategyRegistrationResult           │
  │                    │←──────────────────────│                │
  │ 201 {strategy_id}  │                      │                │
  │←───────────────────│                      │                │
```

## 12. Database Changes

### Migration 0007: `rc10e_session_reports`

**New table: `session_reports`**

| Column | Type | Constraints |
|--------|------|------------|
| `id` | `SERIAL PRIMARY KEY` | |
| `trading_session_id` | `VARCHAR(50)` | NOT NULL, REFERENCES trading_sessions(session_id) |
| `total_trades` | `INTEGER` | NOT NULL DEFAULT 0 |
| `winning_trades` | `INTEGER` | NOT NULL DEFAULT 0 |
| `losing_trades` | `INTEGER` | NOT NULL DEFAULT 0 |
| `win_rate` | `NUMERIC(6,4)` | NOT NULL DEFAULT 0 |
| `realized_pnl` | `NUMERIC(15,2)` | NOT NULL DEFAULT 0 |
| `max_drawdown` | `NUMERIC(15,2)` | NOT NULL DEFAULT 0 |
| `max_drawdown_pct` | `NUMERIC(6,4)` | NOT NULL DEFAULT 0 |
| `strategy_breakdown` | `JSONB` | DEFAULT `{}` |
| `generated_at` | `TIMESTAMPTZ` | NOT NULL server_default=now() |
| `report_version` | `VARCHAR(10)` | NOT NULL DEFAULT '1.0' |

**Indexes:** `(trading_session_id)` UNIQUE, `(generated_at)`

## 13. API Changes

See Public Interfaces section. Summary:
- 11 new strategy management endpoints
- 2 new analytics endpoints
- 1 new report endpoint
- 1 WebSocket endpoint
- Modified `GET /health` response body

## 14. Configuration Changes

```
class OperationsSettings(BaseSettings):
    max_websocket_subscribers: int = 10
    health_alert_poll_interval_seconds: int = 30
    signal_history_limit: int = 50
    report_generation_async: bool = True
    soak_test_default_duration_hours: int = 1

Settings:
    operations: OperationsSettings = Field(default_factory=OperationsSettings)
```

## 15. Integration Points with RC-7, RC-8, RC-9

| Layer | Integration |
|-------|------------|
| RC-8 `FillEventBus` | `AlertDispatcher.subscribe_fill_bus()` |
| RC-8 `RiskEngine` | `AlertDispatcher` monitors kill switch state |
| RC-9 `StrategyCoordinator` | All strategy API endpoints delegate to coordinator |
| RC-9 `MetricsCollector` | `GET /strategies/{id}/metrics` reads from coordinator.get_metrics() |
| RC-9 `StrategyHealthMonitor` | `GET /strategies/{id}/health` reads from coordinator.get_health() |
| RC-9 `StrategyPersistenceAdapter` | `GET /strategies/{id}/signals` queries `strategy_signals` table |
| 10B `ForecastBenchmark` | `GET /strategies/{id}/metrics` includes forecast accuracy |
| 10C `PortfolioAllocator` | `GET /strategies/{id}` includes reserved capital |

## 16. Dependency Order

```
analytics/performance.py      (depends on DB repositories, execution.fills)
    ↓
analytics/reports.py          (depends on performance)
    ↓
alerts/dispatcher.py          (depends on FillEventBus, StrategyHealthMonitor, incidents repo)
    ↓
alerts/websocket.py           (depends on dispatcher, FastAPI WebSocket)
    ↓
api/routers/strategies.py     (depends on StrategyCoordinator, persistence, health, metrics)
    ↓
main.py (modifications)       (wires all above; hooks session close for report generation)
```

## 17. Unit Testing Requirements

**Minimum 40 tests.**

| File | Key Tests |
|------|-----------|
| `test_performance.py` | FIFO P&L: BUY 100 @ 500, SELL 100 @ 520 → P&L=2000; drawdown from peak correct; win_rate = winning/total; handles zero trades |
| `test_reports.py` | Report generated with correct fields; `strategy_breakdown` contains all active strategies; `report_version` = "1.0" |
| `test_dispatcher.py` | CRITICAL alert fired within mock call on kill switch; INFO alert on fill; WebSocket subscriber receives alert; max_subscribers limit enforced; health polling fires CRITICAL on UNHEALTHY |

## 18. Integration Testing Requirements

**Minimum 7 integration tests.**

| Test | Description |
|------|------------|
| `test_strategy_api.py` | Register → start → GET status (ACTIVE) → pause → resume → stop → GET status (STOPPED) |
| `test_strategy_api_auth.py` | Unauthenticated request returns 401 |
| `test_strategy_signals_api.py` | `GET /strategies/{id}/signals` returns up to 50 records |
| `test_analytics_performance.py` | P&L computed correctly from test DB fills |
| `test_report_generated_on_session_close.py` | Session close event triggers report; `GET /reports/{id}` returns it |
| `test_alerts_websocket.py` | WebSocket receives CRITICAL alert when kill switch activated |
| `test_health_endpoint_extended.py` | `GET /health` includes strategy counts |

## 19. Performance Requirements

- `GET /strategies`: < 200ms for 50 strategies
- `PerformanceAnalytics.compute_strategy_performance()`: < 500ms for 1000 fills
- `AlertDispatcher.dispatch()`: < 100ms to all subscribers
- Soak test: < 50MB memory growth over 1 hour, < 10 asyncio task accumulation

## 20. Security Considerations

- All strategy API endpoints require authenticated JWT — no public access
- WebSocket `/alerts/subscribe` requires JWT Bearer token in initial handshake headers
- `AlertRecord` must not include raw SQL, stack traces, or internal exception details — sanitise `message` field
- Report data includes P&L — restrict to authenticated operators only

## 21. Failure and Recovery Behaviour

| Failure | Behaviour |
|---------|-----------|
| WebSocket subscriber disconnects mid-stream | `AlertDispatcher` catches `WebSocketDisconnect`; removes subscriber; continues without interruption |
| `ReportGenerator` DB write fails | Log WARNING; mark session report as `FAILED` status; operator can retry via `POST /reports/generate/{session_id}` |
| `PerformanceAnalytics` encounters zero fills | Returns `StrategyPerformanceSnapshot` with all zeros — not raises |
| `AlertDispatcher` health poll errors | Log WARNING; skip cycle; continue polling |
| Strategy API `start` called when coordinator is shutting down | Returns 409 Conflict with reason |

## 22. Acceptance Criteria

- [ ] All pre-10E tests still pass
- [ ] 40+ new unit tests pass
- [ ] 7+ integration tests pass
- [ ] Full strategy lifecycle via REST: register → start → pause → resume → stop
- [ ] `GET /strategies` returns `HealthReport` and `StrategyMetrics` for each strategy
- [ ] `GET /health` includes `strategy_count`, `healthy_strategies`, `degraded_strategies`
- [ ] CRITICAL alert dispatched within 1s of kill switch activation (integration test)
- [ ] Session report generated and fetchable after session close
- [ ] WebSocket subscriber receives alerts (integration test)
- [ ] Soak test passes for `SOAK_DURATION_HOURS` without OOM or deadlock
- [ ] Alembic migration 0007 applies and rolls back cleanly

## 23. Deliverables

- 7 new source files across analytics, alerts, and API routers
- 1 Alembic migration
- 7 unit test files + 2 integration test files + 1 soak test file
- Modifications to `src/main.py`, `src/api/routers/health.py`, `src/api/routers/sessions.py`, `src/database/models.py`, `src/api/dependencies.py`
- `reviews/Batch10E_closure.md`
- `reviews/RC10_freeze_certificate.md`

## 24. Out-of-Scope Items

- Mobile push notifications
- Grafana / external monitoring integrations
- Automated remediation on alerts
- Historical analytics replay

## 25. Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|-----------|
| Strategy coordinator not thread-safe for concurrent API calls | Low | High | All coordinator methods already use per-strategy asyncio.Lock; API is async |
| FIFO P&L mismatch for partial fills | Medium | Medium | Unit tests with known partial fill sequences |
| WebSocket backlog if consumer is slow | Medium | Low | Use `asyncio.Queue` with size limit; drop oldest alerts on overflow |
| Soak test false positives from GC spikes | Medium | Low | Measure memory after GC; use `gc.collect()` before measurement |

## 26. Rollback Strategy

- All new routers are registered in `main.py` — comment out to disable
- `AlertDispatcher` is injected — removing from startup restores pre-10E
- Migration 0007 `downgrade()` drops `session_reports` table
- Git tag `RC-10E-complete` / `RC-10-complete`

---

# CROSS-CUTTING CONCERNS

## Immutable Invariants Across All Batches

Every RC-10 batch must satisfy these invariants. Violation is a blocking defect.

| Invariant | Enforcement |
|-----------|------------|
| All orders pass through `RiskIntegrationLayer.submit_order()` | `RiskIntegrationLayer` is the only call site for broker order placement. 10D's `ZerodhaExecutionAdapter` routes through it. |
| `SessionContext` is the sole commit site | All new code using DB sessions must use `async with SessionContext(engine) as session`. No direct `session.commit()` calls. |
| Frozen RC-9 contracts must not change | `Signal`, `StrategyConfig`, `StrategyContext`, `CompletedBar`, `Tick`, `ExecutionOrder`, `FillEvent` — immutable. Enrichment via `metadata` dict or `market_snapshots` dict only. |
| No upward dependencies | `market_intelligence`, `ai_forecast`, `portfolio` must not import from `strategy`, `risk`, or `execution` module interiors. Use only frozen contracts. |
| Kronos is read-only | `ai_forecast.kronos_adapter` must not import from `risk.integration_layer`, `strategy.signal_router`, or `brokers`. |
| All monetary values use `Decimal` | `float` is forbidden for any P&L, price, quantity, or monetary calculation in RC-10 code. |
| Deterministic indicator computation | Same bar sequence → same indicator values. No randomness, no datetime.now() in indicator functions. |

---

# KIMI IMPLEMENTATION SPLITS

These are recommended sub-batch splits within each phase for independent parallelism or sequential hand-off.

## 10A Split

| Sub-batch | Files | Notes |
|-----------|-------|-------|
| 10A-α | `timeframe.py`, `indicator_engine.py`, `multi_timeframe_context.py` | Pure computation — no DB, no async. Can be developed and tested completely in isolation. |
| 10A-β | `regime.py`, `ranking.py`, `strategy_scoring.py` | Depends on 10A-α types. |
| 10A-γ | `announcements.py`, `poller.py`, DB repository, migration | Async + DB. Depends on 10A-α types only for `AnnouncementRecord`. |
| 10A-δ | `context_builder.py` modification | Depends on all of 10A-α/β/γ. Final integration step. |

## 10B Split

| Sub-batch | Files | Notes |
|-----------|-------|-------|
| 10B-α | `features.py`, `volatility.py` | Pure computation. Depends on 10A `MultiTimeframeContext`. |
| 10B-β | `kronos_adapter.py`, `confidence_gate.py` | HTTP client. Can be independently developed with mock inference server. |
| 10B-γ | `benchmark.py`, migration | DB layer. Independent of Kronos HTTP. |
| 10B-δ | `signal_router.py` modification | Final integration. Depends on 10B-β. |

## 10C Split

| Sub-batch | Files | Notes |
|-----------|-------|-------|
| 10C-α | `sizing.py`, `allocation.py` | Core sizing logic. No external deps beyond RC-9. |
| 10C-β | `sector.py`, `correlation.py` | Market data consumers. Depends on 10A for sector data. |
| 10C-γ | `capital.py` | Depends on 10A `StrategyScore`. |
| 10C-δ | `signal_router.py` + `risk/rules.py` modifications | Final integration. Depends on all 10C-α/β. |

## 10D Split

| Sub-batch | Files | Notes |
|-----------|-------|-------|
| 10D-α | `zerodha_kite.py`, `zerodha_sessions` repository, migration | Kite client + DB. Core broker layer. |
| 10D-β | `zerodha_adapter.py` | Thin adapter wrapper. Depends on 10D-α. |
| 10D-γ | `order_sync.py`, `position_reconciler.py` | Background services. Depends on 10D-α/β. |
| 10D-δ | `account.py` router, `main.py` modifications | API surface. Depends on 10D-α. |

## 10E Split

| Sub-batch | Files | Notes |
|-----------|-------|-------|
| 10E-α | `analytics/performance.py`, `analytics/reports.py`, migration | Analytics + reporting. No API deps. |
| 10E-β | `alerts/dispatcher.py`, `alerts/websocket.py` | Alert system. Depends on RC-8 FillEventBus and RC-9 health monitor. |
| 10E-γ | `api/routers/strategies.py`, `api/dependencies.py` modification | Strategy management API. Depends on RC-9 coordinator. |
| 10E-δ | `main.py` wiring, health extension, soak test | Final integration. Depends on all 10E-α/β/γ. |

---

# REPLIT VALIDATION CHECKLIST

Run these checks after completing each batch before tagging.

## After Each Batch

```bash
# 1. Run full unit test suite — must show 0 new failures
cd intraday-trading-bot
python -m pytest tests/unit/ -q --tb=short

# 2. Run integration tests
python -m pytest tests/integration/ -q --tb=short

# 3. Apply migration and verify schema
alembic upgrade head
alembic current  # must show head revision

# 4. Rollback migration
alembic downgrade -1
alembic upgrade head  # re-apply

# 5. Type check
cd ..
pnpm exec tsc -b lib/api-client-react lib/api-zod lib/db artifacts/api-server

# 6. Verify no circular imports
python -c "from src.market_intelligence import *"  # 10A
python -c "from src.ai_forecast import *"           # 10B
python -c "from src.portfolio import *"             # 10C
python -c "from src.brokers.zerodha_kite import ZerodhaKiteClient"  # 10D
python -c "from src.analytics import *; from src.alerts import *"   # 10E

# 7. Check pre-existing failure count unchanged
python -m pytest tests/unit/test_kill_switch.py -v
# Expected: 1 failure (test_history — pre-existing)
```

## Batch-Specific Checks

### 10A
```bash
# Verify IndicatorEngine determinism
python -m pytest tests/unit/market_intelligence/test_indicator_engine.py -k "determinism"

# Verify context_builder backward compat
python -m pytest tests/unit/strategy/test_context_builder.py
```

### 10B
```bash
# Verify fail-open
python -m pytest tests/unit/ai_forecast/test_confidence_gate.py -k "fail_open"

# Verify no live Kronos calls
grep -r "requests\." tests/unit/ai_forecast/  # should return nothing
grep -r "httpx\." tests/unit/ai_forecast/      # should return nothing (mocks only)
```

### 10C
```bash
# Verify quantity cap
python -m pytest tests/unit/portfolio/test_sizing.py -k "hard_cap"

# Verify sector rule blocks correctly
python -m pytest tests/unit/portfolio/test_sector.py
```

### 10D
```bash
# Verify rate limiter
python -m pytest tests/unit/brokers/test_zerodha_kite.py -k "rate_limit"

# Verify LIVE mode requires double confirmation
python -c "
import os
os.environ['ENABLE_LIVE_TRADING'] = 'true'
# Should still fail without LIVE_TRADING_CONFIRMED
from src.core.config import TradingSettings
try:
    TradingSettings(mode='LIVE')
    print('FAIL — should have raised')
except ValueError:
    print('PASS — correctly blocked')
"
```

### 10E
```bash
# Run soak test (short duration for CI)
SOAK_DURATION_HOURS=0.1 python -m pytest tests/soak/test_24h_paper_simulation.py -v -s

# Verify WebSocket endpoint registered
python -c "from src.main import app; routes = [r.path for r in app.routes]; assert '/alerts/subscribe' in routes"
```

## Final RC-10 Checklist

```bash
# Complete test suite
python -m pytest tests/ -q --ignore=tests/soak --tb=short
# Expected: 700+ passed, 1 failed (pre-existing kill-switch)

# Soak test
SOAK_DURATION_HOURS=1 python -m pytest tests/soak/ -v -s

# Schema verification
alembic history --verbose
# Expected: 7 migrations (0001 through 0007)

# Git tag
git tag -a RC-10-complete -m "RC-10 Complete: ..."
```

---

# MERGE STRATEGY

## After Each Batch

1. **Run validation checklist** — all checks must pass
2. **Write closure report** — `reviews/Batch10{X}_closure.md`
   - Tests: N new + N total passing
   - Files created/modified
   - Known issues/deferred items
   - Invariants verified
3. **Commit** with message: `feat(10{X}): <batch name> — N new tests, N total`
4. **Git tag** the completion point: `RC-10{X}-complete`
5. **Update `ARCHITECTURE_REFERENCE.md`** — add new modules to the module table
6. **Update `docs/RC10_Reference.md` §21 Current Limitations** — strike through resolved limitations

## Merge Gate Conditions

Before accepting any batch merge:

| Check | Pass Condition |
|-------|---------------|
| Unit test count | ≥ baseline + batch-minimum |
| Pre-existing failures | Exactly 1 (test_kill_switch::test_history) |
| New integration test failures | 0 |
| Alembic `upgrade head` | Clean |
| Alembic `downgrade -1` + `upgrade head` | Clean (round-trip) |
| Circular import check | No new circular imports |
| Invariant audit | All 7 cross-cutting invariants verified |
| Closure report | Present and complete |

## Rollback Protocol

If a merge introduces regressions:

1. Identify the regression (specific test file + test name)
2. Check if it is in a frozen RC-9 module (if so: the batch has a bug, must be fixed before re-merge)
3. If rollback is warranted: `git revert <merge-commit>` + `alembic downgrade -N`
4. Re-open the batch; fix the root cause
5. Re-run full validation checklist before re-merging

---

*End of RC-10 Master Implementation Plan. Version 1.0, 2026-07-23.*  
*Total: 5 batches, ~68 new files, ~17 modified files, 4 migrations, 235+ tests, 17 new API endpoints.*
