# Advanced Paper Trading Analytics — ApexQuant AI
### Phase 8.2 · Advisory Only · Read-Only

---

## Overview

The **Advanced Paper Trading Analytics** module is a comprehensive, read-only intelligence layer built on top of the ApexQuant AI paper trading engine. It gives operators a 360° view of every dimension of their paper portfolio — from trade-level statistics to AI signal quality to pre-open accuracy — without ever modifying orders, strategies, portfolio state, or risk parameters.

All outputs are explicitly **ADVISORY ONLY** and are clearly marked as such throughout the UI.

---

## Architecture

### Backend — `paper_analytics/` (Python)

| File | Purpose |
|---|---|
| `shared_services.py` | Stable public API — the only file other modules import from |
| `models.py` | Feature-flag helpers, grade computation, disabled-response factory |
| `trade_analytics.py` | FIFO P&L, win rate, expectancy, streaks, equity curves, drawdown |
| `strategy_analytics.py` | Per-strategy breakdown, contribution %, best/worst |
| `risk_analytics.py` | Sharpe, Sortino, Calmar, Kelly allocation, Monte Carlo hooks |
| `portfolio_analytics.py` | Portfolio value, utilisation, open-position exposure |
| `preopen_analytics.py` | Pre-open accuracy from reconciled sessions, score-band grouping |
| `execution_analytics.py` | Execution quality grades, slippage, fill-delay distribution |
| `learning_insights.py` | Best sector, strategy, market-condition; learning velocity |
| `ai_insights.py` | AI confidence, prediction accuracy, calibration quality |
| `time_analytics.py` | Best trading hour, session-level P&L distribution |
| `sector_analytics.py` | Sector-level P&L, win rate, concentration |
| `api.py` | FastAPI command handlers registered in `main.py` |
| `test_paper_analytics.py` | **156 unit tests** covering all modules |

### Frontend — `PaperAnalytics.tsx` (React/TypeScript)

A **1,653-line** dashboard with 12 tabs, built with TanStack Query, Recharts, and the ApexQuant AI design system.

---

## Analytics Score (0–100)

The module computes a composite **Analytics Quality Score** on every `get_summary()` call — no caching, always reflecting the latest closed trades.

```
Score = win_rate_pts + profit_factor_pts + sharpe_pts + drawdown_pts + data_pts
```

| Component | Weight | Formula |
|---|---|---|
| Win Rate | 30 pts | `win_rate / 100 × 30` |
| Profit Factor | 20 pts | `min(profit_factor / 3, 1) × 20` |
| Sharpe Ratio | 20 pts | `min(max(sharpe / 2, 0), 1) × 20` |
| Drawdown Penalty | 15 pts | `max(0, 1 − max_drawdown_pct / 30) × 15` |
| Data Quality | 15 pts | `min(total_trades / 30, 1) × 15` |

**Grade thresholds:**

| Grade | Score |
|---|---|
| A+ | ≥ 90 |
| A | ≥ 80 |
| B | ≥ 65 |
| C | ≥ 50 |
| D | < 50 |

---

## Dashboard Tabs

### 1. Overview
- Analytics Score ring (0–100) with grade badge
- Key KPI tiles: total trades, win rate, profit factor, expectancy, Sharpe ratio, Sortino ratio, Calmar ratio, max drawdown, volatility
- Best strategy / sector / market condition highlights
- Advisory-only badge, Phase 8.2 subtitle

### 2. Trades
- Equity curve (daily / weekly / monthly toggle)
- Drawdown curve and recovery curve
- Rolling returns chart
- Largest winner and largest loser detail cards
- Win/loss streak indicators

### 3. Strategies
- Per-strategy table: total trades, win rate, profit factor, expectancy, contribution %
- Best / worst strategy callout
- Confidence rating where available

### 4. Risk
- Sharpe, Sortino, Calmar ratios
- Max drawdown with trough depth and duration
- Volatility (annualised)
- Kelly allocation percentage
- HHI sector concentration score
- 7 stress scenarios (static) + Monte Carlo future hook

