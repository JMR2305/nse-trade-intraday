# Phase 8.3 — Data Quality & Validation Framework
**ApexQuant AI · Advisory-Only Module**

---

## Overview

Phase 8.3 adds a comprehensive, read-only Data Quality & Validation Framework to ApexQuant AI. It continuously audits every major data source used by the platform — market snapshots, pre-open data, paper trades, portfolio state, AI predictions, signals, and system configuration — and publishes a weighted quality score with per-domain grades, detailed issue lists, and exportable reports.

**Key principle:** This module is purely advisory. It reads data, audits it, and reports findings. It never modifies trades, signals, portfolio state, AI models, strategies, or any other data source.

---

## Architecture

```
data_quality/
├── __init__.py            — package export
├── models.py              — feature flag, Issue dataclass, quality_grade(), domain_result()
├── market.py              — OHLCV validator (prices, volume, timestamps)
├── preopen.py             — pre-open session validator (IEP, quantities, providers)
├── paper.py               — paper trade validator (records, sequence, P&L, cash)
├── portfolio.py           — portfolio validator (capital bounds, totals, sectors)
├── ai_check.py            — AI data validator (confidence, accuracy, ECE, signals)
├── signals.py             — signal lifecycle validator (states, duplicates, linkage)
├── config_check.py        — system config validator (env vars, flags, provider)
├── shared_services.py     — composite score, 6 dimensions, exports, alerts, snapshot
├── api.py                 — thin cmd_*() wrappers for all 12 commands
└── test_data_quality.py   — 89 unit tests (100% pass)
```

### Data flow

```
shared_services.get_summary()
    ├── _load_market()    → market.validate_market_snapshot()
    ├── _load_preopen()   → preopen.validate_preopen_snapshot()
    ├── _load_paper()     → paper.validate_* (trades, sequence, cash)
    ├── _load_portfolio() → portfolio.validate_portfolio()
    ├── _load_ai()        → ai_check.validate_ai_snapshot()
    ├── _load_signals()   → signals.validate_signal_set()
    └── _load_config()    → config_check.validate_config()
          ↓
    _weighted_score()     → composite quality_score (0–100)
    quality_grade()       → A+ / A / B / C / D
```

---

## Quality Score Formula

The overall quality score is a weighted average across 7 domains:

| Domain | Weight | What it checks |
|---|---|---|
| Market Data | **20%** | OHLCV consistency, prices, volume, timestamps |
| Paper Trading | **15%** | Trade records, P&L accuracy, sequence, duplicates |
| Portfolio | **15%** | Capital bounds, cash+invested=total, utilisation, sectors |
| AI | **15%** | Confidence/accuracy ranges, ECE calibration, signal counts |
| Configuration | **15%** | Required env vars, feature flags, provider, Python version |
| Pre-Open | **10%** | IEP presence, quantities, gap spikes, provider consistency |
| Signals | **10%** | Lifecycle states, duplicate IDs, EXECUTED→trade linkage |

### Grade thresholds

| Grade | Score |
|---|---|
| A+ | ≥ 92 |
| A  | ≥ 80 |
| B  | ≥ 68 |
| C  | ≥ 50 |
| D  | < 50 |

### Six quality dimensions (cross-cutting)

Each summary also reports scores across 6 quality dimensions aggregated from all domains:

- **Completeness** — required fields present, no missing data
- **Consistency** — values internally coherent (OHLC order, cash+invested=total)
- **Accuracy** — reported values match computed values (P&L check, ECE ranges)
- **Freshness** — timestamps are recent and monotonic
- **Integrity** — no duplicates, no sequence violations, linkage intact
- **Validity** — values within expected bounds (prices > 0, confidence 0–1)

---

## Issue Severity Levels

| Severity | Meaning |
|---|---|
| **CRITICAL** | Impossible value (negative price, OHLC inversion, negative capital) |
| **WARNING** | Out-of-range or suspicious value (zero volume, high ECE, extreme gap) |
| **DUPLICATE** | Same ID or symbol appears more than once |
| **MISSING** | Required field is absent or null |
| **STALE** | Timestamp is outdated (future timestamp, non-monotonic order) |
| **INFO** | Advisory note (fallback provider active, optional field absent) |

---

## Validators in Detail

### Market Data (`market.py`)
- **`validate_ohlcv(row)`** — checks: `high ≥ low`, `open/close within [low, high]`, `all prices > 0`, `volume ≥ 0`
- **`validate_timestamps(rows)`** — checks: future timestamps, non-monotonic order
- **`validate_market_snapshot(rows)`** — aggregates per-symbol checks, detects duplicate symbols, marks snapshot unavailable if empty

### Pre-Open (`preopen.py`)
- **`validate_preopen_symbol(row)`** — checks: IEP present and positive, buy/sell qty ≥ 0, gap_pct < 25%, extreme IEP vs prev_close spike
- **`validate_provider_consistency(rows)`** — checks: all symbols from same provider, flags fallback active
- **`validate_preopen_snapshot(rows)`** — aggregates, detects duplicate symbols

