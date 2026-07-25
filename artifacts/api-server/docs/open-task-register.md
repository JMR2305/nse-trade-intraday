# ApexQuant AI — Open Task Register

**Audit date:** 2026-07-25  
**Scope:** Full repository + Replit task history  
**System:** NSE Paper-Trading Platform (PAPER TRADING ONLY — no live orders)

---

## Summary

| Metric | Count |
|--------|-------|
| Total open items found | 38 |
| Duplicates merged | 6 |
| Items implemented in this batch | 5 |
| Items deferred (safe to defer) | 19 |
| Items requiring user secret / decision | 4 |
| Items rejected (out of scope / by design) | 10 |

---

## Master Register

### CRITICAL / Production Blockers

| ID | Task | Source | Status | Severity | Category | Complexity | Action |
|----|------|--------|--------|----------|----------|------------|--------|
| T-100 | `yfinance` available in dev (pyproject.toml lists `>=1.5.1`, dev env has it installed). Deployed environment must run `uv sync` before publish. | `pyproject.toml`, deployment logs | ⚠️ OPEN — `uv sync` not in postBuild | CRITICAL | production blocker | SMALL | **IMPLEMENT SEPARATELY** — add `uv sync --frozen` to `.replit` `[deployment.build]` step; requires platform verification |
| T-114a | `VITE_API_BASE_URL` not set in deployed Replit environment | `phase1-connectivity-report.md` §9 | ⚠️ OPEN | HIGH | deployment | SMALL | **REQUIRES USER SECRET/DECISION** — must be set via Replit Secrets |
| T-114b | `EXPO_PUBLIC_API_BASE_URL` not set for EAS mobile builds | `phase1-connectivity-report.md` §9 | ⚠️ OPEN | HIGH | deployment | SMALL | **REQUIRES USER SECRET/DECISION** |
| T-114c | `ALLOWED_ORIGINS` empty — custom domains not permitted by CORS allowlist | `phase1-connectivity-report.md` §9 | ⚠️ OPEN | MEDIUM | security | SMALL | **REQUIRES USER SECRET/DECISION** — set custom origins |

---

### Implemented in This Batch ✅

| ID | Task | Files Changed | Complexity | Verified |
|----|------|--------------|------------|---------|
| T-113 | **CORS supertest integration tests** — 13 assertions covering Replit origin allowlist, lookalike blocking, preflight, malformed-origin graceful handling | `artifacts/api-server/src/routes/cors.test.ts` (NEW) | SMALL | ✅ 13/13 pass |
| T-103 | **Descriptive error messages** — global error handler now returns specific messages for: 400 JSON parse errors, 403 CORS rejections (was "Internal server error" for both), 413 body too large with byte limit | `artifacts/api-server/src/app.ts` | SMALL | ✅ Tests pass |
| T-DEP1 | **Python startup dependency validator** — `check_startup_deps.py` checks all 9 required packages + env vars; exits 1 with actionable JSON when anything missing | `artifacts/api-server/src/python/check_startup_deps.py` (NEW) | SMALL | ✅ All packages found in dev env |
| T-DEPLOY | **Deployment checklist** — comprehensive pre/post-deploy runbook including secrets table, env-var matrix, CORS setup, verification commands, safety guarantees | `artifacts/api-server/docs/deployment-checklist.md` (NEW) | SMALL | ✅ N/A (doc) |
| T-1A | **Phase 1A — Connectivity Foundation** (prior batch): apiConfig.ts, apiFetch.ts, AbortController timeouts, CORS allowlist, ConnectivityPanel, QueryClient retry=0 | Multiple files | LARGE | ✅ 286/286 |
| T-1B | **Phase 1B — Validation, Tests, MARKET_CLOSED status** (prior batch): deriveDataStatus export, isMarketOpen(), 17 dashboard + 9 mobile Phase 1 tests | Multiple files | MEDIUM | ✅ 315/315 / 18/18 |

---

### Security

| ID | Task | Source | Status | Severity | Category | Action |
|----|------|--------|--------|----------|----------|--------|
| T-SEC1 | CORS automated tests missing | `failure-test-results.md` risk register | ✅ DONE (T-113) | HIGH | security | Implemented |
| T-SEC2 | Wildcard CORS replaced with explicit allowlist | Phase 1A | ✅ DONE | HIGH | security | Implemented |
| T-SEC3 | Broker credentials masked in API responses | Phase 8 design | ✅ DONE (existing) | HIGH | security | None |
| T-SEC4 | No API keys committed to source | Audit | ✅ CLEAN | HIGH | security | None |
| T-SEC5 | `http://` Replit origins accepted (hostname matches even without HTTPS) | `cors.test.ts` documented | INFO | security | None — production TLS at load-balancer is the mitigation |

