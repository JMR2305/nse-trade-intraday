# TASK974 Step27 — focused closure of the 12 broad Python failures

## Starting state and scope

Read `TASK974_STEP26_REMAINING_FAILURES_STATUS.md` before testing. Historical CI run
33745141650 failed with 12 failed, 6421 passed, 100 skipped and 25 passing subtests.
Its PostgreSQL, guard, API and native Python gates passed. Those historical results
are not rewritten by this report.

Parent review-branch commit: `07421d22b5c0c6436193f6652d930aa917f4de0b`.
Branch: `task967-migration-guard-hardening`.

## Environment and commands

Existing `/workspace/task972/.venv`: Python 3.12.13, pytest 9.1.1,
pytest_asyncio 1.4.0, yfinance 1.5.1. No dependency installation or new environment.
Every local invocation unset DATABASE_URL and TASK967_TEST_DATABASE_URL.
All local tests were restricted to the requested files and focused regressions.
No old pytest process required termination; final `pgrep -a -x python`,
`pgrep -a -x pytest`, and `pgrep -a -x timeout` returned no matching processes.

Working directory for every pytest command:
`/workspace/task972/artifacts/api-server/src/python`.
Each command below used this exact prefix and suffix, with the indicated file list
and evidence tag substituted (no additional test files):

```bash
timeout --signal=INT --kill-after=10s 90s env -u DATABASE_URL -u TASK967_TEST_DATABASE_URL ../../../../.venv/bin/python -m pytest FILES -q --tb=short --durations=20 --junitxml=../../../../task974-step27-TAG.xml > ../../../../task974-step27-TAG.log 2>&1
```

| Tag | Exact FILES argument |
| --- | --- |
| baseline | `test_analysis_agents.py test_daily_session_and_pipeline_e2e.py test_phase20.py tests/unit/portfolio/test_exposure.py tests/unit/portfolio/test_freeze_patch_coverage.py tests/unit/portfolio/test_reconciliation.py` |
| leak-red | `test_observability_center.py test_analysis_agents.py::TestAnalysisLayer::test_timeline_no_buy_sell` |
| regressions-red | `test_task974_step27_regressions.py` |
| regressions-green | `test_task974_step27_regressions.py` (first two regressions, before adding the daily-session clock regression) |
| A | `test_observability_center.py test_analysis_agents.py` |
| B | `test_daily_session_and_pipeline_e2e.py test_phase20.py` |
| C | `tests/unit/portfolio/test_exposure.py tests/unit/portfolio/test_freeze_patch_coverage.py tests/unit/portfolio/test_reconciliation.py test_task974_step27_regressions.py` |
| D | `test_task974_import_isolation.py risk_validation/test_risk_validation.py research_lab/test_research_lab.py test_analysis_agents.py` |
| E | `tests/unit/portfolio/test_exposure.py tests/unit/portfolio/test_freeze_patch_coverage.py tests/unit/portfolio/test_reconciliation.py tests/unit/test_paper_exploration.py tests/unit/test_phase26_live_monitor.py` |

## Reproduction evidence and exact fixes

The six-file baseline completed: **13 failed, 270 passed, 0 skipped, 0 collection
errors, 63.12 seconds**. It reproduced all eleven clock/portfolio failures; the
timeline consumer passed without its producer. Two additional failures were
native-extension reimports in the test harness, described below.

The producer/consumer `leak-red` command completed: **1 failed, 95 passed,
0 skipped, 0 collection errors, 0.43 seconds**. It reproduced the exact JSON
serialization exception without the full suite.

