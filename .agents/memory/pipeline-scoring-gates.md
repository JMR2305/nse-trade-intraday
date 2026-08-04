---
name: Pipeline scoring and gate calibration
description: Three blockers that prevented any paper BUY orders from being created, and how each was fixed.
---

## Root causes and fixes

### Blocker 1 — market_scanner.py reliability denominators
- `_strategy_perf_score` used `min(1.0, trades / 8.0)` → NIFTY trend strategies fire only 2–4× in 6 months, so reliability was permanently 0.375 → scores capped ~54, below BUY threshold of 62
- `_confidence_score` used `min(1.0, trades / 10.0)` → same issue
- **Fix**: Changed denominators to 4 and 5 respectively. Full reliability at 4+ trades (perf) / 5+ trades (conf). Now 3 trades → score ~67 (BUY)

### Blocker 2 — phase20_gates.py provider_zerodha global gate
- Gate checked `kite_connected=True` — always False when using Yahoo Finance
- Provider label "Yahoo Finance (History) — Zerodha login required" contains "login required" → also failed `no_fallback_data` gate
- `global_pass=False` → candidate pool = [] → zero candidates ever evaluated
- **Fix**: Gate now passes when `kite_connected OR live_symbol_count > 0` (LIVE quotes from any provider). `no_fallback_data` changed to only block truly degraded providers (mock/fallback/not-configured), not Yahoo Finance with informational login prompt.

### Blocker 3 — stored settings thresholds too high
- `min_confidence=75`, `min_opportunity_score=70`, `min_trade_quality_score=60` — all above achievable values
- Changed defaults in `phase20_store.py` AND updated stored DB values via `update_settings()`:
  - `min_confidence`: 75 → 60
  - `min_opportunity_score`: 70 → 60
  - `min_trade_quality_score`: 60 → 50

## Pipeline result after fixes
50 scanned → 28 passed intelligence → 4 BUY signals → global gates green → 4 candidates evaluated → per-candidate gates (R:R, duplicate, cap) → 2 paper orders executed

## New pipeline_stats.py module
`GET /api/phase20/pipeline` → full funnel diagnostics (7 stages, gate details, top candidates, candidate blocks, settings snapshot). Rendered in `SPipelineStats` component on AIPaperTraderPage.

**Why:** Low-frequency strategies (NIFTY trend, swing) are legitimate and should not be penalised by denominators calibrated for high-frequency intraday scalping. Yahoo Finance delivers LIVE data; the "Zerodha login required" label is informational only.
