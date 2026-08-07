---
name: V4.3 Research Loader Stability & Risk Audit
description: Concurrent loader design, fail-mode semantics, and audit manifest rules for V4.3 stability work
---

# V4.3 Research Loader Stability & Risk Audit

## Concurrent loader design

`research_agent/agent.py` — `_run_loaders_concurrent()`:
- All three data loaders run in daemon threads simultaneously sharing one `_CYCLE_DEADLINE_S=30s` wall-clock budget. Worst-case cycle = 30s, not 90s.
- Daemon threads do not prevent process exit. CPython cannot interrupt blocking I/O, so timed-out threads run to background completion.

**Why:** Sequential per-loader 30s timeouts meant three hung sources = 90s blockage, stalling the pipeline far beyond the claimed deadline.

**How to apply:** Always pass the full list of loaders to `_run_loaders_concurrent()`. Never call loaders sequentially with independent timeouts.

## None return = loader failure

A loader returning `None` must count as `_loaders_failed` (not `_loaders_succeeded`). `done_flags[i]=True` + `exceptions[i] is None` + `results[i] is None` → failure path with reason "returned None".

**Why:** All-None returns (source unavailable) must trigger `MARKET_ONLY`/`PIPELINE_HALTED`, not `NORMAL`.

**How to apply:** The check order in `_run_loaders_concurrent()` is: timeout → exception → None return → success.

## In-flight guards — bounded thread accumulation

`_active_loader_threads[3]` + `_GUARDS_LOCK` track the live thread for each loader slot. Before starting a new cycle's thread for slot `i`, the guard checks `_active_loader_threads[i].is_alive()`. If alive, the slot is skipped (counts as timeout/failure) — no new thread is spawned.

**Why:** Without guards, recurring cycles while I/O is stuck spawn one thread per cycle per source, accumulating indefinitely.

**How to apply:** Guard array index matches loader position in `loader_specs` in `execute_task()`. If adding a fourth loader, increment `_GUARD_COUNT` and extend the array.

## PIPELINE_HALTED / MARKET_ONLY semantics

- `PIPELINE_HALTED` only when `loaders_failed >= 3 AND loaders_succeeded == 0` AND `research_failure_mode == "fail_closed"`.
- Single-source failure keeps mode `NORMAL`.
- `fail_open` (default) always resolves to `MARKET_ONLY` on total failure (never halts entries).
- The `research_available` entry gate reads `research_agent_mode` from KV and enforces fail-closed by blocking all BUY candidates.

## Audit manifest applicable semantics

`build_risk_audit()` per-symbol rules carry `applicable: bool`:
- `always_applicable=True` (14 standard gates): if missing from `gate_lookup`, counted as **failed** (evaluation gap).
- `always_applicable=False` (3 V4.3 conditional gates): if missing from `gate_lookup`, shows `applicable: false`, skip reason, `passed: true` — **never counted as a failure**.
- `total_rule_checks` and `failed_rule_checks` are computed only over `applicable: true` rules so disabled filters cannot corrupt `pass_rate`.
- Disabled = setting value is 0/0.0; data-absent = setting > 0 but the field (avg_volume, atr_pct) is not in the scan record.

## New entry gates (V4.3)

- `research_available` (global): fail-closed enforcement gate.
- `max_concurrent_positions` (per-symbol): skipped when setting = 0.
- `min_liquidity` (per-symbol): skipped when setting = 0 OR avg_volume not in scan record.
- `max_volatility` (per-symbol): skipped when setting = 0 OR atr_pct not in scan record.
