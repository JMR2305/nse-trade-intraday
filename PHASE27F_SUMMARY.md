# Phase 27F — System Readiness Dashboard: Summary

**Date:** 2026-08-15  
**Status:** COMPLETE  
**Mode:** PAPER TRADING / RESEARCH ONLY — read-only, advisory-only

---

## What Was Built

Phase 27F adds a System Readiness Dashboard that deterministically answers: "Is ApexQuant AI ready to safely run the next/current paper trading session?" It folds canonical health indicators from 10 domains into a single READY / WARNING / BLOCKED / UNKNOWN verdict. Missing evidence is always UNKNOWN — never READY (fail-safe).

| Component | File | Lines | Status |
|-----------|------|-------|--------|
| Python backend | `artifacts/api-server/src/python/phase27_readiness.py` | 881 | Complete |
| React UI | `artifacts/trading-dashboard/src/pages/SystemReadiness.tsx` | 301 | Complete |
| Python tests | `artifacts/api-server/src/python/tests/unit/test_phase27f_system_readiness.py` | 400+ | **NEW — 68/68 passing** |
| Frontend tests | `artifacts/trading-dashboard/src/pages/SystemReadiness.test.tsx` | 280+ | **NEW — 15/15 passing** |

---

## Canonical Data-Source Map

| Domain | Canonical Source | Module |
|--------|-----------------|--------|
| Market & Data (scan freshness, provider coverage) | Scan state store | `scan_state_store.load_latest_meta()` |
| Broker & Authentication | Kite session manager (cached probe, 60s TTL) | `kite_session_manager.get_status(force_probe=False)` |
| Pipeline (last scan outcome, event stream) | Scan state store + pipeline events | `scan_state_store`, `pipeline_events.query_events()` |
| Strategy & Risk (config readable) | Phase 20 settings store | `phase20_store.get_settings()` |
| Execution (settings readable) | Phase 20 settings store | `phase20_store.get_settings()` |
| Portfolio health | Portfolio snapshot | `portfolio_snapshot.get_portfolio_health(emit_alerts=False)` |
| Persistence & Recovery | Scan state store DB probe + Phase 26C recovery | `scan_state_store.db_available()`, `phase26c_store.latest_result("RECOVERY")` |
| Scheduling | Phase 20 scheduler health | `phase20_store.get_scheduler_health()` |
| Safety Controls (paper mode, circuit breaker, live flags) | Config + env flags + Phase 20 circuit breaker | `config.PAPER_TRADING_MODE`, `os.environ`, `phase20_circuit_breaker.get_state()` |
| Configuration (env vars, system resources) | Environment + observability center | `os.environ` (presence-only), `observability_center.system_health.*` |
| Freshness rows | All of the above (timestamps) | Reuses inputs already collected |
| Readiness history | Phase 20 KV store | `phase20_store.kv_get/kv_set(READINESS_HISTORY_KEY)` |

---

## Readiness-State Derivation

```
derive_overall(checks):
  if any blocking check is BLOCKED   → BLOCKED
  elif any blocking check is UNKNOWN → UNKNOWN   (fail-safe: not READY)
  elif any check is WARNING/BLOCKED/UNKNOWN → WARNING
  else → READY
```

Domain status = same fold applied to that domain's checks only.

**Blocking checks** (UNKNOWN or BLOCKED prevents READY): scan_freshness, last_scan_outcome, risk_config, execution_config, db_durable, scheduler_health, execution_mode, circuit_breaker, critical_env.

**Non-blocking checks**: broker_session, pipeline_events, provider_coverage, portfolio_health, recovery_validation, system_resources.

---

## APIs Reused (No New HTTP Routes)

| main.py command | Used by UI at | Description |
|-----------------|--------------|-------------|
| `system_readiness_report` | `GET /api` → command | Full readiness evaluation + history append |
| `system_readiness_history` | `GET /api` → command | KV history entries (latest N) |

Both were pre-existing dispatcher commands. No new routes added.

---

## Database Changes

**No new tables.** Readiness history is appended to the Phase 20 KV store under key `system_readiness_history` (capped at 500 compact entries). The KV store (`phase20_store`) pre-existed.

---

## Test Results

| Suite | File | Tests | Result |
|-------|------|-------|--------|
| Python unit | `test_phase27f_system_readiness.py` | **68** | ✅ 68/68 passed (0.13s) |
| Frontend (Vitest) | `SystemReadiness.test.tsx` | **15** | ✅ 15/15 passed (4.95s) |