| Exact historical test | Proven cause and correction | Final coverage |
| --- | --- | --- |
| `test_analysis_agents.py::TestAnalysisLayer::test_timeline_no_buy_sell` | `test_observability_center.py` installed a MagicMock as `market_intelligence_hub.shared_services` with collection-time `sys.modules.setdefault`. The real agent imported `_get_regime` from that fake module, yielding `mock._get_regime().get()` in timeline JSON. Install the six snapshot/scan doubles only inside the existing `isolated_imports` context in an autouse producer fixture; restore modules and feature flag after each test. No consumer assertion or production serializer changed. | A, D, new regression |
| `test_daily_session_and_pipeline_e2e.py::TestRunTickOpenAlertE2E::test_open_retry_success_emits_no_alert` | OPEN market-status stub did not freeze `market_hours.now_ist`; scheduler correctly claimed the squareoff key after 15:20. Class setup now supplies 2026-09-03 10:00 IST and the matching session date, with `addCleanup` restoring both patches. | B, new regression |
| `test_phase20.py::TestExitsSafety::test_no_exit_keeps_position_open` | OPEN status with actual after-market clock correctly triggered MARKET_CLOSE_EXIT. `_run` now injects 10:00 IST by default, with an explicit clock override for close tests. | B |
| `test_phase20.py::TestExitsSafety::test_trailing_stop_not_armed_without_peak` | Same independent market-close clock branch; same scoped fixture fix. | B |
| `test_phase20.py::TestExitsSafety::test_trailing_stop_triggers_after_peak_then_pullback` | Same market-close clock branch masked the intended trailing-stop sequence. | B |
| `tests/unit/portfolio/test_exposure.py::TestCalculateExposure::test_stale_prices_false_when_fresh` | Collection-time `_NOW` aged while earlier tests ran. Autouse fixture sets `_NOW` from current UTC at each test setup, restoring it afterward. | C, E, artificial-age regression |
| `tests/unit/portfolio/test_freeze_patch_coverage.py::TestHealthMonitorBranches::test_stale_broker_triggers_degraded` | Fresh local snapshot became stale independently of deliberately stale broker data. Same per-test timestamp fixture. | C, E, artificial-age regression |
| `tests/unit/portfolio/test_freeze_patch_coverage.py::TestHealthMonitorBranches::test_unresolved_discrepancies_prevents_readiness` | Collection-time snapshot age polluted the intended discrepancy/readiness case. Same fixture correction. | C, E, artificial-age regression |
| `tests/unit/portfolio/test_freeze_patch_coverage.py::TestHealthMonitorBranches::test_ready_no_issues_is_healthy` | Collection-time local state aged beyond freshness threshold. Same fixture correction. | C, E, artificial-age regression |
| `tests/unit/portfolio/test_freeze_patch_coverage.py::TestHealthMonitorBranches::test_compute_health_via_monitor` | Same aged local-state fixture. | C, E, artificial-age regression |
| `tests/unit/portfolio/test_reconciliation.py::TestStalenessKeyFormats::test_fresh_snapshot_at_key_not_flagged` | Module-level snapshot timestamp aged before execution. Same per-test fixture correction. | C, E, artificial-age regression |
| `tests/unit/portfolio/test_reconciliation.py::TestStalenessKeyFormats::test_snapshot_at_takes_precedence_over_as_of` | The intended fresh snapshot_at value itself became stale. Same fixture correction; precedence assertions unchanged. | C, E, artificial-age regression |

Baseline evidence showed about 62.7 seconds of local snapshot age, following a
61.34-second market-data call in the analysis file. This demonstrates the age
mechanism without arbitrary sleeps or production threshold changes.

Additional focused harness errors:

- `test_daily_session_and_pipeline_e2e.py::TestRunTickOpenAlertE2E::test_busy_branch_still_carries_session_alert`
- `test_phase20.py::TestGates::test_quality_allocation_preview_uses_kite_and_cache_evidence`

Both failed importing NumPy through pandas after per-test module restoration had
removed the native-extension dependency's first import. The test files now import
their real `live_scan_engine` / `ohlcv_cache_store` dependency before per-test
snapshots. This is a normal real-module import, not a fake replacement; the root
conftest isolation mechanism was not changed. Both tests passed in B.

## Regression evidence

New `test_task974_step27_regressions.py`:

