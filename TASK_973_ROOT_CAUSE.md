# Task973 — queue cutoff diagnosis

## Evidence captured before the correction

Historical run9: https://github.com/JMR2305/nse-trade-intraday/actions/runs/33631734721

Diagnostic run10: https://github.com/JMR2305/nse-trade-intraday/actions/runs/33633751550

Diagnostic commit: `43c8d6d79655224826127f9191911dede61824d3`.
All original 25 assertions and application predicates were unchanged. A test-only
observer executed each original queue SELECT before reading raw row evidence.
The observer may change subsequent timing; it did not change query results.
Machine-readable evidence: `TASK_973_QUEUE_DIAGNOSTICS.json`.

## Historical failure matrix (run9)

| Test | Expected fetch calls | Actual | Classification |
| --- | ---: | ---: | --- |
| respects each subscriber's own min_confidence threshold | 1 | 0 | Missing immediate delivery |
| deletes tokens that Expo reports as DeviceNotRegistered and fails the delivery permanently | 2 | 1 | Missing immediate delivery |
| schedules a retry (does not lose the alert) when the push service is down | 1 | 0 | Missing initial attempt |
| sends one alert per enabled subscriber when health_pct < 70 | 2 | 1 | Missing immediate delivery |
| is idempotent: same scan_id is never sent twice (deduped by idempotency key) | 1 | 0 | Missing initial delivery |
| sends again for a different scan_id | 1 | 0 | Missing initial delivery |
| recovery: fires exactly one recovery push per device when health climbs back above the threshold | 2 | 1 | Missing degradation delivery, before recovery assertion |
| recovery: fires the recovery push when the server restarts mid-incident (DB state survives) | 2 | 1 | Missing degradation delivery, before restart assertion |
| alerts a subscriber when healthPct < their minHealthPct even when health is above the default 70% floor | 1 | 0 | Missing immediate delivery |

Historical run9 did not record raw timestamps. They cannot be recovered after
its disposable service was removed. Do not present run10 timestamps as run9 data.

## Native diagnostic result

Run10: 17 passed, 8 failed, 0 skipped; 1.80 seconds. Failure membership changed.
Every failing test has exactly one eligible QUEUED row excluded by the cutoff:

| Test | Missing row ID | next_attempt_at minus JS cutoff (microseconds) |
| --- | ---: | ---: |
| delivers to every subscriber, one queued delivery per device | 110 | 26 |
| includes ERROR agent names in the notification body | 114 | 231 |
| is idempotent: same scan_id is never sent twice (deduped by idempotency key) | 115 | 177 |
| fires even when health_pct >= 70 but an agent is in ERROR | 118 | 393 |
| recovery: fires exactly one recovery push per device when health climbs back above the threshold | 120 | 45 |
| recovery: a second healthy snapshot after recovery does not re-fire the recovery push | 121 | 262 |
| recovery: fires the recovery push when the server restarts mid-incident (DB state survives) | 123 | 302 |
| alerts ALL subscribers when agents are in ERROR regardless of their minHealthPct threshold | 126 | 373 |

Example: row115 had `2026-09-02 13:07:23.138177+00`; actual query parameter was
`2026-09-02T13:07:23.138Z`. PostgreSQL evaluated `next_attempt_at <= cutoff` FALSE.
The row remained QUEUED, attempts0. No sender was called. Other due rows were selected
in created_at order; this was exclusion before ordering, not an ordering tie.

## Root cause and exclusions

`enqueueAlert` uses the timestamptz DEFAULT now(), retaining PostgreSQL microseconds.
`processDueDeliveries` previously supplied a JS Date with millisecond precision.
An insert committed before processing can nevertheless have a timestamp later
than the truncated application cutoff in the same millisecond. The SELECT then
omits it until a later worker tick. This is a real notification latency defect;
dedupe, filtering, recovery, and Expo response logic are not reached for that row.

The common queue defect is the supported explanation for the nine historical
failures; only three historical failing tests failed again in this instrumented
run. The remaining six passed with nonpositive timestamp deltas. Attribution for
their historical execution is an inference, not invented per-row evidence.

Evidence rules out timezone conversion for the reproduced failures (UTC explicit
offsets), fixture leakage (different current_schema per test), and uncommitted
transaction visibility (awaited autocommit queries on one pooled session). There
were no fake timers in the original suite. Dates returned to JS lose submillisecond
precision, but the failed comparison happens inside PostgreSQL before that return.

## Minimal correction

Use PostgreSQL `statement_timestamp()` for due and expiry predicates, preserving
native precision without changing columns, stored values, retries, claims,
membership, or trading behavior. No rounding, sleeps, tolerances, schema migration,
extra worker ticks, or weakened assertions. Statement time is chosen instead of
transaction-start now() so long transactions do not retain a stale cutoff.

The deterministic regression inserts a row exactly one microsecond after a frozen
JS clock, proves the old SQL predicate excludes it, and requires the real queue to
deliver it. It also requires a future retry to remain untouched, an expired row to
expire, and a second drain not to duplicate delivery. Only Date is frozen; real PG
and IO remain active. All original 25 tests and assertions remain intact.

Identity still anchors the historical Task967 tree and exact Task971 changes.
The new runtime exception pins both entire alertQueue source blobs, not a wildcard.
Final application results must come from the correction's actual Actions run.

## Correction run11 and subsequent fresh-fixture reconciliation

Correction commit: `3027f64ffbf4551a5674ec88ee7b241ca71936cc`.
Run: https://github.com/JMR2305/nse-trade-intraday/actions/runs/33634302359

- Native PostgreSQL preservation/catalog/idempotency: PASS.
- Migration adversarial guard: 968 passed, 0 failed; offline SAFE.
- Focused notifier: 26 passed, 0 failed, 0 skipped (25 original + regression), 9.66s.
- Full API: 20 files, 170 passed, 0 failed, 0 skipped, 17.06s.
- Native Python: 8 passed, 12 failed, 3.96s. All 12 failures were teardown
  UndefinedTable errors for reconciliation_runs, not notification regressions.

The integration class cleans both portfolio_events and reconciliation_runs after
each test, but its first tests only initialize portfolio_events. On a fresh DB,
reconciliation_runs does not exist until a later test uses its repository.
The CI-only fixture helper extracts the existing canonical additive declaration
and creates the empty schema before integration tests. It executes neither the
repository's legacy DROP path nor pruning/data operations. Application and test
assertions are unchanged. The helper requires the exact disposable local URL and
PostgreSQL16. This is an additional test-environment defect, separate from the
single queue-clock cause of the notifier failures.

Independent downstream gates now execute after successful native-DB and full-API
gates even if a Python gate fails, so all results remain visible. Failed steps
still fail the job and report; no continue-on-error, warning conversion, or
relaxation of any release gate is used.