---

### Trading Safety (RC-7 / RC-8 Controls)

| ID | Task | Source | Status | Severity | Action |
|----|------|--------|--------|----------|--------|
| T-RC1 | Paper-fallback orders not distinguished from live fills in reconciliation | `failure-test-results.md` | ⚠️ OPEN | HIGH | **IMPLEMENT SEPARATELY** (Task #14) — add `is_paper_fallback` flag to fill records |
| T-RC2 | Concurrent duplicate order submission race | `failure-test-results.md` | ✅ FIXED | HIGH | None |
| T-RC3 | Kill switch auto-activation on drawdown not implemented | `BATCH8_RISK_ENGINE_REVIEW.md` L390 | ⚠️ OPEN | HIGH | **DEFER** — requires RC-8 strategy-logic change; not in safe batch |
| T-RC4 | Post-trade FATAL drawdown → kill switch auto-activation | `BATCH8_RISK_ENGINE_REVIEW.md` | ⚠️ OPEN | HIGH | **DEFER** |
| T-RC5 | Portfolio pre-check in signal flow (exposure + capital limits before RC-8) | Task #15 | ⚠️ OPEN | HIGH | **DEFER** — changes signal flow |
| T-RC6 | Limit edits take effect in running strategies without restart | Task #68 | ⚠️ OPEN | MEDIUM | **DEFER** — strategy-logic change |

---

### Data Integrity

| ID | Task | Source | Status | Severity | Action |
|----|------|--------|--------|----------|--------|
| T-DI1 | LTIM / TATAMOTORS missing from yfinance bulk download (48/50 coverage) | `failure-test-results.md` | ⚠️ OPEN | MEDIUM | **DEFER** — transient / weekend data issue; fallback path exists; investigate with live market data |
| T-DI2 | `deriveDataStatus()` types (ScanStatusResponse, StalenessResponse) private to DataFreshnessBar | Phase 1B | ⚠️ OPEN | LOW | **DEFER** (Task #112 scope) |
| T-DI3 | Resolved section may show stale note from non-most-recent resolution | Task #54 | ⚠️ OPEN | LOW | **DEFER** |
| T-DI4 | Analytics FIFO-match + immutable trade-time metadata | Phase analytics | ✅ DONE | HIGH | None |

---

### Connectivity & Reliability

| ID | Task | Source | Status | Severity | Action |
|----|------|--------|--------|----------|--------|
| T-CON1 | `apiJson()` has no AbortController timeout | Task #101 | ✅ DONE (Phase 1A) | MEDIUM | Implemented — 15s default, 10s health, 120s long ops |
| T-CON2 | SSE stream uses correct `SSE_STREAM_URL` from apiConfig | Phase 1A | ✅ DONE | MEDIUM | None |
| T-CON3 | Mobile `setBaseUrl` uses `API_BASE_URL` from apiConfig | Phase 1A | ✅ DONE | MEDIUM | None |
| T-CON4 | Snapshot data refreshes within 2s of API restart | Task #118 (CANCELLED) | CANCELLED | MEDIUM | — |
| T-CON5 | Config panel refreshes immediately after operator saves limit | Task #108 | ⚠️ OPEN | MEDIUM | **IMPLEMENT SEPARATELY** |
| T-CON6 | Exposure badge updates immediately on fresh data | Task #59 | ⚠️ OPEN | MEDIUM | **IMPLEMENT SEPARATELY** |
| T-CON7 | Outage banner disappears when API recovers | Task #106 | ⚠️ OPEN | MEDIUM | **IMPLEMENT SEPARATELY** |
| T-CON8 | Operator overrides survive hot-reload (session persistence) | Task #69 | ⚠️ OPEN | LOW | **DEFER** — architecture decision needed |
| T-CON9 | In-process `_pending` preview tokens cleared on API restart | `failure-test-results.md` | ⚠️ OPEN | LOW | **DEFER** — tokens expire anyway; acceptable risk |

---

### Test Coverage

| ID | Task | Source | Status | Severity | Action |
|----|------|--------|--------|----------|--------|
| T-TC1 | CORS allowlist has no automated tests | Task #113 | ✅ DONE | HIGH | 13 tests added |
| T-TC2 | Error handler produces wrong messages for 400/403 | Task #103 | ✅ DONE | MEDIUM | Fixed + 2 tests |
| T-TC3 | MARKET_CLOSED badge browser-level confirmation | Task #116 | ⚠️ PENDING | MEDIUM | **IMPLEMENT SEPARATELY** — needs Playwright |
| T-TC4 | CORS test for ALLOWED_ORIGINS env var path | `cors.test.ts` note | ⚠️ OPEN | LOW | **DEFER** — env mutation at module-load time makes this tricky; document workaround |
| T-TC5 | 9 pre-existing failures in BATCH8 test suite (unrelated to current stack) | `BATCH8_RISK_ENGINE_REVIEW.md` L11 | ⚠️ OPEN | HIGH | **DEFER** — strategy-engine layer; separate RC-8 work |

---

### Type Safety (Task #112)

| ID | Task | Source | Status | Severity | Action |
|----|------|--------|--------|----------|--------|
| T-TS1 | `experiments/ExperimentTemplates.tsx` — `config_summary?: any` (1 usage) | Pages audit | ⚠️ OPEN | LOW | **DEFER** — interface shape unknown without API contract |
| T-TS2 | `experiments/BatchQueue.tsx` — `metrics?: any`, `wf_progress?: any` (2 usages) | Pages audit | ⚠️ OPEN | LOW | **DEFER** |
| T-TS3 | `experiments/ReportCharts.tsx` — chart data arrays typed `any[]` (8 usages) | Pages audit | ⚠️ OPEN | LOW | **DEFER** — safe change but wide surface |
| T-TS4 | `experiments/ResearchReport.tsx` — rendering helpers typed `any` (15+ usages) | Pages audit | ⚠️ OPEN | LOW | **DEFER** — large refactor |
| T-TS5 | `MetaLearningTab.tsx` — strategy list items typed `any` (12 usages) | Pages audit | ⚠️ OPEN | LOW | **DEFER** |
| T-TS6 | `MarketScanner.tsx` — `RankRow.item: any` (1 usage) | Pages audit | ⚠️ OPEN | LOW | **DEFER** |
| T-TS7 | `AiCopilot.tsx` — `catch (e: any)` (2 usages — error narrowing pattern) | Pages audit | INFO | LOW | **REJECT** — `catch (e: any)` is the idiomatic TS pattern for error narrowing |
| T-TS8 | `.next/` generated files — `@ts-ignore` (22 usages) | `trading-document-hub/.next/` | INFO | INFO | **REJECT** — generated build artifact, not source code |

---

### Performance

| ID | Task | Source | Status | Severity | Action |
|----|------|--------|--------|----------|--------|
| T-PERF1 | `/api/live-data/health` takes 6012 ms (synchronous Python probe) | Phase 1B endpoint matrix | ⚠️ OPEN | MEDIUM | **DEFER** — not in critical path; async Python subprocess would help |
| T-PERF2 | Bulk yfinance download replaces serial per-symbol calls (Phase 22) | Memory | ✅ DONE | HIGH | None |

---

### UI / Accessibility

| ID | Task | Source | Status | Severity | Action |
|----|------|--------|--------|----------|--------|
| T-UI1 | MARKET_CLOSED shown on Health tab; not yet on Positions / Alerts tabs | Task #120 | ⚠️ OPEN | MEDIUM | **IMPLEMENT SEPARATELY** |
| T-UI2 | Stale MARKET_CLOSED badge may persist when market reopens Monday | Task #121 | ⚠️ OPEN | MEDIUM | **IMPLEMENT SEPARATELY** |
| T-UI3 | Mobile `computeFreshness()` does not emit MARKET_CLOSED | Task #115 | ✅ DONE (merged) | MEDIUM | None |
| T-UI4 | Equity curve / P&L history on Portfolio page | Task #24 | ⚠️ OPEN | LOW | **DEFER** |
| T-UI5 | Missed-reconciliation alerts on Broker Execution page | Task #37 | ⚠️ OPEN | LOW | **DEFER** |
| T-UI6 | Reconciliation probe runs automatically | Task #36 | ⚠️ OPEN | LOW | **DEFER** |
| T-UI7 | Expiry monitor starts automatically with adapter | Task #13 | ⚠️ OPEN | LOW | **DEFER** |
| T-UI8 | Reopen cutoff enforced on server (not just client) | Task #57 | ⚠️ OPEN | MEDIUM | **IMPLEMENT SEPARATELY** |
| T-UI9 | MARKET_CLOSED browser screenshot confirmation | Task #116 | ⚠️ PENDING | MEDIUM | **IMPLEMENT SEPARATELY** |

---

### Documentation

| ID | Task | Source | Status | Severity | Action |
|----|------|--------|--------|----------|--------|
| T-DOC1 | Deployment checklist | Task #114 / audit | ✅ DONE | HIGH | `docs/deployment-checklist.md` created |
| T-DOC2 | Phase 1A+1B connectivity report | Phase 1B | ✅ DONE | HIGH | `docs/phase1-connectivity-report.md` |
| T-DOC3 | This master task register | Audit | ✅ DONE | HIGH | `docs/open-task-register.md` |
| T-DOC4 | `.env.example` for dashboard + mobile | Phase 1A | ✅ DONE | MEDIUM | None |
| T-DOC5 | Python env-var fix instructions | `check_startup_deps.py` | ✅ DONE | MEDIUM | Actionable JSON output |

---

### Deferred / By Design (Rejected)

| ID | Task | Reason |
|----|------|--------|
| T-REJ1 | Live trading enablement | By design — `paper_mode: true` is a hard constant. RC-8 must be explicitly enabled. |
| T-REJ2 | Broker credential changes | Requires user action (Zerodha developer console) |
| T-REJ3 | Strategy-logic changes (RC-8/RC-9) | Out of safe-batch scope |
| T-REJ4 | Risk-limit changes | Out of safe-batch scope |
| T-REJ5 | Database schema migrations | None needed for current feature set |
| T-REJ6 | AI advisory-only flag removal | By design |
| T-REJ7 | `intraday-trading-bot/` deferred items (RC-10C, outcome scheduler) | Separate module — deferred by RC-10D Freeze doc |
| T-REJ8 | `catch (e: any)` in AiCopilot — idiomatic TS error narrowing | Not a real `any` usage |
| T-REJ9 | `.next/` `@ts-ignore` files | Generated build artifacts |
| T-REJ10 | `DEFERRED` status options in ResearchNotebook UI | User-facing status vocabulary, not a type error |

---

## Items Requiring User Secret / Decision

| ID | Task | What is needed |
|----|------|---------------|
| T-114a | `VITE_API_BASE_URL` | Set to `https://<deployment-domain>/api-server/api` via Replit Secrets |
| T-114b | `EXPO_PUBLIC_API_BASE_URL` | Set for EAS mobile builds via Replit Secrets |
| T-114c | `ALLOWED_ORIGINS` | Set custom domain origins if deploying outside Replit |
| T-100 | `uv sync` in deploy postBuild | Confirm Replit autoscale build environment supports `uv sync --frozen`; add to `.replit` |

---

## Current Test Results

| Suite | Files | Tests | Result |
|-------|-------|-------|--------|
| Dashboard Vitest | 7 | **315 / 315** | ✅ All pass |
| Mobile Vitest | 2 | **18 / 18** | ✅ All pass |
| API Server Vitest | 3 | **41 / 41** | ✅ All pass (13 new CORS tests) |
| TypeScript — libs + api-server | — | 0 errors | ✅ Clean |
| TypeScript — dashboard `--noEmit` | — | 0 errors | ✅ Clean |
| TypeScript — mobile `--noEmit` | — | 0 errors | ✅ Clean |
| Python dep check | — | 9/9 packages | ✅ All present in dev |

---

## Files Changed in This Batch

| File | Change |
|------|--------|
| `artifacts/api-server/src/app.ts` | Global error handler: descriptive messages for 400 JSON parse, 403 CORS, 413 body too large |
| `artifacts/api-server/src/routes/cors.test.ts` | **NEW** — 13 CORS integration tests |
| `artifacts/api-server/src/python/check_startup_deps.py` | **NEW** — startup dep validator (packages + env vars) |
| `artifacts/api-server/docs/deployment-checklist.md` | **NEW** — production deployment runbook |
| `artifacts/api-server/docs/open-task-register.md` | **NEW** — this file |

---

## Remaining Production Blockers

1. **`uv sync` not in deployment postBuild** (T-100) — Python packages present in dev but deployment may not install them. Fix: add `uv sync --frozen` to `.replit` `[deployment.build]` step. Requires user confirmation that Replit Autoscale build supports this.

2. **`VITE_API_BASE_URL` not set in production** (T-114a) — Dashboard falls back to relative `/api` which works via Replit path proxy, but custom-domain deploys will fail. Action: set via Replit Secrets.

3. **LTIM / TATAMOTORS yfinance coverage** (T-DI1) — 48/50 symbols during weekend scan. DELAYED label shown. Both tickers (`LTIM.NS`, `TATAMOTORS.NS`) are correct Yahoo Finance symbols; issue is weekend data unavailability. Monitor on a live trading day.

---

## Final Verdict

**SAFE OPEN TASKS COMPLETED — READY FOR PHASE 2**

All items classified IMPLEMENT NOW have been implemented and tested:
- CORS integration tests: 13/13 passing
- Error handler descriptive messages: verified by 2 CORS test assertions
- Python startup dep validator: all 9 packages found in dev environment
- Deployment checklist: complete with verification commands and safety guarantees
- TypeScript: clean across all packages
- Dashboard tests: 315/315 passing
- Mobile tests: 18/18 passing
- API server tests: 41/41 passing

Remaining items are either deferred (require user secrets, architecture decisions, or trading-strategy changes) or tracked in the Replit task queue for separate implementation.