### 5. Portfolio
- Portfolio value, realised P&L, unrealised P&L
- Cash available, invested capital, utilisation %
- Open-position exposure summary

### 6. Time
- Best / worst trading hour heatmap
- Session-level P&L distribution (morning vs afternoon split)
- Day-of-week performance breakdown

### 7. Sectors
- Sector-level P&L, win rate, trade count
- Concentration bar showing sector HHI
- Best and worst performing sector callout

### 8. Pre-Open
- Pre-open accuracy from reconciled live sessions
- Hit rate, continuation rate, reversal rate, confirmation rate, false-positive rate
- Score-band accuracy (0–39 / 40–59 / 60–79 / 80–100) grouped from symbol-level data
- Gap-and-go count and rate
- Historical session accuracy table (all reconciled dates)
- MAE (indicative vs open-price error %)
- MFE explicitly marked unavailable (requires intraday data)

### 9. Execution
- Overall execution quality grade
- Average slippage and fill-delay distribution
- Best / worst execution trade detail
- Grade distribution (A+ through D)

### 10. Learning
- Best sector / strategy / market condition derived from closed trades
- Learning velocity metric
- Advisory recommendations for future session setup

### 11. AI Insights
- AI confidence level, prediction accuracy, calibration quality
- Signal success rate and high-confidence signal %
- Trend direction (Improving / Stable / Declining)

### 12. Export
- Download Full Report (JSON) — all analytics modules bundled
- Download CSV — tabular trade data for external analysis
- Advisory/paper-trading disclaimer in export output

---

## Key Engineering Decisions

### Zero-Trade Safety
When `total_trades == 0`, all rate and ratio fields (`win_rate`, `profit_factor`, `expectancy`, `sharpe_ratio`, `sortino_ratio`, `calmar_ratio`, `volatility_pct`) return **`None`** (not `0.0`). The React formatter renders `None` as `"—"` rather than the misleading `"0.00%"`. Aggregate dollar fields (`total_pnl`, `realised_pnl`) correctly return `0.0` since zero is accurate.

### Score Freshness
`get_summary()` calls all sub-module loaders on every invocation. There is **no module-level caching** — a new paper trade closing mid-session is reflected on the very next summary call.

### Pre-Open Integration
`preopen_analytics.py` imports `preopen_accuracy.get_accuracy()` and `get_accuracy_history()` at call time (not module load). When no sessions have been reconciled yet the response returns `available: False` and the tab shows a clear "no data" state rather than fabricated zeros.

### Read-Only / Advisory Contract
The module is enforced read-only at the architectural level:
- No writes to `paper_trades`, `paper_portfolio`, `signals_cache`, or any strategy table
- Every response payload carries `"advisory_only": true`
- The feature flag `PAPER_ANALYTICS_ENABLED` gates all endpoints; when disabled every function returns a consistent `disabled_response()` shape so callers never need to handle `None`

### Executive Dashboard Integration
`get_paper_analytics_snapshot()` exports a flat KPI dict for the Executive Dashboard. The dashboard includes **paper analytics as the 7th score component** (10% weight), with the remaining 6 components each scaled to ×0.9. The Executive Score ring (`stroke-dasharray` CSS transition, 0.6 s ease) smoothly animates when paper analytics improves between 60-second auto-refresh cycles.

---

## API Endpoints (registered in `main.py`)

| Command | Function | Returns |
|---|---|---|
| `paper_analytics_summary` | `cmd_summary()` | Score, grade, all KPI highlights |
| `paper_analytics_trades` | `cmd_trades()` | Equity curves, streak, largest winner/loser |
| `paper_analytics_strategies` | `cmd_strategies()` | Per-strategy breakdown |
| `paper_analytics_risk` | `cmd_risk()` | Risk ratios, drawdown, Kelly, HHI |
| `paper_analytics_preopen` | `cmd_preopen()` | Pre-open accuracy, score-band, history |
| `paper_analytics_portfolio` | `cmd_portfolio()` | Portfolio exposure |
| `paper_analytics_learning` | `cmd_learning()` | Best sector/strategy/condition |
| `paper_analytics_snapshot` | `cmd_snapshot()` | Flat KPI for Executive Dashboard |
| `paper_analytics_export_json` | `cmd_export_json()` | Full JSON bundle |
| `paper_analytics_export_csv` | `cmd_export_csv()` | CSV trade data |

