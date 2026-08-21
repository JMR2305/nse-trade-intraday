# ApexQuant AI — Phase 2B Advisory Multi-Bot Implementation Report

**Date:** 22 August 2026 (IST)  
**Branch:** `phase2a-advisory-multi-bot-logic`  
**Status:** Implemented and validated on the isolated branch. **Not merged. Not deployed.**

## Scope completed

Phase 2B implements a manually invoked, read-input-only advisory analysis package for the approved `CUSTOM_LOW_PRICE_SECTOR` universe.

- It remains advisory-only and paper-only.
- It has no API route, UI route, scheduler hook, background task, or automated invocation.
- It has no live broker, order, trade, position, portfolio, or settings-write integration.
- It does not modify Phase 20 execution, scheduler, exits, EOD, or deployment code.

## Advisory components

The `advisory_bots` package now provides:

1. **Universe validation**
   - Requires exactly 23 active symbols explicitly labelled `CUSTOM_LOW_PRICE_SECTOR`.
   - Rejects inactive exclusions, legacy NIFTY rows, missing universe labels, and any fallback condition.

2. **Data-quality validation**
   - Fails closed for missing, unsupported, stale, malformed, future-dated, or incomplete market data.
   - Accepts only fresh `LIVE` or `NEAR_LIVE` inputs with positive finite price and volume evidence.

3. **Regime classification**
   - Produces an advisory market-context classification only.

4. **Strategy scoring**
   - Provides VWAP Pullback, Opening Range Breakout, and EMA Pullback scores.
   - Scores are never order instructions.

5. **Risk gate**
   - Enforces the Phase 2B advisory limits: ₹100,000 capital, ₹25,000 per stock, ₹1,000 per idea, and ₹3,000 daily loss.
   - Rejects missing or non-finite risk evidence instead of assuming zero exposure.

6. **Decision ranking and supervisor**
   - Produces explainable advisory rankings.
   - Blocks executable terms, order/action/broker fields, unsafe settings, unhealthy universe state, and contract violations.

7. **Manual orchestrator**
   - Runs only over caller-supplied, read-only rows and supplied context.
   - Defaults to `persist=false`.
   - Contains explicit metadata confirming manual-only invocation and no scheduler integration.

## Additive advisory storage

The existing advisory-learning storage module now owns four approved append-only tables:

- `advisory_bot_outputs`
- `advisory_strategy_scores`
- `advisory_decision_audit`
- `advisory_universe_health`

Storage protections:

- Strict four-table allow-list; no generic access to any other table.
- Deterministic immutable IDs and `ON CONFLICT DO NOTHING` idempotency.
- No update or delete API.
- `paper_only=true` and `advisory_only=true` are required by both code and database checks.
- Direct storage callers must satisfy the full advisory-output contract.
- Existing-table upgrade logic refuses to add the advisory constraint if non-advisory legacy rows exist.
- JSON fallback preserves the same append-only/idempotent semantics when the database is unavailable.

The audit adapter validates the entire output batch before the first write. It recomputes supervisor approval from the actual outputs, supplied safe settings, and current universe-health output; it never trusts a caller-provided supervisor verdict.

## Validation evidence

All required tests pass after the final hardening changes:

| Command | Result |
| --- | --- |
| `python3 -m pytest tests/unit/test_advisory_bots.py -v` | 17 passed, 1 subtest passed |
| `python3 -m pytest tests/unit/test_phase0c_safety_fixes.py -v` | 22 passed, 1 existing datetime deprecation warning |
| `python3 -m pytest tests/unit/test_custom_universe_store.py -v` | 20 passed |
| `python3 -m py_compile advisory_bots/*.py phase24_store.py` | Passed |

Advisory regression coverage includes:

- no broker/execution imports or execution calls;
- exact custom-universe scope with no NIFTY fallback;
- malformed data and missing risk evidence fail closed;
- fixed advisory risk limits;
- default no-persistence/manual-only behavior;
- append-only storage and table allow-list enforcement;
- no partial write on an unsafe output;
- forged executable records blocked with zero writes;
- forged contract-valid supervisor approval unable to override unhealthy universe state.

## Independent safety review

A focused independent review identified and then re-verified the hardening of:

- complete-batch persistence validation;
- direct-store advisory-contract validation;
- malformed data-quality rejection;
- missing risk-evidence rejection;
- explicit active-universe labelling;
- recomputed supervisor approval;
- upgrade-safe `advisory_only` database constraint.

The final review reported no remaining concrete safety defects.

## Source-diff and deployment guard

Final source-diff checks passed:

- No Phase 20 executor, scheduler, exits, EOD, paper-trader, broker, deployment, workflow, or artifact configuration file changed.
- No prohibited imports or execution calls appear in `advisory_bots`.
- `git diff --check main` passed with no whitespace errors.

## Operational state

No production deployment or merge was performed. No trade, position, broker, scheduler, or production setting was created or changed by this work.

The existing operating posture remains unchanged:

- capital: ₹100,000;
- custom universe: `CUSTOM_LOW_PRICE_SECTOR`;
- auto-paper entries: disabled;
- bootstrap paper mode: disabled;
- auto-paper exits: enabled;
- live broker activity: disabled.

## Release decision

**Review-ready only.** Keep this branch unmerged and undeployed until the operator explicitly approves a separate merge/review decision.