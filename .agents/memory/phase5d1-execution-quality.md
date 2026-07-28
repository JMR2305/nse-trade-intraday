---
name: Phase 5D.1 Execution Quality
description: Design decisions for the read-only execution quality analytics module.
---

# Phase 5D.1 — Execution Quality Intelligence

## Key design decisions

**Module location:** `artifacts/api-server/src/python/execution_quality/` (6 files: `__init__.py`, `models.py`, `metrics.py`, `slippage.py`, `fill_analysis.py`, `report.py`, `api.py`).

**Feature flag:** `EXECUTION_QUALITY_ENABLED` env var (shared). Default `false`. All 4 API endpoints return `{"status":"DISABLED"}` when off.

**Data source:** Reads only from `portfolio_store.load_all_trades_any()` for paper trades, and tries `signal_validation_db` for fill delay enrichment. Never writes.

**Slippage source:** Uses `est_slippage` field already computed on each paper trade. Entry slippage % = `est_slippage / total * 100`.

**Fill delay:** 0 by default for paper trades (instantaneous); enriched from `signal_validation_records.signal_ts` / `paper_fill_ts` when `paper_order_id` matches trade ID.

**Trade matching:** FIFO BUY→SELL within same symbol by timestamp. One ExecutionRecord per BUY trade; `is_complete=True` only when matched SELL found.

**Score formula:** Entry quality 30% + Exit quality 25% + Fill speed 20% + Stop execution 15% + Target execution 10% = 100 pts. Grades: 90+=Excellent, 75+=Good, 60+=Fair, <60=Poor.

**API routes:** `executionQuality.ts` mounted via `routes/index.ts`. Uses same `PYTHON_BIN`/`PYTHON_DIR` from `python-env.ts` pattern (no local runPython).

**Dashboard import:** `@/lib/api` (not `@/lib/queryClient`). `apiJson("execution-quality/...")` — no `/api/` prefix (API_BASE_URL already adds it).

**Why:** All analytics are derived-in-memory; no new DB tables needed. Safety: AST scan in test suite verifies no forbidden broker/order calls in any module file.