---

## Test Coverage

| Layer | Tests | Status |
|---|---|---|
| Python (all 14 sub-modules) | **156** | ✅ All passing |
| React (PaperAnalytics.tsx — 12 tabs) | **50** | ✅ All passing |
| TypeScript | Full codebase | ✅ Clean |

### Test classes (Python)

| Class | Focus |
|---|---|
| `TestFeatureFlag` | Disabled state, flag toggling |
| `TestTradeAnalytics` | Win rate, streaks, equity curves, drawdown |
| `TestStrategyAnalytics` | Per-strategy metrics, contribution % |
| `TestRiskAnalytics` | Sharpe, Sortino, Calmar, Kelly, stress |
| `TestPortfolioAnalytics` | Exposure, utilisation |
| `TestTimeAnalytics` | Session-level P&L distribution |
| `TestSectorAnalytics` | Sector breakdown, concentration |
| `TestPreopenAnalytics` | Accuracy, score-band, history |
| `TestExecutionAnalytics` | Grade, slippage, fill-delay |
| `TestLearningInsights` | Best-of derivation |
| `TestAIInsights` | Confidence, accuracy, calibration |
| `TestAnalyticsScore` | Score formula validation |
| `TestSummarySnapshot` | Executive Dashboard KPI shape |
| `TestScoreFreshnessOnNewTrade` | No stale cache — score reflects new trade immediately |
| `TestZeroTradePortfolio` | Null-not-zero contract for all rate/ratio fields |
| `TestPreopenWithRealSessionData` | Full accuracy pipeline with reconciled session data |
| `TestPaperAnalyticsNeutralFallback` | Executive score at neutral input |
| `TestPaperAnalyticsScoreImpact` | Executive score changes when analytics improves |

---

## File Locations

```
artifacts/
├── api-server/src/python/
│   └── paper_analytics/
│       ├── shared_services.py        ← public API (stable)
│       ├── models.py                 ← feature flag, grade, disabled_response
│       ├── trade_analytics.py        ← FIFO P&L, equity curves, streaks
│       ├── strategy_analytics.py     ← per-strategy breakdown
│       ├── risk_analytics.py         ← Sharpe, Kelly, drawdown, stress
│       ├── portfolio_analytics.py    ← exposure, utilisation
│       ├── preopen_analytics.py      ← pre-open accuracy & score bands
│       ├── execution_analytics.py    ← execution quality grades
│       ├── learning_insights.py      ← best sector / strategy / condition
│       ├── ai_insights.py            ← AI confidence & calibration
│       ├── time_analytics.py         ← session / hour P&L distribution
│       ├── sector_analytics.py       ← sector-level breakdown
│       ├── api.py                    ← FastAPI command handlers
│       └── test_paper_analytics.py   ← 156 unit tests
└── trading-dashboard/src/pages/
    ├── PaperAnalytics.tsx            ← 12-tab React dashboard (1,653 lines)
    └── PaperAnalytics.test.tsx       ← 50 React tests
```

---

## Feature Flag

Set `PAPER_ANALYTICS_ENABLED=true` in the server environment to activate the module. When `false` (default in production until live-trading readiness is confirmed), every endpoint returns:

```json
{
  "status": "DISABLED",
  "message": "Set PAPER_ANALYTICS_ENABLED=true to activate."
}
```

The React dashboard renders a clear disabled state rather than an empty screen.

---

*Generated: 2026-07-31 · ApexQuant AI — Phase 8.2*
