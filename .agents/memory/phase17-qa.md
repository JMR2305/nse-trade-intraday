---
name: Phase 17 QA engine
description: Automated QA/release-validation engine conventions — suite parsing, gating policy, honesty rules
---

## Test suite output formats
Rule: any runner that aggregates the Python test suites must parse two formats:
newer suites print `N passed, N failed`; older suites (Phases 7 and 8) print
per-check `[PASS]`/`[FAIL]` lines and end with `ALL TESTS PASSED` (exit code 0/1).
**Why:** the first Phase 17 run reported 0/0 for suites 7 and 8 because only the
newer format was parsed, silently downgrading them to warnings.
**How to apply:** count `[PASS]`/`[FAIL]` markers as fallback and trust exit code.

## Release gating policy
Rule: checklist items are FAIL with any failed check, WARN with any warning,
PASS only when everything passed. `production_ready` is strict (all PASS);
readiness string is READY / READY WITH WARNINGS / NOT READY.
**Why:** architect review failed the first implementation for marking sections
with open warnings as PASS and "Production Ready", contradicting the honesty rules.
**How to apply:** never derive readiness from `failed == 0` alone.

## Honesty conventions
Client-side UI behaviour, auth and rate limits are disclosed under
`not_checkable` (auth/rate limits don't exist by design). Legacy trades missing
scan_id/stop/target metadata are warnings, not failures.
