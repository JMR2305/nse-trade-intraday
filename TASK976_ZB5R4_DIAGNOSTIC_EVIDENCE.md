# TASK976-ZB5R4 diagnostic candidate

Root cause: **NOT PROVEN**. This is an offline tooling correction, not a ZB5 PASS claim. The user-reported live status remains Tier 1 NORMAL PASS, Tier 2 PEAK PASS, Tier 3 HEADROOM FAIL — `worker evidence count mismatch`. No live evidence was collected in this continuation.

## Starting state and scope

Starting HEAD: `a2b9fd34dd867d6ac0e972c074daa34279e38bc1`

Branch: `task967-migration-guard-hardening`.

The transferred unfinished candidate was already present. This continuation changed only:

- `scripts/task976_zb5_runner.py`
- `scripts/test_task976_zb5_runner.py`
- `scripts/task976_zb5_timing_and_evidence_test.py`
- `TASK976_ZB5R4_DIAGNOSTIC_EVIDENCE.md`

The untracked `TASK976_ZB5R4_FREEBUFF_TRANSFER.patch` was neither modified nor staged.

## Three blocker corrections

1. **Launch timing:** `spawn_worker()` captures `time.monotonic_ns() // 1000` immediately after successful `Popen`, and returns the process and timestamp together. The runner retains these pairs through collection and cleanup. Both successful collection and timeout/termination calculate `duration_monotonic_ms` from that original timestamp. This measures spawn-to-collection/termination elapsed time, including time before collection; it does not claim the precise instant a previously exited child stopped executing. A real local subprocess regression delays collection and proves that delay is included. Deterministic clock tests cover normal and timeout paths.

2. **Failure diagnostics:** `collect_worker_evidence()` collects all worker outcomes before calling the unchanged exact-count validator. On `SafetyError`, it attaches structured `worker_diagnostics` to the same exception and re-raises it. The exception text remains exactly `worker evidence count mismatch`. The CLI emits those diagnostics on stderr, then the canonical FAIL/error lines, and exits 1. Records include each worker index, classification, reason, launch/elapsed time, return code, stream presence, parse state, and cleanup state. Arbitrary stderr and worker error text are suppressed; only the known deadline reason is retained verbatim. Parsed diagnostics allow only bounded numeric metadata, avoiding conversion failures and disclosure through malformed fields.

3. **Explicit acceptance:** only `PASS_EVIDENCE` outcomes enter `worker_data`. Explicit non-PASS statuses, timeout, nonzero exit, stderr, empty stdout, invalid JSON, invalid evidence, unknown exit state, and failed cleanup remain rejected. The existing unmodified worker emits successful evidence without a `status` key (`run_deterministic_workload()` / `main()`); compatibility is retained only after its full evidence passes the existing validator. Bare statusless JSON is rejected. Explicit PASS payloads also require valid evidence. Final aggregate validation still requires the exact configured count and tier.

The supplemental test now imports real runner/worker modules; copied implementations, the psycopg2 stub, stale installation claims, and the proposed deadline increase were removed. Its tests are included in the required suite through the runner test module.

## Unchanged bounds

| Tier | Bars per symbol | Workers | Worker bound | Parent communicate timeout | Whole-run deadline | Shell timeout |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 252 | 1 | 75s | 75s | 180s | 240s |
| 2 | 252 | 2 | 75s | 75s | 240s | 300s |
| 3 | 504 | 3 | 75s | 75s | 240s | 300s |

All request counts, concurrency, workload durations, symbol gates, and safety evidence checks remain unchanged. No worker-bound increase and no Phase D work.

## Offline verification

`uv` was absent from PATH. It was installed under `/tmp/task976-uv`; the repository environment was installed using:

```sh
/tmp/task976-uv/bin/uv sync --frozen --cache-dir /tmp/task976-uv-cache
```

This created `.venv` from the existing lockfile. Dependency declarations and lockfiles were not modified. Package downloads required sandbox network approval.

The required command was run against real imported modules:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest -v \
  scripts/test_task976_zeabur_fixture.py \
  scripts/test_task976_zeabur_benchmark.py \
  scripts/test_task976_zb5_runner.py \
  scripts/test_task976_zb5_worker.py
```

Final result: **131 tests, OK; 0 failures, 0 errors, 0 skipped**. This includes the 10 continuation regressions. The supplemental module also passed separately: **10 tests, OK** (overlapping tests, not an additional 10 unique tests). Log: `/tmp/task976-offline.log`.

The initial sandbox run blocked the existing localhost Node listener and socket creation test. The complete suite passed with approved execution permitting those offline tests. DB operations in these tests use mocks; printed fixture/benchmark messages are synthetic test output, not live accesses.

The pre-fix regression run exposed the missing collection/spawn helpers, incorrect elapsed duration, absent PASS_EVIDENCE, and absent cleanup-failure classification. All final regressions pass, including zero-exit explicit FAIL rejection, exactly three PASS acceptance, two PASS plus one failure with all diagnostics emitted, malformed payload redaction, and rejection of each required failure classification.

Other checks:

- `node --check scripts/task976_zb5_node_probe.mjs`: exit 0.
- AST parsing and in-memory Python compilation of all three modified Python files: PASS.
- `git diff --check`: exit 0.

## Final working-tree status

```text
 M scripts/task976_zb5_runner.py
 M scripts/test_task976_zb5_runner.py
?? TASK976_ZB5R4_DIAGNOSTIC_EVIDENCE.md
?? TASK976_ZB5R4_FREEBUFF_TRANSFER.patch
?? scripts/task976_zb5_timing_and_evidence_test.py
```

No Zeabur access, DB access, live benchmark, or broker/provider access. No production/runtime application, migration, ZB3/ZB4, worker, Node probe, dependency, or timing changes. No commit, push, merge, or deploy.

A separately authorized Tier-3 rerun is still needed to determine the actual live failure mechanism. Offline correctness does not establish that mechanism.
