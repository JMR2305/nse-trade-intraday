---
name: Phase 8.6 Security & Compliance Centre
description: Architecture, score formula, secret-validation rules, and READ-ONLY enforcement for Phase 8.6.
---

## Hard rule — secret values
NEVER return, log, store, or include actual secret values in any response. Only check presence (env var set?) and minimum length (len >= min_length). Use `PRESENCE_PRESENT / MISSING / WEAK` enum. The detail field must never contain the actual value.

## Feature flag
`SECURITY_CENTER_ENABLED=true` (supports "1", "true", "yes").

## Compliance score formula (full — with dep audit)
```
overall = secrets×0.30 + session×0.20 + config×0.20 + api×0.15 + deps×0.15
```

## Snapshot interface formula (lightweight — no dep audit, for downstream use)
```
security_score = secrets×0.35 + session×0.25 + config×0.25 + api×0.15
```

## Risk levels
LOW ≥ 80, MEDIUM ≥ 60, HIGH ≥ 40, CRITICAL < 40.

## Security status
SECURE if score ≥ 80 and 0 critical alerts; DEGRADED if score ≥ 50 or critical ≤ 2; AT_RISK otherwise.

## Commands (main.py sec_* dispatch)
13 commands: sec_summary, sec_auth, sec_sessions, sec_secrets, sec_config, sec_api, sec_dependencies, sec_audit, sec_compliance, sec_alerts, sec_snapshot, sec_export_json, sec_export_csv.

## Upstream used (read-only, _safe wrapped)
observability_center, operations_center, phase20_store (scan_runs + notifications), kite_token_store (structural check only, no value).

## Dep audit
subprocess `pip list --format=json` with 15s timeout. 5 known-CVE package patterns. NEVER auto-updates.

## Tests
76/76 passing. Weak-secret test uses 34-char string to pass the 32-char threshold.

**Why:** SECRET_CENTER_ENABLED must be READ-ONLY at every level. Any future phase consuming security data must use get_security_snapshot() only.
