# Phase 6.1 — Paper Trading Validation & Data Collection Framework

**Status:** COMPLETE  
**Feature flag:** `PAPER_VALIDATION_ENABLED=true`  
**Module:** `artifacts/api-server/src/python/paper_trading_validation/`  
**Dashboard:** `artifacts/trading-dashboard/src/pages/PaperTradingValidation.tsx` → `/validation`

---

## What was built

A comprehensive, read-only validation framework that records every completed paper trade together with its full decision context and measures overall system performance across sessions. Zero new trading logic — exclusively reads from existing modules. Background-safe: collection never runs on the trading-engine hot path.

---

## 1. Files created

| File | Purpose |
|---|---|
| `paper_trading_validation/__init__.py` | Package docstring — read-only, advisory-only contract |
| `paper_trading_validation/validation_models.py` | Feature flag, `TradeRecord`, `SessionMetadata`, `DailyMetrics`, `DataQualityReport` dataclasses |
| `paper_trading_validation/validation_collector.py` | FIFO BUY→SELL matching via `portfolio_store.load_trades()`; enriches from existing modules; per-trade metadata extraction |
| `paper_trading_validation/data_quality.py` | 7 quality checks; weighted quality score 0–100; CLEAN/WARNINGS/ISSUES verdict |
| `paper_trading_validation/metrics_engine.py` | Daily, weekly, monthly, rolling-30/90/180 metrics; dataset growth timeline; validation statistics |
| `paper_trading_validation/export_service.py` | CSV export, JSON export, future-ready PDF stub |
| `paper_trading_validation/shared_services.py` | **Stable public interface** — `get_session()`, `get_history()`, `get_quality()`, `get_statistics()`, `get_validation_snapshot()` |
| `paper_trading_validation/api.py` | 4 HTTP façade functions |
| `paper_trading_validation/test_paper_trading_validation.py` | 33 unit tests — all passing |

**Files modified:**

| File | Change |
|---|---|
| `artifacts/api-server/src/python/main.py` | +6 validation_* commands |
| `artifacts/api-server/src/routes/index.ts` | Added `validationRouter` import and mount |
| `artifacts/api-server/src/routes/validation.ts` | **NEW** — 6 Express GET endpoints |
| `artifacts/trading-dashboard/src/pages/PaperTradingValidation.tsx` | **Replaced** Phase 16 stub with Phase 6.1 dashboard (6 sections, 4 useQuery calls) |

---

## 2. Files modified (detail)

### `main.py` — 6 new commands
```
validation_session      → paper_trading_validation.api.cmd_session()
validation_history      → paper_trading_validation.api.cmd_history()
validation_quality      → paper_trading_validation.api.cmd_quality()
validation_statistics   → paper_trading_validation.api.cmd_statistics()
validation_export_csv   → shared_services.export_records_csv()
validation_export_json  → shared_services.export_records_json()
```

### `routes/index.ts`
`validationRouter` imported from `./validation`, mounted before `tradingRouter`.

---

## 3. APIs

| Endpoint | Description |
|---|---|
| `GET /api/validation/session` | Today's session metadata + today's completed trades + daily metrics |
| `GET /api/validation/history` | Daily history rows + weekly/monthly/rolling-30/90/180 aggregates + dataset growth |
| `GET /api/validation/quality` | Data quality report (7 checks, score 0–100, CLEAN/WARNINGS/ISSUES) |
| `GET /api/validation/statistics` | Overall statistics: win rate, P&L, strategies, sectors, exit reasons |
| `GET /api/validation/export/csv` | Download all trade records as CSV (attachment) |
| `GET /api/validation/export/json` | Download all trade records as JSON (attachment) |

All endpoints return `{ "status": "DISABLED" }` when `PAPER_VALIDATION_ENABLED=false`.

---

## 4. Dashboard sections