### Python test coverage
- `TestDeriveOverall` (8): READY, BLOCKED, UNKNOWN (blocking), UNKNOWN not READY, non-blocking BLOCKED→WARNING, non-blocking WARNING, BLOCKED beats UNKNOWN, empty→READY
- `TestCheckMarketData` (5): fresh→READY, stale→WARNING, missing ts→UNKNOWN, no meta→UNKNOWN (blocking), missing ts empty string→UNKNOWN
- `TestCheckBroker` (6): CONNECTED→READY, LOGIN_REQUIRED→WARNING, API_ERROR→WARNING, None→UNKNOWN, non-blocking verification (×2)
- `TestCheckPipeline` (4): SUCCESS→READY, 0 events→WARNING, meta None→UNKNOWN, positive events→READY
- `TestCheckSafety` (6): paper+no-live→READY, LIVE_EXECUTION_ENABLED=true→BLOCKED, AUTO_EXECUTION_ENABLED_set→BLOCKED, env_flags None→UNKNOWN, paper_mode=None→UNKNOWN (not READY), paper_mode=False→BLOCKED
- `TestCheckScheduling` (5): HEALTHY→READY, DISABLED→WARNING, DOWN+open→BLOCKED, DOWN+closed→WARNING, UNKNOWN health
- `TestCheckConfiguration` (3): all present→READY, DATABASE_URL missing→BLOCKED, SESSION_SECRET missing→BLOCKED
- `TestMissingTelemetryNotReady` (3): None scan_meta, None env_flags, None scheduler — all produce non-READY
- `TestExecutionModeValidation` (3): LIVE_EXECUTION_ENABLED=true→BLOCKED+blocking, LIVE_ORDERS_ENABLED_set→BLOCKED, paper+no-live→READY
- `TestBuildReportOverall` (4): healthy inputs→not BLOCKED, live execution→BLOCKED overall, all required fields, counts sum
- `TestGetHistory` (5): empty KV, None KV, 3 entries reversed, limit respected, exception→ok+error
- `TestCheckStrategyRisk` (2), `TestCheckExecution` (2), `TestCheckPortfolio` (4), `TestCheckPersistenceRecovery` (5), `TestBuildFreshness` (3)

### Frontend test coverage
15 tests: heading, loading state, READY banner, BLOCKED banner, domain card render, check row render, evidence JSON expand on click, BLOCKING badge, remediation text, FreshnessCard columns, HistoryCard empty, HistoryCard 2 entries, source-errors banner, run-check button, error state.

---

## UI Route

`/system-readiness` — registered in `App.tsx:207` and `AgentConfig.ts:226` (Operations Agent group).

### Page layout
- **Top:** Overall readiness banner (READY/WARNING/BLOCKED/UNKNOWN) with counts and "Run readiness check" button
- **Source errors** section (shown if any source could not be read)
- **Domain grid** (2 columns): Market & Data, Broker & Authentication, Pipeline, Strategy & Risk, Execution, Portfolio, Persistence & Recovery, Scheduling, Safety Controls, Configuration
- **Lower grid** (2 columns): Data Freshness table + Check History

Each check row shows: status dot + badge, label, BLOCKING indicator, expected, actual, remediation, and collapsible evidence JSON.

---

## Known Limitations

| Limitation | Impact |
|------------|--------|
| Broker check is non-blocking (paper trading never requires Kite) | Expected — warning shown but never prevents READY |
| `recovery_latest=None` → UNKNOWN (not BLOCKED) | Expected — no recovery run yet is non-fatal for first startup |
| Scheduler heartbeat budget only enforced during market hours | By design — heartbeat staleness is irrelevant off-session |
| Readiness history capped at 500 compact entries | By design — uses existing KV infrastructure without a new table |
| `collect_inputs()` uses Kite cached probe (60s TTL) — not a live Kite API call | By design — readiness polling must never hammer the Kite API |

---

## Duplicate-Source Audit

**No duplicate health checks.** Phase 27F:
- **Never imports `readiness_checker.py`** (Phase 8 broker module) — this is enforced by the module docstring and verified by grep
- Delegates broker state to `kite_session_manager` only
- Delegates portfolio health to `portfolio_snapshot.get_portfolio_health(emit_alerts=False)` only
- Delegates system resources to `observability_center.system_health.*` only
- Does not re-implement any checker already in Phase 8.1–8.8 centers

---

## Safety Verification

- `LIVE_EXECUTION_ENABLED="true"` → execution_mode check = **BLOCKED** (blocking) → overall = **BLOCKED**
- `config.PAPER_TRADING_MODE = None` (unreadable) → **UNKNOWN** (blocking) — never assumed safe
- `config.PAPER_TRADING_MODE = False` → **BLOCKED** (blocking)
- `paper_mode=True` + live flags off → **READY** — positive paper-mode verification required
- `emit_alerts=False` passed to `get_portfolio_health()` — readiness poll never writes notifications
- No `INSERT`/`UPDATE`/`DELETE` executed by this module except the compact KV history append (fail-soft, capped)
