# TASK976-ZB5R11 — Current 2-vCPU Capacity Boundary

Recorded: 2026-09-09. This documentation-only record captures the benchmark
evidence and hosting decision supplied for TASK976-ZB5R11; it is not a new run
or an independent re-verification of the supplied runtime evidence.

- Repository: `JMR2305/nse-trade-intraday`
- Branch: `task967-migration-guard-hardening`
- Reviewed commit: `31acb487e699ce439e05fcc4f59e4731b303aa32`
- Reported deployed commit: `31acb48`
- Infrastructure: Zeabur, Tencent Singapore, **2 vCPU / 4 GB RAM**.
  This is the current purchased hosting baseline.

## Observations — supplied benchmark evidence

| Tier | Workload | Result |
| --- | --- | --- |
| 1 | NORMAL | PASS |
| 2 | PEAK | PASS |
| 3 | HEADROOM | FAIL |

The unchanged Tier-3 contract is 3 scanner workers, 23 symbols per worker,
504 bars per symbol, a 75-second worker requirement, 1080 HTTP requests,
HTTP concurrency 10, a 240-second whole-run deadline, and a 300-second shell
timeout. Fail-closed safety, resource, and evidence gates remain mandatory,
with zero DB mutation and zero broker/provider/order activity.

The latest instrumented Tier-3 result was **FAIL**. The canonical failure was
`worker evidence count mismatch`. All three workers had `NONZERO_EXIT`,
return code `1`, and `WORKER_DEADLINE_EXCEEDED`; **0/3 worker evidence rows
were accepted**. The diagnostic timings below are not accepted worker rows.

| Container CPU evidence | Observed value |
| --- | --- |
| `elapsed_seconds` | approximately 127.89 |
| `usage_usec_delta` | approximately 207,667,696 |
| `user_usec_delta` | approximately 190,978,965 |
| `system_usec_delta` | approximately 16,688,731 |
| `nr_throttled_delta` | 0 |
| `throttled_usec_delta` | 0 |
| `cpu.max` quota mode | unbounded |
| `effective_cpu_quota` | null |

| Worker | Wall time (s, approx.) | User CPU (s, approx.) | System CPU (s, approx.) | Outcome |
| --- | --- | --- | --- | --- |
| 0 | 109.36 | 36.62 | 0.25 | WORKER_DEADLINE_EXCEEDED |
| 1 | 107.22 | 35.58 | 0.24 | WORKER_DEADLINE_EXCEEDED |
| 2 | 127.15 | 53.23 | 0.27 | WORKER_DEADLINE_EXCEEDED |

An independent Zeabur server observation during the run showed CPU usage
reaching **100%**, with a warning that very high CPU may slow services.
Memory was not comparably stressed in the displayed server view.

**No cgroup CPU throttling was observed** in the reported counters.
**Heavy CPU/scheduling pressure was observed**, supported by the server CPU
observation and worker wall-time/CPU evidence. The unbounded cgroup quota
does not imply unlimited host CPU capacity.

## Interpretation and current decision

The current 2-vCPU / 4-GB server supports NORMAL and PEAK under the reported
benchmark conditions. HEADROOM is not satisfied under the present contract.
This is a documented **capacity boundary, not a benchmark bug or software
defect**. The evidence does not establish the capacity needed to pass HEADROOM.

No infrastructure upgrade is currently required, and none is authorized.
4 vCPU was considered only as a diagnostic experiment; it is neither
authorized nor required. No claim is made that 4 vCPU would pass.
Future development can proceed on the current purchased host without an
infrastructure change merely to force HEADROOM PASS.

```text
KEEP_CURRENT_HOST = 2_VCPU_4GB
NORMAL = PASS
PEAK = PASS
HEADROOM / CURRENT TIER-3 STATUS = FAIL
75-SECOND WORKER CONTRACT = UNCHANGED
504-BAR TIER-3 WORKLOAD = UNCHANGED
3-WORKER CONCURRENCY = UNCHANGED
1080 HTTP REQUESTS = UNCHANGED
HTTP CONCURRENCY 10 = UNCHANGED
90-SECOND DEADLINE = NOT AUTHORIZED
INFRASTRUCTURE UPGRADE = NOT REQUIRED / NOT AUTHORIZED
ZB5 PASS = NOT CLAIMED
```

## Future decision triggers

Reconsider capacity if any of the following occurs:

- PEAK begins failing.
- Production-like paper workload approaches sustained PEAK.
- Scheduler/runtime latency degrades materially.
- Additional approved workloads materially increase CPU demand.

These are triggers for a future evidence-based decision, not authorization
to upgrade infrastructure or change the benchmark contract.
