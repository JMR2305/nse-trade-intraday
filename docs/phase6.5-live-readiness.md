# Phase 6.5 — Live Readiness & Operational Validation Framework

## Overview

Phase 6.5 provides a unified **Operational Readiness Score** and **GO/NO-GO assessment** for
extended paper trading. It aggregates results from all Phase 6.x analytics modules plus
independent system, data quality, recovery, security, and configuration checks.

**This module NEVER enables live trading, places orders, or modifies any trading engine,
portfolio, strategies, signals, AI models, or risk parameters. ALL output is advisory-only.**

---

## Feature Flag

```
READINESS_VALIDATION_ENABLED=true
```

Set in the shared environment. When `false` (default), all endpoints return
`{ "status": "DISABLED" }`.

---

## Architecture

### Python Module — `artifacts/api-server/src/python/live_readiness/`

| File | Purpose |
|---|---|
| `readiness_models.py` | Feature flag, `ReadinessCheck` dataclass, scoring helpers, GO/NO-GO logic |
| `system_health_checker.py` | Python runtime, DB connectivity, module health, latency |
| `data_quality_checker.py` | FIFO consistency, duplicates, field completeness, freshness |
| `recovery_checker.py` | Portfolio state recovery, config, watchlist, Phase 6.x snapshots |
| `security_checker.py` | Secrets present, debug mode, advisory-only flags, audit trail |
| `config_checker.py` | Env vars, feature flags, config module, checksum |
| `api_health_checker.py` | Phase 6.x module probe + response shape consistency |
| `shared_services.py` | Public API: all endpoints + `get_readiness_snapshot()` |
| `api.py` | Thin façade for `main.py` command dispatch |
| `test_live_readiness.py` | **50/50 tests** |

### Operational Readiness Score — weighted formula

| Category | Weight |
|---|---|
| System Health | 20% |
| Data Quality | 20% |
| API Health | 15% |
| Configuration | 15% |
| Security | 15% |
| Recovery | 15% |

**Grade:** A+ (≥90) → A (≥80) → B (≥65) → C (≥50) → D (<50)

### GO/NO-GO Verdict

| Condition | Verdict |
|---|---|
| Score ≥ 80 AND no required-FAIL checks | READY FOR EXTENDED PAPER TRADING |
| Score ≥ 60 AND no required-FAIL checks | READY WITH OBSERVATIONS |
| Score < 60 OR any required-FAIL check | NOT READY |

---

## API Endpoints

All endpoints under `/api/readiness/`:

| Method | Path | Returns |
|---|---|---|
| GET | `/summary` | Score, grade, verdict, category breakdown, Phase 6.x snapshot |
| GET | `/system` | System health checks + broker readiness + feature flags |
| GET | `/data` | Data quality checks + API health checks |
| GET | `/recovery` | Recovery capability checks |
| GET | `/security` | Security checks + configuration checks |
| GET | `/report` | Full consolidated report + recommendations + CI/CD hook stub |
| GET | `/export/csv` | Summary as CSV |
| GET | `/export/json` | Full report as JSON |

---

## Dashboard Page

`artifacts/trading-dashboard/src/pages/LiveReadiness.tsx`

10 sections:
1. **Overall Readiness** — Score ring, GO/NO-GO banner, category score bars
2. **System Health** — All module/DB/latency checks
3. **Data Quality** — Trade record quality checks
4. **Recovery Capability** — Portfolio state, config, Phase 6.x snapshot recovery
5. **API Health** — Phase 6.x module probe results
6. **Broker Readiness** — Paper-trading-only summary; live orders NEVER placed
7. **Configuration** — Feature flags, env vars, config checksum
8. **Security** — Secret presence, debug mode, advisory-only enforcement
9. **Go / No-Go Summary** — Strengths, observations, weaknesses, blocking actions
10. **Future Integration Hooks** — CI/CD gate stub, Phase 6.x status board

Nav: **Analytics → Live Readiness** (Rocket icon)

---

## Tests

```
50 tests in 10 classes — 50/50 PASS (3.66s)
```

- Feature flag (5)
- Readiness models (5)
- System health (5)
- Data quality (7)
- Recovery (4)
- Security (6)
- Config (5)
- API health (4)
- Shared services (7)
- Export (2)

---

## Design Principles

- **Read-only:** All checks are read-only. Nothing is modified.
- **No re-implementation:** System health uses stdlib only (no psutil). Phase 6.x results
  are read via the existing `get_*_snapshot()` stable interfaces — never re-calculated.
- **No import from `readiness_checker.py`:** The Phase 8 live readiness checker imports
  `execution_engine` (broker integration). Phase 6.5 is a separate `live_readiness/` package.
- **Fail-safe security check:** A `PASS` on the advisory-only flags check confirms
  `AUTO_EXECUTION_ENABLED` and `LIVE_ORDERS_ENABLED` are not set.
- **Downstream interface:** `get_readiness_snapshot()` provides a flat KPI dict
  (`readiness_score`, `grade`, `verdict`) for any future executive dashboard aggregation.

---

## wiring

- `artifacts/api-server/src/python/main.py` — 9 new command dispatch entries
- `artifacts/api-server/src/routes/readiness.ts` — 8 HTTP routes
- `artifacts/api-server/src/routes/index.ts` — `router.use(readinessRouter)`
- `artifacts/trading-dashboard/src/App.tsx` — `<Route path="/live-readiness" ...>`
- `artifacts/trading-dashboard/src/components/layout/AppLayout.tsx` — Analytics nav item
