# Phase 27C + 27D — Verification Report

Date: 2026-08-09 · READ-ONLY / ADVISORY-ONLY — no trading logic touched.

## Part C — AI Explainability
Delivered as a new **"Why (27C)" tab** on the Explainable AI page
(`/explainable-ai`), backed by `GET /api/explain/symbol/:symbol`
(`phase27_explainability.py`).

- Per-symbol: current stage, current status, decision
  (BUY / SELL / WATCH / HOLD / REJECTED / NOT_SCANNED), confidence, strategy.
  "STRONG BUY" normalises to BUY; an open canonical position → HOLD.
- WHY factors sourced **only** from the canonical scan snapshot: regime,
  trend (EMA20/50 + ADX), momentum/RSI, EMA alignment, volume ratio,
  liquidity, sector, support (stop), resistance (target), risk score (heat),
  R/R, expected reward, maximum risk, confidence breakdown, historical
  evidence. Factors the pipeline does **not** compute (VWAP, MACD, ATR, news
  impact, corporate actions) are shown as *not evaluated* — never fabricated.
- Agent contributions: existing stage journey (Scanner→…→Execution) rendered
  as the AI reasoning timeline; each stage shows status, decision, reason.
- Rejections use the spec contract: rejected_by / rule / threshold / actual /
  reason / recommendation — mapped from journey `why_not` + failed scan gates.

## Part D — Strategy Optimization
Delivered as the **"Historical Optimization" section** appended to the
Strategy Optimisation page (`/strategy-optimisation`), backed by
`GET /api/strategy-optimization/report` (`phase27_strategy_optimization.py`,
30 s cached + single-flight in Node).

- Per-strategy full metric contract: trades, wins, losses, win %, avg profit,
  avg loss, profit factor, max drawdown, Sharpe, avg hold time, capital
  utilisation (vs `INITIAL_CAPITAL`), net PnL. `low_evidence` flag below
  MIN_EVIDENCE=5 trades.
- Filter analysis over the 4 canonical scan gates (price, R/R, volume,
  data-quality): times triggered, symbols rejected; good/bad rejections and
  missed opportunities reuse the phase24 missed-opportunity store —
  `INSUFFICIENT_EVIDENCE` when no outcomes exist. Classification:
  OVERLY_CONSERVATIVE / EFFECTIVE / MIXED / DUPLICATE_REJECTION_SET /
  UNUSED_ON_LATEST_SCAN / INSUFFICIENT_EVIDENCE. Threshold domains
  (confidence, risk, sector exposure, liquidity, news, volatility) mapped to
  their real pipeline owners; news filters honestly N/A.
- Recommendations aggregated from the existing advisory engines
  (5D.3 strategy intelligence + phase24 learning); every entry carries
  `advisory_only: true`; nothing is ever auto-applied.
- Dashboards: daily/weekly/monthly period performance; heatmaps
  (strategy×regime, sector×regime, weekday×strategy); confidence and risk
  distributions — all derived from the canonical FIFO trade records
  (`collect_all_trade_records()`), zero recomputation of business logic.

## Validation checklist
- ✓ Read-only (both modules import canonical stores only; no writes)
- ✓ Uses canonical event/scan/ledger/portfolio stores
- ✓ No duplicated calculations (reuses validation_collector, phase24 store,
  strategy-intelligence recommendations, ops_centre journey)
- ✓ No trading logic changes (no scanner/executor/gate file touched)
- ✓ Mobile responsive (grids collapse to single column; verified at 402×874)
- ✓ Existing tests pass; `tsc` clean across workspace
- ✓ New tests: `tests/unit/test_phase27_explain_optimize.py` — 11/11 pass
  (decision mapping, HOLD, honest NOT_SCANNED, unevaluated factors,
  spec-label rejection mapping, metric contract math, duplicate/unused gate
  taxonomy, INSUFFICIENT_EVIDENCE, empty-history honesty)

## Architect review fixes (post-review, re-verified live)
- HOLD detection now uses `build_canonical_portfolio()` (real export).
- Gate handling uses the canonical `{passed, reason}` dict shape in both
  modules; gate failure reasons surface in rejection details.
- phase24 missed-opportunity rows are unwrapped from their `record` envelope;
  good/bad counts derive from `rejection_correct` / `should_have_allowed`
  against `rejected_by_gates`.
- Symbols whose data fetch failed (all gates tripped at once) are excluded
  from per-filter counts and listed separately — prevents false
  DUPLICATE_REJECTION_SET classifications.
- When the ops journey disagrees with the canonical scan (e.g. "Not in
  universe" for a scanned symbol), the timeline is hidden with an explicit
  out-of-sync note; current stage falls back to the canonical scan.
- Position-size factor added (paper eligibility/order fields).

## Live verification (dev)
- `GET /api/explain/symbol/TCS` → ok, decision WATCH, 21 factors.
- `GET /api/strategy-optimization/report` → ok; 0 closed trades →
  INSUFFICIENT EVIDENCE banner; 4 gates analysed; 3 advisory recommendations.
- Screenshots: both pages render on desktop and mobile with honest empty
  states (no fabricated data, market closed).
