# ApexQuant AI — Monday Market Test and Merge Checklist

**Scope:** Phase 1H market-session watch plus Phase 2D/Phase 3A advisory merge gates
**Operating posture:** PAPER ONLY / ADVISORY ONLY
**Use:** Complete during and after the first Monday market session. Do not treat this weekend template as a completed production verification.

## Preconditions

- [ ] Confirm `initial_capital=100000`.
- [ ] Confirm `active_intraday_universe=CUSTOM_LOW_PRICE_SECTOR`.
- [ ] Confirm `auto_paper_entries=false`.
- [ ] Confirm `bootstrap_paper_enabled=false`.
- [ ] Confirm `auto_paper_exits=true`.
- [ ] Confirm positions are `[]` before the session review begins.
- [ ] Confirm no merge or deployment approval has been issued accidentally.

## Phase 1H required production checks

Record the observed endpoint/report, timestamp, and operator initials beside each check.

- [ ] First completed scan reports `universe_mode=CUSTOM_LOW_PRICE_SECTOR`.
- [ ] First completed scan reports `symbols_analysed=23`.
- [ ] First completed scan reports `symbols_with_errors=0`.
- [ ] Confirm there is no `NIFTY_50` fallback.
- [ ] Confirm positions remain `[]`.
- [ ] Confirm there are no `AUTO` trades.
- [ ] Confirm there are no `BOOTSTRAP_AUTO` trades.
- [ ] After 15:20 IST, confirm EOD status works.
- [ ] Confirm EOD outcomes contain no `ERROR` rows.

## Advisory merge checks

- [ ] Confirm the Phase 2D branch/package remains clean and unchanged.
- [ ] Confirm `phase3a-advisory-integration-disabled` remains disabled by default.
- [ ] Confirm all five advisory flags are false unless an operator is running an explicitly approved development-only test:
  - [ ] `ADVISORY_BOTS_ENABLED=false`
  - [ ] `ADVISORY_BOTS_API_ENABLED=false`
  - [ ] `ADVISORY_BOTS_UI_ENABLED=false`
  - [ ] `ADVISORY_BOTS_PERSIST_ENABLED=false`
  - [ ] `ADVISORY_BOTS_SCHEDULER_ENABLED=false`
- [ ] Confirm no protected files changed: Phase 20 executor/scheduler/exits/EOD, paper trader, broker/Kite, settings writers, deployment configuration, workflows, or production execution configuration.
- [ ] Rerun the advisory, Phase 0C, and custom-universe test suites.
- [ ] Confirm no scheduler hook, broker call, trade/position path, settings mutation path, or automatic trade path was added.
- [ ] Operator explicitly approves any later merge.
- [ ] Deployment remains a separate, explicit operator approval.

## Decision record

- Monday observer:
- Session date:
- Evidence/report links:
- Phase 1H verdict: PASS / BLOCKED
- Advisory merge recommendation: CONSIDER / HOLD
- Merge approved by:
- Deployment separately approved by:

## Stop conditions

Stop and hold merge/deployment consideration if any required check fails, a
fallback universe appears, symbols-with-errors is nonzero, an unapproved
automatic trade exists, EOD produces an error row, advisory flags are enabled
without explicit approval, or protected execution files changed.