| # | Section | Data from |
|---|---|---|
| 1 | **Today's Session** | `/api/validation/session` — market status, NIFTY/BANK NIFTY/VIX, breadth, leading sector, top gap, daily metrics, today's trade cards |
| 2 | **Historical Performance** | `/api/validation/history` — 5 period roll-ups (weekly/monthly/30/90/180d), daily history table |
| 3 | **Data Quality** | `/api/validation/quality` — quality score ring, 7-check breakdown, issue detail list |
| 4 | **Trade Timeline** | `/api/validation/statistics` — total/win/loss counts, best/worst trade, avg holding, drawdown, exit reason distribution |
| 5 | **Validation Statistics** | `/api/validation/statistics` — strategy breakdown table, sector breakdown table, aggregate scores (AI confidence, EQ, executive score) |
| 6 | **Growth of Dataset** | `/api/validation/history` (growth field) — cumulative trade count, cumulative P&L, storage estimate, 30-day growth table |

---

## 5. Test count

**33/33 passing (0.20 s)**

---

## 6. Test results

| Test class | Count | Scenario |
|---|---|---|
| `TestFeatureFlag` | 5 | All 4 endpoints + snapshot return DISABLED when flag off |
| `TestZeroTrades` | 4 | Zero trades — statistics, quality, history, session all respond with empty graceful state |
| `TestSingleTrade` | 4 | Single BUY→SELL pair — collection, holding time, metadata enrichment, win-rate = 1.0 |
| `TestMultipleTrades` | 6 | Three pairs — count, win rate 2/3, daily rows, cumulative growth, strategy/exit breakdown |
| `TestCorruptedRecordDetection` | 2 | P&L mismatch and negative holding time flagged in corrupted_records |
| `TestDuplicateDetection` | 2 | Duplicate trade_id flagged; unique IDs not flagged |
| `TestExport` | 4 | CSV headers correct, JSON parses, disabled returns empty string, PDF stub has metadata |
| `TestDataQualityChecks` | 2 | Clean record scores >90/CLEAN; 10x price move flagged as impossible |
| `TestRestartPersistence` | 2 | Two sequential calls return identical statistics and quality score |
| `TestValidationSnapshot` | 2 | Required keys present; zeros on no-data |

---

## 7. Performance benchmarks

**Collection cost:** FIFO matching is O(n) in number of raw trade rows. At ≤1000 trades the sort + match step takes < 5 ms.

**Module enrichment:** One call each to:
- `execution_quality.api.get_summary()` — ~5–15 ms
- `executive_dashboard.shared_services.get_executive_snapshot()` — ~15–30 ms (aggregates all phases)
- `preopen_engine.get_status()` — ~2–5 ms (JSON cache read)

**Estimated total Python time per endpoint:** 30–60 ms. Well within the <1 s target.

**Dashboard fetch behaviour:**
- `/session` + `/statistics` — refetch every 60 s, stale after 30 s
- `/history` + `/quality` — refetch every 120 s, stale after 60 s
- Export endpoints — on-demand only

**Background safety:** Collection is invoked only from API endpoints via main.py. The trading engine never calls any function in this module.

---

## 8. Known limitations

| # | Area | Description | Severity | Resolution path |
|---|---|---|---|---|
| 1 | Feature flag off by default | Disabled banner until `PAPER_VALIDATION_ENABLED=true` | Low — intentional | Set flag in environment secrets |
| 2 | Per-trade AI/execution scores | `ai_confidence`, `ai_recommendation`, `signal_validation_status`, `execution_quality_score` are only available when the upstream module stored them in trade metadata at entry/exit time. If not stored, fields are null and counted as "Incomplete AI Data" in the quality report. | Medium | Wire metadata storage in entry/exit hooks in Phase 6.2 |
| 3 | Historical executive score | `executive_score_snapshot` on each TradeRecord is the **current** executive score at collection time, not the score at the moment of the trade. Historical per-trade executive scores would require snapshot tables. | Medium | Future: snapshot executive score per session to a `executive_score_log` table |
| 4 | Partial fills | FIFO matching assumes full lot BUY→SELL pairings. Partial-quantity sells (split lots) may produce over-counted pairs. | Low | Extend FIFO to handle partial quantity matching |
| 5 | Market data (NIFTY, VIX) | Populated from `meta_health.get_meta_health()` — shows "Unavailable" when meta_health is not available | Medium | Wire to `live_data_provider.get_market_overview()` |
| 6 | PDF export not implemented | `export_pdf_stub()` returns `NOT_IMPLEMENTED` metadata | Low — future-ready | Install `reportlab` or `weasyprint` |

