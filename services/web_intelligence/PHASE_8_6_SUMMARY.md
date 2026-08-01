# Phase 8.6 — Security & Compliance Centre
## ApexQuant AI · Build Summary

---

## Objective

Build a comprehensive **read-only / advisory-only** Security & Compliance Centre that continuously audits platform security, configuration, authentication, secrets, APIs and compliance posture. It monitors, validates, scores and reports — never modifies.

**Hard constraint:** The module MUST NEVER:
- Modify secrets or rotate credentials
- Disable users or modify feature flags
- Modify configuration or restart services
- Place orders, modify portfolio, or execute trades

Every API response carries `advisory_only: true` and `read_only: true`.

---

## Feature Flag

| Variable | Values accepted | Default |
|---|---|---|
| `SECURITY_CENTER_ENABLED` | `true`, `1`, `yes` | `false` (disabled) |

When the flag is off every endpoint returns `{ "status": "DISABLED", "available": false }`.

---

## Files Delivered

### Python Module — `artifacts/api-server/src/python/security_center/`

| File | Purpose |
|---|---|
| `__init__.py` | Package marker with advisory-only enforcement docstring |
| `models.py` | Feature-flag helpers, grade/risk-level functions, status constants, `REQUIRED_SECRETS` (4 secrets), `REQUIRED_CONFIG` (7 keys), `KNOWN_VULNERABLE_PACKAGES` (5 CVEs), `WEAK_SECRET_INDICATORS`, dataclasses (`SecAlert`, `SecretCheck`, `ConfigCheck`) |
| `shared_services.py` | Full audit engine — secret presence checks, session validation, auth checks, config audit, API security checks, dependency audit, audit log builder, compliance scoring, alert aggregation, export helpers. Exposes `get_security_snapshot()` as stable downstream interface |
| `api.py` | 13 CLI command functions dispatched by `main.py` |
| `test_security_center.py` | 76-test suite (all passing) |

### Express Route — `artifacts/api-server/src/routes/security.ts`

Inline `runPython` pattern (consistent with all prior phases). Registers 12 routes:

```
GET /api/security/summary
GET /api/security/auth
GET /api/security/sessions
GET /api/security/secrets
GET /api/security/config
GET /api/security/api
GET /api/security/dependencies
GET /api/security/audit
GET /api/security/compliance
GET /api/security/alerts
GET /api/security/snapshot
GET /api/security/export          (?format=json|csv)
```

### React Page — `artifacts/trading-dashboard/src/pages/SecurityCenter.tsx`

11-tab dashboard at `/security-center`, registered in the **Operations** nav group as **Security & Compliance**:

| Tab | Data source | Refresh |
|---|---|---|
| **Overview** | `/security/summary` | 20 s |
| **Authentication** | `/security/auth` | 20 s |
| **Sessions** | `/security/sessions` | 20 s |
| **Secrets** | `/security/secrets` | 60 s |
| **Configuration** | `/security/config` | 60 s |
| **API Security** | `/security/api` | 30 s |
| **Dependencies** | `/security/dependencies` | 120 s |
| **Audit Log** | `/security/audit` | 30 s |
| **Compliance** | `/security/compliance` | 60 s |
| **Alerts** | `/security/alerts` | 15 s |
| **Export** | Client-side fetch on demand | — |

### Wiring Changes

| File | Change |
|---|---|
| `artifacts/api-server/src/routes/index.ts` | Import + `router.use(securityRouter)` |
| `artifacts/api-server/src/python/main.py` | 13 `sec_*` command dispatchers (after Phase 8.5 block) |
| `artifacts/trading-dashboard/src/App.tsx` | Import `SecurityCenter` + `<Route path="/security-center">` |
| `artifacts/trading-dashboard/src/components/layout/AppLayout.tsx` | Nav entry **Security & Compliance** under Operations group |

---

## Architecture

### Security Score — Compliance Formula (Summary endpoint)

```
security_score = secrets_score  × 0.30
               + session_score  × 0.20
               + config_score   × 0.20
               + api_score      × 0.15
               + dep_score      × 0.15
```

### Snapshot Interface Formula (lightweight — no dep audit)

```
security_score = secrets_score  × 0.35
               + session_score  × 0.25
               + config_score   × 0.25
               + api_score      × 0.15
```

### Grade Mapping

| Grade | Score |
|---|---|
| A+ | ≥ 92 |
| A  | ≥ 80 |
| B  | ≥ 68 |
| C  | ≥ 50 |
| D  | < 50 |

