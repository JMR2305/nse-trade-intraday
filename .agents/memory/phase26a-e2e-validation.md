---
name: Phase 26A end-to-end validation engine
description: Validation-only engine over canonical stores; chain semantics, replay BUY normalisation fix, append-only run store.
---

- Validators are read-only and injectable: counts only from `replay_engine.build_replay`, portfolio aggregate checks only via `validation_engines.validate_portfolio`; never re-derive pipeline numbers.
- Execution-chain semantics: a paper-eligible BUY with no ledger row is a **BLOCKED chain** (replay counts it `cancelled` by construction; auto paper entries default OFF). Missing block *evidence* is WARN, never ERROR — otherwise every routine run FAILs. ERRORs are reserved for executed trades with missing links (ledger↔position qty/cost linkage, CLOSED without realized_pnl, missing learning record on CLOSED, missing pipeline/replay events).
- Per-trade portfolio linkage matters: aggregate balances can pass while a specific trade's position is absent — chain validator must match ledger rows to canonical positions by trade_id/symbol.
- replay_engine bug fixed: BUY classification must use `_is_buy_action` ("BUY"/"STRONG BUY"/"STRONG_BUY"); exact `== "BUY"` misclassified STRONG BUY rows as execution orphans/anomalies (false FAIL on every validation run).
- Append-only run store JSON fallback needs flock (`.lock` file) + unique temp names — concurrent per-request Python processes otherwise lose runs.
- **How to apply:** any future validation layer (26B/26C/26D) should reuse these semantics and the `phase26_store` pattern.