### Paper Trading (`paper.py`)
- **`validate_trade_record(t)`** — checks: trade ID present, qty > 0, price > 0, P&L within 5% tolerance of `(exit_price - entry_price) × qty`
- **`validate_duplicate_trades(trades)`** — DUPLICATE severity if same ID appears twice
- **`validate_trade_sequence(trades)`** — FIFO inventory tracking, flags OVERSELL
- **`validate_portfolio_cash(portfolio)`** — checks: cash ≥ 0, `cash + invested ≈ total` (within 5%)

### Portfolio (`portfolio.py`)
- Checks: `total_value > 0`, `cash_available ≥ 0`, `invested_capital ≥ 0`
- `cash + invested ≈ total` (within 5% tolerance)
- Utilisation in `[0, 100]%`
- Sector allocation sum ≤ 105%
- Each position value ≥ 0

### AI (`ai_check.py`)
- Confidence and accuracy in `[0, 1]`
- Calibration ECE < 0.20 (warning above)
- `executed_signals ≤ total_signals`
- Health score in `[0, 100]`

### Signals (`signals.py`)
- Signal ID must be present
- Status must be a valid lifecycle state: `GENERATED`, `APPROVED`, `REJECTED`, `EXECUTED`, `EXPIRED`, `CANCELLED`
- Confidence in `[0, 1]`
- No duplicate IDs
- `EXECUTED` signals without `paper_trade_id` → MISSING_LINKAGE warning

### Configuration (`config_check.py`)
- **Required** env vars: `DATABASE_URL`, `SESSION_SECRET`
- **Recommended**: `MARKET_DATA_PROVIDER`, `PYTHON_EXEC`
- Valid providers: `nse_official`, `kite`, `yahoo`, `mock`
- Reports current state of all `*_ENABLED` feature flags
- Checks Python ≥ 3.11

---

## API Endpoints

All 11 endpoints are registered under `/api/data-quality/`:

| Method | Path | Description |
|---|---|---|
| GET | `/summary` | Overall quality score, grade, 7 domain scores, 6 dimensions |
| GET | `/market` | Market data validation result + issue list |
| GET | `/preopen` | Pre-open data validation result + issue list |
| GET | `/paper` | Paper trade validation result + issue list |
| GET | `/portfolio` | Portfolio validation result + issue list |
| GET | `/ai` | AI data validation result + issue list |
| GET | `/signals` | Signal validation result + issue list |
| GET | `/config` | Config validation result + feature flag states |
| GET | `/alerts` | All issues across all domains, sorted by severity |
| GET | `/snapshot` | Lightweight snapshot for executive summary consumption |
| GET | `/export?format=json` | Full JSON report (all domains + issues) |
| GET | `/export?format=csv` | Issues as CSV: `domain,severity,check,field,message,symbol,value` |

### Feature flag

```bash
DATA_QUALITY_ENABLED=true   # default: false
```

All endpoints return `{ "status": "DISABLED", "available": false }` when the flag is off.

### Sample summary response

```json
{
  "status": "ENABLED",
  "available": true,
  "advisory_only": true,
  "quality_score": 82.5,
  "grade": "A",
  "score_components": {
    "completeness": 90.0,
    "consistency": 85.0,
    "accuracy": 78.0,
    "freshness": 88.0,
    "integrity": 80.0,
    "validity": 75.0
  },
  "total_issues": 3,
  "critical_count": 0,
  "warning_count": 3,
  "domains": [ ... ],
  "generated_at": "2026-07-30T09:15:00+05:30"
}
```

---

## React Dashboard (`/data-quality`)

11-tab dashboard accessible from the Analytics sidebar group.

| Tab | Content |
|---|---|
| **Overview** | Score ring (animated, live-updating), 6 dimension KPI cards, domain scores table, critical alert banner |
| **Market Data** | Score, grade, checks passed/failed, issue table |
| **Pre-Open** | Score, grade, checks, issue table |
| **Paper Trading** | Score, grade, trades checked, issue table |
| **Portfolio** | Score, grade, checks, issue table |
| **AI** | Score, grade, checks, issue table |
| **Signals** | Score, grade, signals checked, note if empty, issue table |
| **Configuration** | Score, grade, feature flag states table, provider name, issue table |
| **Alerts** | All issues grouped by severity (Critical / Warnings / Duplicates / Missing / Stale / Info), collapsible sections |
| **History** | Phase 8.4 placeholder (validation run history) |
| **Export** | Download full JSON report or CSV issue list |

### Score ring
- SVG arc ring with `stroke-dasharray` fill proportional to quality score
- `style.transition: stroke-dasharray 0.6s ease` — animates smoothly on data refresh
- Color: emerald ≥ 90, blue ≥ 75, yellow ≥ 60, red < 60
- Updates live via React Query auto-refetch (60-second interval)

### Critical alert banner
When `critical_count > 0`, a red banner appears at the top of the page directing operators to the Alerts tab.