### Risk Level

| Level | Score range |
|---|---|
| LOW      | ≥ 80 |
| MEDIUM   | ≥ 60 |
| HIGH     | ≥ 40 |
| CRITICAL | < 40 |

### Security Status

| Condition | Status |
|---|---|
| Score ≥ 80, 0 critical alerts | `SECURE` |
| Score ≥ 50 or critical ≤ 2 | `DEGRADED` |
| Otherwise | `AT_RISK` |

---

## Security Methodology

### 1 — Secret Validation (Presence Only)

**Principle:** Never expose, log, store, or transmit secret values.

Checks performed per secret:
1. **Presence** — is the env var set?
2. **Minimum length** — does it meet the configured minimum (32 chars for SESSION_SECRET)?
3. **Known-weak patterns** — does it match a name-indexed list of common insecure defaults?

Result per secret: `PRESENT` / `MISSING` / `WEAK`.

Secrets audited:
| Secret | Category | Critical | Min Length |
|---|---|---|---|
| `SESSION_SECRET` | authentication | Yes | 32 |
| `ZERODHA_API_KEY` | broker | No | 8 |
| `ZERODHA_API_SECRET` | broker | No | 8 |
| `DATABASE_URL` | database | Yes | 10 |

### 2 — Session Validation

- SESSION_SECRET presence and strength (≥ 32 chars)
- Kite token presence and structural validity (access_token + login_time)
- Never exposes token values

### 3 — Authentication Check

- Zerodha live mode detection via `ZERODHA_ENABLED` flag
- API key / secret presence validation (conditional on live mode)
- API and DB status from Observability Center snapshot (no new probes)

### 4 — Configuration Audit

Checks 7 required environment variables/flags for presence and valid values. Reports `OK` / `MISSING` / `INVALID` per item.

### 5 — API Security Check

8 security properties validated read-only:
- HTTPS enforcement (via Replit proxy detection)
- SESSION_SECRET presence (session signing)
- CORS policy strictness (production vs. development)
- API availability (from observability snapshot)
- NODE_ENV correctness
- Rate limiting (Replit platform layer)
- Input validation (Zod schema active)
- Authentication middleware presence

### 6 — Dependency Audit

- Runs `pip list --format=json` (subprocess, 15s timeout, read-only)
- Checks against 5 known-vulnerable package patterns with CVE references
- Node package count from workspace `package.json` (read-only)
- **Never auto-updates** — advisory output only
- Score: 100 − (advisory_count × 10), floor 0

### 7 — Audit Log

Aggregates platform events from:
- `phase20_store.list_scan_runs()` — scheduler scan history
- `phase20_store.list_notifications()` — system notifications
- Security Centre audit execution event
- Sorted chronological descending, capped at 50 events

### 8 — Alert Aggregation

Collects alerts from all 6 sub-modules (secrets, sessions, auth, config, API, dependencies), normalised to a common schema with `severity`, `category`, `title`, `detail`, and `advisory_only: true`.

---

## Upstream Modules Reused

All calls wrapped in `_safe(fn, default)` — upstream failures never propagate to operators.

| Module | Usage |
|---|---|
| `observability_center.shared_services` | API/DB status, system health (no new probes) |
| `operations_center.shared_services` | `get_operations_snapshot()` for platform context |
| `phase20_store` | `list_scan_runs()`, `list_notifications()` for audit log |
| `kite_token_store` | Token presence / structural validation (no value exposure) |

---

## Test Coverage

**76 / 76 tests — all passing (0.24 s)**

| Test Class | Tests | Coverage |
|---|---|---|
| `TestFeatureFlag` | 5 | Flag gate, all endpoints disabled when off |
| `TestSecretValidation` | 8 | Presence, missing, weak, value never in output |
| `TestSessionValidation` | 5 | Present/strong/missing/weak, advisory flag |
| `TestAuthCheck` | 4 | Keys, Zerodha-mode alert, no-live-mode OK |
| `TestConfigAudit` | 5 | All required keys, score range, advisory flag |
| `TestApiSecurity` | 5 | Checks list, score, missing-secret → CRITICAL |
| `TestDependencyAudit` | 5 | Advisory only, alert generation, score decay, version compare |
| `TestAlertAggregation` | 5 | Keys, counts consistent, critical from bad secrets |
| `TestComplianceScore` | 6 | Keys, score range, grade, risk level, advisory, score decay |
| `TestSummary` | 4 | Required keys, advisory flag, grade/status valid |
| `TestAuditLog` | 4 | Keys, platform event present, scan run events |
| `TestExport` | 4 | JSON keys, advisory flag, CSV format, CSV header |
| `TestSnapshot` | 3 | Keys, available, advisory_only + read_only |
| `TestApiCommands` | 2 | All 13 commands return dicts, snapshot available |
| `TestGradeHelpers` | 11 | All grades, all risk levels, REQUIRED_ structures |

