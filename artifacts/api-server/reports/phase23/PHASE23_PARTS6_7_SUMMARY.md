# Phase 23 — Parts 6 & 7 Summary

**AI Strategy Optimization Lab + Institutional Performance Analytics**
**Date:** 2026-08-08 · **Status:** ✅ Complete & Verified (lab_verify: PASS, 24/24 tests)

---

## What was built

### Part 6 — Strategy Optimization Lab (`/optimization-lab`, Strategy Agent group)
| Section | What it does |
|---|---|
| Run Picker | Select completed backtest runs or the paper portfolio as the data source |
| Multi-Run Comparison | Side-by-side metrics table (Sharpe, Sortino, drawdown, profit factor, expectancy, recovery factor, capital growth, max exposure) + equity-curve overlay |
| Config Comparison / What-If | Up to 4 editable configurations (confidence floor, stop/target/trailing multipliers, risk scale, max open trades, regime/sector/volume filters) replayed over the recorded run — **derived simulations only; the base run is never modified** |
| Walk-Forward Validation | 3–6 folds, train-vs-validate comparison, generalization score, consistency, overfitting-risk badge (LOW/MEDIUM/HIGH) |
| Monte Carlo | Deterministic-seeded bootstrap (up to 2,000 paths) over **portfolio-level** trade returns: probability of profit, drawdown risk, survival probability, risk of ruin, return/drawdown histograms, sample-path spaghetti chart |
| Run Diff | Any two runs: trades added/removed, PnL/drawdown/strategy/confidence/risk differences |
| Recommendations | Evidence-backed advisory suggestions (confidence sweeps, best/worst sector/hour/weekday, stop-multiplier sweeps) — auto-apply is permanently disabled |
| Export | JSON / CSV / Markdown downloads + print-to-PDF |
| Validation | One-click `lab_verify`: proves runs are byte-identical after every lab operation |

### Part 7 — Institutional Analytics (`/institutional-analytics`, Operations group)
| Section | What it does |
|---|---|
| KPI Strip | Trades, win rate, total PnL, profit factor, expectancy, Sharpe, Sortino, max drawdown, recovery factor |
| Portfolio Charts | Equity curve, drawdown curve, monthly returns, rolling 10-trade metrics |
| Strategy Leaderboard | Per-strategy ranking with confidence accuracy and capital efficiency |
| Regime / Sector / Time Analysis | Bucketed performance by market regime, sector, hour, weekday, and month with best/worst strategy per bucket |
| Confidence Calibration | Reliability curve (predicted vs observed win rate), per-bucket calibration error, Brier score, confidence distribution |
| Risk Heatmap | Sector × regime PnL grid |
| Capital Utilization | Deployed-capital percentage over time |
| Monte Carlo Summary | Key risk tiles + return histogram |

## Architecture
- **Backend:** `src/python/strategy_lab.py` (~800 lines) — one read-only module over the canonical stores (backtest store, phase20 paper ledger, candle cache, settings store). Metric math delegates to the existing `expectancy.compute_metrics`; paper calibration embeds `phase21_calibration` verbatim — **zero duplicate calculation engines**.
- **CLI:** 13 `lab_*` commands in `main.py`.
- **API:** `src/routes/lab.ts` — 13 endpoints under `/api/lab/*` with input caps, bounded coalescing cache (30–60s TTL), and 120–300s timeouts for heavy operations.
- **Frontend:** `OptimizationLab.tsx` and `InstitutionalAnalytics.tsx`, registered in the app router and agent navigation.

## Safety guarantees
1. **Strictly read-only** — what-if variants are recomputed on demand and never persisted; `lab_verify` byte-compares the run record + ledger after what-if, walk-forward and recommendations (PASS on real run `BT-85a4febee3`), and confirms replay integrity and live settings are untouched.
2. **Advisory only** — every response carries an advisory note; recommendations hardcode `auto_apply: false`.
3. **No extrapolation** — fewer than 5 trades in any analytic ⇒ explicit `INSUFFICIENT_EVIDENCE` verdict, rendered as intentional amber states in the UI.
4. **Honest simulations** — failed exit re-simulations are excluded (verdict `RESIM_INCOMPLETE`), never silently replaced by baseline exits; Monte Carlo compounds PnL relative to actual portfolio capital, not all-in per-trade returns.

## Verification
- `test_backtest_engine.py`: 24/24 pass, incl. 6 new Strategy Lab tests (immutability byte-check, deterministic Monte Carlo, insufficient-evidence fail-safes).
- Typecheck clean (api-server + trading-dashboard); both pages verified live via screenshots.
- Architect code review completed; all 4 high-severity findings fixed and re-verified.

Full details: `PHASE23_PARTS6_7_VERIFICATION.md` (same directory).
