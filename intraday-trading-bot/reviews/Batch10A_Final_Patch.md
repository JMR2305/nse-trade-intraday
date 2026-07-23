# RC-10A Final Patch Report

**Date:** 2026-07-23  
**Based on:** `reviews/Batch10A_Replit_Audit.md` — observations O-1 and O-2  
**Scope:** Corrections only. No new features. No RC-10B work.

---

## 1. Files Modified

| File | Change |
|------|--------|
| `src/strategy/context_builder.py` | Full rewrite of intelligence injection path (Fix 1 + Fix 2) |
| `tests/integration/test_context_builder_with_intelligence.py` | Updated assertions to use `MultiTimeframeContext` attribute access |

---

## 2. Fixes Applied

### Fix 1 — `MultiTimeframeContext` Injection (O-1, High Priority)

**Before:** `market_snapshots[token]` held a raw `dict` with keys `"timeframes"`, `"regime"`, `"active_announcements"`.

**After:** `market_snapshots[token]` holds a typed, frozen `MultiTimeframeContext` instance as defined in `market_intelligence/multi_timeframe_context.py`.

Both `build()` and `build_context()` now produce `MultiTimeframeContext` objects via the shared `_inject_market_intelligence()` helper. No change to the no-intelligence path — `market_snapshots` remains `{}` when no `indicator_engine` is injected.

---

### Fix 2 — Eliminate Duplicate Injection Logic (O-2, Medium)

**Before:** The intelligence injection block (indicator query → regime detection → announcement lookup) was duplicated verbatim inside both `build()` and `build_context()` — approximately 30 lines each.

**After:** All injection logic lives in one private method:

```python
def _inject_market_intelligence(
    self,
    instrument_token: str,
    snapshot_ts: datetime,
) -> Optional[MultiTimeframeContext]:
```

- Returns `None` if no data is available for the token (unknown instrument guard preserved).
- Each service failure is caught individually and logged at `DEBUG` — intelligence errors never propagate to strategy callers.
- Both `build()` and `build_context()` are now single `for`-loop callers of this helper.

---

### Test assertions updated

`test_context_builder_with_intelligence.py` assertions migrated from dict-subscript style to typed attribute access:

| Old assertion | New assertion |
|---------------|---------------|
| `"timeframes" in ctx.market_snapshots["INFY"]` | `isinstance(snap, MultiTimeframeContext)` + `snap.timeframes` |
| `"regime" in ctx.market_snapshots["INFY"]` | `snap.regime is not None` |
| `ctx.market_snapshots["INFY"]["regime"]` | `snap.regime` |
| `ctx.market_snapshots["TCS"]` (no type check) | + `isinstance(..., MultiTimeframeContext)` |

The no-intelligence tests in `test_context_builder_no_intelligence.py` are **unchanged** — they assert `market_snapshots == {}` which remains correct.

---

## 3. Test Results

```
tests/unit/market_intelligence/test_announcements.py            25 passed
tests/unit/market_intelligence/test_indicator_engine.py         25 passed
tests/unit/market_intelligence/test_regime.py                   11 passed
tests/unit/market_intelligence/test_ranking.py                   9 passed
tests/unit/market_intelligence/test_strategy_scoring.py          7 passed
tests/unit/market_intelligence/test_timeframe.py                11 passed

tests/integration/test_context_builder_with_intelligence.py      5 passed
tests/integration/test_context_builder_no_intelligence.py        4 passed
tests/integration/test_timeframe_pipeline.py                     2 passed
tests/integration/test_regime_from_bars.py                       2 passed
tests/integration/test_announcement_persistence.py               2 passed

RC-10A total: 104 passed, 0 failed
```

---

## 4. Regression Results

```
tests/unit/ (full suite)

534 passed
1 pre-existing failure: tests/unit/test_kill_switch.py::TestKillSwitch::test_history
  — tracked since RC-8B, unrelated to RC-10A
```

**RC-10A Final Patch introduced zero new failures.**

---

## 5. Remaining Deferred Items

The following observations from `Batch10A_Replit_Audit.md` are explicitly out of scope for this patch and deferred to later batches:

| Observation | Deferred to |
|-------------|-------------|
| O-3: Input sanitisation + JSONB size cap on announcement text | Before HTTP polling activation (10E) |
| O-4: `WatchlistRanker.score()` signature (`dict+regime` vs `MultiTimeframeContext`) | 10B — normalise alongside 10B callers |
| O-5: `get_active_announcements()` async vs sync naming | 10B — normalise when async polling activated |
| O-6: `AnnouncementRepository` not called by `AnnouncementIntelligenceService` | 10D/10E — requires operational session management |
| O-7: Count-based aggregation, not clock-aligned (10A-F01) | 10B or 10C — requires NSE calendar integration |
| O-8: MACD O(N²) — acceptable at max_bars=150 | Optimise when buffer sizes grow |
| O-9: Volume ratio and spread/liquidity factors hardcoded to 1.0 | 10C/10D — requires Quote data access |
| O-10: `datetime.utcnow()` deprecated throughout | Separate housekeeping batch |
| O-11: `market_intelligence/__init__.py` exports nothing | Low priority — consumers import submodules directly |

---

✅ RC-10A FINAL PATCH COMPLETE