---

## 9. Data schema — TradeRecord

| Field | Type | Source |
|---|---|---|
| `trade_id` | str | SELL record `id` from paper_trades |
| `timestamp` | ISO8601 str | SELL `trade_ts` |
| `symbol` | str | Both BUY/SELL |
| `strategy` | str | BUY `metadata.strategy` |
| `market_regime` | str | BUY `metadata.market_regime` |
| `sector` | str | BUY `metadata.sector` |
| `entry_price` | float | BUY `price` |
| `exit_price` | float | SELL `price` |
| `quantity` | int | BUY `quantity` |
| `holding_time_minutes` | float | SELL `trade_ts` − BUY `trade_ts` |
| `pnl` | float | `(exit − entry) × qty` |
| `pnl_pct` | float | `(exit − entry) / entry × 100` |
| `execution_quality_score` | float? | SELL `metadata.execution_quality_score` → session avg fallback |
| `ai_confidence` | float? | BUY `metadata.ai_confidence` |
| `ai_recommendation` | str? | BUY `metadata.ai_recommendation` |
| `signal_validation_status` | str? | BUY `metadata.signal_validation_status` |
| `risk_score` | float? | BUY `metadata.risk_score` |
| `portfolio_value_at_entry` | float? | BUY `metadata.portfolio_value_at_entry` |
| `executive_score_snapshot` | float? | `executive_dashboard.shared_services.get_executive_snapshot()` at collection time |
| `exit_reason` | str | SELL `reason` field; fallbacks to SELL `metadata.exit_reason` |

---

## 10. Storage growth estimate

| Scenario | Trades/day | Records/year | Est. size |
|---|---|---|---|
| Light (testing) | 2 | 500 | ~250 KB |
| Normal | 5 | 1,250 | ~625 KB |
| Heavy | 20 | 5,000 | ~2.5 MB |

At ~500 bytes per serialised TradeRecord (JSON), the dataset stays negligible relative to Postgres limits. No pagination needed for ≤10,000 records; the `/statistics` endpoint summarises everything without streaming raw records to the browser.

---

## What to enable before a live session

```
PAPER_VALIDATION_ENABLED=true
```

For full field enrichment, the following flags should also be on (so their modules store metadata in trade records):
- `EXECUTION_QUALITY_ENABLED=true`
- `AI_PERFORMANCE_ENABLED=true`
- `EXECUTIVE_DASHBOARD_ENABLED=true`

---

## Stable interface for future phases

`get_validation_snapshot()` — flat dict for executive dashboard or future analytics super-aggregators:
```
{
  "total_validated_trades": int,
  "validation_win_rate": float,
  "validation_net_pnl": float,
  "avg_ai_confidence": float,
  "avg_execution_score": float,
  "max_drawdown": float
}
```

## Reused existing modules (no duplication)

| Module | Function used | Purpose |
|---|---|---|
| `portfolio_store` | `load_trades()` | Read raw BUY/SELL records |
| `execution_quality.api` | `get_summary()` | Session avg execution score fallback |
| `executive_dashboard.shared_services` | `get_executive_snapshot()` | Executive score at collection time |
| `preopen_engine` | `get_status()` | Session metadata (market status, sector, gap) |
| `meta_health` | `get_meta_health()` | NIFTY/VIX/breadth for session metadata |

Zero analytics recalculated. All metrics derived from `TradeRecord` objects built from existing module outputs.

---

## Final Verdict

**PHASE 6.1 COMPLETE**