---

## File Locations

| Purpose | Path |
|---|---|
| Python package | `artifacts/api-server/src/python/data_quality/` |
| Express router | `artifacts/api-server/src/routes/data-quality.ts` |
| Route registration | `artifacts/api-server/src/routes/index.ts` |
| main.py dispatch | `artifacts/api-server/src/python/main.py` (Phase 8.3 block) |
| React dashboard | `artifacts/trading-dashboard/src/pages/DataQuality.tsx` |
| React tests | `artifacts/trading-dashboard/src/pages/DataQuality.test.tsx` |
| Python tests | `artifacts/api-server/src/python/data_quality/test_data_quality.py` |
| Sidebar nav | `artifacts/trading-dashboard/src/components/layout/AppLayout.tsx` |
| App route | `artifacts/trading-dashboard/src/App.tsx` |

---

## Test Coverage

### Python unit tests — 89 / 89 passing

| Class | Tests | What it covers |
|---|---|---|
| `TestFeatureFlag` | 5 | `is_enabled()`, `disabled_response()`, flag values `true`/`1`/`false` |
| `TestMarketValidation` | 17 | OHLC inversion, negative/zero prices, volume, duplicate symbols, timestamp checks |
| `TestPreopenValidation` | 12 | IEP, qty signs, gap spike, provider consistency, fallback flag, duplicates |
| `TestPaperValidation` | 11 | Trade ID, qty, price, P&L tolerance, duplicate IDs, FIFO sequence, cash/total |
| `TestPortfolioValidation` | 8 | Capital/cash negative, utilisation, total mismatch, sector sum, position value |
| `TestAIValidation` | 8 | Confidence/ECE ranges, missing fields, execution overflow, health score bounds |
| `TestSignalValidation` | 8 | ID missing, invalid state, confidence range, duplicates, EXECUTED linkage |
| `TestConfigValidation` | 6 | Missing DATABASE_URL, invalid/valid provider, flag states, advisory_only |
| `TestQualityScore` | 7 | Grade thresholds (A+/A/B/C/D), `domain_result()` pass rate, zero-check safety |
| `TestSharedServices` | 7 | Summary fields, advisory flag, score components, weighted average, alerts sort, CSV export, snapshot |

### React unit tests — 40 / 40 passing

| Group | Tests |
|---|---|
| Header & navigation | 5 — heading, subtitle, 11 tab labels, active tab styling, grade badge |
| Overview tab | 6 — score text, SVG arc, 6 dimensions, domain table, ADVISORY badge, generated_at |
| Critical banner | 2 — shown when `critical_count > 0`, hidden when 0 |
| Disabled state | 2 — "Data Quality Disabled" text, env var hint |
| Domain tabs | 10 — each of 7 domain tabs shows correct heading; issue check name rendered; all-passed message; KPI card |
| Configuration extras | 2 — flag states table, provider name |
| Alerts tab | 3 — empty state, critical alert, warning alert |
| History tab | 1 — Phase 8.4 placeholder |
| Export tab | 4 — heading, JSON button, CSV button, advisory disclaimer |
| Score ring animation | 5 — arc present, fill > 0, CSS transition, fill grows on score increase, text updates |

### TypeScript typecheck
Clean — `pnpm exec tsc -b ... && pnpm --filter trading-dashboard exec tsc --noEmit` exits 0.

---

## Design Decisions

- **Advisory-only at every layer.** The `advisory_only: true` flag is set in every API response and every domain result. The Python modules never write to any store.
- **Feature flag guards at the summary level.** `get_summary()` checks the flag first and short-circuits to `disabled_response()` before loading any domain validators.
- **Null-safe price parsing.** `validate_ohlcv` uses `None` as the sentinel for absent values (not `-1`), allowing it to correctly distinguish "value missing" from "value present but negative."
- **Numeric-string timestamps.** `validate_timestamps` tries ISO parse first, falls back to `float()` for Unix epoch strings.
- **Domain weights are constants.** `_DOMAIN_WEIGHTS` in `shared_services.py` is the single source of truth for the weighted score formula.
- **CSV export is always string.** `get_export_csv()` returns a plain Python string starting with the header row `domain,severity,check,field,message,symbol,value`.

---

## Phase 8.3 Completion Criteria

| Criterion | Status |
|---|---|
| 7 domain validators implemented | ✅ |
| 12 API endpoints (Express router + main.py dispatch) | ✅ |
| 11-tab React dashboard with score ring | ✅ |
| Sidebar nav + App.tsx route `/data-quality` | ✅ |
| Python unit tests ≥ 80, 100% pass | ✅ 89/89 |
| React unit tests ≥ 30, 100% pass | ✅ 40/40 |
| TypeScript typecheck clean | ✅ |
| Advisory-only throughout (no data mutations) | ✅ |
| Feature flag guard (`DATA_QUALITY_ENABLED`) | ✅ |
| Freshness coverage marker present | ✅ |