---

## Downstream Interface

Stable API for Phase 8.7 (Performance Optimisation) and Phase 8.8 (Deployment & Disaster Recovery):

```python
from security_center.shared_services import get_security_snapshot

snap = get_security_snapshot()
# Returns (lightweight — no dependency audit):
# {
#   "available": True,
#   "advisory_only": True,
#   "read_only": True,
#   "security_score": float,
#   "grade": "A+" | "A" | "B" | "C" | "D",
#   "risk_level": "LOW" | "MEDIUM" | "HIGH" | "CRITICAL",
#   "missing_secrets": int,
#   "weak_secrets": int,
#   "config_issues": int,
#   "generated_at": ISO-8601 str,
# }
```

---

## GitHub-Inspired Enhancements

Inspired by security posture patterns from reviewed projects (without copying implementations):

| Enhancement | Implementation |
|---|---|
| **Security posture scoring** | 5-domain weighted compliance score (secrets 30%, session 20%, config 20%, API 15%, deps 15%) |
| **Secret strength validation** | Minimum-length checks + known-weak-default pattern matching by name |
| **Session monitoring** | SESSION_SECRET strength + Kite token structural validity |
| **Configuration auditing** | 7 required env vars with expected-value enforcement |
| **Dependency health reporting** | CVE-pattern checks against 5 known-vulnerable packages with upgrade guidance |
| **Compliance dashboard** | Colour-coded grade (A+/A/B/C/D) with risk level (LOW/MEDIUM/HIGH/CRITICAL) |

---

## Known Limitations

| Limitation | Reason |
|---|---|
| Dependency CVE list is static (5 packages) | Dynamic CVE database integration requires external API (future: OSV/NVD integration) |
| HTTPS check is environment-inferred | Direct TLS probe would require network access; Replit proxy provides TLS transparently |
| Kite token validation is structural only | Full validity requires a live Zerodha API probe (done in Phase 8.1 / Phase 19A) |
| Audit log is derived, not ledger-based | Dedicated immutable audit ledger is a Phase 9+ concern |
| Rate-limiting marked INFO | Rate limiting is at Replit proxy layer, not inspectable from application code |

---

## Deployment Checklist

- [x] `SECURITY_CENTER_ENABLED=true` set in environment
- [x] API server restarted — build + start confirmed clean
- [x] `/api/security/summary` responding 200
- [x] Dashboard nav entry **Security & Compliance** visible under Operations group
- [x] 11 tabs render; disabled state shows setup prompt when flag is off
- [x] Secrets tab shows presence-only (no secret values exposed anywhere)
- [x] Export tab generates advisory-only CSV/JSON (no secret values)
- [x] 76/76 unit tests passing

---

## PHASE 8.6 COMPLETE

All deliverables provided:

1. ✅ **Files created** — 5 Python module files, 1 Express route, 1 React page
2. ✅ **Files modified** — `routes/index.ts`, `main.py`, `App.tsx`, `AppLayout.tsx`
3. ✅ **Shared services reused** — Observability, Operations, Phase 20 store, Kite token store
4. ✅ **APIs** — 12 GET endpoints under `/api/security/*`
5. ✅ **Dashboard** — 11-tab React page at `/security-center`
6. ✅ **Test count** — 76 tests
7. ✅ **Test results** — 76/76 passing (0.24 s)
8. ✅ **Security methodology** — 8-domain validation with secret-value-never-exposed guarantee
9. ✅ **Known limitations** — documented above
10. ✅ **GitHub-inspired enhancements** — 6 patterns applied
11. ✅ **Future integration** — `get_security_snapshot()` stable interface ready for Phase 8.7 / 8.8
12. ✅ **READ-ONLY and ADVISORY-ONLY** — confirmed; `advisory_only: true` + `read_only: true` in every response; no write paths exist anywhere in the module

*Phase 8.6 complete — READ-ONLY · ADVISORY-ONLY*
