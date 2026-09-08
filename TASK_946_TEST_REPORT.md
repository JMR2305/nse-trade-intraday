# Task 946 — Test Report

## Verification refresh — 2026-08-27

Task 950 re-ran the safety matrix without performing a database, scanner,
execution, or production mutation.

| Safety area | Evidence | Result |
| --- | --- | --- |
| Version-store and custom membership rules | `test_universe_version_store`, `test_universe_management`, `test_custom_universe_store`, `test_runtime_universe` | Passed |
| Scanner + pre-open coverage | `test_scanner_coverage`, `test_preopen_universe_coverage` | Passed |
| Pre-open, readiness, and Kite safety | Pre-open lifecycle/provider/validation tests, live-readiness tests, Kite LTP overlay, system-readiness tests | 348 passed |
| Current Phase 20 safety | Paper-only executor, entry cutoff, EOD status, capital migration, and Phase 0C safety tests | 68 passed |
| Portfolio and ledger safety | Recovery, configuration, endpoint contract, snapshots, pre-check events, execution and portfolio unit suites | 777 passed |
| API route retirement + management guards | Universe management, legacy admin, coverage invalidation, Kite callback, portfolio config routes | 43 passed |
| Dashboard UI | Full dashboard Vitest suite | 1,007 passed |
| Full API server suite | `pnpm --filter @workspace/api-server test` | 165 passed |
| Type and syntax safety | Workspace typecheck and Python `compileall` | Passed |
| Production build | API bundle and dashboard Vite build with required `PORT`/`BASE_PATH` | Passed |

The scanner coverage fixtures were updated to carry the current immutable
universe version/hash metadata. This restores test fidelity after session
pinning; it does not alter runtime coverage, membership, or execution logic.

## Phase 20 legacy test isolation limitation

The previously stale test fixtures now pass when invoked as their intended
independent modules:

* `test_phase20.py` — 62 passed;
* `test_bootstrap_paper_trade.py` — 53 passed; and
* `test_paper_sell_no_position.py` — 12 passed.

The tests were updated only to supply the current pinned-universe provenance
and to patch the current exit-pending accessor. No production or runtime
trading code changed.

The same three files still do **not** run cleanly as one pytest process:
69 fail and 58 pass. `test_bootstrap_paper_trade.py` installs global
`sys.modules` stubs during collection; depending on collection order, those
stubs replace the real paper-trader dependencies required by the other two
modules. This is a deterministic test-isolation problem, not evidence of a
runtime safety bypass. It remains an unresolved regression-gate limitation and
has a dedicated follow-up.

Warnings observed during passing checks were Python's `datetime.utcnow`
deprecation warning and non-blocking Vite sourcemap/chunk-size advisories.