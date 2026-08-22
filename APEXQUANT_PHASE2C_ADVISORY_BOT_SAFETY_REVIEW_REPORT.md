# ApexQuant AI — Phase 2C Advisory Bot Safety Review

**Review date:** 22 August 2026 (IST)  
**Controlling report:** `APEXQUANT_PHASE2B_ADVISORY_MULTI_BOT_IMPLEMENTATION_REPORT.md`  
**Reviewed branch:** `phase2a-advisory-multi-bot-logic`  
**Verdict:** **SAFE FOR LATER MERGE REVIEW**

## 1. Branch state

- The reviewed branch is `phase2a-advisory-multi-bot-logic`.
- It is not merged into `main`.
- No production deployment was triggered.
- No production configuration, workflow, artifact manifest, or deployment file changed.
- The Phase 2C safety hardening is committed only on the isolated branch.

## 2. Files changed

Committed product changes relative to `main` are limited to:

- the `artifacts/api-server/src/python/advisory_bots/` advisory package;
- `artifacts/api-server/src/python/tests/unit/test_advisory_bots.py`;
- additive advisory storage in `artifacts/api-server/src/python/phase24_store.py`;
- Phase 2A/2B supporting plan and implementation reports; and
- advisory safety-governance memory documentation.

The untracked Phase 2C instruction attachment is not product code and was not included in the branch commit.

## 3. Files confirmed untouched

The committed branch diff contains no changes to:

- `phase20_executor.py`
- `phase20_scheduler.py`
- `phase20_exits.py`
- `phase20_eod_outcomes.py`
- `phase20_eod_status.py`
- `paper_trader.py`
- `broker_client.py`
- Kite or other live-order modules
- settings write handlers
- deployment configuration
- workflows
- artifact manifests

## 4. AST/import deny-list review

The advisory package and advisory storage were inspected with an AST-based import/call deny-list.

**Result: PASS**

- No imports of Phase 20 execution, scheduler, exits, paper trader, broker, or Kite modules.
- No calls to order placement, trade/position lifecycle, paper-entry automation, or settings mutation methods.
- No broker, live-order, scheduler, or execution path was found.

## 5. Advisory contract review

**Result: PASS**

Every accepted advisory output is required to have:

- `advisory_only=true`
- `paper_only=true`
- one of the only permitted decisions:
  - `WATCH`
  - `CANDIDATE`
  - `REJECTED`
  - `BLOCKED_DATA_QUALITY`
  - `INSUFFICIENT_CONTEXT`
  - `SUPERVISOR_BLOCKED`

Executable action, order, quantity, broker, Kite, and auto-enable fields or values are prohibited and blocked by the contract and supervisor.

## 6. Universe safety review

**Result: PASS**

- The universe must be explicitly `CUSTOM_LOW_PRICE_SECTOR`.
- The active set is pinned to the approved 23 symbols, not merely any 23 symbols.
- Unknown active symbols and missing approved symbols fail closed.
- `IOB` and `UCOBANK` must remain inactive exclusions.
- NIFTY_50 fallback, empty scope, duplicate scope, legacy labels, and missing labels are blocked.

## 7. Data-quality review

**Result: PASS**

Scoring requires:

- master OHLCV availability;
- `LIVE` or `NEAR_LIVE` quality;
- positive finite price and volume;
- non-future, fresh snapshot timestamp;
- supported intraday timeframe;
- at least 30 candles;
- valid positive finite OHLCV values; and
- valid candle ranges where `low <= open/close <= high`.

Missing, stale, malformed, daily/unsupported-timeframe, insufficient, or invalid-candle evidence returns a blocked/zero-score result. Strategies independently enforce the same intraday-evidence gate.

## 8. Strategy review

**Result: PASS**

VWAP Pullback, Opening Range Breakout, and EMA Pullback produce advisory scores only. They do not return executable orders, quantities, entries, exits, stop-loss payloads, target payloads, or broker instructions.

Missing or invalid intraday evidence returns `INSUFFICIENT_CONTEXT` with score zero.

## 9. Risk Gate review

**Result: PASS**

The fixed internal advisory limits are:

- capital basis: ₹100,000
- per-stock cap: ₹25,000
- risk per idea: ₹1,000
- daily loss limit: ₹3,000

Callers cannot override these limits. Missing or non-finite risk evidence fails closed. Configuration mismatch rejects the advisory result. The risk gate has no capital reservation, daily counter mutation, trade write, or position write path.

## 10. Supervisor review

**Result: PASS**

The supervisor blocks:

- unsafe settings;
- unhealthy or forged universe state;
- executable action/order/broker fields and values; and
- contract violations.

Before any advisory persistence, approval is recomputed from the actual subject outputs, safe settings, and universe-health output. Caller-provided approval cannot bypass this recomputation. Supervisor approval authorizes advisory recording only, never execution.

## 11. Storage review

**Result: PASS**

The advisory writer is allow-listed to exactly four tables:

- `advisory_bot_outputs`
- `advisory_strategy_scores`
- `advisory_decision_audit`
- `advisory_universe_health`

Storage protections:

- append-only insertion with `ON CONFLICT DO NOTHING`;
- no update or delete API;
- no foreign key, trigger, or write path to Phase 20 trade, position, portfolio, or settings tables;
- full-batch validation before the first write;
- one rollback-capable PostgreSQL transaction for the complete batch;
- staged JSON fallback with restore-on-write-failure behavior;
- `advisory_only=true` and `paper_only=true` checks for both new and upgraded tables; and
- direct storage callers must also satisfy the advisory contract.

Unsafe records and forged-looking approvals cannot produce a partial advisory audit write.

## 12. Test results

| Validation | Result |
| --- | --- |
| `python3 -m pytest tests/unit/test_advisory_bots.py -v` | 22 passed, 1 subtest passed |
| `python3 -m pytest tests/unit/test_phase0c_safety_fixes.py -v` | 22 passed, 1 existing datetime deprecation warning |
| `python3 -m pytest tests/unit/test_custom_universe_store.py -v` | 20 passed |
| `python3 -m py_compile advisory_bots/*.py phase24_store.py` | Passed |
| AST import/call deny-list | Passed |
| Storage allow-list/no-FK/no-trigger guard | Passed |
| `git diff --check main...HEAD` | Passed |

The advisory suite additionally covers unknown-symbol rejection, unsupported/malformed candle rejection, non-overridable risk limits, no-write unsafe batches, simulated transactional rollback, dual safety-flag migrations, and supervisor recomputation.

## 13. No merge confirmation

No merge to `main` was performed.

## 14. No deployment confirmation

No production deployment was performed.

## 15. No trading activity confirmation

This review created no trades, closed no positions, invoked no broker order API, enabled no auto-paper entries, enabled no bootstrap mode, and added no scheduler hook or production endpoint.

The operating posture remains paper-only and advisory-only.

## 16. Final verdict

**SAFE FOR LATER MERGE REVIEW**

This verdict authorizes consideration of a later human-approved merge review only. It does not authorize a merge, production deployment, scheduler hookup, endpoint rollout, auto-entry enablement, bootstrap enablement, trade creation, position closure, or live-order activity.