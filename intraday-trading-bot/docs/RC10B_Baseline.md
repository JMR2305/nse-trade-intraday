# RC-10B Baseline Declaration

**Date:** 2026-07-23  
**Baseline tag:** `RC-10A-FINAL`  
**Baseline commit:** see `git rev-parse RC-10A-FINAL`

---

## RC-10A is the Official Baseline for RC-10B

RC-10A has been independently audited, patched, and accepted. The `RC-10A-FINAL`
tag is the authoritative starting point for all RC-10B (and later) development.

---

## RC-10A Read-Only Policy

RC-10A source files are **frozen**. The following directories and files must not
be modified in RC-10B or later batches except to fix a **production-critical bug**
(data corruption, security vulnerability, or crash in the live trading path):

```
src/market_intelligence/multi_timeframe_context.py   ← domain models; frozen
src/market_intelligence/timeframe.py                 ← frozen
src/market_intelligence/indicator_engine.py          ← frozen
src/market_intelligence/regime.py                    ← frozen
src/market_intelligence/ranking.py                   ← frozen
src/market_intelligence/strategy_scoring.py          ← frozen
src/market_intelligence/announcements.py             ← frozen
src/market_intelligence/poller.py                    ← frozen
migrations/versions/0004_rc10a_announcements_sector.py  ← frozen
```

`src/strategy/context_builder.py` remains extensible but the following are frozen:
- `build_context()` signature and return type
- Constructor positional arguments
- Optional keyword-only injection arguments (names and types)

Any change to a frozen file requires:
1. A documented production-critical justification.
2. A new audit review entry in `reviews/`.
3. A new patch tag (e.g. `RC-10A-FINAL-P1`).

---

## What RC-10B Can Safely Build On

| Artifact | Status | Notes for 10B |
|----------|--------|---------------|
| `MultiTimeframeContext` model | ✅ Stable | Use `.timeframes`, `.regime`, `.active_announcements` |
| `MarketRegimeSnapshot` model | ✅ Stable | `.regime`, `.confidence`, `.detected_at` |
| `IndicatorEngine.get_all_timeframes(token)` | ✅ Stable | Returns `Dict[str, Dict[str, Decimal]]` |
| `MarketRegimeDetector.detect(token, indicators)` | ✅ Stable | Returns `MarketRegimeSnapshot` |
| `WatchlistRanker.score(token, indicators, regime)` | ✅ Stable | Note: takes `indicators: Dict`, not `MultiTimeframeContext` |
| `StrategyScorer.score(config, regime, score)` | ✅ Stable | |
| `ContextBuilder._inject_market_intelligence()` | ⚠ Private | Do not call from outside `ContextBuilder` |
| `ContextBuilder.build()` | ✅ Stable | `market_snapshots[token]` is `MultiTimeframeContext` |
| `ContextBuilder.build_context()` | ✅ Stable | Same; RC-9 contract frozen |
| `AnnouncementRepository.upsert()` | ✅ Stable | Wire from service in 10D/10E |
| `poll_and_classify()` | ⚠ Stub | HTTP implementation deferred to 10E |

---

## First Tasks for RC-10B (Mandatory Pre-Conditions)

Before any new 10B code consumes `market_snapshots`, the following must be confirmed:

1. **Verify typed access** — all 10B consumers must access `market_snapshots[token]`
   as a `MultiTimeframeContext` instance (attribute access), never as a dict.

2. **Normalise `WatchlistRanker.score()` signature** (O-4 from audit) — if 10B
   callers need to pass a `MultiTimeframeContext`, update the signature then.
   Do not silently pass dicts where the spec expects a typed object.

3. **Async normalisation** (O-5 from audit) — if 10B activates async announcement
   polling, rename `get_active_announcements_sync()` to `get_active_announcements()`
   and make it `async` at that point.

---

## Test Baseline

| Suite | Count | Status |
|-------|-------|--------|
| RC-10A unit tests | 89 | ✅ All pass |
| RC-10A integration tests | 15 | ✅ All pass |
| Pre-existing unit tests | 534 | ✅ All pass |
| Pre-existing failure | 1 | ⚠ `test_kill_switch::test_history` — tracked since RC-8B, unrelated |

RC-10B must not reduce these counts. All new 10B tests must be added, not substituted.

---

## Reference Documents

- `docs/RC10_Master_Implementation_Plan.md` — authoritative implementation plan
- `docs/RC10_Reference.md` — reference specification
- `reviews/Batch10A_Replit_Audit.md` — independent production audit
- `reviews/Batch10A_Final_Patch.md` — final patch report
- `reviews/Batch10A_closure.md` — closure report