1. Importing the observability producer does not install stubs. Exercise its
   scoped snapshot double twice; assert watched module identities are restored
   each time; run the real timeline consumer's JSON assertion afterward. Only the
   external base-regime data input is stubbed for deterministic subprocess timing;
   the previously contaminated shared-services module and real timeline remain real.
2. Artificially age the three portfolio modules' `_NOW` values by 120 seconds
   after collection, then execute all seven exact freshness node IDs. No sleep,
   tolerance widening or production clock/threshold edit. Before the fixture fix,
   six of these seven failed in this isolated experiment (all seven failed in the
   original six-file baseline); after the fix all seven pass.
3. Run the real open-session retry test under ambient midnight and 16:10 IST
   clocks; its setup supplies intraday time, assertions pass, and the ambient
   clock is restored after teardown.

The first two new regressions were executed before fixing fixtures: **2 failed**,
then **2 passed** after correction. All three passed together in C.

Two additional Phase20 regressions execute in B:

- Explicit 15:20 IST still produces MARKET_CLOSE_EXIT and one sell.
- An ambient 16:10 clock cannot alter the three intraday exit/trailing-stop
  cases; the inner injected clock is restored afterward.

## Final focused verification

| Group | Passed | Failed | Skipped | Collection errors | Seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| A: producer then entire consumer | 180 | 0 | 0 | 0 | 49.261 |
| B: daily session and Phase20 | 91 | 0 | 0 | 0 | 1.094 |
| C: portfolio and all new Step27 subprocess regressions | 112 | 0 | 0 | 0 | 1.665 |
| D: unchanged Step26 controls | 230 | 0 | 0 | 0 | 55.764 |
| E: affected Step26 historical portfolio group | 185 | 0 | 0 | 0 | 0.562 |
| Total test executions (overlapping groups, not unique tests) | 798 | 0 | 0 | 0 | 108.346 |

All commands completed within their individual 90-second limit. Slowest tests
were the real analysis snapshot call (48.24 seconds in A), and the analogous call
in D; no group needed termination or a broader retry. Existing warnings remained
visible; no failure was downgraded to a warning or skipped.

Evidence: `task974-step27-{baseline,leak-red,regressions-red,regressions-green,A,B,C,D,E}.{log,xml}`.

## Exact Step27 changed files

- `artifacts/api-server/src/python/test_observability_center.py`
- `artifacts/api-server/src/python/test_daily_session_and_pipeline_e2e.py`
- `artifacts/api-server/src/python/test_phase20.py`
- `artifacts/api-server/src/python/tests/unit/portfolio/test_exposure.py`
- `artifacts/api-server/src/python/tests/unit/portfolio/test_freeze_patch_coverage.py`
- `artifacts/api-server/src/python/tests/unit/portfolio/test_reconciliation.py`
- `artifacts/api-server/src/python/test_task974_step27_regressions.py` (new)
- `scripts/task969_ci_report.py`: exact before/after blob pins for these seven
  test files only, plus this report's exact path.
- `.github/workflows/task969-postgres16-validation.yml`: upload this report's
  exact path; no gate, condition, timeout or execution command changed.
- `TASK974_STEP27_BROAD_PYTHON_12_STATUS.md` (this report).

Existing dirty worktree history and runtime-generated JSON files are excluded
from the Step27 commit. No `git add .`, reset, force-push or historical evidence
rewrite. The commit is based on the current remote review branch, not the older
local HEAD. Identity keeps the original reviewed Task967 tree unchanged.

## Safety and release status

No production code changed. No trading, risk, database, universe, provenance,
staleness or squareoff safety check was weakened. No migration/schema logic,
production DB, deployment configuration, universe membership or live trading
settings were changed. No dashboard, TypeScript, build, migration gate or full
repository test was run during focused diagnosis. No merge or deployment.

All twelve requested failures have passed focused verification. This checkpoint
authorizes the user's single final review-branch push/CI run, not a release.

**Focused verdict: READY FOR ONE FINAL FULL VALIDATION.**

The completed final CI outcome must be recorded separately after that one run;
focused success alone is not a full-CI or release PASS.
